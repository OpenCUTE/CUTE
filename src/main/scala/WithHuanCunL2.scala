package cute

import org.chipsalliance.cde.config.{Field, Parameters}
import freechips.rocketchip.diplomacy._
import freechips.rocketchip.tilelink._
import freechips.rocketchip.subsystem._
import huancun._
import shuttle.common.ShuttleTile
import utility.{PerfCounterOptionsKey, PerfCounterOptions, XSPerfLevel}

case class HuanCunL2Params(
  ways:            Int             = 8,
  sets:            Int             = 128,
  inclusive:       Boolean         = false,
  tcmBaseAddr:     Option[BigInt]  = None,
  // Base of the MMIO control region that lets software runtime-repartition
  // cache vs TCM ways. Ignored when tcmBaseAddr is None.
  tcmCtrlBaseAddr: Option[BigInt]  = None,
  // Initial (reset-time) number of TCM ways. Must be one of {0, 1, 2, ...,
  // pow2 ≤ ways}. When None, defaults to ways/2. Also caps the maximum
  // TCM allocation — TcmCtrl accepts writes up to this value only.
  tcmWayCount:     Option[Int]     = None
)

case object HuanCunL2ParamsKey extends Field[HuanCunL2Params](HuanCunL2Params())

case class HuanCunL2MasterPortParams(
  tileId: Int,
  base:   HierarchicalElementPortParamsLike,
  l2:     HuanCunL2Params
) extends HierarchicalElementPortParamsLike {

  def where = base.where

  def injectNode(context: Attachable)(implicit p: Parameters): TLNode = {
    val sbus = context.locateTLBusWrapper(where)
    val beatBytes = sbus.beatBytes

    val hcParams = HCCacheParameters(
      name              = s"tile${tileId}_L2",
      level             = 2,
      ways              = l2.ways,
      sets              = l2.sets,
      blockBytes        = 64,
      channelBytes      = TLChannelBeatBytes(beatBytes),
      inclusive         = l2.inclusive,
      elaboratedTopDown = false,
      clientCaches      = if (!l2.inclusive) Seq(CacheParameters(
        name             = s"tile${tileId}_DCache",
        sets             = 64,
        ways             = 4,
        blockGranularity = 6,
        blockBytes       = 64
      )) else Nil,
      tcmBaseAddr       = l2.tcmBaseAddr,
      tcmCtrlBaseAddr   = l2.tcmCtrlBaseAddr,
      tcmWayCountOpt    = l2.tcmWayCount
    )

    val privateL2 = LazyModule(new HuanCun()(p.alterPartial {
      case HCCacheParamsKey => hcParams
      case PerfCounterOptionsKey => PerfCounterOptions(
        enablePerfPrint = false,
        enablePerfDB    = false,
        perfLevel       = XSPerfLevel.CRITICAL,
        perfDBHartID    = 0
      )
    }))
    privateL2.suggestName(s"tile${tileId}_huancun_L2")

    // cacheNode goes through the standard master-injection chain to sbus.
    // Its manager address filter has TCM subtracted, so upstream Xbar routes
    // TCM traffic elsewhere (see the tcmNode binding below).
    val chainNode = privateL2.cacheNode :*=* base.injectNode(context)(p)

    // Helper: look up the ShuttleTile associated with this tileId.
    // Both the tcmNode binding and the optional DMA integration need the tile.
    def lookupShuttleTile(): ShuttleTile = context match {
      case sub: InstantiatesHierarchicalElements =>
        sub.totalTiles.getOrElse(tileId,
          throw new IllegalStateException(
            s"WithHuanCunL2: tile $tileId not present in subsystem totalTiles")) match {
          case st: ShuttleTile => st
          case other =>
            throw new IllegalStateException(
              s"WithHuanCunL2 currently only supports ShuttleTile; got ${other.getClass.getSimpleName}")
        }
      case _ =>
        throw new IllegalStateException(
          "WithHuanCunL2 requires an InstantiatesHierarchicalElements context")
    }

    // Bind tcmNode as an ADDITIONAL slave directly on the tile's internal
    // tlMasterXbar. This is what makes HuanCun a true dual-port L2 from the
    // tile's view: cache and TCM travel on physically distinct TL edges out
    // of tlMasterXbar and never share any Diplomacy channel.
    privateL2.tcmNode.foreach { tcmN =>
      lookupShuttleTile().attachSlaveToMasterXbar(tcmN)
    }

    // Optional TCM partition control (Step 2A). When the user sets
    // l2.tcmCtrlBaseAddr, HuanCun instantiates a TcmCtrl MMIO regmap; couple
    // its ctrlNode onto PBUS so software can write it.
    privateL2.tcmCtrlNode.foreach { ctrlN =>
      val pbus = context.locateTLBusWrapper(PBUS)
      pbus.coupleTo(s"tile${tileId}_tcm_ctrl") { bus =>
        ctrlN := TLFragmenter(pbus.beatBytes, pbus.blockBytes) := bus
      }
    }

    // Optional TCM DMA engine. When a WithTcmDma fragment has populated the
    // Field, we spin up one DMA per tile that also has TCM enabled. Its two
    // master edges join the tile's tlMasterXbar; its MMIO control window is
    // coupled onto PBUS.
    (p(TcmDmaKey), privateL2.tcmNode) match {
      case (Some(dmaBaseParams), Some(_)) =>
        val dmaParams = dmaBaseParams.copy(
          // Give every tile a unique MMIO window so multi-tile configs don't
          // collide.
          ctrlAddress = dmaBaseParams.ctrlAddress + BigInt(tileId) * dmaBaseParams.ctrlWindow)
        val dma = LazyModule(new TcmDmaEngine(dmaParams))
        dma.suggestName(s"tile${tileId}_tcm_dma")

        val tile = lookupShuttleTile()
        tile.attachMasterToMasterXbar(dma.memReadNode)
        tile.attachMasterToMasterXbar(dma.tcmWriteNode)

        val pbus = context.locateTLBusWrapper(PBUS)
        pbus.coupleTo(s"tile${tileId}_tcm_dma_ctrl") { bus =>
          dma.ctrlNode := TLFragmenter(pbus.beatBytes, pbus.blockBytes) := bus
        }
      case (Some(_), None) =>
        throw new IllegalStateException(
          s"WithTcmDma set for tile $tileId but HuanCunL2 has no TCM (l2.tcmBaseAddr = None)")
      case _ => // no DMA requested
    }

    chainNode
  }
}
