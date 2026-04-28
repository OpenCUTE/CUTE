# CUTE 测试框架重构 — 总体规划 (Big Plan)

> 目标：将 verify（基于 trace 的系统级正确性验证）、perf（基于 trace 的 top-down 性能分析）、test（基于 CONFIG 的软件测试流程）三大体系重新规划，用统一的 CONFIG 机制和结构化 trace 串联。

---

## 一、现状痛点

| 问题 | 具体表现 |
|------|----------|
| **测试样板严重** | 355+ 测试文件全部 copy-paste，每个文件 60+ 行样板代码只改 M/N/K 参数 |
| **手写头文件与生成头文件并存** | `cuteMarcoinstHelper.h`（手写，硬编码 funct 64/128 等）与 `instruction.h.generated`（自动生成）功能重叠，参数定义重复 |
| **无结构化 trace** | 只有 `printf` 调试，格式不统一，无法自动化解析 |
| **无系统级正确性验证** | `/verify` 目录为空，无自动化 golden 对比，全靠人眼比对 UART 输出 |
| **无性能分析工具** | 有 `rdcycle` 读数但无结构化 top-down 分析（计算利用率、带宽、流水线 stall） |
| **Config 割裂** | Chisel 端用 `CUTEParameters.scala` 定义配置，C 端通过 `generate-headers.sh` 生成头文件，但手写的 `cuteMarcoinstHelper.h` 硬编码了 `Tensor_M_Element_Length = 64` 等值，与生成的 `validation.h.generated` 不一致 |
| **测试脚本不灵活** | `build-test.sh` / `run-simulator-test.sh` 硬编码 CONFIG 名和测试 binary，不支持批量回归 |

---

## 二、设计原则

1. **Single Source of Truth（唯一真相源）**：所有硬件参数、指令编码、数据类型定义只来自 `CUTEParameters.scala`，通过 `HeaderGenerator` 生成 C 头文件，消除手写硬编码
2. **CONFIG-Driven（配置驱动）**：每个测试用例、每次验证、每次性能分析都由一个 CONFIG 文件（YAML/TOML）声明式描述，而非 C 代码中硬编码
3. **Trace-First（trace 优先）**：所有验证和性能分析都基于结构化 trace，仿真和 FPGA 共用同一套 trace 格式和工具
4. **分层解耦**：Verify（正确性） / Perf（性能） / Test（功能测试） 三条线独立但共用基础设施（trace parser、config loader、golden generator）

---

## 三、架构总览

```
                    ┌──────────────────────────────────────┐
                    │         Config Layer (统一配置)        │
                    │  cute_config.yaml + HeaderGenerator   │
                    │  (参数/指令/测试用例 唯一真相源)         │
                    └──────────┬───────────────────────────┘
                               │
               ┌───────────────┼───────────────┐
               ▼               ▼               ▼
    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
    │   Verify     │  │    Perf      │  │    Test      │
    │  正确性验证   │  │  性能分析     │  │  功能测试     │
    │              │  │              │  │              │
    │ · Golden Gen │  │ · Top-Down   │  │ · Matmul     │
    │ · Trace Check│  │   分析       │  │ · Conv       │
    │ · 回归测试    │  │ · Bottleneck │  │ · Blockscale │
    └──────┬───────┘  │   定位       │  │ · Datatype   │
           │          └──────┬───────┘  └──────┬───────┘
           │                 │                 │
           └─────────────────┼─────────────────┘
                             ▼
                ┌────────────────────────┐
                │    Trace Layer         │
                │  结构化 Trace 基础设施   │
                │                        │
                │ · RTL trace emit       │
                │ · Trace parser (Python) │
                │ · Trace analyzer       │
                │ · Trace visualizer     │
                └────────────────────────┘
```

---

## 四、Config Layer — 统一配置机制

### 4.1 当前问题

- Chisel 端 `CUTEParameters.scala` 定义了 5 种配置（2Tops/4Tops/8Tops/16Tops/32Tops）
- `generate-headers.sh` 从 Scala Config 提取参数生成 C 头文件
- 但 `cuteMarcoinstHelper.h` 仍然手写了 funct 编号（64+偏移）、`Tensor_M_Element_Length = 64` 等，与生成的头文件冲突
- 新的 `instruction.h.generated` 已生成了完整的指令封装函数（`CUTE_CONFIG_TENSOR_A` 等），但测试代码仍在用旧的手写函数

### 4.2 新 Config 设计

#### 4.2.1 硬件参数配置 — 继续用 HeaderGenerator

保持 Scala → C 头文件的生成链路，但**彻底淘汰手写的硬编码**：

```
CUTEParameters.scala (Chisel, 唯一定义)
        │
        ▼ HeaderGenerator.scala (反射加载 Config)
        │
        ├── datatype.h.generated    (数据类型定义)
        ├── validation.h.generated  (硬件参数常量)
        ├── instruction.h.generated (指令集 + 封装函数)
        │
        ▼ 新增
        ├── cute_config.h.generated (CONFIG 元信息，见下)
        └── cute_tensor.h.generated (张量描述符宏)
```

**淘汰策略**：
- `cuteMarcoinstHelper.h` → 迁移到 `instruction.h.generated` 的自动生成函数
- `marcohelper.h` 中的底层 `YGJK_INS_RRR` 宏保留（这是真正的 inline asm），但上层的 funct 编号用 `instruction.h.generated` 中的宏
- `datatype.h`（手写）→ `datatype.h.generated`
- `validation.h`（手写）→ `validation.h.generated`

#### 4.2.2 测试配置 — YAML 声明式测试用例

新增 `test_config.yaml` 描述每个测试场景：

```yaml
# configs/test_configs/matmul_i8_i32.yaml
name: matmul_i8_i32_basic
description: "Basic INT8 matmul correctness test"
category: matmul

hardware:
  config: chipyard.CUTE2TopsSCP64Config

test:
  op: matmul
  elem_type: CUTEDataTypeI8I8I32   # 0
  bias_type: TaskTypeTensorZeroLoad  # 1
  M: 128
  N: 128
  K: 128
  transpose: false

golden:
  method: cpu_reference            # CPU 参考实现
  tolerance:
    abs_err: 0                     # 整数精确匹配
    rel_err: 0

trace:
  collect: true                    # 是否收集 trace
  events: [COMPUTE_DONE, D_STORE_DATA]  # 关注的事件
```

```yaml
# configs/test_configs/conv_fp16_resnet.yaml
name: conv_fp16_resnet_block1
description: "ResNet50 block1 convolution"
category: conv

hardware:
  config: chipyard.CUTE4TopsSCP128Config

test:
  op: conv
  elem_type: CUTEDataTypeF16F16F32
  bias_type: TaskTypeTensorLoad
  M: 196        # ohow
  N: 256        # oc
  K: 256        # ic (for first conv)
  kernel_size: 3
  conv_stride: 1
  oh_max: 14
  ow_max: 14

golden:
  method: cpu_reference
  tolerance:
    abs_err: 1e-3
    rel_err: 1e-4
```

#### 4.2.3 HeaderGenerator 扩展

在现有 `HeaderGenerator.scala` 中新增生成目标：

| 生成文件 | 内容 |
|----------|------|
| `cute_config.h.generated` | `#define CUTE_CONFIG_NAME "CUTE2TopsSCP64"` 等元信息，供测试代码标识当前配置 |
| `cute_tile.h.generated` | 分块相关的宏：`CUTE_TILE_M`、`CUTE_TILE_N`、`CUTE_TILE_K`、自动 tiling 循环辅助宏 |

#### 4.2.4 Python Config Loader

```python
# verify/python/cute_config.py
@dataclass
class CuteTestConfig:
    name: str
    category: str  # matmul / conv / blockscale
    hardware_config: str
    op_params: dict
    golden: dict
    trace: dict

def load_test_config(path: str) -> CuteTestConfig:
    """加载 YAML 测试配置"""
    ...
```

---

## 五、Trace Layer — 结构化 Trace 基础设施

### 5.1 统一 Trace 格式

```
[CYCLE:<cycle>] <MODULE>:<SUB_ID> <EVENT> <KEY=VALUE ...>
```

| 字段 | 说明 |
|------|------|
| CYCLE | 十进制周期计数器 |
| MODULE | TC / MMU / TE / PE / ADC / BDC / CDC / AML / BML / CML / ASL / BSL / ASC / BSC |
| SUB_ID | 实例编号（双缓冲区分 0/1） |
| EVENT | INST_DECODE / INST_ISSUE / INST_COMPLETE / MEM_REQ / MEM_RSP / COMPUTE_START / COMPUTE_DONE / D_STORE / DATA_VALIDATE |
| KEY=VALUE | 事件载荷（地址、数据、维度等） |

### 5.2 RTL 侧 Trace 发射

在关键模块中添加结构化 printf，受 `YJPTraceEnable` 参数控制：

| 模块 | 事件 | 载荷 |
|------|------|------|
| `TaskController` | INST_DECODE | funct, cfgData1, cfgData2 |
| `TaskController` | INST_ISSUE | inst_type |
| `TaskController` | INST_COMPLETE | inst_index, cycles |
| `LocalMMU` | MEM_REQ | addr, size, source |
| `LocalMMU` | MEM_RSP | addr, data_beats |
| `MatrixTE` | COMPUTE_START | tile_m, tile_n, tile_k |
| `MatrixTE` | COMPUTE_DONE | tile_m, tile_n, cycles |
| `CMemoryLoader` | D_STORE | addr, data_checksum, row_count |
| `CUTETOP` | TASK_BEGIN | M, N, K, elem_type |
| `CUTETOP` | TASK_END | total_cycles |

### 5.3 Python Trace 工具链

```
trace/
├── python/
│   ├── cute_trace.py            # TraceEvent dataclass + CuteTraceParser
│   ├── cute_trace_analyzer.py   # Top-Down 性能分析（见第六节）
│   ├── cute_trace_golden.py     # 从 D_STORE 重建 D tensor
│   └── cute_trace_viz.py        # Matplotlib 时间线可视化
├── scripts/
│   ├── trace_filter.py          # CLI: 按模块/事件/周期过滤
│   ├── trace_stats.py           # CLI: 统计摘要
│   └── trace_golden_check.py    # CLI: trace golden 对比
└── format_spec.md               # 格式规范文档
```

---

## 六、Verify Line — 基于 Trace 的系统级正确性验证

### 6.1 设计思路

不再依赖人眼比对 UART 输出，而是：

1. **Golden 生成**：Python/CPU 参考实现生成正确结果
2. **Trace 提取**：从仿真 trace 的 `D_STORE` 事件中提取实际 D tensor
3. **自动比对**：数值比较（整数精确 / 浮点容差）
4. **报告生成**：PASS/FAIL + 详细 mismatch 信息

### 6.2 目录结构

```
verify/
├── python/
│   ├── cute_config.py           # Config loader（与 Test Line 共用）
│   ├── cute_golden.py           # Golden 参考生成器
│   │                            # · matmul golden (numpy)
│   │                            # · conv golden (numpy/scipy)
│   │                            # · blockscale golden
│   ├── cute_verify.py           # 核心验证逻辑
│   │                            # · 数值比对 (int exact / float tolerance)
│   │                            # · mismatch 报告
│   │                            # · PASS/FAIL 判定
│   ├── cute_trace_golden.py     # 从 trace 提取 D tensor
│   └── cute_verify_runner.py    # 回归测试 runner
├── configs/                     # 验证配置 YAML 文件
│   ├── matmul/
│   │   ├── matmul_i8_64x64x64.yaml
│   │   ├── matmul_i8_128x128x128.yaml
│   │   ├── matmul_fp16_64x64x64.yaml
│   │   └── matmul_boundary.yaml  # 边界用例
│   ├── conv/
│   │   ├── conv_resnet_block1.yaml
│   │   └── conv_resnet_block2.yaml
│   ├── blockscale/
│   │   └── blockscale_mxfp8.yaml
│   └── regression.yaml          # 全量回归列表
├── scripts/
│   ├── run_verify.py             # CLI: 单个用例验证
│   ├── run_regression.py         # CLI: 全量回归
│   └── gen_golden_header.py      # 生成 golden .h 文件（兼容现有 C 测试）
└── README.md
```

### 6.3 工作流程

```
1. 读取 verify/configs/matmul/matmul_i8_64x64x64.yaml
2. cute_golden.py 生成 golden D tensor (numpy)
3. 编译测试 binary (用生成的 golden .h)
4. 运行仿真 (带 TraceEnable)
5. cute_trace_golden.py 从 trace 提取 D tensor
6. cute_verify.py 比对 golden vs actual
7. 输出: PASS/FAIL + mismatch 详情
```

### 6.4 Golden 生成策略

| 操作类型 | Golden 方法 | 精度 |
|----------|-------------|------|
| INT8 matmul | numpy int32 matmul | 精确匹配 |
| FP16 matmul | numpy float32 → round to FP16 | abs_err ≤ 1 ULP |
| BF16 matmul | numpy float32 → round to BF16 | abs_err ≤ 1 ULP |
| Conv | scipy.signal.correlate2d | exact / tolerance |
| Blockscale | numpy + 手动 quantize/dequantize | tolerance-based |

---

## 七、Perf Line — 基于 Trace 的 Top-Down 性能分析

### 7.1 设计思路

Top-Down 分析模型，逐层定位性能瓶颈：

```
Level 0: Overall Utilization (实际 TOPS / 理论峰值 TOPS)
    ├── Level 1: Pipeline Utilization
    │   ├── Compute Utilization  (TE 活跃周期 / 总周期)
    │   ├── Memory Utilization   (有效带宽 / 理论带宽)
    │   └── Overlap Efficiency   (计算/访存重叠度)
    ├── Level 2: Stall Analysis
    │   ├── Stall on Memory      (等待访存完成的周期)
    │   ├── Stall on Result FIFO (D store 反压)
    │   └── Stall on Config      (等待指令配置)
    └── Level 3: Detailed Breakdown
        ├── Tile-level throughput (每个 tile 的周期)
        ├── Memory access pattern (连续性、银行冲突)
        └── Control overhead      (配置/同步开销)
```

### 7.2 从 Trace 提取的指标

| 指标 | Trace 事件来源 | 计算方式 |
|------|---------------|----------|
| **总执行周期** | `TASK_BEGIN → TASK_END` | `end_cycle - start_cycle` |
| **计算利用率** | `COMPUTE_START → COMPUTE_DONE` | `Σ(compute_cycles) / total_cycles` |
| **有效计算 TOPS** | `COMPUTE_DONE` 的 tile 维度 | `Σ(M×N×K×2) / total_time` |
| **理论峰值 TOPS** | Config 中的频率和 PE 数 | `PE_count × freq × 2` |
| **访存带宽利用率** | `MEM_REQ → MEM_RSP` | `actual_bytes / (theoretical_bw × time)` |
| **流水线气泡** | `COMPUTE_DONE → next COMPUTE_START` | 间隔周期数 |
| **Tile 级性能** | `COMPUTE_START/DONE` 的 tile_id | 单 tile 延迟 |
| **Result FIFO 反压** | `D_STORE` 前的等待周期 | stall_cycles |

### 7.3 目录结构

```
perf/
├── python/
│   ├── cute_perf_analyzer.py     # Top-Down 分析引擎
│   │                              # · Level 0-3 逐层分析
│   │                              # · 输出结构化报告
│   ├── cute_perf_model.py        # Roofline 模型
│   │                              # · 理论峰值计算
│   │                              # · Arithmetic Intensity 计算
│   │                              # · Roofline 图表生成
│   └── cute_perf_report.py       # 报告生成器
│                                  # · Console report
│                                  # · JSON report
│                                  # · HTML report (with charts)
├── configs/
│   ├── roofline_2tops.yaml       # Roofline 模型参数
│   └── roofline_4tops.yaml
├── scripts/
│   ├── analyze_perf.py           # CLI: 分析单个 trace
│   ├── compare_perf.py           # CLI: 对比不同配置的性能
│   └── generate_roofline.py      # CLI: 生成 Roofline 图
└── README.md
```

### 7.4 报告示例

```
═══════════════════════════════════════════════════
  CUTE Performance Analysis Report
  Config: CUTE4TopsSCP128Config
  Test: matmul_fp16_128x128x128
═══════════════════════════════════════════════════

Level 0 — Overall
  Total Cycles:        12,450
  Total Time (1GHz):   12.45 μs
  Actual TOPS:         3.42
  Peak TOPS:           4.00
  Utilization:         85.5%  ████████████████░░░░

Level 1 — Pipeline
  Compute Util:        78.2%  ███████████████░░░░░
  Memory Util:         92.1%  ██████████████████░░
  Overlap Efficiency:  89.3%  █████████████████░░░

Level 2 — Stalls
  Memory Stall:        14.2%  (1,769 cycles)
  Result FIFO Stall:    3.1%  (  386 cycles)
  Config Overhead:      4.5%  (  561 cycles)

Level 3 — Tile Breakdown
  Tile (0,0): 1,240 cycles [compute: 980, wait: 260]
  Tile (0,1): 1,235 cycles [compute: 978, wait: 257]
  ...

Recommendations:
  ⚠ Memory stall 占比较高 (14.2%)，建议:
    - 检查 A/B scratchpad 双缓冲是否生效
    - 考虑增大 prefetch 提前量
═══════════════════════════════════════════════════
```

---

## 八、Test Line — 基于 CONFIG 的软件测试流程

### 8.1 设计思路

用统一的测试框架替代 355+ 个 copy-paste 测试文件：

- **测试框架头文件**：提供 CuteTensor 抽象、算子封装、自动 tiling
- **声明式测试用例**：YAML 描述测试参数，Python 脚本自动生成 C 代码
- **自动 golden 验证**：CPU 参考实现 + 自动比对，替代人眼

### 8.2 测试框架 API

#### 8.2.1 核心 API（替代手写样板代码）

```c
// cutetest/include/cute.h — 新的总入口
#include "datatype.h.generated"
#include "validation.h.generated"
#include "instruction.h.generated"
#include "cute_tensor.h"
#include "cute_op.h"
#include "cute_verify.h"
#include "cute_perf.h"
```

```c
// cutetest/include/cute_tensor.h — 张量描述符
typedef struct {
    void     *data;
    uint64_t  rows, cols;
    uint64_t  stride;      // 行步长（字节），0 = 自动 packed
    uint64_t  elem_type;
} CuteTensor;

static inline void cute_tensor_init(CuteTensor *t, void *data,
                                     uint64_t rows, uint64_t cols,
                                     uint64_t elem_type) {
    t->data = data;
    t->rows = rows;
    t->cols = cols;
    t->elem_type = elem_type;
    uint64_t bits = CUTE_GET_ADATA_BITWIDTH(elem_type);
    t->stride = cols * (bits / 8);
}
```

```c
// cutetest/include/cute_op.h — 算子封装（用 instruction.h.generated 的函数）
static inline uint64_t cute_matmul(CuteTensor *A, CuteTensor *B,
                                    CuteTensor *Bias, CuteTensor *D,
                                    uint64_t M, uint64_t N, uint64_t K,
                                    uint64_t elem_type, uint64_t bias_type) {
    // 调用 instruction.h.generated 生成的封装函数
    CUTE_CONFIG_TENSOR_A((uint64_t)A->data, A->stride);
    CUTE_CONFIG_TENSOR_B((uint64_t)B->data, B->stride);
    CUTE_CONFIG_TENSOR_C((uint64_t)Bias->data, Bias->stride);
    CUTE_CONFIG_TENSOR_D((uint64_t)D->data, D->stride);
    CUTE_CONFIG_TENSOR_DIM(M, N, K, 0);
    CUTE_CONFIG_CONV_PARAMS(elem_type, bias_type, 0, 1, 0, 0,
                            1, 0, CUTE_TENSOR_N, 0, 0);
    return CUTE_SEND_MACRO_INST();
}
```

```c
// cutetest/include/cute_perf.h — 性能计数器封装
typedef struct {
    uint64_t total_cycles;
    uint64_t compute_cycles;
    uint64_t mem_read_count;
    uint64_t mem_write_count;
} CutePerfResult;

static inline CutePerfResult cute_perf_query(void) {
    CutePerfResult r;
    r.total_cycles   = CUTE_QUERY_RUNTIME(0, 0);
    r.compute_cycles  = CUTE_QUERY_COMPUTE_TIME(0, 0);
    r.mem_read_count  = CUTE_QUERY_MEM_READ_COUNT(0, 0);
    r.mem_write_count = CUTE_QUERY_MEM_WRITE_COUNT(0, 0);
    return r;
}
```

#### 8.2.2 测试用例：从 60 行样板到 10 行

**旧方式**（当前，~60 行）：
```c
#include "cuteMarcoinstHelper.h"
#include "matmul_value_mnk_128_128_128_zeroinit.h"
int main(void) {
    uint64_t A_Stride = APPLICATION_K * sizeof(a[0][0]);
    // ... 20 行 stride 计算 ...
    issue_cute_matmul_marco_inst(a, A_Stride, b, B_Stride, ...);
    // ... 10 行 FIFO 等待 ...
    // ... 10 行性能查询 ...
}
```

**新方式**（目标，~10 行）：
```c
#include "cute.h"
#include "golden.h.generated"  // 自动生成的 golden 数据

int main(void) {
    DECLARE_ALIGNED_TENSOR(A, 128, 128, i8);
    DECLARE_ALIGNED_TENSOR(B, 128, 128, i8);
    DECLARE_ALIGNED_TENSOR(D, 128, 128, i32);
    LOAD_GOLDEN_DATA(A, B);  // 从 golden.h 加载

    cute_matmul(&A, &B, NULL, &D, 128, 128, 128,
                CUTEDataTypeI8I8I32, TaskTypeTensorZeroLoad);
    cute_wait_finish();

    CutePerfResult perf = cute_perf_query();
    PRINT_PERF(perf);

    VERIFY_RESULT(D, golden_d, 128, 128);
    return CUTE_TEST_RESULT;  // 0 = pass, -1 = fail
}
```

### 8.3 测试自动生成

Python 脚本从 YAML 配置自动生成测试 C 文件和 golden 数据：

```
test_generator.py 读 YAML → 生成:
  · test_<name>.c              (测试代码)
  · golden_<name>.h.generated  (golden 数据)
```

### 8.4 目录结构

```
cutetest/
├── include/
│   ├── cute.h                    # 总入口（新）
│   ├── cute_tensor.h             # 张量抽象（新）
│   ├── cute_op.h                 # 算子封装（新）
│   ├── cute_op_tiled.h           # 大矩阵自动 tiling（新）
│   ├── cute_verify.h             # CPU 参考验证（新）
│   ├── cute_perf.h               # 性能计数器（新）
│   ├── datatype.h.generated      # 保留
│   ├── validation.h.generated    # 保留
│   ├── instruction.h.generated   # 保留
│   ├── ygjk.h                    # 保留（底层 inline asm）
│   ├── cuteMarcoinstHelper.h     # → deprecated, 保留做兼容
│   └── marcohelper.h             # → deprecated, 保留做兼容
├── framework/
│   ├── cute_verify_impl.c        # CPU 参考实现（软件 matmul/conv）
│   ├── cute_verify_impl.h
│   └── Makefile                  # 编译框架库
├── tests/
│   ├── auto/                     # 自动生成的测试
│   │   ├── matmul/
│   │   │   ├── test_matmul_i8_64x64x64.c
│   │   │   ├── golden_matmul_i8_64x64x64.h
│   │   │   └── ...
│   │   ├── conv/
│   │   └── blockscale/
│   ├── manual/                   # 手写的复杂测试
│   │   ├── resnet50_block.c
│   │   └── llama_attention.c
│   └── regression/               # 回归测试集
│       └── regression_list.yaml
├── generator/
│   ├── test_generator.py         # YAML → C 测试代码
│   ├── golden_generator.py       # YAML → golden .h
│   └── Makefile
├── scripts/
│   ├── run_test.py               # CLI: 编译+仿真+验证 单个测试
│   ├── run_regression.py         # CLI: 批量回归
│   └── run_all_configs.py        # CLI: 跑所有 CONFIG
└── base_test/                    # 旧测试保留，逐步迁移
    └── ...
```

---

## 九、实施路线图

### Phase 1：基础设施（2-3 周）

**目标**：统一 Config、清理头文件依赖、定义 trace 格式

| 任务 | 具体内容 | 依赖 |
|------|----------|------|
| 1.1 HeaderGenerator 扩展 | 新增 `cute_config.h.generated`，确保所有参数都通过生成获取 | 无 |
| 1.2 迁移 cuteMarcoinstHelper.h → instruction.h.generated | 逐步替换测试代码中的旧函数调用为新 API | 1.1 |
| 1.3 定义 Trace 格式规范 | 编写 `trace/format_spec.md`，确定所有事件和载荷格式 | 无 |
| 1.4 实现 Trace Parser | `trace/python/cute_trace.py`：TraceEvent dataclass + parser | 1.3 |
| 1.5 新建 cute.h / cute_tensor.h / cute_op.h | 新的统一 API 头文件 | 1.1 |

### Phase 2：Verify Line（2-3 周）

**目标**：建立自动化的正确性验证流程

| 任务 | 具体内容 | 依赖 |
|------|----------|------|
| 2.1 Golden 生成器 | `verify/python/cute_golden.py`：numpy 参考实现 | 1.5 |
| 2.2 Golden Header 生成器 | `verify/scripts/gen_golden_header.py`：生成 C 头文件 | 2.1 |
| 2.3 Verify 比对引擎 | `verify/python/cute_verify.py`：数值比对逻辑 | 无 |
| 2.4 测试配置 YAML 定义 | `verify/configs/` 下创建测试配置 | 1.5 |
| 2.5 Test Generator | `cutetest/generator/test_generator.py` | 2.1, 2.2 |
| 2.6 Verify Runner | `verify/python/cute_verify_runner.py`：端到端验证 | 2.3, 2.4 |
| 2.7 RTL 添加 Trace Emit | 在 TaskController/CMemoryLoader 添加结构化 printf | 1.3 |

### Phase 3：Perf Line（2-3 周）

**目标**：建立 top-down 性能分析工具链

| 任务 | 具体内容 | 依赖 |
|------|----------|------|
| 3.1 RTL 补全 Trace Emit | 在 MatrixTE/LocalMMU/CUTETOP 添加 trace | Phase 2.7 |
| 3.2 Top-Down 分析引擎 | `perf/python/cute_perf_analyzer.py` | 1.4 |
| 3.3 Roofline 模型 | `perf/python/cute_perf_model.py` | 3.2 |
| 3.4 报告生成器 | `perf/python/cute_perf_report.py` | 3.2 |
| 3.5 CLI 工具 | `perf/scripts/analyze_perf.py` 等 | 3.2, 3.3 |
| 3.6 Trace 可视化 | `trace/python/cute_trace_viz.py` | 1.4 |

### Phase 4：Test Line 完善（2-3 周）

**目标**：建立完整的回归测试体系

| 任务 | 具体内容 | 依赖 |
|------|----------|------|
| 4.1 CuteVerify C 实现 | `cutetest/framework/cute_verify_impl.c` | 1.5 |
| 4.2 自动 tiling | `cutetest/include/cute_op_tiled.h` | 1.5 |
| 4.3 批量测试生成 | 从 YAML 批量生成 matmul/conv/blockscale 测试 | 2.5 |
| 4.4 回归测试脚本 | `cutetest/scripts/run_regression.py` | 4.3 |
| 4.5 多 CONFIG 支持 | 跑不同硬件配置的回归测试 | 4.4 |
| 4.6 旧测试迁移 | 逐步将 base_test/ 下的 355+ 文件迁移到新框架 | 4.3 |

### Phase 5：FPGA Trace（后续）

| 任务 | 具体内容 | 依赖 |
|------|----------|------|
| 5.1 RTL Trace Buffer | BRAM 环形 buffer + XDMA bridge | Phase 3 |
| 5.2 FPGA Trace 采集 | Python 脚本通过 XDMA 读取 | 5.1 |
| 5.3 FPGA 与仿真一致性验证 | 对比两种 trace 的分析结果 | 5.2 |

---

## 十、关键设计决策讨论点

以下是需要进一步讨论确认的设计决策：

### 10.1 手写头文件迁移策略

**方案 A**：激进迁移 — 一次性淘汰 `cuteMarcoinstHelper.h`，所有测试立即用 `instruction.h.generated`
**方案 B**：渐进迁移 — 保留旧头文件做兼容层，新测试用新 API，旧测试逐步迁移

> 建议：方案 B，降低风险

### 10.2 Golden 数据格式

**方案 A**：Golden 数据作为 `.h.generated` 嵌入 C 程序（当前方式）
**方案 B**：Golden 数据存为独立二进制文件，仿真通过 UART/md5 传递结果，Python 端比对
**方案 C**：混合 — 小矩阵用 `.h.generated`，大矩阵用二进制文件

> 建议：方案 C，平衡编译速度和灵活性

### 10.3 Trace 实现方式

**方案 A**：RTL printf（Verilator 仿真直接输出到 stdout）
**方案 B**：RTL 内部 trace buffer + DMA 输出
**方案 C**：A（仿真）+ B（FPGA），共用格式

> 建议：方案 C，仿真用 printf 即可（简单），FPGA 用硬件 buffer

### 10.4 测试框架的 CPU 参考实现

**方案 A**：纯 C 实现在 RISC-V 上运行（与测试同进程）
**方案 B**：Python numpy 在 host 上生成 golden，嵌入到测试 binary
**方案 C**：两者都支持 — C 参考用于嵌入式验证，Python 用于 host 端回归

> 建议：方案 C，覆盖更多场景

### 10.5 Config 文件格式

**方案 A**：YAML — 可读性好，Python 原生支持
**方案 B**：TOML — 更简洁，适合简单配置
**方案 C**：JSON — 无额外依赖

> 建议：方案 A (YAML)，复杂嵌套结构更清晰

---

## 十一、文件依赖关系

```
CUTEParameters.scala (唯一真相源)
    │
    ├─→ HeaderGenerator.scala
    │       ├─→ datatype.h.generated
    │       ├─→ validation.h.generated
    │       ├─→ instruction.h.generated
    │       ├─→ cute_config.h.generated (新)
    │       └─→ cute_tile.h.generated (新)
    │
    │           ↓ 被以下文件 include
    │
    ├─→ cute.h (总入口)
    │       ├─→ cute_tensor.h
    │       ├─→ cute_op.h  ──→ instruction.h.generated
    │       ├─→ cute_op_tiled.h ──→ validation.h.generated
    │       ├─→ cute_verify.h
    │       └─→ cute_perf.h
    │
    ├─→ YAML test configs
    │       ├─→ test_generator.py ──→ test_*.c + golden_*.h
    │       └─→ cute_golden.py ──→ golden data
    │
    └─→ RTL trace (YJPTraceEnable)
            ├─→ CuteTraceParser (Python)
            ├─→ CutePerfAnalyzer (Python)
            └─→ CuteVerifyRunner (Python)
```

---

## 十二、总结

| 维度 | 现状 | 目标 |
|------|------|------|
| **Config** | 手写硬编码 + 生成文件并存 | HeaderGenerator 单一真相源 |
| **测试** | 355+ copy-paste 文件 | YAML 声明 + 自动生成 + 统一 API |
| **验证** | 人眼看 UART 输出 | 自动 golden 比对 + trace 提取 |
| **性能** | rdcycle 读数 | Top-Down 分析 + Roofline 模型 |
| **Trace** | printf 无格式 | 统一格式 + parser + analyzer + viz |
| **回归** | 手动跑单个 binary | 一键回归 + 多 CONFIG + CI-ready |

预计总工期：**8-12 周**（Phase 1-4），Phase 5 (FPGA) 另行安排。
