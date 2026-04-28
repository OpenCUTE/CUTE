# Layer 1: Python 驱动的模块级测试框架 (cocotb) — 详细实施计划

## Context

CUTE 有 22 个 Chisel3 硬件模块，当前零模块级测试。任何 bug 都只能通过全系统 SoC 仿真（Verilator + 软件驱动）发现，定位慢、迭代慢。

**本阶段目标**：
1. 建立 cocotb + Verilator 的 Python 驱动测试框架
2. 为每个核心模块编写 Verilog wrapper + Python 测试
3. 实现快速迭代：单个模块秒级验证，无需编译整个 SoC

**关键约束**：
- Chisel3 生成的 Verilog 端口命名规则：`io.BundleName_FieldName`（下划线分隔，展平嵌套）
- 生成的是 SystemVerilog (.sv) 文件
- 模块名直接等于 Chisel class 名（1:1 映射）
- Clock/Reset 固定命名 `clock` / `reset`
- 所有 DecoupledIO 的 valid/ready/bits 展平为独立端口

---

## Step 1: 创建 Layer 1 目录结构

```
CUTE/layer1/cocotb/
├── Makefile                          # 顶层 make: make -C layer1/cocotb
├── common/
│   ├── __init__.py
│   ├── cute_params.py                # Python 镜像硬件参数
│   ├── cute_utils.py                 # 随机数据、位操作、FP 转换
│   └── cute_test_utils.py            # cocotb 通用 helper (reset, wait_valid)
├── tests/
│   ├── test_reduce_pe/
│   │   ├── Makefile
│   │   ├── test_reduce_pe.py
│   │   ├── conftest.py               # 参数化配置
│   │   └── verilog/ReducePETop.sv
│   ├── test_matrix_te/
│   │   ├── Makefile
│   │   ├── test_matrix_te.py
│   │   └── verilog/MatrixTETop.sv
│   ├── test_task_controller/
│   ├── test_local_mmu/
│   ├── test_a_scratchpad/
│   ├── test_c_scratchpad/
│   ├── test_a_data_controller/
│   ├── test_c_data_controller/
│   ├── test_a_memory_loader/
│   ├── test_c_memory_loader/
│   ├── test_after_ops/
│   ├── test_a_scale_loader/
│   ├── test_a_scale_controller/
│   ├── test_a_scale_scratchpad/
│   └── test_cute2tl_node/
```

注意：B 系列模块（BScratchpad, BDataController, BMemoryLoader, BScaleLoader, BScaleController, BScaleScratchpad）与 A 系列结构对称，测试模式相同，放在 Phase 2 扩展。

---

## Step 2: 环境安装

### 2.1 `scripts/setup-cocotb.sh`

```bash
#!/bin/bash
set -e
pip3 install cocotb pytest cocotb-bus
# Verilator 需要 >= 5.0，Chipyard 已自带
verilator --version
cocotb-config --version
```

### 2.2 Python 参数镜像 `common/cute_params.py`

精确镜像 `CUTEParameters.scala` 中 CUTE_2TopsSCP64 配置的参数：

```python
CUTE_PARAMS = {
    # 数据通路宽度 (bits)
    'outsideDataWidth':      512,
    'outsideDataWidthByte':  64,
    'memoryDataWidth':       64,
    'reduceWidthByte':       64,
    'reduceWidth':           512,   # reduceWidthByte * 8
    'vectorWidth':           256,
    'resultWidthByte':       4,
    'resultWidth':           32,    # resultWidthByte * 8
    'scaleWidth':            128,   # reduceWidthByte * ScaleElementWidth / MinDataTypeWidth / MinGroupSize
    # 张量维度
    'tensorM':               64,
    'tensorN':               64,
    'tensorK':               64,
    'matrixM':               4,
    'matrixN':               4,
    # MMU
    'mmuAddrWidth':          39,
    'llcSourceMaxNum':       64,
    'memorySourceMaxNum':    64,
    # FIFO
    'marcoInstFifoDepth':    4,
    'resultFifoDepth':       8,
    # Scratchpad
    'reduceGroupSize':       2,
    'aScratchpadNBanks':     4,     # = matrixM
    'bScratchpadNBanks':     4,     # = matrixN
    'cScratchpadNBanks':     4,     # = matrixN
}
```

### 2.3 通用 helper `common/cute_test_utils.py`

```python
import cocotb
from cocotb.triggers import RisingEdge, Timer

async def reset_dut(dut, cycles=2):
    """Standard reset sequence."""
    dut.reset.value = 1
    for _ in range(cycles):
        await RisingEdge(dut.clock)
    dut.reset.value = 0
    await RisingEdge(dut.clock)

async def wait_for_signal(signal, timeout_cycles=1000):
    """Wait until signal is high, raise on timeout."""
    for _ in range(timeout_cycles):
        if signal.value:
            return
        await RisingEdge(signal.value if hasattr(signal, 'value') else cocotb.clk)
    raise TimeoutError(f"Signal not asserted within {timeout_cycles} cycles")

async def drive_valid_ready(driver, data, dut_ready_signal, max_cycles=100):
    """Drive a valid/ready handshake with data."""
    driver.valid.value = 1
    driver.bits.value = data
    for _ in range(max_cycles):
        await RisingEdge(dut.clock)
        if dut_ready_signal.value:
            driver.valid.value = 0
            return True
    driver.valid.value = 0
    return False
```

---

## Step 3: 获取 Chisel 生成的 Verilog

### 构建流程

```bash
# 1. 生成 Verilog (已有脚本)
cd /root/opencute/CUTE
bash scripts/build-verilog.sh CUTE2TopsSCP64Config

# 2. 生成的 Verilog 位置
VERILOG_DIR=build/chipyard/generated-src/chipyard.harness.TestHarness.CUTE2TopsSCP64Config/gen-collateral/
# 关键文件: FReducePE.sv, MatrixTE.sv, AScratchpad.sv, etc.
```

### Chisel3 → Verilog 命名规则（关键）

| Chisel | Verilog |
|--------|---------|
| `class FReducePE` | `module FReducePE` |
| `io.AVector.valid` | `io_AVector_valid` |
| `io.AVector.ready` | `io_AVector_ready` |
| `io.AVector.bits` | `io_AVector_bits` |
| `io.ConfigInfo.foo` | `io_ConfigInfo_foo` |
| `io.ScarchPadIO.FromDataController.BankAddr.valid` | `io_ScarchPadIO_FromDataController_BankAddr_valid` |

---

## Step 4: Verilog Wrapper 设计模式

### 4.1 通用 Wrapper 模式

每个被测模块需要一个薄 SystemVerilog wrapper，作用：
1. 将 Chisel 生成的模块例化
2. 展平所有嵌套 Bundle 为顶层端口
3. 暴露 clock/reset

### 4.2 ReducePE Wrapper (`test_reduce_pe/verilog/ReducePETop.sv`)

```systemverilog
module ReducePETop(
    input  logic        clock,
    input  logic        reset,
    // AVector: Flipped(DecoupledIO(UInt(512)))
    input  logic                    io_AVector_valid,
    output logic                    io_AVector_ready,
    input  logic [511:0]            io_AVector_bits,
    // BVector: Flipped(DecoupledIO(UInt(512)))
    input  logic                    io_BVector_valid,
    output logic                    io_BVector_ready,
    input  logic [511:0]            io_BVector_bits,
    // CAdd: Flipped(DecoupledIO(UInt(32)))
    input  logic                    io_CAdd_valid,
    output logic                    io_CAdd_ready,
    input  logic [31:0]             io_CAdd_bits,
    // AScale: Flipped(DecoupledIO(UInt(128)))
    input  logic                    io_AScale_valid,
    output logic                    io_AScale_ready,
    input  logic [127:0]            io_AScale_bits,
    // BScale: Flipped(DecoupledIO(UInt(128)))
    input  logic                    io_BScale_valid,
    output logic                    io_BScale_ready,
    input  logic [127:0]            io_BScale_bits,
    // DResult: DecoupledIO(UInt(32))
    output logic                    io_DResult_valid,
    input  logic                    io_DResult_ready,
    output logic [31:0]             io_DResult_bits,
    // Config
    input  logic [3:0]             io_opcode
);
    FReducePE dut (.*);
endmodule
```

**注意**：端口名用 `io_` 前缀匹配 Chisel 生成的命名。wrapper 用 `(.*)` 自动连接同名信号。

### 4.3 MatrixTE Wrapper (`test_matrix_te/verilog/MatrixTETop.sv`)

```systemverilog
module MatrixTETop(
    input  logic                              clock,
    input  logic                              reset,
    // VectorA: Flipped(DecoupledIO(UInt(2048)))  = ReduceWidth*Matrix_M
    input  logic                              io_VectorA_valid,
    output logic                              io_VectorA_ready,
    input  logic [2047:0]                     io_VectorA_bits,
    // VectorB: Flipped(DecoupledIO(UInt(2048)))  = ReduceWidth*Matrix_N
    input  logic                              io_VectorB_valid,
    output logic                              io_VectorB_ready,
    input  logic [2047:0]                     io_VectorB_bits,
    // ScaleA: Flipped(DecoupledIO(UInt(512)))     = ScaleWidth*Matrix_M
    input  logic                              io_ScaleA_valid,
    output logic                              io_ScaleA_ready,
    input  logic [511:0]                      io_ScaleA_bits,
    // ScaleB: Flipped(DecoupledIO(UInt(512)))
    input  logic                              io_ScaleB_valid,
    output logic                              io_ScaleB_ready,
    input  logic [511:0]                      io_ScaleB_bits,
    // MatirxC: Flipped(DecoupledIO(UInt(512)))   = ResultWidth*Matrix_M*Matrix_N = 32*16
    input  logic                              io_MatirxC_valid,
    output logic                              io_MatirxC_ready,
    input  logic [511:0]                      io_MatirxC_bits,
    // MatrixD: DecoupledIO(UInt(512))
    output logic                              io_MatrixD_valid,
    input  logic                              io_MatrixD_ready,
    output logic [511:0]                      io_MatrixD_bits,
    // ConfigInfo: MTEMicroTaskConfigIO (需要展开)
    input  logic                              io_ConfigInfo_valid,
    output logic                              io_ConfigInfo_ready,
    input  logic                              io_ConfigInfo_bits_*,  // 具体字段见 ConfigIO 定义
    // ComputeGo
    output logic                              io_ComputeGo,
    // DebugInfo
    input  logic [63:0]                       io_DebugInfo_DebugTimeStampe
);
    MatrixTE dut (.*);
endmodule
```

**注意**：MatrixTE 的 ConfigInfo 是一个复杂 Bundle，wrapper 中需要展平所有字段。具体字段名需要查看生成 Verilog 确认。

### 4.4 Scratchpad Wrapper 模式

Scratchpad 的 IO 通过嵌套 Bundle（`FromDataController` / `FromMemoryLoader`）组织。Wrapper 需要展平：

```systemverilog
module AScratchpadTop(
    input  logic        clock,
    input  logic        reset,
    // FromDataController 接口
    input  logic                                 io_ScarchPadIO_FromDataController_BankAddr_valid,
    output logic                                 io_ScarchPadIO_FromDataController_BankAddr_ready,
    input  logic [BANK_ADDR_W-1:0]               io_ScarchPadIO_FromDataController_BankAddr_bits,
    input  logic                                 io_ScarchPadIO_FromDataController_Data_valid,
    output logic                                 io_ScarchPadIO_FromDataController_Data_ready,
    input  logic [ENTRY_W-1:0]                   io_ScarchPadIO_FromDataController_Data_bits_0,
    // ... 其他 bank 的 Data
    // FromMemoryLoader 接口
    // ... 类似结构
);
    AScratchpad dut (.*);
endmodule
```

---

## Step 5: 每个 cocotb 测试的 Makefile 模板

```makefile
# test_reduce_pe/Makefile
SIM ?= verilator
TOPLEVEL_LANG = systemverilog
VERILOG_SOURCES = $(shell pwd)/verilog/ReducePETop.sv
VERILOG_SOURCES += $(CUTE_VERILOG_DIR)/FReducePE.sv
# 如果 FReducePE 依赖其他子模块，递归添加:
# VERILOG_SOURCES += $(wildcard $(CUTE_VERILOG_DIR)/BlackBox*.sv)

TOPLEVEL = ReducePETop
MODULE = test_reduce_pe

# cocotb + Verilator 参数
EXTRA_ARGS = --trace --trace-structs
SIM_BUILD = sim_build

include $(shell cocotb-config makefile)/Makefile.sim
```

环境变量 `CUTE_VERILOG_DIR` 由顶层 Makefile 设置。

### 顶层 Makefile

```makefile
# layer1/cocotb/Makefile
CUTE_ROOT ?= $(shell cd ../.. && pwd)
CONFIG ?= CUTE2TopsSCP64Config
CUTE_VERILOG_DIR ?= $(CUTE_ROOT)/build/chipyard/generated-src/chipyard.harness.TestHarness.$(CONFIG)/gen-collateral
export CUTE_VERILOG_DIR

.PHONY: all test_reduce_pe test_matrix_te test_a_scratchpad test_task_controller

all: test_reduce_pe test_matrix_te

test_reduce_pe:
	$(MAKE) -C tests/test_reduce_pe

test_matrix_te:
	$(MAKE) -C tests/test_matrix_te

test_a_scratchpad:
	$(MAKE) -C tests/test_a_scratchpad

# ... 其他模块
```

---

## Step 6: 优先模块的测试设计

### 6.1 ReducePE 测试 (`test_reduce_pe.py`) — 最高优先级

**被测模块**: `FReducePE`
**功能**: MAC (Multiply-Accumulate) 单元，支持 13 种数据类型
**端口宽度**:
- AVector: 512 bits (ReduceWidth)
- BVector: 512 bits (ReduceWidth)
- CAdd: 32 bits (ResultWidth)
- AScale: 128 bits (ScaleWidth)
- BScale: 128 bits (ScaleWidth)
- DResult: 32 bits (ResultWidth)
- opcode: 4 bits

**测试用例**:

| 测试名 | opcode | 描述 | 验证方法 |
|--------|--------|------|----------|
| `test_i8_mac_basic` | 0 | 32 对 int8 相乘累加 | DResult == 32 个 a[i]*b[i] 之和 |
| `test_i8_mac_accumulate` | 0 | 连续多拍累加 | 第一拍 C=0, 第二拍 C=第一拍结果 |
| `test_i8_mac_zero_a` | 0 | A 全零 | DResult == CAdd |
| `test_i8_mac_zero_b` | 0 | B 全零 | DResult == CAdd |
| `test_i8_mac_overflow` | 0 | 最大值测试 | 检查饱和/溢出行为 |
| `test_f16_mac_basic` | 1 | FP16 MAC | DResult ≈ expected (允许 1 ULP 误差) |
| `test_bf16_mac_basic` | 2 | BF16 MAC | 同上 |
| `test_tf32_mac_basic` | 3 | TF32 MAC | 同上 |
| `test_fp8e4m3_mac_basic` | 7 | MXFP8 E4M3 MAC | DResult ≈ expected |
| `test_backpressure` | 0 | DResult_ready 拉低 | 验证 valid 保持、不会丢数据 |

```python
@cocotb.test()
async def test_i8_mac_basic(dut):
    """32 对 int8 相乘累加: sum(A[i]*B[i]) + C"""
    await reset_dut(dut)
    dut.io_opcode.value = 0  # CUTEDataTypeI8I8I32

    # 准备数据: 32 个 int8 = 1, B = 2 → sum = 32*2 = 64
    dut.io_AVector_bits.value = int('01' * 32, 16)
    dut.io_BVector_bits.value = int('02' * 32, 16)
    dut.io_CAdd_bits.value = 0

    dut.io_AVector_valid.value = 1
    dut.io_BVector_valid.value = 1
    dut.io_CAdd_valid.value = 1
    dut.io_AScale_valid.value = 0
    dut.io_BScale_valid.value = 0
    dut.io_DResult_ready.value = 1

    # 等待计算完成
    for _ in range(200):
        await RisingEdge(dut.clock)
        if dut.io_DResult_valid.value:
            result = int(dut.io_DResult_bits.value)
            assert result == 64, f"Expected 64, got {result}"
            return
    raise AssertionError("No DResult within 200 cycles")
```

### 6.2 AScratchpad 测试 (`test_a_scratchpad.py`)

**被测模块**: `AScratchpad`
**功能**: 双缓冲 SRAM，4 bank (AScratchpadNBanks=Matrix_M=4)
**IO**: 通过 `ScarchPadIO` Bundle，分 `FromDataController` 和 `FromMemoryLoader` 两个子接口

**端口** (需要从生成 Verilog 确认确切名):
- MemoryLoader 写路径: BankAddr, Data (per-bank), BankId
- DataController 读路径: BankAddr, Data (per-bank)
- 每个 bank 的 Data 宽度: AScratchpadEntryBitSize = 512 bits

**测试用例**:

| 测试名 | 描述 |
|--------|------|
| `test_single_bank_write_read` | 写 bank 0 addr 0，读回验证 |
| `test_all_banks_write_read` | 写所有 4 个 bank，分别读回 |
| `test_address_wrap` | 写超过 bank 深度的地址，验证回绕 |
| `test_double_buffer` | 通过 config 切换 ping/pong buffer |
| `test_concurrent_rw` | 一个 bank 写的同时读另一个 bank |

### 6.3 TaskController 测试 (`test_task_controller.py`)

**被测模块**: `TaskController`
**功能**: 接收 YGJK 指令，解码为微任务配置，管理指令 FIFO

**端口**:
- `ygjkctrl`: YGJKControl Bundle (config: DecoupledIO, InstFIFO_Info, InstFIFO_Full)
- `instfifo_head_id`, `instfifo_tail_id`, `instfifo_release`: Output
- 12 个 MicroTaskConfigIO 输出 (ADC, BDC, ASC, BSC, CDC, AML, BML, ASL, BSL, CML, MTE, AOP)
- `SCP_CtrlInfo`: SCPControlInfo
- `DebugTimeStampe`: Input UInt(32.W)
- `ctrlCounter`: CTRLCounter

**测试用例**:

| 测试名 | 描述 |
|--------|------|
| `test_matmul_decode` | 发送 matmul 配置序列，验证 12 个 MicroTaskConfig 输出正确解码 |
| `test_fifo_single` | 单条指令进出 FIFO，验证 head/tail/release |
| `test_fifo_full` | 填满 FIFO (depth=4)，验证 full 信号 |
| `test_fifo_dequeue` | 发送 2 条指令，消费 1 条，验证 head 推进 |

### 6.4 MatrixTE 测试 (`test_matrix_te.py`)

**被测模块**: `MatrixTE`
**功能**: 4×4 PE 阵列，执行矩阵乘法
**端口宽度**:
- VectorA: 2048 bits (ReduceWidth*Matrix_M = 512*4)
- VectorB: 2048 bits (ReduceWidth*Matrix_N = 512*4)
- ScaleA: 512 bits (ScaleWidth*Matrix_M = 128*4)
- ScaleB: 512 bits (ScaleWidth*Matrix_N = 128*4)
- MatirxC: 512 bits (ResultWidth*16 = 32*16)
- MatrixD: 512 bits
- ConfigInfo: MTEMicroTaskConfigIO

**测试用例**:

| 测试名 | 描述 |
|--------|------|
| `test_single_compute_i8` | 发送单对 VectorA/B，验证 MatrixD 正确 |
| `test_pipelined_compute` | 连续发送多对 Vector，验证流水线不丢数据 |
| `test_config_gating` | 不发 ConfigInfo 时 ComputeGo 应为低 |
| `test_identity_matrix` | A=I, B=I → D 应该是单位矩阵 |

### 6.5 ADataController 测试

**被测模块**: `ADataController`
**功能**: 从 AScratchpad 读取数据，按调度输出给 MatrixTE

### 6.6 CMemoryLoader 测试

**被测模块**: `CMemoryLoader`
**功能**: 通过 LocalMMU 从内存加载/存储 C tensor
**重点测试**: D_STORE_DATA trace 事件的正确性

### 6.7 AfterOps 测试

**被测模块**: `AfterOpsModule`
**功能**: 后处理（激活函数、数据重排）

### 6.8 LocalMMU 测试

**被测模块**: `LocalMMU`
**功能**: 虚拟地址翻译 + TL 请求仲裁
**重点测试**: TLB 命中/缺失、地址翻译正确性、5 路请求仲裁

---

## Step 7: FP 数据类型工具 (`common/cute_utils.py`)

为了在 Python 端生成和验证 FP 数据，需要实现 FP 格式转换：

```python
import struct

def fp16_to_float(raw):
    """uint16 raw bits → Python float"""
    return struct.unpack('>e', struct.pack('>H', raw))[0]

def bf16_to_float(raw):
    """uint16 raw bits → Python float (BF16 has 8 exp, 7 mantissa)"""
    sign = (raw >> 15) & 1
    exp = (raw >> 7) & 0xFF
    mantissa = raw & 0x7F
    if exp == 0 and mantissa == 0:
        return -0.0 if sign else 0.0
    if exp == 0xFF:
        return float('nan') if mantissa else float('inf')
    mantissa <<= 16
    f32_bits = (sign << 31) | (exp << 23) | mantissa
    return struct.unpack('>f', struct.pack('>I', f32_bits))[0]

def tf32_to_float(raw):
    """uint32 raw bits → Python float (TF32: 1+8+10, top 19 bits)"""
    raw_clean = raw & 0xFFFFE000
    return struct.unpack('>f', struct.pack('>I', raw_clean))[0]

def fp8_e4m3_to_float(raw):
    """uint8 FP8 E4M3 → Python float"""
    sign = (raw >> 7) & 1
    exp = (raw >> 3) & 0xF
    mantissa = raw & 0x7
    if exp == 0 and mantissa == 0:
        return -0.0 if sign else 0.0
    real_exp = exp - 7 + 127  # → FP32 exponent bias
    mantissa_shifted = mantissa << 20
    f32_bits = (sign << 31) | (real_exp << 23) | mantissa_shifted
    return struct.unpack('>f', struct.pack('>I', f32_bits))[0]

def pack_i8_vector(values):
    """将 n 个 int8 打包为一个整数"""
    result = 0
    for i, v in enumerate(values):
        result |= (v & 0xFF) << (i * 8)
    return result

def unpack_result_vector(raw, elem_bits, n_elems):
    """从一个 int 解包 n_elems 个元素"""
    return [(raw >> (i * elem_bits)) & ((1 << elem_bits) - 1)
            for i in range(n_elems)]
```

---

## Step 8: 构建脚本

### `scripts/build-layer1.sh`

```bash
#!/bin/bash
set -e
CUTE_ROOT=$(cd "$(dirname "$0")/.." && pwd)

CONFIG=${1:-CUTE2TopsSCP64Config}
VERILOG_DIR="$CUTE_ROOT/build/chipyard/generated-src/chipyard.harness.TestHarness.$CONFIG/gen-collateral"

if [ ! -d "$VERILOG_DIR" ]; then
    echo "Verilog not found, generating..."
    bash "$CUTE_ROOT/scripts/build-verilog.sh" "$CONFIG"
fi

echo "Using Verilog from: $VERILOG_DIR"
export CUTE_VERILOG_DIR=$VERILOG_DIR

cd "$CUTE_ROOT/layer1/cocotb"
make -j$(nproc) ${2:-all}
```

---

## Step 9: 验证

### 9.1 单模块验证

```bash
# 先确保 Verilog 已生成
bash scripts/build-verilog.sh CUTE2TopsSCP64Config

# 跑单个模块测试
cd layer1/cocotb
make -C tests/test_reduce_pe
```

验证 cocotb 输出包含 `PASS`。

### 9.2 全量验证

```bash
cd layer1/cocotb
make all
```

所有测试通过。

### 9.3 回归验证

```bash
# 修改 Chisel 源码后重新生成 Verilog 并跑测试
bash scripts/build-verilog.sh CUTE2TopsSCP64Config
make -C layer1/cocotb all
```

---

## 新建文件完整列表

| 文件 | 说明 |
|------|------|
| `layer1/cocotb/Makefile` | 顶层 make |
| `layer1/cocotb/common/__init__.py` | Package init |
| `layer1/cocotb/common/cute_params.py` | Python 参数镜像 |
| `layer1/cocotb/common/cute_utils.py` | FP 转换、位打包工具 |
| `layer1/cocotb/common/cute_test_utils.py` | reset/wait 通用 helper |
| `layer1/cocotb/tests/test_reduce_pe/Makefile` | |
| `layer1/cocotb/tests/test_reduce_pe/test_reduce_pe.py` | 10 个测试用例 |
| `layer1/cocotb/tests/test_reduce_pe/verilog/ReducePETop.sv` | Verilog wrapper |
| `layer1/cocotb/tests/test_matrix_te/Makefile` | |
| `layer1/cocotb/tests/test_matrix_te/test_matrix_te.py` | 4 个测试用例 |
| `layer1/cocotb/tests/test_matrix_te/verilog/MatrixTETop.sv` | |
| `layer1/cocotb/tests/test_a_scratchpad/Makefile` | |
| `layer1/cocotb/tests/test_a_scratchpad/test_a_scratchpad.py` | 5 个测试用例 |
| `layer1/cocotb/tests/test_a_scratchpad/verilog/AScratchpadTop.sv` | |
| `layer1/cocotb/tests/test_task_controller/Makefile` | |
| `layer1/cocotb/tests/test_task_controller/test_task_controller.py` | 4 个测试用例 |
| `layer1/cocotb/tests/test_task_controller/verilog/TaskControllerTop.sv` | |
| `layer1/cocotb/tests/test_local_mmu/Makefile` | |
| `layer1/cocotb/tests/test_local_mmu/test_local_mmu.py` | |
| `layer1/cocotb/tests/test_local_mmu/verilog/LocalMMUTop.sv` | |
| `layer1/cocotb/tests/test_a_data_controller/` | 同上模式 |
| `layer1/cocotb/tests/test_c_data_controller/` | |
| `layer1/cocotb/tests/test_a_memory_loader/` | |
| `layer1/cocotb/tests/test_c_memory_loader/` | |
| `layer1/cocotb/tests/test_after_ops/` | |
| `layer1/cocotb/tests/test_a_scale_loader/` | |
| `layer1/cocotb/tests/test_a_scale_controller/` | |
| `layer1/cocotb/tests/test_a_scale_scratchpad/` | |
| `layer1/cocotb/tests/test_cute2tl_node/` | |
| `scripts/setup-cocotb.sh` | 环境安装 |
| `scripts/build-layer1.sh` | 构建入口 |

## 依赖的现有文件（只读）

| 文件 | 用途 |
|------|------|
| `src/main/scala/FReducePE.scala` | 被 ReducePE 测试引用的 DUT |
| `src/main/scala/MatrixTE.scala` | 被 MatrixTE 测试引用 |
| `src/main/scala/TaskController.scala` | 被 TaskController 测试引用 |
| `src/main/scala/LocalMMU.scala` | 被 LocalMMU 测试引用 |
| `src/main/scala/AScratchpad.scala` | 被 Scratchpad 测试引用 |
| `src/main/scala/CUTEParameters.scala` | 参数定义 → cute_params.py 镜像源 |
| `scripts/build-verilog.sh` | 生成 Chisel Verilog |
| `build/chipyard/generated-src/.../gen-collateral/*.sv` | cocotb 编译依赖的 Verilog |

## 注意事项

1. **Verilog wrapper 端口名必须与 Chisel 生成 Verilog 完全一致** — 先 `build-verilog.sh`，再检查 `gen-collateral/*.sv` 获取确切端口名
2. **wrapper 用 `(.*)` 自动连接** — 只要顶层端口名与 DUT 内部端口名一致即可
3. **Config Bundle 字段需要从生成 Verilog 中提取** — TaskController 和 MatrixTE 的 ConfigIO 字段较多，不能靠猜
4. **ScaleWidth 计算公式** 取决于 CuteFPEParams，不同配置可能不同，必须从生成的 Verilog 确认实际位宽
5. **Scratchpad 有 scp_id 参数** — `class AScratchpad(scp_id: Int)`，wrapper 需要传参或固定
