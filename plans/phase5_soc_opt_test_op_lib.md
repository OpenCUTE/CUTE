# Phase 5 Plan: SOCOptTest -> Opt Op Lib

## 目标

Phase 5 的目标是结合特定 SoC/HWConfig family 做足量优化，形成 `opt_op_lib`。

这阶段的重点从“功能能否正确”转向“在特定 HWConfig 上如何跑得更好”。因此 target 会非常窄。

## 候选 HWConfig Family

建议选择一个明确家族：

```text
Shuttle512 + DRAM48
```

或：

```text
CUTE4Tops + specific bus/membus width + DRAMSim preset
```

选择标准：

- simulator 可用。
- baseline 测试可运行。
- 有明确优化目标。
- 能稳定复现实验。

## 主要产物

```text
cutetest/opt_ops/<hw-family>/
├── project.yaml
├── include/
├── src/
├── baselines/
├── reports/
└── build_rules/
```

## Project.yaml 要求

```yaml
id: opt.shuttle512_dram48
kind: soc_opt_test
target:
  hwconfigs:
    include_tags: [shuttle512, dramsim48]
  required_capability:
    trace_perf_level: P2_stage
code:
  entry: src/main.c
  build: make
  deps:
    - cutetest/runtime/cute_runtime
    - cutetest/tensor_ops/matmul
    - cutetest/layer_ops/llama_ffn
  variants:
    - name: baseline
    - name: optimized
golden:
  level: layer
  source: inherited
perf:
  baseline: baselines/baseline.json
```

## Opt Op Lib 边界

Opt op lib 可以做：

- 针对特定 SoC 的 tiling。
- 针对 DRAMSim preset 的调度。
- 针对 bus/memory width 的数据布局。
- 针对 core/TCM/cache 的路径选择。

Opt op lib 不应伪装成通用 op lib。它必须显式绑定 target family。

## Trace.perf 口径

Trace.perf 仍待专题设计。本阶段只要求：

- 能保存 raw perf data。
- 能对 baseline/optimized 做基本对比。
- 能输出 stage/memory/utilization 的初步报告，哪怕是占位指标。

可接受状态：

```text
CORRECTNESS_PASS
PERF_PROFILE_OK
PERF_MODEL_NOT_READY
PERF_REGRESSED
PERF_IMPROVED
```

## 验收标准

- opt project 只能匹配指定 HWConfig family。
- baseline 和 optimized 至少都能运行。
- correctness 仍由 Trace.func 或 inherited checker 判断。
- perf report 能解释优化前后至少一个指标变化。
- artifact 保存 baseline/optimized 的 run-id 和比较报告。

## 不做事项

- 不要求优化通用化到所有 HWConfig。
- 不要求完整模型。
- 不要求 perf model 最终定稿。

## 风险

- 过早优化不稳定底层：必须建立在通过的 Tensor/Layer/Fuse 测试上。
- benchmark 噪声：固定 simulator、DRAMSim preset、max cycles、variant 参数。
- perf 指标口径漂移：即使 Trace.perf 待定，也要在 report 中记录指标定义。

