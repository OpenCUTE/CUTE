package cute

import chisel3._
import chisel3.util._
import org.chipsalliance.cde.config._

class AMECommand()(implicit p: Parameters) extends CuteBundle {
  val inst    = UInt(32.W)   // full 32-bit AME instruction word
  val funct   = UInt(7.W)    // RoCC funct field (= inst[31:25] in RoCC encoding)
  val rd_id   = UInt(5.W)
  val rs1_id  = UInt(5.W)
  val rs2_id  = UInt(5.W)
  val rs1_data = UInt(64.W)
  val rs2_data = UInt(64.W)
}

class AMEDecoderIO()(implicit p: Parameters) extends CuteBundle {
  val ame_cmd = Flipped(Valid(new AMECommand))

  val load_inject    = Valid(new LoadMicroInst)
  val load_resource_inject = Valid(new LoadMicroInst_Resource_Info)
  val compute_inject = Valid(new ComputeMicroInst)
  val compute_resource_inject = Valid(new ComputeMicroInst_Resource_Info)
  val store_inject   = Valid(new StoreMicroInst)
  val store_resource_inject = Valid(new StoreMicroInst_Resource_Info)
  val scp_override   = Valid(new SCPControlInfo)

  val load_fifo_full    = Input(Bool())
  val compute_fifo_full = Input(Bool())
  val store_fifo_full   = Input(Bool())
  val all_fifo_empty    = Input(Bool())
  val load_fifo_head    = Input(UInt(2.W))
  val compute_fifo_head = Input(UInt(2.W))
  val stall             = Output(Bool())

  val resp_data  = Output(UInt(64.W))
  val resp_valid = Output(Bool())
  val DebugTimeStampe = Input(UInt(32.W))
}

class AMEDecoder()(implicit p: Parameters) extends CuteModule {
  val io = IO(new AMEDecoderIO)

  // --- AME CSR Registers ---
  val csr_mtilem = RegInit(Tensor_M.U(ScaratchpadMaxTensorDimBitSize.W))
  val csr_mtilen = RegInit(Tensor_N.U(ScaratchpadMaxTensorDimBitSize.W))
  val csr_mtilek = RegInit(ReduceGroupSize.U(ScaratchpadMaxTensorDimBitSize.W))
  val csr_xmcsr  = RegInit(0.U(64.W))

  // Read-only CSR constants
  val csr_xmisa  = (1.U(64.W)) // INT8 support
  val csr_xtlenb = (Tensor_M * ReduceGroupSize * ReduceWidthByte).U(64.W)
  val csr_xtrenb = ReduceWidthByte.U(64.W)
  val csr_xalenb = (Tensor_M * Tensor_N * ResultWidthByte).U(64.W)

  // --- Instruction fields ---
  val cmd_valid = io.ame_cmd.valid
  val inst      = io.ame_cmd.bits.inst   // full 32-bit AME instruction
  val rs1_data  = io.ame_cmd.bits.rs1_data
  val rs2_data  = io.ame_cmd.bits.rs2_data

  // AME native 32-bit instruction field extraction (per insts spec & ame.h)
  val inst_func4    = inst(31, 28)        // instruction sub-type
  val inst_uop      = inst(27, 26)        // 00=config, 01=load/store, 10=matmul, 11=misc
  val inst_size_sup = inst(25, 23)        // matmul: type info [25:23]
  val inst_imm_sel  = inst(25)            // config: 0=imm, 1=register
  val inst_ls       = inst(25)            // load/store: 0=load, 1=store
  val inst_rs2      = inst(24, 20)        // load/store: rs2 (stride register)
  val inst_ms2      = inst(22, 20)        // matmul: source 2 matrix register (B)
  val inst_rs1      = inst(19, 15)        // config/load/store: rs1
  val inst_s_size   = inst(19, 18)        // matmul: source element size
  val inst_ms1      = inst(17, 15)        // matmul: source 1 matrix register (A)
  val inst_d_size   = inst(11, 10)        // load/store/matmul: element size
  val inst_md       = inst(9, 7)          // destination matrix register

  // --- Instruction classification (based on uop and func4) ---
  // uop=00: config
  val is_config     = cmd_valid && inst_uop === 0.U
  val is_msettilem  = is_config && inst_func4 === 0.U && inst_imm_sel === 1.U
  val is_msettilek  = is_config && inst_func4 === 1.U && inst_imm_sel === 1.U
  val is_msettilen  = is_config && inst_func4 === 2.U && inst_imm_sel === 1.U
  val is_mrelease   = is_config && inst === "h0000002B".U  // all zeros except opcode=0x2B

  // uop=01: load/store
  val is_ldst       = cmd_valid && inst_uop === 1.U
  val is_load       = is_ldst && !inst_ls
  val is_store      = is_ldst && inst_ls
  // func4 determines matrix type: 0=A, 1=B, 2=C, 4=At, 5=Bt, 6=Ct, 8=whole
  val is_load_a     = is_load && (inst_func4 === 0.U || inst_func4 === 4.U)
  val is_load_b     = is_load && (inst_func4 === 1.U || inst_func4 === 5.U)
  val is_load_c     = is_load && (inst_func4 === 2.U || inst_func4 === 6.U)
  val is_store_c    = is_store && (inst_func4 === 2.U || inst_func4 === 6.U)
  val is_transpose  = cmd_valid && (inst_func4 === 4.U || inst_func4 === 5.U || inst_func4 === 6.U)

  // uop=10: matrix multiplication
  val is_compute    = cmd_valid && inst_uop === 2.U

  // uop=11: misc
  val is_misc       = cmd_valid && inst_uop === 3.U
  val is_mzero      = is_misc && inst_func4 === 0.U

  // fence.m and mstatus are handled at CUTE2YGJK level, never reach AMEDecoder
  val funct         = io.ame_cmd.bits.funct

  // --- Stall logic ---
  // Stall must NOT depend on cmd_valid to avoid combinational cycle.
  // Uses inst fields (pure data path from io.cmd.bits) and FIFO status.
  // fence.m stall is handled at CUTE2YGJK level.
  val would_load    = inst_uop === 1.U && !inst_ls  // load
  val would_mzero   = inst_uop === 3.U && inst_func4 === 0.U  // mzero
  val would_compute = inst_uop === 2.U  // matmul
  val would_store   = inst_uop === 1.U && inst_ls  // store

  val load_stall    = (would_load || would_mzero) && io.load_fifo_full
  val compute_stall = would_compute && io.compute_fifo_full
  val store_stall   = would_store && io.store_fifo_full
  io.stall := load_stall || compute_stall || store_stall

  // --- CSR write handling ---
  when(is_msettilem) {
    csr_mtilem := Mux(rs1_data(ScaratchpadMaxTensorDimBitSize-1, 0) > Tensor_M.U,
                      Tensor_M.U, rs1_data(ScaratchpadMaxTensorDimBitSize-1, 0))
  }
  when(is_msettilen) {
    csr_mtilen := Mux(rs1_data(ScaratchpadMaxTensorDimBitSize-1, 0) > Tensor_N.U,
                      Tensor_N.U, rs1_data(ScaratchpadMaxTensorDimBitSize-1, 0))
  }
  when(is_msettilek) {
    csr_mtilek := Mux(rs1_data(ScaratchpadMaxTensorDimBitSize-1, 0) > ReduceGroupSize.U,
                      ReduceGroupSize.U, rs1_data(ScaratchpadMaxTensorDimBitSize-1, 0))
  }
  when(is_mrelease) {
    csr_mtilem := Tensor_M.U
    csr_mtilen := Tensor_N.U
    csr_mtilek := ReduceGroupSize.U
    csr_xmcsr  := 0.U
  }

  // --- Response (CSR read / status query) ---
  // resp_valid/resp_data: no longer used (mstatus handled at CUTE2YGJK level)
  io.resp_valid := false.B
  io.resp_data  := 0.U

  // --- SCP bank selection from native instruction register fields ---
  // AME spec: md/ms1/ms2 are 3-bit, 000-011=tr0-tr3, 100-111=acc0-acc3
  // tr0→ASCP[0], tr1→ASCP[1], tr2→BSCP[0], tr3→BSCP[1]
  // acc0→CSCP[0], acc1→CSCP[1]
  // For load/store: inst_md[9:7] is the target/source matrix register
  // For compute: inst_ms1=A source, inst_ms2=B source, inst_md=C dest (acc)
  val a_scp_bank = Wire(UInt(1.W))
  val b_scp_bank = Wire(UInt(1.W))
  val c_scp_bank = Wire(UInt(1.W))

  a_scp_bank := Mux(is_load_a, inst_md(0), inst_ms1(0))
  b_scp_bank := Mux(is_load_b, inst_md(0), inst_ms2(0))
  c_scp_bank := inst_md(0)

  // --- SCP override output ---
  io.scp_override.valid := (is_load || is_mzero || is_compute || is_store) && !io.stall
  io.scp_override.bits  := 0.U.asTypeOf(new SCPControlInfo)
  when(is_load_a || is_compute) {
    io.scp_override.bits.AML_SCP_ID := a_scp_bank
    io.scp_override.bits.ADC_SCP_ID := a_scp_bank
  }
  when(is_load_b || is_compute) {
    io.scp_override.bits.BML_SCP_ID := b_scp_bank
    io.scp_override.bits.BDC_SCP_ID := b_scp_bank
  }
  when(is_load_c || is_mzero || is_compute || is_store) {
    io.scp_override.bits.CML_SCP_ID := c_scp_bank
    io.scp_override.bits.CDC_SCP_ID := c_scp_bank
  }

  // --- Load micro-instruction generation ---
  val load_inst = Wire(new LoadMicroInst)
  load_inst := 0.U.asTypeOf(new LoadMicroInst)

  // Derive datatype from instruction's d_size field for load/store
  // d_size: 00=8bit, 01=16bit, 10=32bit, 11=64bit
  // Map to CUTE ElementDataType (used for address stride calculation)
  val ls_datatype = Wire(UInt(ElementDataType.DataTypeBitWidth.W))
  ls_datatype := ElementDataType.DataTypeI8I8I32 // default: 8-bit
  switch(inst_d_size) {
    is("b00".U) { ls_datatype := ElementDataType.DataTypeI8I8I32 }      // 8-bit
    is("b01".U) { ls_datatype := ElementDataType.DataTypeF16F16F32 }    // 16-bit
    is("b10".U) { ls_datatype := ElementDataType.DataTypeTF32TF32F32 }  // 32-bit
  }

  load_inst.ApplicationTensor_A.ApplicationTensor_A_BaseVaddr := rs1_data(MMUAddrWidth-1, 0)
  load_inst.ApplicationTensor_A.BlockTensor_A_BaseVaddr       := rs1_data(MMUAddrWidth-1, 0)
  load_inst.ApplicationTensor_A.ApplicationTensor_A_Stride_M  := rs2_data(MMUAddrWidth-1, 0)
  load_inst.ApplicationTensor_A.dataType                      := ls_datatype
  load_inst.ApplicationTensor_A.Convolution_OH_DIM_Length     := 0.U
  load_inst.ApplicationTensor_A.Convolution_OW_DIM_Length     := 0.U
  load_inst.ApplicationTensor_A.Convolution_Stride_H          := 0.U
  load_inst.ApplicationTensor_A.Convolution_Stride_W          := 0.U
  load_inst.ApplicationTensor_A.Convolution_KH_DIM_Length     := 0.U
  load_inst.ApplicationTensor_A.Convolution_KW_DIM_Length     := 0.U

  load_inst.ApplicationTensor_B.ApplicationTensor_B_BaseVaddr := rs1_data(MMUAddrWidth-1, 0)
  load_inst.ApplicationTensor_B.BlockTensor_B_BaseVaddr       := rs1_data(MMUAddrWidth-1, 0)
  load_inst.ApplicationTensor_B.ApplicationTensor_B_Stride_N  := rs2_data(MMUAddrWidth-1, 0)
  load_inst.ApplicationTensor_B.dataType                      := ls_datatype
  load_inst.ApplicationTensor_B.Convolution_KH_DIM_Length     := 0.U
  load_inst.ApplicationTensor_B.Convolution_KW_DIM_Length     := 0.U

  load_inst.ApplicationScale_A := 0.U.asTypeOf(new ApplicationScale_A_Info)
  load_inst.ApplicationScale_B := 0.U.asTypeOf(new ApplicationScale_B_Info)

  load_inst.ApplicationTensor_C.ApplicationTensor_C_BaseVaddr := rs1_data(MMUAddrWidth-1, 0)
  load_inst.ApplicationTensor_C.BlockTensor_C_BaseVaddr       := rs1_data(MMUAddrWidth-1, 0)
  load_inst.ApplicationTensor_C.ApplicationTensor_C_Stride_M  := rs2_data(MMUAddrWidth-1, 0)
  load_inst.ApplicationTensor_C.dataType                      := ls_datatype

  load_inst.CLoadTaskInfo.Is_ZeroLoad      := is_mzero
  load_inst.CLoadTaskInfo.Is_RepeatRowLoad := false.B
  load_inst.CLoadTaskInfo.Is_FullLoad      := is_load_c

  load_inst.ScaratchpadTensor_M := csr_mtilem
  load_inst.ScaratchpadTensor_N := csr_mtilen
  load_inst.ScaratchpadTensor_K := csr_mtilek

  load_inst.Convolution_Current_OH_Index := 0.U
  load_inst.Convolution_Current_OW_Index := 0.U
  load_inst.Convolution_Current_KH_Index := 0.U
  load_inst.Convolution_Current_KW_Index := 0.U

  load_inst.ConherentA := true.B
  load_inst.ConherentB := true.B
  load_inst.ConherentC := true.B

  load_inst.Is_A_Work       := is_load_a
  load_inst.Is_B_Work       := is_load_b
  load_inst.Is_A_Scale_Work := false.B
  load_inst.Is_B_Scale_Work := false.B
  load_inst.Is_C_Work       := is_load_c || is_mzero

  load_inst.A_SCPID := a_scp_bank
  load_inst.B_SCPID := b_scp_bank
  load_inst.C_SCPID := c_scp_bank

  load_inst.IsTranspose := is_transpose

  io.load_inject.valid := (is_load || is_mzero) && !io.stall
  io.load_inject.bits  := load_inst

  val load_resource = Wire(new LoadMicroInst_Resource_Info)
  load_resource.A_SCPID := a_scp_bank
  load_resource.B_SCPID := b_scp_bank
  load_resource.C_SCPID := c_scp_bank
  io.load_resource_inject.valid := io.load_inject.valid
  io.load_resource_inject.bits  := load_resource

  // --- Compute micro-instruction generation ---
  val compute_inst = Wire(new ComputeMicroInst)
  compute_inst := 0.U.asTypeOf(new ComputeMicroInst)

  // Decode data type from native 32-bit AME instruction fields (per insts spec)
  // inst_func4: 0000=float, 0001=integer, 0010=integer hybrid
  // inst_size_sup[25:23]: signedness and fp8 type info
  // inst_s_size[19:18]: source element size (00=8b, 01=16b, 10=32b, 11=64b)
  // inst_d_size[11:10]: dest element size
  val ame_datatype = Wire(UInt(ElementDataType.DataTypeBitWidth.W))
  ame_datatype := ElementDataType.DataTypeI8I8I32 // default

  when(inst_func4 === "b0001".U) {
    // Integer matrix multiplication (func4=0001)
    // inst[24]=ms1 sign, inst[23]=ms2 sign, inst[25]: 0=int8, 1=int4
    val ms1_signed = inst(24)
    val ms2_signed = inst(23)
    when(ms1_signed && ms2_signed)        { ame_datatype := ElementDataType.DataTypeI8I8I32 }   // mmacc.w.b
    .elsewhen(!ms1_signed && !ms2_signed) { ame_datatype := ElementDataType.DataTypeU8U8I32 }   // mmaccu.w.b
    .elsewhen(ms1_signed && !ms2_signed)  { ame_datatype := ElementDataType.DataTypeI8U8I32 }   // mmaccsu.w.b
    .elsewhen(!ms1_signed && ms2_signed)  { ame_datatype := ElementDataType.DataTypeU8I8I32 }   // mmaccus.w.b
  }.elsewhen(inst_func4 === "b0000".U) {
    // Float matrix multiplication (func4=0000)
    val is_hybrid = inst(24)    // 1=hybrid/widen, 0=same-precision
    val half_is_bf16 = inst(25) // when half-precision present: 0=fp16, 1=bf16
    val fp8_is_e4m3 = inst(23)  // when fp8: 0=E5M2, 1=E4M3

    when(!is_hybrid) {
      // Non-widen: src_size == dst_size
      switch(inst_s_size) {
        is("b01".U) { ame_datatype := ElementDataType.DataTypeF16F16F32 }   // mfmacc.h (fp16)
        is("b10".U) { ame_datatype := ElementDataType.DataTypeTF32TF32F32 } // mfmacc.s (fp32)
      }
    }.otherwise {
      // Widen/hybrid precision
      when(inst_s_size === "b01".U) {
        // 16-bit source -> 32-bit dest (double-widen)
        when(!half_is_bf16) { ame_datatype := ElementDataType.DataTypeF16F16F32 }    // mfmacc.s.h
        .otherwise          { ame_datatype := ElementDataType.DataTypeBF16BF16F32 }  // mfmacc.s.bf16
      }.elsewhen(inst_s_size === "b00".U) {
        // 8-bit source (fp8)
        when(inst_d_size === "b01".U) {
          // fp8 -> fp16 (double-widen)
          when(fp8_is_e4m3) { ame_datatype := ElementDataType.DataTypeMxfp8e4m3F32 } // mfmacc.h.e4
          .otherwise        { ame_datatype := ElementDataType.DataTypeMxfp8e5m2F32 } // mfmacc.h.e5
        }.elsewhen(inst_d_size === "b10".U) {
          // fp8 -> fp32 (quad-widen)
          when(fp8_is_e4m3) { ame_datatype := ElementDataType.DataTypefp8e4m3F32 }   // mfmacc.s.e4
          .otherwise        { ame_datatype := ElementDataType.DataTypefp8e5m2F32 }   // mfmacc.s.e5
        }
      }.elsewhen(inst_s_size === "b10".U) {
        // fp32 -> fp64 (double-widen): mfmacc.d.s
        ame_datatype := ElementDataType.DataTypeTF32TF32F32 // closest mapping
      }
    }
  }

  compute_inst.DataType   := ame_datatype
  compute_inst.DataType_A := ame_datatype
  compute_inst.DataType_B := ame_datatype
  compute_inst.DataType_C := ame_datatype
  compute_inst.DataType_D := ame_datatype

  compute_inst.Have_Aops             := false.B
  compute_inst.Is_AfterOps_Tile      := false.B
  compute_inst.Is_Transpose          := false.B
  compute_inst.Is_Reorder_Only_Ops   := false.B
  compute_inst.Is_EasyScale_Only_Ops := false.B
  compute_inst.Is_VecFIFO_Ops        := false.B

  compute_inst.ScaratchpadTensor_M := csr_mtilem
  compute_inst.ScaratchpadTensor_N := csr_mtilen
  compute_inst.ScaratchpadTensor_K := csr_mtilek
  compute_inst.Have_Store_Micro_Inst := false.B

  io.compute_inject.valid := is_compute && !io.stall
  io.compute_inject.bits  := compute_inst

  val compute_resource = Wire(new ComputeMicroInst_Resource_Info)
  compute_resource.A_SCPID := a_scp_bank
  compute_resource.B_SCPID := b_scp_bank
  compute_resource.C_SCPID := c_scp_bank
  // Point to the last enqueued Load entry. Since Load FIFO has depth 4 (2-bit index),
  // after Load injection head has advanced, so the last Load is at (head-1) mod 4.
  // Load is executed sequentially, so when the last Load finishes, all prior Loads
  // are guaranteed to have finished already.
  compute_resource.Load_Micro_Inst_FIFO_Index := (io.load_fifo_head - 1.U)(1, 0)
  io.compute_resource_inject.valid := io.compute_inject.valid
  io.compute_resource_inject.bits  := compute_resource

  // --- Store micro-instruction generation ---
  val store_inst = Wire(new StoreMicroInst)
  store_inst := 0.U.asTypeOf(new StoreMicroInst)

  store_inst.ApplicationTensor_D.ApplicationTensor_D_BaseVaddr := rs1_data(MMUAddrWidth-1, 0)
  store_inst.ApplicationTensor_D.BlockTensor_D_BaseVaddr       := rs1_data(MMUAddrWidth-1, 0)
  store_inst.ApplicationTensor_D.ApplicationTensor_D_Stride_M  := rs2_data(MMUAddrWidth-1, 0)
  store_inst.ApplicationTensor_D.dataType                      := ls_datatype

  store_inst.Conherent          := true.B
  store_inst.Is_Transpose       := is_transpose
  store_inst.ScaratchpadTensor_M := csr_mtilem
  store_inst.ScaratchpadTensor_N := csr_mtilen
  store_inst.Is_Last_Store       := true.B

  io.store_inject.valid := is_store && !io.stall
  io.store_inject.bits  := store_inst

  val store_resource = Wire(new StoreMicroInst_Resource_Info)
  store_resource.C_SCPID := c_scp_bank
  // Point to the last enqueued Compute entry: (head-1) mod 4.
  store_resource.Compute_Micro_Inst_FIFO_Index := (io.compute_fifo_head - 1.U)(1, 0)
  store_resource.Marco_Inst_FIFO_Index := 0.U
  io.store_resource_inject.valid := io.store_inject.valid
  io.store_resource_inject.bits  := store_resource

  // --- ZZH Debug prints ---
  if (ZZHDebugEnable) {
    when(cmd_valid) {
      printf("[AME-DEC %d] inst=%x uop=%d func4=%d md=%d ms1=%d ms2=%d d_size=%d s_size=%d size_sup=%d\n",
        io.DebugTimeStampe, inst, inst_uop, inst_func4, inst_md, inst_ms1, inst_ms2, inst_d_size, inst_s_size, inst_size_sup)
    }
    when(io.load_inject.valid) {
      printf("[AME-DEC %d] LOAD inject: is_A=%d is_B=%d is_C=%d is_mzero=%d a_bank=%d b_bank=%d c_bank=%d M=%d N=%d K=%d\n",
        io.DebugTimeStampe,is_load_a, is_load_b, is_load_c, is_mzero, a_scp_bank, b_scp_bank, c_scp_bank,
        csr_mtilem, csr_mtilen, csr_mtilek)
    }
    when(io.compute_inject.valid) {
      printf("[AME-DEC %d] COMPUTE inject: datatype=%d a_bank=%d b_bank=%d c_bank=%d dep_load_idx=%d M=%d N=%d K=%d\n",
        io.DebugTimeStampe,ame_datatype, a_scp_bank, b_scp_bank, c_scp_bank,
        compute_resource.Load_Micro_Inst_FIFO_Index, csr_mtilem, csr_mtilen, csr_mtilek)
    }
    when(io.store_inject.valid) {
      printf("[AME-DEC] STORE inject: c_bank=%d dep_compute_idx=%d addr=%x stride=%x M=%d N=%d\n",
        c_scp_bank, store_resource.Compute_Micro_Inst_FIFO_Index,
        rs1_data, rs2_data, csr_mtilem, csr_mtilen)
    }
    when(is_config) {
      printf("[AME-DEC %d] CONFIG: funct=%x mtilem=%d mtilen=%d mtilek=%d\n",
        io.DebugTimeStampe,funct, csr_mtilem, csr_mtilen, csr_mtilek)
    }
    when(io.stall) {
      printf("[AME-DEC] STALL: load_full=%d compute_full=%d store_full=%d fence_wait=%d\n",
        io.load_fifo_full, io.compute_fifo_full, io.store_fifo_full, false.B)
    }
  }
}
