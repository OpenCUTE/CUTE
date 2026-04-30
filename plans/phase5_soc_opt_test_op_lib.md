# Phase 5 Plan: SOCOptTest -> Opt Op Lib

## 目标

Phase 5 的目标是在 Fuse Layer Op Lib 基础上，结合特定 SoC/HWConfig family 做足量优化，形成 `opt_op_lib`。

重点从"功能能否正确"转向"在特定 HWConfig 上如何跑得更好"。因此 target 会非常窄。

本阶段同时开始实现 `Trace.perf` 的初步性能分析能力（Top-Down 分析 + Roofline 模型）。

## 候选 HWConfig Family

建议选择一个明确家族：

```text
cute4tops_scp128 + shuttle + dramsim48
```

或沿用 Phase 1 的默认配置加上更多参数控制：

```text
cute2tops_scp64 + shuttle + dramsim32
```

选择标准：

- simulator 可用。
- Phase 2/3 的 baseline 测试可运行。
- 有明确优化目标（带宽、tiling、流水线重叠）。
- 能稳定复现实验。

## 主要产物

```text
cute-sdk/opt_ops/<hw-family>/
├── project.yaml
├── include/
│   └── cute_opt_<family>.h             # SOC 优化 op 头文件
├── src/
│   ├── main.c                          # 优化版 test driver
│   └── cute_opt_matmul.c              # 优化 matmul 实现
├── baselines/
│   └── baseline.json                   # 优化前基线数据
├── reports/
└── build_rules/
    └── Makefile

tools/perf/
├── cute_perf_analyzer.py               # Top-Down 分析引擎
├── cute_perf_model.py                  # Roofline 模型
└── cute_perf_report.py                 # 报告生成器

trace/perf/
├── timeline.py                         # 时间线模型
├── stage_model.py                      # Stage 分解模型
├── memory_model.py                     # 带宽模型
└── utilization.py                      # 利用率模型

scripts/
└── cute-perf.py                        # 性能分析 CLI
```

---

## Task 5.1: 定义 Opt Op 边界

### 5.1.1 Opt Op Lib 职责

Opt op lib 可以做：

| 优化方向 | 具体策略 | 依赖的硬件特性 |
|----------|----------|---------------|
| **Tiling 优化** | 根据 Tensor_M/N/K 和 scratchpad 大小自动选择最优 tile | `CUTE_TENSOR_M/N/K` |
| **调度优化** | 重叠计算和访存，利用双缓冲 | scratchpad 双缓冲 |
| **数据布局优化** | 根据 bus width 和 memory burst 优化 stride 对齐 | `sysbus_width`, `membus_width` |
| **路径选择** | 根据 core/TCM/cache 选择数据搬运路径 | `soc.core`, cache 配置 |

Opt op lib **不应**伪装成通用 op lib。它必须显式绑定 target family。

### 5.1.2 project.yaml

```yaml
version: 1
id: opt.shuttle_dram32_matmul
name: shuttle_dram32_matmul_opt
kind: soc_opt_test
version_name: v0.1

target:
  hwconfigs:
    include_tags: [cute_tensor_v1, shuttle]
    exclude_tags: [boom, rocket]   # 明确只针对 shuttle
  required_capability:
    datatypes: [i8i8i32]
    tensor_ops: [matmul]
    trace_perf_level: P2_stage      # 需要至少 stage 级 perf 数据

code:
  entry: src/main.c
  build: make
  runtime_lib: runtime.cute_runtime
  op_lib: tensor.matmul
  variants:
    - name: baseline
      description: "未优化的 matmul，使用默认 cute_matmul()"
    - name: optimized_tiling
      description: "优化 tiling 策略：利用 scratchpad 双缓冲"
    - name: optimized_scheduling
      description: "优化调度：重叠计算和访存"

golden:
  level: tensor_op                  # 正确性仍用 tensor_op 级 golden
  source: python_reference
  compare:
    mode: exact

perf:
  baseline: baselines/baseline.json
  metrics:
    - total_cycles
    - compute_utilization
    - memory_bandwidth_utilization
```

---

## Task 5.2: 实现 Opt Op

### 5.2.1 `cute-sdk/opt_ops/shuttle_dram32/include/cute_opt_matmul.h`

```c
#ifndef CUTE_OPT_MATMUL_H
#define CUTE_OPT_MATMUL_H

#include "cute_tensor.h"
#include "cute_ops.h"
#include "cute_runtime.h"

/* 优化版 matmul — 针对 shuttle + dramsim32 的 tiling 策略 */
int cute_opt_matmul_tiled(
    const cute_matmul_desc_t *desc,
    uint64_t tile_m,  /* 手动指定的 tile 大小，0 = 自动 */
    uint64_t tile_n,
    uint64_t tile_k
);

/* 优化版 matmul — 双缓冲调度 */
int cute_opt_matmul_double_buffer(
    const cute_matmul_desc_t *desc
);

/* 自动选择最优策略 */
int cute_opt_matmul_auto(
    const cute_matmul_desc_t *desc
);

#endif /* CUTE_OPT_MATMUL_H */
```

### 5.2.2 实现思路

```c
int cute_opt_matmul_tiled(
    const cute_matmul_desc_t *desc,
    uint64_t tile_m, uint64_t tile_n, uint64_t tile_k
) {
    if (tile_m == 0) tile_m = CUTE_TENSOR_M;
    if (tile_n == 0) tile_n = CUTE_TENSOR_N;
    if (tile_k == 0) tile_k = CUTE_TENSOR_K;

    /* 手动 tiling 循环 */
    for (uint64_t m = 0; m < desc->M; m += tile_m) {
        for (uint64_t n = 0; n < desc->N; n += tile_n) {
            for (uint64_t k = 0; k < desc->K; k += tile_k) {
                cute_matmul_desc_t tile_desc = *desc;
                tile_desc.M = min(tile_m, desc->M - m);
                tile_desc.N = min(tile_n, desc->N - n);
                tile_desc.K = min(tile_k, desc->K - k);
                /* 调整 A/B/C/D 的 data 指针到 tile 起始位置 */
                tile_desc.A.data = (char*)desc->A.data + m * desc->A.stride_bytes + k * elem_size;
                tile_desc.B.data = (char*)desc->B.data + n * desc->B.stride_bytes + k * elem_size;
                tile_desc.D.data = (char*)desc->D.data + m * desc->D.stride_bytes + n * elem_size;

                cute_matmul_submit(&tile_desc);
                cute_wait_fifo_finish(800000000);
            }
        }
    }
    return 0;
}
```

### 5.2.3 Baseline 对比

```c
/* Test driver: baseline vs optimized */
int main(void) {
    cute_matmul_desc_t desc = { ... };

    /* Baseline */
    uint64_t t0 = cute_rdcycle();
    cute_matmul(&desc);
    uint64_t baseline_cycles = cute_rdcycle() - t0;
    cute_perf_t baseline_perf = cute_perf_query();

    /* 清空 D */
    memset(d, 0, sizeof(d));

    /* Optimized */
    t0 = cute_rdcycle();
    cute_opt_matmul_tiled(&desc, 0, 0, 0);
    uint64_t optimized_cycles = cute_rdcycle() - t0;
    cute_perf_t optimized_perf = cute_perf_query();

    printf("[CUTE_PERF] baseline=%lu optimized=%lu speedup=%.2f\n",
           baseline_cycles, optimized_cycles,
           (double)baseline_cycles / optimized_cycles);

    /* 正确性验证：优化后输出必须与 golden 一致 */
    int pass = verify_golden(d, golden_d, ...);
    printf("[CUTE_TEST] opt %s\n", pass ? "PASS" : "FAIL");
}
```

---

## Task 5.3: 实现 Trace.perf 初步分析

### 5.3.1 `trace/perf/timeline.py`

```python
"""
从 trace 事件构建时间线模型

事件序列:
  TASK_BEGIN → COMPUTE_START → COMPUTE_DONE → ... → TASK_END

分析指标:
  - 总执行周期
  - 计算活跃周期 / 总周期 = 计算利用率
  - 访存等待周期 = 总周期 - 计算活跃 - 控制开销
"""

@dataclass
class TaskTimeline:
    task_begin_cycle: int
    task_end_cycle: int
    compute_segments: List[Tuple[int, int]]  # (start, end)
    mem_segments: List[Tuple[int, int]]

    @property
    def total_cycles(self) -> int:
        return self.task_end_cycle - self.task_begin_cycle

    @property
    def compute_cycles(self) -> int:
        return sum(e - s for s, e in self.compute_segments)

    @property
    def compute_utilization(self) -> float:
        return self.compute_cycles / self.total_cycles if self.total_cycles > 0 else 0
```

### 5.3.2 `tools/perf/cute_perf_analyzer.py`

```python
"""
CUTE Top-Down 性能分析引擎

分析层级:
  Level 0: Overall Utilization
  Level 1: Pipeline Utilization (compute / memory / overlap)
  Level 2: Stall Analysis (memory stall / FIFO stall / config stall)
  Level 3: Detailed Breakdown (tile-level / access pattern / control overhead)
"""

@dataclass
class PerfReport:
    # Level 0
    total_cycles: int
    actual_tops: float
    peak_tops: float
    utilization: float

    # Level 1
    compute_util: float
    memory_util: float
    overlap_efficiency: float

    # Level 2
    memory_stall_pct: float
    fifo_stall_pct: float
    config_overhead_pct: float

    # Level 3
    tile_stats: List[dict]

    # 推荐建议
    recommendations: List[str]

class CutePerfAnalyzer:
    def __init__(self, hwconfig: dict):
        self.hwconfig = hwconfig
        self.peak_tops = self._compute_peak_tops()

    def analyze(self, events: List[TraceEvent], test_params: dict) -> PerfReport:
        timeline = build_timeline(events)
        return PerfReport(
            total_cycles=timeline.total_cycles,
            actual_tops=self._compute_actual_tops(timeline, test_params),
            peak_tops=self.peak_tops,
            utilization=...,
            compute_util=timeline.compute_utilization,
            ...
        )
```

### 5.3.3 `tools/perf/cute_perf_model.py`

```python
"""
CUTE Roofline 模型

Arithmetic Intensity = FLOPs / Bytes_transferred
Peak FLOPs = PE_count × frequency × 2 (MAC)
Peak Bandwidth = bus_width × frequency / 8

Roofline:
  Attainable TOPS = min(Peak_TOPS, Peak_BW × Arithmetic_Intensity)
"""

@dataclass
class RooflinePoint:
    label: str
    arithmetic_intensity: float
    actual_tops: float
    peak_tops: float
    peak_bandwidth: float  # GB/s
    roofline_tops: float   # min(peak_tops, peak_bw * AI)
    is_compute_bound: bool

def compute_roofline(
    hwconfig: dict,
    test_params: dict,
    perf_data: dict
) -> RooflinePoint:
    """计算 Roofline 模型"""
    M, N, K = test_params['M'], test_params['N'], test_params['K']
    flops = 2 * M * N * K  # MAC = 2 FLOPs
    bytes_transferred = (M*K + N*K + M*N) * elem_bytes  # A + B + D

    ai = flops / bytes_transferred
    actual_tops = flops / (perf_data['total_cycles'] / freq)

    return RooflinePoint(
        label=test_params.get('name', ''),
        arithmetic_intensity=ai,
        actual_tops=actual_tops,
        peak_tops=peak_tops,
        peak_bandwidth=peak_bw,
        roofline_tops=min(peak_tops, peak_bw * ai),
        is_compute_bound=ai > (peak_tops / peak_bw)
    )
```

### 5.3.4 性能报告输出

```text
═══════════════════════════════════════════════════
  CUTE Performance Analysis Report
  Config: cute2tops_scp64_dramsim32
  Test: matmul_i8_128x128x128
═══════════════════════════════════════════════════

Level 0 — Overall
  Total Cycles:        12,450
  Actual TOPS:         3.42
  Peak TOPS:           4.00
  Utilization:         85.5%  ████████████████░░░░

Level 1 — Pipeline
  Compute Util:        78.2%  ███████████████░░░░░
  Memory Util:         92.1%  ██████████████████░░
  Overlap Efficiency:  89.3%  █████████████████░░░

Level 2 — Stalls
  Memory Stall:        14.2%  (1,769 cycles)
  FIFO Stall:           3.1%  (  386 cycles)
  Config Overhead:      4.5%  (  561 cycles)

Roofline
  Arithmetic Intensity: 42.7 FLOP/Byte
  Actual: 3.42 TOPS  |  Roofline: 3.80 TOPS
  Bound: COMPUTE

Recommendations:
  ⚠ Memory stall 占比 14.2% → 检查双缓冲
═══════════════════════════════════════════════════
```

---

## Task 5.4: Perf CLI 工具

### 5.4.1 `tools/runner/cute-perf.py`

```text
Usage:
  tools/runner/cute-perf.py --artifact build/cute-runs/<run-id>
    分析单个 run artifact 的性能

  tools/runner/cute-perf.py --compare <artifact1> <artifact2>
    对比两个 run 的性能（baseline vs optimized）

  tools/runner/cute-perf.py --roofline --hwconfig <path> --test-params <json>
    生成 Roofline 图
```

---

## 验收标准总表

- [ ] Opt project 只匹配指定 HWConfig family（target matcher 验证）
- [ ] Baseline 和 optimized 至少都能运行
- [ ] 正确性仍由 Trace.func 或 golden checker 判断（优化不破坏正确性）
- [ ] Perf report 能解释优化前后至少一个指标变化
- [ ] Top-Down 分析引擎能输出 Level 0-2 指标
- [ ] Roofline 模型能计算 Arithmetic Intensity 和 Attainable TOPS
- [ ] Artifact 保存 baseline/optimized 的 run-id 和比较报告
- [ ] `cute-perf.py --compare` 能输出对比结果

---

## 不做事项

- 不要求优化通用化到所有 HWConfig。
- 不要求完整模型（Phase 6）。
- 不要求 perf model 最终定稿（Level 3 tile breakdown 可后续完善）。
- 不做 FPGA 端 trace 采集。
- 不要求可视化图表（先做 console 报告，后续加 matplotlib）。

---

## 风险与应对

| 风险 | 应对 |
|------|------|
| 过早优化不稳定底层 | 必须建立在通过的 Tensor/Layer/Fuse 测试上 |
| Benchmark 噪声 | 固定 simulator、DRAMSim preset、max cycles、variant 参数 |
| Perf 指标口径漂移 | 即使 Trace.perf 待定，也要在 report 中记录指标定义 |
| Opt op 绑定硬件太紧 | 通过 project.yaml target 明确绑定，不支持时返回 `TARGET_UNSUPPORTED` |
| Trace 事件不足以做 perf 分析 | Phase 5 允许只用 query 指令的性能计数器（total/compute/read/write），不做 tile 级分析 |

---

## 与 Phase 4 的衔接

- 复用 `cute_llama_ffn_fused` 作为优化对象
- 复用 Trace.func 的 verify 结果确保优化不破坏正确性
- 在 fused layer op 上叠加 SOC-specific 优化

## 与 Phase 6 的衔接

Phase 5 完成后，Phase 6 可以直接：
- 组合 tensor/layer/fuse/opt lib 形成完整模型
- 用 Top-Down 分析引擎做端到端 profile
- 用 Roofline 模型评估模型级效率
