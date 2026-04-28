# Phase 4 Plan: FuseLayerTest -> Fuse Layer Op Lib

## 目标

Phase 4 的目标是在 layer op lib 基础上引入融合语义，形成第一个 `fuse_layer op lib`。

融合测试不是简单把多个 layer 放在一个 C 文件里，而是验证：

- 中间数据是否按预期被消除或复用。
- 最终输出是否与未融合 golden 对齐。
- target 范围是否明确变窄。
- trace.func 是否能解释融合路径的必要语义。

## 候选样板

建议二选一：

- LLaMA FFN fused。
- attention QKV fused。

选择标准：

- 代码路径已有雏形。
- 能基于 Phase 3 layer op lib 改造。
- 有可获得的非融合 golden。
- 融合收益或语义边界清晰。

## 主要产物

```text
cutetest/fuse_layer_ops/<fuse-project>/
├── project.yaml
├── include/
├── src/
├── golden/
├── data/
└── build_rules/
```

## Project.yaml 要求

```yaml
id: fuse_layer.llama_ffn_fused
kind: fuse_layer_test
target:
  required_capability:
    tensor_ops: [matmul]
    layer_ops: [llama_ffn]
    fused_ops: [llama_ffn_fused]
    trace_func_level: F4_fused_layer
code:
  entry: src/main.c
  build: make
  deps:
    - cutetest/runtime/cute_runtime
    - cutetest/tensor_ops/matmul
    - cutetest/layer_ops/llama_ffn
  variants:
    - name: small_fused
golden:
  level: fused_layer
  source: golden/fused_ref.py
```

## Fuse Layer Op Lib 边界

Fuse layer op lib 应负责：

- 融合调度。
- 中间 tensor 生命周期管理。
- 融合前后 layout 约定。
- 调用下层 layer/tensor op lib。
- 暴露 fused op API。

不应负责：

- 重新实现 runtime。
- 重新实现基础 matmul。
- 伪装成所有 HWConfig 都支持。

## Trace.func 口径

Phase 4 仍不展开 Trace schema，但要明确 `F4_fused_layer` 的目标：

- 能验证最终输出。
- 可选验证关键 intermediate invariant。
- 能区分“运行成功但无法验证融合语义”和“融合语义 pass”。

状态：

```text
RUN_OK
FINAL_OUTPUT_PASS
INTERMEDIATE_INVARIANT_PASS
FUNC_MODEL_NOT_READY
PASS
FAIL
```

## 验收标准

- FuseLayerTest 有明确 target，且比 LayerTest 更窄。
- 至少一个 fused variant 能运行。
- fused op lib 复用 layer/tensor/runtime lib。
- 有 golden 或非融合等价路径。
- 不支持的 HWConfig 返回 `TARGET_UNSUPPORTED`。

## 不做事项

- 不做 SOC-specific 最终优化。
- 不要求完整 model test。
- 不要求 perf bottleneck 完整解释。

## 风险

- 融合正确性难判断：先只要求最终输出，再逐步加入 intermediate invariant。
- target 过宽：project.yaml 必须显式声明 fused capability。
- 代码层级倒挂：fuse op 不能绕过下层 lib 大量复制实现。

