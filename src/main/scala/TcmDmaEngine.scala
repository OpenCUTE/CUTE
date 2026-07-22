// TCM DMA Engine — Phase 3 skeleton.
//
// Bulk-copies contiguous blocks from main memory into a TCM region via two TL
// client channels:
//   - memReadNode: emits Get requests on the tile's tlMasterXbar; hits go
//     through HuanCun L2 (cacheNode) → DRAM.
//   - tcmWriteNode: emits PutFull to the TCM address range; served by the
//     TcmSinkA/TcmSourceD path inside HuanCun.
//
// Control surface: MMIO manager node (ctrlNode) exposes SRC_ADDR / DST_ADDR /
// LENGTH / CTRL / STATUS / IRQ_CLR registers. See section 3.4 of
// L2_TCM_DMA_Refactor_Plan.md for the register layout.
//
// This first iteration keeps the FSM simple:
//   IDLE → ISSUE_READ → WAIT_RESP → ISSUE_WRITE → WAIT_ACK → ADVANCE → DONE
// Single outstanding, single-block (blockBytes) transfer, no burst-overlap.
// Future phases add burst, multi-outstanding, and read/write pipelining.

package cute

import chisel3._
import chisel3.util._
import org.chipsalliance.cde.config.Parameters
import freechips.rocketchip.diplomacy._
import freechips.rocketchip.tilelink._
import freechips.rocketchip.regmapper._
import freechips.rocketchip.resources.SimpleDevice

case class TcmDmaEngineParams(
  ctrlAddress:   BigInt,           // MMIO base for control registers (aligned to 0x40)
  beatBytes:     Int = 8,          // MMIO register bus beat bytes
  memMaxBurst:   Int = 64,         // max bytes per memReadNode transfer (aligned)
  tcmMaxBurst:   Int = 64,         // max bytes per tcmWriteNode transfer (aligned)
  sourceIdBits:  Int = 2           // in-flight transactions per client node
) {
  require(memMaxBurst > 0 && (memMaxBurst & (memMaxBurst - 1)) == 0,
    "memMaxBurst must be a positive power of 2")
  require(tcmMaxBurst > 0 && (tcmMaxBurst & (tcmMaxBurst - 1)) == 0,
    "tcmMaxBurst must be a positive power of 2")
  require(ctrlAddress % 0x40 == 0, "ctrlAddress must be 64B aligned")
}

class TcmDmaEngine(params: TcmDmaEngineParams)(implicit p: Parameters)
  extends LazyModule {

  // Client nodes ---------------------------------------------------------------
  // Reads from main memory. Hooked to tlMasterXbar by the tile integration
  // fragment; L2 cacheNode handles the addresses.
  val memReadNode: TLClientNode = TLClientNode(Seq(TLMasterPortParameters.v1(
    clients = Seq(TLMasterParameters.v1(
      name     = "tcm_dma_mem_read",
      sourceId = IdRange(0, 1 << params.sourceIdBits)
    ))
  )))

  // Writes to the TCM address range. Same tlMasterXbar, address routing selects
  // HuanCun's TCM segment.
  val tcmWriteNode: TLClientNode = TLClientNode(Seq(TLMasterPortParameters.v1(
    clients = Seq(TLMasterParameters.v1(
      name     = "tcm_dma_tcm_write",
      sourceId = IdRange(0, 1 << params.sourceIdBits)
    ))
  )))

  // MMIO control surface (mounted on PBUS by the tile fragment).
  val device = new SimpleDevice("tcm-dma", Seq("cute,tcm-dma-engine"))
  val ctrlNode: TLRegisterNode = TLRegisterNode(
    address     = Seq(AddressSet(params.ctrlAddress, 0x3f)),
    device      = device,
    beatBytes   = params.beatBytes,
    concurrency = 1
  )

  lazy val module = new TcmDmaEngineImp(this)
}

class TcmDmaEngineImp(outer: TcmDmaEngine) extends LazyModuleImp(outer) {
  // FSM and TL wiring land in the next sub-step. For now, tie off all
  // Decoupled signals so Chisel elaboration passes even before the FSM exists.
  val (memA, _) = outer.memReadNode.out.head
  val (tcmA, _) = outer.tcmWriteNode.out.head

  memA.a.valid := false.B
  memA.a.bits  := DontCare
  memA.d.ready := true.B
  tcmA.a.valid := false.B
  tcmA.a.bits  := DontCare
  tcmA.d.ready := true.B

  // Placeholder registers so ctrlNode has something to map. Real semantics
  // arrive in the FSM sub-step.
  val srcAddr = RegInit(0.U(64.W))
  val dstAddr = RegInit(0.U(64.W))
  val length  = RegInit(0.U(32.W))
  val ctrl    = RegInit(0.U(32.W))
  val status  = RegInit(0.U(32.W))

  outer.ctrlNode.regmap(
    0x00 -> Seq(RegField(64, srcAddr)),
    0x08 -> Seq(RegField(64, dstAddr)),
    0x10 -> Seq(RegField(32, length)),
    0x14 -> Seq(RegField(32, ctrl)),
    0x18 -> Seq(RegField.r(32, status)),
    0x1C -> Seq(RegField(32, WireDefault(0.U(32.W))))   // IRQ_CLR (no-op stub)
  )
}
