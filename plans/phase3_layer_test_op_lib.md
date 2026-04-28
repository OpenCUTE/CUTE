# Phase 3 Plan: LayerTest -> Layer Op Lib

## 目标

Phase 3 的目标是在 tensor op lib 上叠加向量任务和 layer 语义，形成第一个 layer op lib。

建议选择一个代表样板：

- ResNet50 的单个 conv layer，或
- LLaMA FFN 的一个非融合版本。

选择标准：

- 已有测试代码或 golden 参考。
- 输入输出规模可控。
- 能复用 Phase 2 的 tensor op lib。
- 不依赖复杂融合。

## 主要产物

```text
cutetest/layer_ops/<layer-project>/
├── project.yaml
├── include/
├── src/
├── data/
├── golden/
└── build_rules/
```

示例：

```text
cutetest/layer_ops/llama_ffn/
```

## Project.yaml 要求

```yaml
id: layer.llama_ffn
kind: layer_test
target:
  required_capability:
    tensor_ops: [matmul]
    layer_ops: [llama_ffn]
    trace_func_level: F3_layer
code:
  entry: src/main.c
  build: make
  deps:
    - cutetest/runtime/cute_runtime
    - cutetest/tensor_ops/matmul
  variants:
    - name: small_ffn
      hidden: 256
      intermediate: 1024
golden:
  level: layer
  source: golden/layer_ref.py
```

## Layer Op Lib 边界

Layer op lib 不应该复制底层 tensor op 实现。它应该：

- 调用 tensor op lib。
- 管理 layer 级输入输出。
- 管理向量任务或非矩阵部分。
- 管理 layer 中多个 tensor op 的顺序。
- 负责 layer-level layout 约定。

## Trace.func 口径

Trace 仍待专题设计，本阶段只要求：

- project 声明需要 `F3_layer`。
- 如果 `F3_layer` 未实现，允许状态为 `FUNC_MODEL_NOT_READY`。
- 若要标记 LayerTest pass，必须能比较 layer output。

可接受状态：

```text
RUN_OK
TRACE_OK
FUNC_MODEL_NOT_READY
PASS
FAIL
```

## Golden

可用来源：

- Python layer reference。
- 已有 C checker。
- 已有模型层 golden 数据。

本阶段应优先选一个已有 golden 路径最清楚的 layer。

## 验收标准

- `LayerTest` target 范围比 `TensorTest` 更窄，并在 project.yaml 中显式表达。
- layer project 能复用 runtime lib 和 tensor op lib。
- 至少一个 layer variant 能运行。
- 若 `Trace.func F3_layer` 已实现，则 LayerTest pass。
- 若未实现，则状态清晰标记为 `FUNC_MODEL_NOT_READY`，不能误判为 pass。

## 不做事项

- 不做 fused layer。
- 不做 SOC-specific 足量优化。
- 不要求完整模型。
- 不要求最终 trace 设计定稿。

## 风险

- layer 代码复制 tensor 细节：必须通过 tensor op lib 调用。
- golden 太复杂：选择最小 layer variant。
- target 范围虚标：target matcher 必须输出不支持原因。

