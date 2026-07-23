// TcmDmaCtrl — programmer for the TcmDmaEngine, driven by CUTE's AME
// custom instruction AME_DMA_LOAD (funct7=0x72).
//
// Receives one DMA request at a time (src, dst, len) from CUTE's tile module,
// then walks a scripted sequence of TL PutFull/Get transactions against the
// engine's MMIO surface:
//
//   1. Write SRC_LO, SRC_HI, DST_LO, DST_HI, LENGTH  (5 x 32-bit PutFull)
//   2. Write CTRL = 1                                (start pulse)
//   3. Loop { Get STATUS; check bit1 (done) }         (poll)
//   4. Write IRQ_CLR = 1, CTRL = 0                    (cleanup)
//   5. Assert done for one cycle; return to idle
//
// The MMIO transactions ride the tile's tlMasterXbar → sbus → PBUS chain.
// Single outstanding per transaction; source ID always 0.

package cute

import chisel3._
import chisel3.util._
import org.chipsalliance.cde.config.Parameters
import freechips.rocketchip.diplomacy._
import freechips.rocketchip.tilelink._

class TcmDmaCtrlReq extends Bundle {
  val src = UInt(64.W)
  val dst = UInt(64.W)
  val len = UInt(32.W)
}

class TcmDmaCtrl(baseAddr: BigInt)(implicit p: Parameters) extends LazyModule {
  val node: TLClientNode = TLClientNode(Seq(TLMasterPortParameters.v1(
    clients = Seq(TLMasterParameters.v1(
      name     = "cute_tcm_dma_ctrl",
      sourceId = IdRange(0, 1)                 // single outstanding
    ))
  )))

  lazy val module = new Impl
  class Impl extends LazyModuleImp(this) {
    val io = IO(new Bundle {
      val req  = Flipped(Decoupled(new TcmDmaCtrlReq))
      val busy = Output(Bool())
      val done = Output(Bool())                // 1-cycle pulse on transfer complete
    })

    val (tl, edge) = node.out.head

    // Register-window offsets (see TcmDmaEngine.scala section 3.4).
    val OFF_SRC_LO  = 0x00.U
    val OFF_SRC_HI  = 0x04.U
    val OFF_DST_LO  = 0x08.U
    val OFF_DST_HI  = 0x0C.U
    val OFF_LENGTH  = 0x10.U
    val OFF_CTRL    = 0x14.U
    val OFF_STATUS  = 0x18.U
    val OFF_IRQ_CLR = 0x1C.U

    // ---- FSM -----------------------------------------------------------
    val sIdle :: sIssue :: sWaitAck :: sCheckStatus :: Nil = Enum(4)
    val state = RegInit(sIdle)

    // Latched request fields.
    val src = Reg(UInt(64.W))
    val dst = Reg(UInt(64.W))
    val len = Reg(UInt(32.W))

    // Step counter. 0-5 = setup+start, 6-7 = poll (read STATUS then re-decide),
    // 8-9 = cleanup, 10 = done pulse.
    val step = RegInit(0.U(4.W))

    // Per-step directive (address offset, read/write, write data).
    // Only meaningful for steps that emit a transaction: 0..5, poll steps,
    // and cleanup steps 8..9.
    val stepAddr = Wire(UInt(5.W))
    val stepIsRd = Wire(Bool())
    val stepData = Wire(UInt(32.W))
    stepAddr := 0.U
    stepIsRd := false.B
    stepData := 0.U

    switch(step) {
      is(0.U) { stepAddr := OFF_SRC_LO;  stepIsRd := false.B; stepData := src(31, 0) }
      is(1.U) { stepAddr := OFF_SRC_HI;  stepIsRd := false.B; stepData := src(63, 32) }
      is(2.U) { stepAddr := OFF_DST_LO;  stepIsRd := false.B; stepData := dst(31, 0) }
      is(3.U) { stepAddr := OFF_DST_HI;  stepIsRd := false.B; stepData := dst(63, 32) }
      is(4.U) { stepAddr := OFF_LENGTH;  stepIsRd := false.B; stepData := len }
      is(5.U) { stepAddr := OFF_CTRL;    stepIsRd := false.B; stepData := 1.U }        // start
      is(6.U) { stepAddr := OFF_STATUS;  stepIsRd := true.B                          }  // poll read
      is(8.U) { stepAddr := OFF_IRQ_CLR; stepIsRd := false.B; stepData := 1.U }
      is(9.U) { stepAddr := OFF_CTRL;    stepIsRd := false.B; stepData := 0.U }
    }

    // Full physical address of the current MMIO register.
    val stepPaddr = baseAddr.U + stepAddr

    // TileLink data-lane alignment. The outward edge is `beatBytes` wide, but
    // each MMIO transaction is only 4 bytes; the payload must sit at the
    // address-aligned byte lane inside the wide beat, not at bits[31:0]. Same
    // thing on the D side for reads — AccessAckData returns the 4 bytes at
    // the same aligned lane, so we shift back to reconstruct the value.
    val beatBytes  = edge.bundle.dataBits / 8
    val laneBits   = if (beatBytes > 1) log2Ceil(beatBytes) else 1
    val byteLane   = stepPaddr(laneBits - 1, 0)          // 0 .. beatBytes-1
    val laneShift  = Cat(byteLane, 0.U(3.W))             // in bits

    // Place the 4-byte write payload at the correct lane before handing it to
    // edge.Put. Truncate to the beat width; edge.Put just does `a.data := data`.
    val alignedPut = ((stepData.pad(edge.bundle.dataBits) << laneShift))(edge.bundle.dataBits - 1, 0)

    // 4-byte MMIO Put / Get on the TL A channel.
    val (getLegal, getBits) = edge.Get(fromSource = 0.U, toAddress = stepPaddr, lgSize = 2.U)
    val (putLegal, putBits) = edge.Put(fromSource = 0.U, toAddress = stepPaddr, lgSize = 2.U, data = alignedPut)

    tl.a.valid := state === sIssue
    tl.a.bits  := Mux(stepIsRd, getBits, putBits)
    tl.d.ready := state === sWaitAck

    // Latch STATUS read data for the check step — shift the beat back down so
    // we grab the correct 32-bit lane.
    val statusReg = Reg(UInt(32.W))
    val dReadData = (tl.d.bits.data >> laneShift)(31, 0)

    io.req.ready := state === sIdle
    io.busy      := state =/= sIdle
    io.done      := false.B

    when(state === sIdle && io.req.fire) {
      src   := io.req.bits.src
      dst   := io.req.bits.dst
      len   := io.req.bits.len
      step  := 0.U
      state := sIssue
      printf(p"[TcmDmaCtrl] req fire src=${Hexadecimal(io.req.bits.src)} dst=${Hexadecimal(io.req.bits.dst)} len=${io.req.bits.len}\n")
    }

    when(state === sIssue && tl.a.ready) {
      state := sWaitAck
      printf(p"[TcmDmaCtrl] step=${step} a.fire addr=${Hexadecimal(stepPaddr)} isRd=${stepIsRd} data=${Hexadecimal(stepData)} lane_shift_bits=${laneShift} aligned=${Hexadecimal(tl.a.bits.data)}\n")
    }

    when(state === sWaitAck && tl.d.valid) {
      when(stepIsRd) { statusReg := dReadData }
      state := Mux(step === 6.U, sCheckStatus, sIssue)
      // Advance the step counter here for non-poll paths. Poll advancement is
      // handled below to keep the retry loop tight.
      when(step =/= 6.U) {
        step := step + 1.U
      }
      printf(p"[TcmDmaCtrl] step=${step} d.fire beat=${Hexadecimal(tl.d.bits.data)} extracted=${Hexadecimal(dReadData)}\n")
    }

    // Poll decision: if STATUS.done (bit1) is set, jump to cleanup; else retry.
    when(state === sCheckStatus) {
      val doneBit = statusReg(1)
      when(doneBit) {
        step  := 8.U                              // begin cleanup
        state := sIssue
        printf(p"[TcmDmaCtrl] STATUS done, entering cleanup\n")
      }.otherwise {
        step  := 6.U                              // re-issue STATUS read
        state := sIssue
      }
    }

    // End of cleanup: after step 9's ACK, we pulse `done` and go idle.
    when(state === sWaitAck && tl.d.valid && step === 9.U) {
      io.done := true.B
      state   := sIdle
      step    := 0.U
      printf(p"[TcmDmaCtrl] done, back to idle\n")
    }

    // Sanity: TL protocol must accept our accesses.
    when(state === sIssue) {
      assert(Mux(stepIsRd, getLegal, putLegal),
        "TcmDmaCtrl: MMIO Get/Put marked illegal by manager")
    }
  }
}
