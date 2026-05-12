package cute

import chisel3._
import chisel3.util._

// AME instruction encoding based on RISC-V Matrix Specification Proposal v0.6.0
// Original 32-bit format uses custom-1 opcode (0101011 = 0x2B).
// For RoCC integration, we map the full instruction into the 7-bit funct field
// plus rd/rs1/rs2 register fields and rs1_data/rs2_data GPR values.
//
// RoCC funct encoding scheme:
//   [6:4] = instruction class
//   [3:0] = sub-type (element size, transpose, signedness, etc.)
//
// AME 32-bit native encoding reference:
//   Config:  func3=000, uop=00, func4 distinguishes m/n/k
//   Load/Store: func3=000, uop=01, inst[25]=ls, func4=load/store type, d_size=element size
//   MatMul: func3=000, uop=10, func4=float/int type, d_size/s_size=element sizes
//   MISC:   func3=000, uop=11, func4=misc type
//
// md/ms1/ms2 are 3-bit: 000-011=tr0-tr3, 100-111=acc0-acc3
// d_size/s_size: 00=8bit, 01=16bit, 10=32bit, 11=64bit

object AMEInstConfigs {
  val AME_OPCODE = "h2B".U(7.W)

  // ============================================================
  // RoCC funct encoding (7-bit)
  // ============================================================
  // [6:4]=001: Load instructions
  // [3:2]=element size (00=8b,01=16b,10=32b,11=64b)
  // [1:0]=matrix type (00=A, 01=B, 10=C, 11=A_transposed for load; B_transposed for store)
  // ============================================================

  // --- Load instructions: funct[6:4] = 001 ---
  // Load A (left matrix): mlae<8/16/32/64>
  val FUNCT_MLAE8   = "h10".U(7.W)  // 001_00_00
  val FUNCT_MLAE16  = "h14".U(7.W)  // 001_01_00
  val FUNCT_MLAE32  = "h18".U(7.W)  // 001_10_00
  val FUNCT_MLAE64  = "h1C".U(7.W)  // 001_11_00

  // Load B (right matrix): mlbe<8/16/32/64>
  val FUNCT_MLBE8   = "h11".U(7.W)  // 001_00_01
  val FUNCT_MLBE16  = "h15".U(7.W)  // 001_01_01
  val FUNCT_MLBE32  = "h19".U(7.W)  // 001_10_01
  val FUNCT_MLBE64  = "h1D".U(7.W)  // 001_11_01

  // Load C (output/accumulator): mlce<8/16/32/64>
  val FUNCT_MLCE8   = "h12".U(7.W)  // 001_00_10
  val FUNCT_MLCE16  = "h16".U(7.W)  // 001_01_10
  val FUNCT_MLCE32  = "h1A".U(7.W)  // 001_10_10
  val FUNCT_MLCE64  = "h1E".U(7.W)  // 001_11_10

  // Load A transposed: mlate<8/16/32/64>
  val FUNCT_MLATE8  = "h13".U(7.W)  // 001_00_11
  val FUNCT_MLATE16 = "h17".U(7.W)  // 001_01_11
  val FUNCT_MLATE32 = "h1B".U(7.W)  // 001_10_11
  val FUNCT_MLATE64 = "h1F".U(7.W)  // 001_11_11

  // --- Store instructions: funct[6:4] = 010 ---
  // [3:2]=element size, [1:0]=matrix type (00=A, 01=B, 10=C, 11=C_transposed)
  // Store A: msae<8/16/32/64>
  val FUNCT_MSAE8   = "h20".U(7.W)
  val FUNCT_MSAE16  = "h24".U(7.W)
  val FUNCT_MSAE32  = "h28".U(7.W)
  val FUNCT_MSAE64  = "h2C".U(7.W)

  // Store B: msbe<8/16/32/64>
  val FUNCT_MSBE8   = "h21".U(7.W)
  val FUNCT_MSBE16  = "h25".U(7.W)
  val FUNCT_MSBE32  = "h29".U(7.W)
  val FUNCT_MSBE64  = "h2D".U(7.W)

  // Store C: msce<8/16/32/64>
  val FUNCT_MSCE8   = "h22".U(7.W)
  val FUNCT_MSCE16  = "h26".U(7.W)
  val FUNCT_MSCE32  = "h2A".U(7.W)
  val FUNCT_MSCE64  = "h2E".U(7.W)

  // Store C transposed: mscte<8/16/32/64>
  val FUNCT_MSCTE8  = "h23".U(7.W)
  val FUNCT_MSCTE16 = "h27".U(7.W)
  val FUNCT_MSCTE32 = "h2B".U(7.W)
  val FUNCT_MSCTE64 = "h2F".U(7.W)

  // --- Load transposed B/C: funct[6:4] = 011 ---
  // Load B transposed: mlbte<8/16/32/64>
  val FUNCT_MLBTE8  = "h30".U(7.W)
  val FUNCT_MLBTE16 = "h31".U(7.W)
  val FUNCT_MLBTE32 = "h32".U(7.W)
  val FUNCT_MLBTE64 = "h33".U(7.W)

  // Load C transposed: mlcte<8/16/32/64>
  val FUNCT_MLCTE8  = "h34".U(7.W)
  val FUNCT_MLCTE16 = "h35".U(7.W)
  val FUNCT_MLCTE32 = "h36".U(7.W)
  val FUNCT_MLCTE64 = "h37".U(7.W)

  // Store A transposed: msate<8/16/32/64>
  val FUNCT_MSATE8  = "h38".U(7.W)
  val FUNCT_MSATE16 = "h39".U(7.W)
  val FUNCT_MSATE32 = "h3A".U(7.W)
  val FUNCT_MSATE64 = "h3B".U(7.W)

  // Store B transposed: msbte<8/16/32/64>
  val FUNCT_MSBTE8  = "h3C".U(7.W)
  val FUNCT_MSBTE16 = "h3D".U(7.W)
  val FUNCT_MSBTE32 = "h3E".U(7.W)
  val FUNCT_MSBTE64 = "h3F".U(7.W)

  // --- Matrix Multiplication: funct[6:4] = 100 ---
  // Integer quad-widen (int8 -> int32): AME spec func4=0001
  val FUNCT_MMACC_W_B    = "h40".U(7.W)  // mmacc.w.b   (signed * signed)
  val FUNCT_MMACCU_W_B   = "h41".U(7.W)  // mmaccu.w.b  (unsigned * unsigned)
  val FUNCT_MMACCSU_W_B  = "h42".U(7.W)  // mmaccsu.w.b (signed * unsigned)
  val FUNCT_MMACCUS_W_B  = "h43".U(7.W)  // mmaccus.w.b (unsigned * signed)

  // Float non-widen: AME spec func4=0000, same src/dst size
  val FUNCT_MFMACC_H     = "h44".U(7.W)  // mfmacc.h   (fp16 -> fp16)
  val FUNCT_MFMACC_S     = "h45".U(7.W)  // mfmacc.s   (fp32 -> fp32)
  val FUNCT_MFMACC_D     = "h46".U(7.W)  // mfmacc.d   (fp64 -> fp64)

  // Float double-widen: AME spec func4=0000, dst=2x src
  val FUNCT_MFMACC_S_H    = "h48".U(7.W)  // mfmacc.s.h    (fp16 -> fp32)
  val FUNCT_MFMACC_S_BF16 = "h49".U(7.W)  // mfmacc.s.bf16 (bf16 -> fp32)
  val FUNCT_MFMACC_D_S    = "h4A".U(7.W)  // mfmacc.d.s    (fp32 -> fp64)
  val FUNCT_MFMACC_H_E4   = "h4B".U(7.W)  // mfmacc.h.e4   (fp8e4m3 -> fp16)
  val FUNCT_MFMACC_H_E5   = "h4C".U(7.W)  // mfmacc.h.e5   (fp8e5m2 -> fp16)
  val FUNCT_MFMACC_BF16_E4 = "h4D".U(7.W) // mfmacc.bf16.e4 (fp8e4m3 -> bf16)
  val FUNCT_MFMACC_BF16_E5 = "h4E".U(7.W) // mfmacc.bf16.e5 (fp8e5m2 -> bf16)

  // Float quad-widen: AME spec func4=0000, dst=4x src
  val FUNCT_MFMACC_S_E4  = "h4F".U(7.W)  // mfmacc.s.e4 (fp8e4m3 -> fp32)
  val FUNCT_MFMACC_S_E5  = "h50".U(7.W)  // mfmacc.s.e5 (fp8e5m2 -> fp32)

  // --- MISC instructions: funct[6:4] = 101 ---
  val FUNCT_MZERO   = "h58".U(7.W)  // mzero: zero accumulator/tile register

  // --- Config instructions: funct[6:4] = 110 ---
  // Matches AME spec func4 ordering: 0000=M, 0001=K, 0010=N
  val FUNCT_MSETTILEM = "h60".U(7.W)  // msettile{m}[i]: set tile M dimension (func4=0000)
  val FUNCT_MSETTILEK = "h61".U(7.W)  // msettile{k}[i]: set tile K dimension (func4=0001)
  val FUNCT_MSETTILEN = "h62".U(7.W)  // msettile{n}[i]: set tile N dimension (func4=0010)
  val FUNCT_MRELEASE  = "h63".U(7.W)  // mrelease: set MS field to Initial

  // --- Fence/status: funct[6:4] = 111 ---
  val FUNCT_FENCE_M   = "h70".U(7.W)  // fence.m: wait for all operations to complete
  val FUNCT_MSTATUS   = "h71".U(7.W)  // query FIFO/pipeline status -> rd

  // ============================================================
  // CSR addresses (AME spec Chapter 3)
  // ============================================================
  val CSR_XMCSR    = 0x802  // matrix control and status register
  val CSR_MTILEM   = 0x803  // tile length in M direction
  val CSR_MTILEN   = 0x804  // tile length in N direction
  val CSR_MTILEK   = 0x805  // tile length in K direction
  val CSR_XMXRM    = 0x806  // fixed-point rounding mode
  val CSR_XMSAT    = 0x807  // fixed-point saturation flag
  val CSR_XMFFLAGS = 0x808  // float-point exception flags
  val CSR_XMFRM    = 0x809  // float-point rounding mode
  val CSR_XMSATEN  = 0x80A  // saturation mode enable (fp8/integer)
  val CSR_XMISA    = 0xCC0  // matrix ISA register (read-only)
  val CSR_XTLENB   = 0xCC1  // tile register size in bytes (read-only)
  val CSR_XTRENB   = 0xCC2  // tile register row size in bytes (read-only)
  val CSR_XALENB   = 0xCC3  // accumulation register size in bytes (read-only)

  // ============================================================
  // Element size encoding (d_size / s_size in AME spec)
  // ============================================================
  val ESIZE_8   = 0.U(2.W)
  val ESIZE_16  = 1.U(2.W)
  val ESIZE_32  = 2.U(2.W)
  val ESIZE_64  = 3.U(2.W)

  // ============================================================
  // Matrix register index encoding (md/ms1/ms2, 3-bit in AME spec)
  // Mapped to RoCC rd/rs1/rs2 5-bit fields (only low 3 bits used)
  // ============================================================
  // 000=tr0, 001=tr1, 010=tr2, 011=tr3
  // 100=acc0, 101=acc1, 110=acc2, 111=acc3

  def isTileReg(idx: UInt): Bool = !idx(2)
  def isAccReg(idx: UInt): Bool = idx(2)

  // ============================================================
  // Instruction classification helpers
  // ============================================================
  def isLoadInst(funct: UInt): Bool = {
    (funct >= "h10".U && funct <= "h1F".U) ||
    (funct >= "h30".U && funct <= "h37".U)
  }
  def isStoreInst(funct: UInt): Bool = {
    (funct >= "h20".U && funct <= "h2F".U) ||
    (funct >= "h38".U && funct <= "h3F".U)
  }
  def isComputeInst(funct: UInt): Bool = funct >= "h40".U && funct <= "h50".U
  def isMiscInst(funct: UInt): Bool = funct >= "h58".U && funct <= "h5F".U
  def isConfigInst(funct: UInt): Bool = funct >= "h60".U && funct <= "h63".U
  def isFenceInst(funct: UInt): Bool = funct >= "h70".U && funct <= "h71".U
  def isAMEInst(funct: UInt): Bool = {
    isLoadInst(funct) || isStoreInst(funct) || isComputeInst(funct) ||
    isMiscInst(funct) || isConfigInst(funct) || isFenceInst(funct)
  }
}