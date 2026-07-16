package cute

import org.chipsalliance.cde.config.{Field, Parameters}
import freechips.rocketchip.diplomacy._
import freechips.rocketchip.tilelink._
import freechips.rocketchip.subsystem._
import huancun._
import utility.{PerfCounterOptionsKey, PerfCounterOptions, XSPerfLevel}

case class HuanCunL2Params(
  ways:        Int             = 8,
  sets:        Int             = 128,
  inclusive:   Boolean         = false,
  cacheWays:   Int             = 0,          // 0 = use all `ways` for cache
  tcmWays:     Int             = 0,          // 0 = no TCM
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
      cacheWays         = l2.cacheWays,
      tcmWays           = l2.tcmWays,
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

    privateL2.node :*=* base.injectNode(context)(p)
  }
}
