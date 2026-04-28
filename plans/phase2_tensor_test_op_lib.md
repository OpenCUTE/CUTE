# Phase 2 Plan: TensorTest -> Tensor Op Lib

## 目标

Phase 2 的目标是在 Phase 1 runtime lib 上包装 Tensor Config，形成第一个可复用 tensor op lib，并用 matmul TensorTest 验证。

这阶段要让框架第一次真正验证“数据结果”：

- `cutetest/tensor_ops/matmul/project.yaml` 成为 Test 主入口。
- Tensor descriptor / Tensor config wrapper 可用。
- 能构建并运行 matmul variant。
- 能通过占位或初版 `Trace.func F1/F2` 重建输出并比较 golden。

## 主要产物

```text
cutetest/tensor_ops/matmul/
├── project.yaml
├── include/cute_tensor_matmul.h
├── src/main.c
├── src/matmul_driver.c
├── golden/golden_matmul.py
├── data/
└── build_rules/Makefile

cutetest/include/cute_tensor.h
cutetest/include/cute_ops.h
```

## Tensor Descriptor

建议第一版保持简单：

```c
typedef struct {
    void *data;
    uint64_t rows;
    uint64_t cols;
    uint64_t stride_bytes;
    uint64_t dtype;
    uint64_t layout;
} cute_tensor_t;
```

Matmul descriptor：

```c
typedef struct {
    cute_tensor_t A;
    cute_tensor_t B;
    cute_tensor_t C;
    cute_tensor_t D;
    uint64_t M;
    uint64_t N;
    uint64_t K;
    uint64_t bias_mode;
    uint64_t transpose;
} cute_matmul_desc_t;
```

第一版 API：

```c
int cute_matmul_submit(const cute_matmul_desc_t *desc);
int cute_matmul_wait(uint64_t timeout_cycles);
```

## Project.yaml 要求

`cutetest/tensor_ops/matmul/project.yaml` 至少包含：

```yaml
id: tensor.matmul
kind: tensor_test
target:
  required_capability:
    tensor_ops: [matmul]
    datatypes: [i8i8i32]
    trace_func_level: F2_tensor_op
code:
  entry: src/main.c
  build: make
  variants:
    - name: i8_128
      M: 128
      N: 128
      K: 128
      dtype: i8i8i32
golden:
  level: tensor_op
  source: golden/golden_matmul.py
  compare:
    mode: exact
```

## Trace.func 口径

Trace 设计仍未专题展开。本阶段允许两种路径：

1. 结构化 trace 已可用：解析 `D_STORE_DATA`。
2. 结构化 trace 尚不可用：使用现有日志/store trace 的 legacy parser。

无论哪种方式，artifact 中都必须标明：

```text
trace_func_level: F1_store or F2_tensor_op
trace_source: structured / legacy
```

## Golden

第一版只做整数 exact：

- `i8i8i32`
- M/N/K 小规模固定 variant
- golden 可用 Python 生成
- 输出 `golden.npy` 或简单二进制/csv

浮点、fp8/mxfp/nvfp4 后续扩展。

## Runner 扩展

Runner 需要新增：

- project variant 选择。
- variant 参数传入 build。
- golden 生成步骤。
- actual 重建步骤。
- compare 步骤。

状态增加：

```text
GENERATE_GOLDEN
RECONSTRUCT_ACTUAL
COMPARE_GOLDEN
```

## Artifact 增量

```text
test/golden/golden.npy
func/actual.npy
func/mismatch.csv
func/verify.json
```

## 验收标准

- `tensor.matmul:i8_128` 能在至少一个 HWConfig 上运行。
- 能生成 golden。
- 能重建 actual。
- compare 通过，TensorTest pass。
- tensor op lib API 被 `src/main.c` 使用，而不是在测试中散写指令。

## 不做事项

- 不做 layer。
- 不做 fused layer。
- 不做复杂 perf。
- 不要求所有 datatype 都支持。

## 风险

- D store trace 不稳定：允许 legacy parser 兜底，但 artifact 必须标明。
- Tensor layout 不清楚：先固定 row-major 和单个 dtype。
- Runtime API 不够：只补 matmul 所需，不扩张到通用框架。

