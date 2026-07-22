package cute

import org.chipsalliance.cde.config.{Field, Parameters}
import freechips.rocketchip.diplomacy._
import freechips.rocketchip.tilelink._
import freechips.rocketchip.subsystem._
import huancun._
import shuttle.common.ShuttleTile
import utility.{PerfCounterOptionsKey, PerfCounterOptions, XSPerfLevel}

case class HuanCunL2Params(
  ways:        Int             = 8,
  sets:        Int             = 128,
  inclusive:   Boolean         = false,
  tcmBaseAddr: Option[BigInt]  = None
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
      tcmBaseAddr       = l2.tcmBaseAddr
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

    // Bind tcmNode as an ADDITIONAL slave directly on the tile's internal
    // tlMasterXbar. This is what makes HuanCun a true dual-port L2 from the
    // tile's view: cache and TCM travel on physically distinct TL edges out
    // of tlMasterXbar and never share any Diplomacy channel.
    privateL2.tcmNode.foreach { tcmN =>
      context match {
        case sub: InstantiatesHierarchicalElements =>
          val tile = sub.totalTiles.getOrElse(tileId,
            throw new IllegalStateException(
              s"WithHuanCunL2: tile $tileId not present in subsystem totalTiles"))
          tile match {
            case st: ShuttleTile =>
              st.attachSlaveToMasterXbar(tcmN)
            case other =>
              throw new IllegalStateException(
                s"WithHuanCunL2 dual-port TCM currently only supports ShuttleTile; got ${other.getClass.getSimpleName}")
          }
        case _ =>
          throw new IllegalStateException(
            "WithHuanCunL2 dual-port TCM requires an InstantiatesHierarchicalElements context")
      }
    }

    chainNode
  }
}
