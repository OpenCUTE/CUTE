// TCM DMA Engine — Phase 3.
//
// Bulk-copies contiguous blocks from main memory into a TCM region via two TL
// client channels:
//   - memReadNode: emits Get requests on the tile's tlMasterXbar; hits go
//     through HuanCun L2 (cacheNode) → DRAM.
//   - tcmWriteNode: emits PutFull to the TCM address range; served by the
//     TcmSinkA/TcmSourceD path on HuanCun's tcmNode.
//
// Control surface: MMIO manager node (ctrlNode) exposes SRC_ADDR / DST_ADDR /
// LENGTH / CTRL / STATUS / IRQ_CLR registers. See section 3.4 of
// L2_TCM_DMA_Refactor_Plan.md for the register layout.
//
// First iteration:
//   IDLE → ISSUE_READ → WAIT_RESP → ISSUE_WRITE → WAIT_ACK → (loop | IDLE)
// Single outstanding, one blockBytes (=64B) chunk per iteration, no burst
// overlap. Future phases add burst, multi-outstanding, and read/write
// pipelining.

package cute

import chisel3._
import chisel3.util._
import org.chipsalliance.cde.config.{Field, Parameters}
import freechips.rocketchip.diplomacy._
import freechips.rocketchip.tilelink._
import freechips.rocketchip.regmapper._
import freechips.rocketchip.resources.SimpleDevice

// Config Field consulted by the WithHuanCunL2 injectNode: when set, an
// additional TcmDmaEngine is created alongside the L2, its master edges are
// joined onto the tile's tlMasterXbar, and its control regmap is coupled onto
// the peripheral bus.
case object TcmDmaKey extends Field[Option[TcmDmaEngineParams]](None)

case class TcmDmaEngineParams(
  ctrlAddress:   BigInt,           // MMIO base for control registers (page-aligned)
  ctrlWindow:    BigInt = 0x1000,  // MMIO window size; 4KB satisfies Saturn's page-alignment check
  beatBytes:     Int = 8,          // MMIO register bus beat bytes
  memMaxBurst:   Int = 64,         // max bytes per memReadNode transfer (aligned)
  tcmMaxBurst:   Int = 64,         // max bytes per tcmWriteNode transfer (aligned)
  sourceIdBits:  Int = 2           // in-flight transactions per client node
) {
  require(memMaxBurst > 0 && (memMaxBurst & (memMaxBurst - 1)) == 0,
    "memMaxBurst must be a positive power of 2")
  require(tcmMaxBurst > 0 && (tcmMaxBurst & (tcmMaxBurst - 1)) == 0,
    "tcmMaxBurst must be a positive power of 2")
  require((ctrlWindow & (ctrlWindow - 1)) == 0 && ctrlWindow >= 0x1000,
    s"ctrlWindow must be a power of 2 and at least 4KB (got 0x${ctrlWindow.toString(16)})")
  require(ctrlAddress % ctrlWindow == 0,
    s"ctrlAddress (0x${ctrlAddress.toString(16)}) must be aligned to ctrlWindow (0x${ctrlWindow.toString(16)})")
}

class TcmDmaEngine(val params: TcmDmaEngineParams)(implicit p: Parameters)
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
  // The window is deliberately >= 4KB so Saturn's fault-check for
  // page-aligned memory devices in the tile's tlMasterXbar edge is satisfied.
  val device = new SimpleDevice("tcm-dma", Seq("cute,tcm-dma-engine"))
  val ctrlNode: TLRegisterNode = TLRegisterNode(
    address     = Seq(AddressSet(params.ctrlAddress, params.ctrlWindow - 1)),
    device      = device,
    beatBytes   = params.beatBytes,
    concurrency = 1
  )

  lazy val module = new TcmDmaEngineImp(this)
}

class TcmDmaEngineImp(outer: TcmDmaEngine) extends LazyModuleImp(outer) {
  val (memA, memEdge) = outer.memReadNode.out.head
  val (tcmA, tcmEdge) = outer.tcmWriteNode.out.head

  private val blockBytes = 64
  private val blockBits  = blockBytes * 8
  private val lgBlock    = log2Ceil(blockBytes)

  require(memEdge.manager.beatBytes == blockBytes,
    s"TcmDmaEngine v2 requires memory-side beatBytes == $blockBytes, got ${memEdge.manager.beatBytes}")
  require(tcmEdge.manager.beatBytes == blockBytes,
    s"TcmDmaEngine v2 requires TCM-side beatBytes == $blockBytes, got ${tcmEdge.manager.beatBytes}")

  // -----------------------------------------------------------------------
  // Pipelined transfer with N outstanding reads.
  //
  // Structure:
  //   * Read side issues Gets round-robin over source IDs 0..N-1, up to N
  //     in flight. Each response is written into roBuf indexed by its source
  //     tag, with roValid tracking arrival.
  //   * Write side runs independently: it takes the block at writerSeq (in
  //     issue order), issues a PutFull on the TCM side, and waits for an ACK
  //     before advancing.
  //   * slotsInUse counts Gets issued minus Puts completed, gating the read
  //     side so it never exceeds N in-flight blocks (i.e. never reuses a
  //     source tag while its previous response hasn't been consumed).
  //
  // Because sourceIdBits was already set to `params.sourceIdBits`, N is a
  // power of 2 (default 4). Rotating tag = issueSeq mod N; the reorder buffer
  // is indexed directly by the tag so out-of-order responses across sources
  // still land in the correct slot.
  // -----------------------------------------------------------------------
  private val N       = 1 << outer.params.sourceIdBits
  private val tagBits = if (N > 1) log2Ceil(N) else 1
  require(memEdge.bundle.sourceBits >= tagBits,
    s"memReadNode edge sourceBits (${memEdge.bundle.sourceBits}) < tagBits ($tagBits)")

  val active = RegInit(false.B)

  val roBuf   = Reg(Vec(N, UInt(blockBits.W)))
  val roValid = RegInit(VecInit(Seq.fill(N)(false.B)))

  val issueSeq  = RegInit(0.U(tagBits.W))          // next tag to allocate for a Get
  val writerSeq = RegInit(0.U(tagBits.W))          // next tag to consume for a Put
  val slotsInUse = RegInit(0.U(log2Ceil(N + 1).W)) // 0 .. N

  val readAddr  = Reg(UInt(64.W))
  val writeAddr = Reg(UInt(64.W))
  val readRem   = Reg(UInt(32.W))
  val writeRem  = Reg(UInt(32.W))

  val writeInFlight = RegInit(false.B)

  // MMIO-visible registers.
  val srcAddrLo = RegInit(0.U(32.W))
  val srcAddrHi = RegInit(0.U(32.W))
  val dstAddrLo = RegInit(0.U(32.W))
  val dstAddrHi = RegInit(0.U(32.W))
  val lengthReg = RegInit(0.U(32.W))
  val ctrlReg   = RegInit(0.U(32.W))
  val doneLatch = RegInit(false.B)
  val errLatch  = RegInit(false.B)

  val busy = active

  // Pulsed for one cycle when SW writes CTRL[0]=1 while the engine is idle.
  val startPulse = WireInit(false.B)

  // -----------------------------------------------------------------------
  // Read side (up to N outstanding Gets).
  // -----------------------------------------------------------------------
  val getSource = issueSeq.pad(memEdge.bundle.sourceBits)
  val (getLegal, getBits) = memEdge.Get(
    fromSource = getSource,
    toAddress  = readAddr(memEdge.bundle.addressBits - 1, 0),
    lgSize     = lgBlock.U)

  val canIssueGet = active && (readRem =/= 0.U) && (slotsInUse < N.U)
  memA.a.valid := canIssueGet
  memA.a.bits  := getBits
  memA.d.ready := true.B                           // reorder buf always accepts

  when(canIssueGet) {
    assert(getLegal, "TcmDmaEngine: memory-side Get is illegal (bad size or address)")
  }

  val getIssued = memA.a.fire
  val getRespd  = memA.d.fire

  when(getIssued) {
    readAddr := readAddr + blockBytes.U
    readRem  := readRem  - blockBytes.U
    issueSeq := issueSeq + 1.U
  }

  when(getRespd) {
    val rspTag = memA.d.bits.source(tagBits - 1, 0)
    roBuf(rspTag)   := memA.d.bits.data
    roValid(rspTag) := true.B
    errLatch := errLatch | memA.d.bits.denied | memA.d.bits.corrupt
  }

  // -----------------------------------------------------------------------
  // Write side (1 outstanding Put; TCM is fast so this is rarely a bottleneck).
  // -----------------------------------------------------------------------
  val putSource = 0.U(tcmEdge.bundle.sourceBits.W)
  val (putLegal, putBits) = tcmEdge.Put(
    fromSource = putSource,
    toAddress  = writeAddr(tcmEdge.bundle.addressBits - 1, 0),
    lgSize     = lgBlock.U,
    data       = roBuf(writerSeq))

  val canIssuePut = active && (writeRem =/= 0.U) && !writeInFlight && roValid(writerSeq)
  tcmA.a.valid := canIssuePut
  tcmA.a.bits  := putBits
  tcmA.d.ready := true.B

  when(canIssuePut) {
    assert(putLegal, "TcmDmaEngine: TCM-side Put is illegal (bad size or address)")
  }

  val putIssued = tcmA.a.fire
  val putAcked  = tcmA.d.fire

  when(putIssued) {
    writeInFlight     := true.B
    writeAddr         := writeAddr + blockBytes.U
    writeRem          := writeRem  - blockBytes.U
    roValid(writerSeq) := false.B                  // slot data has been latched into tcmA
    writerSeq         := writerSeq + 1.U
  }

  when(putAcked) {
    writeInFlight := false.B
    errLatch := errLatch | tcmA.d.bits.denied | tcmA.d.bits.corrupt
  }

  // -----------------------------------------------------------------------
  // slotsInUse: Gets in flight or waiting to be Put. Increments on Get issue,
  // decrements on Put ACK (which is when the slot becomes fully consumed).
  // If both happen in the same cycle, they net to zero.
  // -----------------------------------------------------------------------
  val slotsInc = getIssued && !putAcked
  val slotsDec = putAcked  && !getIssued
  when(slotsInc) { slotsInUse := slotsInUse + 1.U }
  when(slotsDec) { slotsInUse := slotsInUse - 1.U }

  // -----------------------------------------------------------------------
  // Completion detection: no more reads to issue, no more writes to issue,
  // all outstanding requests have retired, and no ACK still pending.
  // -----------------------------------------------------------------------
  val allDone = active && (readRem === 0.U) && (writeRem === 0.U) &&
                (slotsInUse === 0.U) && !writeInFlight
  when(allDone) {
    active    := false.B
    doneLatch := true.B
  }

  // -----------------------------------------------------------------------
  // Start handshake.
  // -----------------------------------------------------------------------
  when(startPulse && !busy) {
    readAddr      := Cat(srcAddrHi, srcAddrLo)
    writeAddr     := Cat(dstAddrHi, dstAddrLo)
    readRem       := lengthReg
    writeRem      := lengthReg
    issueSeq      := 0.U
    writerSeq     := 0.U
    slotsInUse    := 0.U
    writeInFlight := false.B
    roValid.foreach(_ := false.B)
    doneLatch     := false.B
    errLatch      := false.B
    when(lengthReg === 0.U) {
      doneLatch := true.B
    }.otherwise {
      active := true.B
    }
  }

  // -----------------------------------------------------------------------
  // MMIO regmap. Register offsets match section 3.4 of the plan document.
  // -----------------------------------------------------------------------
  val statusVal = Cat(0.U(29.W), errLatch, doneLatch, busy)

  outer.ctrlNode.regmap(
    0x00 -> Seq(RegField(32, srcAddrLo,
      RegFieldDesc("src_addr_lo", "Source address low 32b"))),
    0x04 -> Seq(RegField(32, srcAddrHi,
      RegFieldDesc("src_addr_hi", "Source address high 32b"))),
    0x08 -> Seq(RegField(32, dstAddrLo,
      RegFieldDesc("dst_addr_lo", "Destination address low 32b (TCM)"))),
    0x0C -> Seq(RegField(32, dstAddrHi,
      RegFieldDesc("dst_addr_hi", "Destination address high 32b (TCM)"))),
    0x10 -> Seq(RegField(32, lengthReg,
      RegFieldDesc("length", "Transfer length in bytes; must be a multiple of 64"))),
    0x14 -> Seq(RegField(32,
      RegReadFn(ctrlReg),
      RegWriteFn((valid: Bool, data: UInt) => {
        when(valid) {
          ctrlReg := data
          when(data(0) && !busy) { startPulse := true.B }
        }
        true.B
      }),
      RegFieldDesc("ctrl", "bit0=start, bit1=irq_en (reserved), bit2=dir (reserved)"))),
    0x18 -> Seq(RegField.r(32, statusVal,
      RegFieldDesc("status", "bit0=busy, bit1=done, bit2=error"))),
    0x1C -> Seq(RegField(32,
      RegReadFn(0.U),
      RegWriteFn((valid: Bool, data: UInt) => {
        when(valid && data(0)) { doneLatch := false.B }
        true.B
      }),
      RegFieldDesc("irq_clr", "Write bit0=1 to clear the done latch")))
  )
}
