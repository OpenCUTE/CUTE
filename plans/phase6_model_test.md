# Phase 6 Plan: ModelTest

## 目标

Phase 6 的目标是用下层 lib 组合完整模型或模型片段测试，形成 model-level correctness/profile。

ModelTest 是最上层测试，target 最窄，不追求所有 HWConfig 都支持。

## 候选模型

建议选择一个优先目标：

- ResNet50 子集或完整模型。
- BERT layer stack。
- LLaMA3 1B 的若干层或一个完整 block。

选择标准：

- 已有代码或 golden。
- 可拆成已有 layer/fuse/opt lib。
- 运行时间可控。
- target HWConfig 明确。

## 主要产物

```text
cutetest/model_tests/<model>/
├── project.yaml
├── src/
├── include/
├── data/
├── golden/
├── reports/
└── build_rules/
```

## Project.yaml 要求

```yaml
id: model.llama3_1b_block
kind: model_test
target:
  hwconfigs:
    include_tags: [model_llama, shuttle512]
  required_capability:
    layer_ops: [llama_ffn]
    fused_ops: [llama_ffn_fused]
    trace_func_level: F5_model
code:
  entry: src/main.c
  build: make
  deps:
    - cutetest/runtime/cute_runtime
    - cutetest/tensor_ops/matmul
    - cutetest/layer_ops/llama_ffn
    - cutetest/fuse_layer_ops/llama_ffn_fused
    - cutetest/opt_ops/shuttle512_dram48
  variants:
    - name: block0
    - name: block0_optimized
golden:
  level: model
  source: external_checker
```

## ModelTest 边界

ModelTest 负责：

- 组合下层 op lib。
- 管理模型级输入输出。
- 调用外部或内部 golden。
- 输出端到端 correctness report。
- 输出端到端 performance report。

ModelTest 不应：

- 复制 layer/fuse/opt 实现。
- 假装 target 很宽。
- 绕过 artifact 直接手工读日志。

## Correctness 策略

允许多级状态：

```text
RUN_OK
LAYER_OUTPUT_PASS
MODEL_OUTPUT_PASS
EXTERNAL_CHECKER_PASS
FUNC_MODEL_NOT_READY
FAIL
```

如果 `Trace.func F5_model` 未完成，可以使用 external checker，但 artifact 必须记录：

```text
verify_source: trace_func / external_checker / hybrid
```

## Performance 策略

ModelTest 的 profile 应关注：

- model total cycles。
- per-layer cycles。
- fused vs non-fused 对比。
- opt vs baseline 对比。
- memory pressure。
- stage-level profile，若 Trace.perf 支持。

Trace.perf 仍可处于待定状态，但 artifact 必须保存足够 raw data 供后续重分析。

## 验收标准

- 至少一个 model variant 能运行。
- target 明确绑定 HWConfig family。
- correctness 状态明确，不将 `RUN_OK` 误判为 pass。
- report 同时包含 correctness 和 performance summary。
- 下层 lib 复用关系清晰。

## 不做事项

- 不追求所有模型。
- 不追求所有 HWConfig。
- 不要求 F5_model 一次完成。
- 不要求最终 perf visualization。

## 风险

- 模型测试过重：先做模型片段或单 block。
- external golden 难维护：记录 checker 版本、输入、输出快照。
- 上层复制底层代码：强制通过 deps 调用下层 lib。

