# Phase 2 Plan: TensorTest -> Tensor Op Lib

## 目标

Phase 2 的目标是在 Phase 1 runtime lib 上包装 Tensor Config，形成第一个可复用 tensor op lib，并用 matmul TensorTest 验证。

这阶段要让框架第一次真正验证"数据结果"：

- `cute-sdk/tensor_ops/matmul/project.yaml` 成为 Test 主入口。
- Tensor descriptor / Tensor config wrapper 可用。
- 能构建并运行 matmul variant。
- 能通过占位或初版 `Trace.func F1/F2` 重建输出并比较 golden。

## 主要产物

```text
cute-sdk/include/
├── cute_tensor.h                       # Tensor 描述符（公共头文件）
├── cute_ops.h                          # Tensor op 封装（公共头文件）

cute-sdk/tensor_ops/matmul/
├── project.yaml                        # Phase 0 已创建
├── src/
│   └── main.c                          # Matmul 测试驱动
├── golden/
│   └── golden_matmul.py                # Golden 数据生成脚本
├── data/                               # 自动生成的 golden .h 文件
│   ├── golden_i8_128.h
│   └── golden_i8_64.h
└── build_rules/
    └── Makefile

tools/verify/
├── cute_golden.py                      # Golden 参考生成引擎
├── cute_verify.py                      # 数值比对引擎
└── cute_trace_golden.py                # 从 trace 提取 D tensor（占位）

scripts/
├── cute-gen-golden.py                  # Golden 生成 CLI
└── cute-run.py                         # Runner 扩展（增加 golden/verify 步骤）
```

---

## Task 2.1: 实现 Tensor Descriptor

### 2.1.1 `cute-sdk/include/cute_tensor.h`

设计原则：
- 与现有 golden .h 的数据布局对齐（row-major, `static a[M][K] __attribute__((aligned(256)))`）
- stride 自动计算与现有 `APPLICATION_K * sizeof(a[0][0])` 逻辑对齐
- 使用 `datatype.h.generated` 的类型定义

```c
#ifndef CUTE_TENSOR_H
#define CUTE_TENSOR_H

#include <stdint.h>
#include <stddef.h>
#include "datatype.h.generated"
#include "validation.h.generated"

/* Tensor 描述符 */
typedef struct {
    void     *data;          /* 数据指针，必须 256 字节对齐 */
    uint64_t  rows;          /* 行数 (M for A, N for B) */
    uint64_t  cols;          /* 列数 (K for A, K for B, N for D) */
    uint64_t  stride_bytes;  /* 行步长（字节），0 = 自动 packed */
    uint64_t  elem_type;     /* CUTEDataTypeI8I8I32 等 */
} cute_tensor_t;

/* 初始化 tensor，stride 自动计算 */
static inline void cute_tensor_init(
    cute_tensor_t *t, void *data,
    uint64_t rows, uint64_t cols, uint64_t elem_type
) {
    t->data = data;
    t->rows = rows;
    t->cols = cols;
    t->elem_type = elem_type;
    if (t->stride_bytes == 0) {
        uint64_t bits = CUTE_GET_ADATA_BITWIDTH(elem_type);
        t->stride_bytes = cols * (bits / 8);
    }
}

/* 获取 tensor 元素字节大小 */
static inline uint64_t cute_tensor_elem_size(const cute_tensor_t *t) {
    return CUTE_GET_ADATA_BITWIDTH(t->elem_type) / 8;
}

/* 获取 tensor 总字节大小 */
static inline uint64_t cute_tensor_total_bytes(const cute_tensor_t *t) {
    return t->rows * t->stride_bytes;
}

/* Bias 模式 */
#define CUTE_BIAS_ZERO       1  /* TaskTypeTensorZeroLoad */
#define CUTE_BIAS_REPEAT_ROW 2  /* TaskTypeTensorRepeatRowLoad */
#define CUTE_BIAS_FULL       3  /* TaskTypeTensorLoad */

/* Matmul 描述符 */
typedef struct {
    cute_tensor_t A;         /* 输入 A [M x K] */
    cute_tensor_t B;         /* 输入 B [N x K] */
    cute_tensor_t C;         /* Bias (可为 NULL) */
    cute_tensor_t D;         /* 输出 D [M x N] */
    uint64_t M;
    uint64_t N;
    uint64_t K;
    uint64_t bias_mode;      /* CUTE_BIAS_ZERO / REPEAT_ROW / FULL */
    uint64_t transpose;      /* 0 or 1 */
} cute_matmul_desc_t;

/* Conv 描述符 */
typedef struct {
    cute_tensor_t A;         /* 输入 [ohow x ic] */
    cute_tensor_t B;         /* 权重 [oc x ic] */
    cute_tensor_t C;         /* Bias */
    cute_tensor_t D;         /* 输出 [ohow x oc] */
    uint64_t ohow;
    uint64_t oc;
    uint64_t ic;
    uint64_t kernel_size;
    uint64_t conv_stride;
    uint64_t oh_max;
    uint64_t ow_max;
    uint64_t bias_mode;
    uint64_t transpose;
} cute_conv_desc_t;

/* Blockscale Matmul 描述符 */
typedef struct {
    cute_tensor_t A;
    cute_tensor_t B;
    cute_tensor_t A_scale;   /* A scale 数据 */
    cute_tensor_t B_scale;   /* B scale 数据 */
    cute_tensor_t C;
    cute_tensor_t D;
    uint64_t M, N, K;
    uint64_t bias_mode;
    uint64_t transpose;
} cute_blockscale_matmul_desc_t;

#endif /* CUTE_TENSOR_H */
```

### 2.1.2 验收

- 类型定义与现有 golden .h 中的数据布局对齐
- `CUTE_BIAS_ZERO` 等常量与 `cuteMarcoinstHelper.h` 中的 `TaskTypeTensorZeroLoad` 值一致

---

## Task 2.2: 实现 Tensor Op 封装

### 2.2.1 `cute-sdk/include/cute_ops.h`

设计原则：
- 使用 `instruction.h.generated` 的封装函数，不手写 funct
- 参数传递顺序与现有 `issue_cute_matmul_marco_inst` 一致
- 上层调用者只接触 `cute_tensor_t` 和 `cute_matmul_desc_t`

```c
#ifndef CUTE_OPS_H
#define CUTE_OPS_H

#include "cute_tensor.h"
#include "cute_runtime.h"
#include "instruction.h.generated"

/* ---- Matmul ---- */

/* 提交 matmul 任务到 CUTE 硬件（不等待完成） */
static inline uint64_t cute_matmul_submit(const cute_matmul_desc_t *desc) {
    /* 配置 A/B/C/D tensor 基地址和 stride */
    CUTE_CONFIG_TENSOR_A((uint64_t)desc->A.data, desc->A.stride_bytes);
    CUTE_CONFIG_TENSOR_B((uint64_t)desc->B.data, desc->B.stride_bytes);
    CUTE_CONFIG_TENSOR_C(
        desc->C.data ? (uint64_t)desc->C.data : 0,
        desc->C.data ? desc->C.stride_bytes : 0
    );
    CUTE_CONFIG_TENSOR_D((uint64_t)desc->D.data, desc->D.stride_bytes);

    /* 配置 M/N/K */
    CUTE_CONFIG_TENSOR_DIM(desc->M, desc->N, desc->K, 0);

    /* 配置 conv 参数（matmul 是 conv 的特例） */
    CUTE_CONFIG_CONV_PARAMS(
        desc->A.elem_type, desc->bias_mode, desc->transpose,
        1,   /* conv_stride = 1 for matmul */
        0,   /* conv_oh_max = 0 */
        0,   /* conv_ow_max = 0 */
        1,   /* kernel_size = 1 */
        0,   /* conv_oh_per_add = 0 */
        CUTE_TENSOR_N,  /* conv_ow_per_add = Tensor_N */
        0,   /* conv_oh_index = 0 */
        0    /* conv_ow_index = 0 */
    );

    /* 发送宏指令 */
    return CUTE_SEND_MACRO_INST(0, 0);
}

/* 提交 matmul 并等待完成 */
static inline uint64_t cute_matmul(const cute_matmul_desc_t *desc) {
    cute_matmul_submit(desc);
    return cute_wait_fifo_finish(800000000);
}

/* ---- Conv ---- */

/* 提交 conv 任务到 CUTE 硬件（不等待完成） */
static inline uint64_t cute_conv_submit(const cute_conv_desc_t *desc) {
    CUTE_CONFIG_TENSOR_A((uint64_t)desc->A.data, desc->A.stride_bytes);
    CUTE_CONFIG_TENSOR_B((uint64_t)desc->B.data, desc->B.stride_bytes);
    CUTE_CONFIG_TENSOR_C(
        desc->C.data ? (uint64_t)desc->C.data : 0,
        desc->C.data ? desc->C.stride_bytes : 0
    );
    CUTE_CONFIG_TENSOR_D((uint64_t)desc->D.data, desc->D.stride_bytes);
    CUTE_CONFIG_TENSOR_DIM(desc->ohow, desc->oc, desc->ic,
                           desc->kernel_size * desc->ic * /* kernel_stride */);
    CUTE_CONFIG_CONV_PARAMS(
        desc->A.elem_type, desc->bias_mode, desc->transpose,
        desc->conv_stride, desc->oh_max, desc->ow_max,
        desc->kernel_size,
        0, 0,  /* conv_oh_per_add, conv_ow_per_add — 待确认计算逻辑 */
        0, 0   /* conv_oh_index, conv_ow_index */
    );
    return CUTE_SEND_MACRO_INST(0, 0);
}

/* 提交 conv 并等待完成 */
static inline uint64_t cute_conv(const cute_conv_desc_t *desc) {
    cute_conv_submit(desc);
    return cute_wait_fifo_finish(800000000);
}

/* ---- Blockscale Matmul ---- */

static inline uint64_t cute_blockscale_matmul_submit(
    const cute_blockscale_matmul_desc_t *desc
) {
    CUTE_CONFIG_TENSOR_A((uint64_t)desc->A.data, desc->A.stride_bytes);
    CUTE_CONFIG_TENSOR_B((uint64_t)desc->B.data, desc->B.stride_bytes);
    CUTE_CONFIG_SCALE_A((uint64_t)desc->A_scale.data);
    CUTE_CONFIG_SCALE_B((uint64_t)desc->B_scale.data);
    CUTE_CONFIG_TENSOR_C(
        desc->C.data ? (uint64_t)desc->C.data : 0,
        desc->C.data ? desc->C.stride_bytes : 0
    );
    CUTE_CONFIG_TENSOR_D((uint64_t)desc->D.data, desc->D.stride_bytes);
    CUTE_CONFIG_TENSOR_DIM(desc->M, desc->N, desc->K, 0);
    CUTE_CONFIG_CONV_PARAMS(
        desc->A.elem_type, desc->bias_mode, desc->transpose,
        1, 0, 0, 1, 0, CUTE_TENSOR_N, 0, 0
    );
    return CUTE_SEND_MACRO_INST(0, 0);
}

static inline uint64_t cute_blockscale_matmul(
    const cute_blockscale_matmul_desc_t *desc
) {
    cute_blockscale_matmul_submit(desc);
    return cute_wait_fifo_finish(800000000);
}

#endif /* CUTE_OPS_H */
```

### 2.2.2 注意事项

- `CUTE_CONFIG_CONV_PARAMS` 的 `conv_oh_per_add` 和 `conv_ow_per_add` 计算逻辑需要从现有 `cuteMarcoinstHelper.h` 的 `issue_cute_config_MatMul` 函数中确认：
  - `conv_ow_per_add = Tensor_M_Element_Length` (即 `CUTE_TENSOR_N`)
  - `conv_oh_per_add = 0`
- 如果 `instruction.h.generated` 生成的封装函数参数签名与上述不一致，需要调整 HeaderGenerator 或在这里做适配

### 2.2.3 验收

- `cute_ops.h` 的 matmul 封装与 `issue_cute_matmul_marco_inst` 功能等价
- 不依赖 `cuteMarcoinstHelper.h`

---

## Task 2.3: 实现 Matmul Test Driver

### 2.3.1 `cute-sdk/tensor_ops/matmul/src/main.c`

从 60 行样板到 ~15 行的新方式：

```c
#include <stdio.h>
#include <stdint.h>
#include "cute_runtime.h"
#include "cute_tensor.h"
#include "cute_ops.h"

/* Golden 数据由 cute-gen-golden.py 生成 */
#include VARIANT_GOLDEN_HEADER

int main(void) {
    cute_print_config_info();
    printf("[CUTE_TEST] matmul variant=%s start\n", VARIANT_NAME);

    /* 初始化 tensor 描述符 */
    cute_tensor_t A, B, C, D;
    cute_tensor_init(&A, a, APPLICATION_M, APPLICATION_K, CUTEDataTypeI8I8I32);
    cute_tensor_init(&B, b, APPLICATION_N, APPLICATION_K, CUTEDataTypeI8I8I32);
    cute_tensor_init(&D, d, APPLICATION_M, APPLICATION_N, CUTEDataTypeI8I8I32);

    /* 配置 matmul */
    cute_matmul_desc_t desc = {
        .A = A, .B = B, .C = {0}, .D = D,
        .M = APPLICATION_M, .N = APPLICATION_N, .K = APPLICATION_K,
        .bias_mode = CUTE_BIAS_ZERO,
        .transpose = 0
    };

    /* 执行 */
    uint64_t wait_cycles = cute_matmul(&desc);
    printf("[CUTE_TEST] matmul wait=%lu cycles\n", wait_cycles);

    /* 性能查询 */
    cute_perf_t perf = cute_perf_query();
    cute_perf_print(&perf);

    /* 验证 golden */
    int pass = 1;
    for (int i = 0; i < APPLICATION_M && pass; i++) {
        for (int j = 0; j < APPLICATION_N && pass; j++) {
            if (d[i][j] != gloden_c[i][j]) {
                printf("[CUTE_VERIFY] mismatch at [%d][%d]: got %d expected %d\n",
                       i, j, d[i][j], gloden_c[i][j]);
                pass = 0;
            }
        }
    }

    if (pass) {
        printf("[CUTE_TEST] matmul PASS\n");
    } else {
        printf("[CUTE_TEST] matmul FAIL\n");
    }

    return pass ? 0 : -1;
}
```

### 2.3.2 Build Rules

`cute-sdk/tensor_ops/matmul/build_rules/Makefile` 与 Phase 1 类似，但增加：
- 依赖 runtime lib
- 通过 `-D` 传入 variant 参数

```makefile
VARIANT ?= i8_128

# Variant 参数映射
ifeq ($(VARIANT),i8_128)
  VARIANT_M = 128
  VARIANT_N = 128
  VARIANT_K = 128
  VARIANT_DTYPE = CUTEDataTypeI8I8I32
  VARIANT_GOLDEN_HEADER = "golden_i8_128.h"
endif
ifeq ($(VARIANT),i8_64)
  VARIANT_M = 64
  VARIANT_N = 64
  VARIANT_K = 64
  VARIANT_DTYPE = CUTEDataTypeI8I8I32
  VARIANT_GOLDEN_HEADER = "golden_i8_64.h"
endif

CFLAGS += -DVARIANT_NAME=\"$(VARIANT)\"
CFLAGS += -DVARIANT_GOLDEN_HEADER=$(VARIANT_GOLDEN_HEADER)
CFLAGS += -DAPPLICATION_M=$(VARIANT_M) -DAPPLICATION_N=$(VARIANT_N) -DAPPLICATION_K=$(VARIANT_K)
CFLAGS += -I$(PWD)/../data      # golden .h 文件目录
```

### 2.3.3 验收

- 测试代码不包含 `cuteMarcoinstHelper.h`
- 使用 `cute_matmul()` 封装而非手写 `issue_cute_matmul_marco_inst`
- 使用 `cute_tensor_t` 描述符而非手动计算 stride
- Golden 验证在 C 代码中完成（int32 精确匹配）

---

## Task 2.4: 实现 Golden 生成器

### 2.4.1 `tools/verify/cute_golden.py`

```python
"""
CUTE Golden 参考生成引擎

支持的 op:
  - matmul: numpy int32 / float32 matmul
  - conv:   scipy signal correlate2d (后续)

输出格式:
  - C header (.h) 文件，与现有 golden .h 格式对齐
  - 或 numpy .npy 文件（用于 Python 端比对）
"""

import numpy as np
from dataclasses import dataclass
from typing import Optional

@dataclass
class GoldenConfig:
    op: str              # "matmul" | "conv" | "blockscale_matmul"
    dtype: str           # "i8i8i32" | "fp16fp16fp32" | ...
    M: int
    N: int
    K: int
    bias_mode: str       # "zero" | "repeat_row" | "full"
    kernel_size: int = 1
    conv_stride: int = 1
    # ... conv params

def generate_golden_matmul(cfg: GoldenConfig, seed: int = 42) -> dict:
    """生成 matmul golden 数据"""
    rng = np.random.RandomState(seed)

    if cfg.dtype.startswith("i8"):
        a = rng.randint(-128, 127, (cfg.M, cfg.K), dtype=np.int8)
        b = rng.randint(-128, 127, (cfg.N, cfg.K), dtype=np.int8)
        # CUTE matmul: D = A @ B^T (B is [N x K])
        golden = np.int32(a) @ np.int32(b.T)
    elif cfg.dtype.startswith("fp16"):
        # float32 reference, round to fp16
        a = rng.randn(cfg.M, cfg.K).astype(np.float32)
        b = rng.randn(cfg.N, cfg.K).astype(np.float32)
        golden = a @ b.T
    # ... 其他 dtype

    return {"a": a, "b": b, "golden": golden}

def golden_to_header(data: dict, cfg: GoldenConfig, output_path: str):
    """将 golden 数据写为 C header 文件"""
    # 格式与现有 matmul_value_mnk_*.h 对齐
    ...
```

### 2.4.2 `tools/runner/cute-gen-golden.py`

```text
Usage:
  tools/runner/cute-gen-golden.py \
    --project cute-sdk/tensor_ops/matmul \
    --variant i8_128 \
    --output-dir cute-sdk/tensor_ops/matmul/data

行为:
  1. 读取 project.yaml
  2. 找到对应 variant 的参数 (M, N, K, dtype)
  3. 调用 cute_golden.py 生成 golden 数据
  4. 输出 golden_i8_128.h 到 data/ 目录
```

### 2.4.3 输出格式

Golden header 与现有格式对齐，确保现有对比逻辑可以复用：

```c
// golden_i8_128.h — Auto-generated by cute-gen-golden.py
#define APPLICATION_M 128
#define APPLICATION_N 128
#define APPLICATION_K 128

static char a[128][128] __attribute__((aligned(256))) = { ... };
static char b[128][128] __attribute__((aligned(256))) = { ... };
static int gloden_c[128][128] __attribute__((aligned(256))) = { ... };
static int d[128][128] __attribute__((aligned(256))) = { 0 };
```

### 2.4.4 验收

- `cute-gen-golden.py` 生成的 `.h` 文件格式与现有手工生成的 golden 一致
- INT8 golden 与现有 `get_matrix_test.c` 生成的值在相同 seed 下一致

---

## Task 2.5: 实现 Verify 比对引擎

### 2.5.1 `tools/verify/cute_verify.py`

```python
"""
CUTE 数值比对引擎
"""

from dataclasses import dataclass
from typing import Optional
import numpy as np

@dataclass
class VerifyResult:
    passed: bool
    total_elements: int
    mismatch_count: int
    max_abs_error: float
    max_rel_error: float
    first_mismatch: Optional[tuple]  # (row, col, actual, expected)

def verify_exact_int32(actual: np.ndarray, expected: np.ndarray) -> VerifyResult:
    """INT32 精确匹配验证"""
    mismatch = actual != expected
    indices = np.where(mismatch)
    return VerifyResult(
        passed=not mismatch.any(),
        total_elements=actual.size,
        mismatch_count=int(mismatch.sum()),
        max_abs_error=float(np.max(np.abs(actual.astype(np.int64) - expected.astype(np.int64)))),
        max_rel_error=0.0,
        first_mismatch=(int(indices[0][0]), int(indices[1][0]),
                        int(actual[indices[0][0], indices[1][0]]),
                        int(expected[indices[0][0], indices[1][0]])) if mismatch.any() else None
    )

def verify_tolerance_float(actual: np.ndarray, expected: np.ndarray,
                           rtol: float = 1e-3, atol: float = 1e-3) -> VerifyResult:
    """浮点容差验证"""
    diff = np.abs(actual - expected)
    close = diff <= (atol + rtol * np.abs(expected))
    ...
```

### 2.5.2 验收

- `verify_exact_int32` 对相同矩阵返回 `passed=True`
- 对有差异的矩阵返回 `mismatch_count > 0` 和 `first_mismatch`

---

## Task 2.6: Runner 扩展

在 Phase 1 Runner 基础上增加：

```text
新增状态:
  GENERATE_GOLDEN   → 调用 cute-gen-golden.py
  RECONSTRUCT_ACTUAL → 从 D 内存区读取实际输出（本阶段用 C 代码内嵌验证，暂不从 trace 提取）
  COMPARE_GOLDEN    → 调用 cute_verify.py

Runner 完整流程:
  RESOLVE_HWCONFIG
  → GENERATE_HEADERS
  → RESOLVE_TARGET
  → GENERATE_GOLDEN        # 新增
  → BUILD
  → RUN
  → CAPTURE_LOG
  → CHECK_PASS             # 检查 [CUTE_TEST] ... PASS
  → SAVE_ARTIFACT
```

### Artifact 增量

```text
test/golden/
├── golden_i8_128.h          # 生成的 golden header
└── golden_meta.json         # golden 生成参数

func/
├── verify.json              # {"status": "PASS", "method": "c_embedded"}
└── (actual.npy)             # 如果从 trace 提取
```

### 验收

- `cute-run.py --hwconfig ... --project cute-sdk/tensor_ops/matmul --variant i8_128` 跑通
- artifact 包含 golden 数据和 verify 结果

---

## 验收标准总表

- [ ] `cute_tensor.h` 和 `cute_ops.h` 不依赖 `cuteMarcoinstHelper.h`
- [ ] `cute_matmul()` 封装与现有 `issue_cute_matmul_marco_inst` 功能等价
- [ ] `cute-gen-golden.py` 能生成 INT8 matmul golden .h 文件
- [ ] Golden .h 格式与现有手工生成的格式对齐
- [ ] 测试代码 ~15 行（对比现有 ~60 行）
- [ ] `cute-run.py` 一条命令跑通 matmul i8_128 variant
- [ ] TensorTest 输出包含 `[CUTE_TEST] matmul PASS` 或 `FAIL`
- [ ] artifact 包含 golden 和 verify 结果
- [ ] tensor op lib API 被 `main.c` 使用，测试中无散写指令

---

## 不做事项

- 不做 layer 级操作（Phase 3）。
- 不做 fused layer（Phase 4）。
- 不做复杂 perf 分析（Phase 5）。
- 不要求所有 datatype 都支持（Phase 2 只做 i8i8i32）。
- 不从 trace 提取 D tensor（C 代码内嵌验证，trace 提取留 Phase 3）。

---

## 风险与应对

| 风险 | 应对 |
|------|------|
| `instruction.h.generated` 的 `CUTE_CONFIG_CONV_PARAMS` 参数签名与 `issue_cute_config_MatMul` 不一致 | 先用实际生成的头文件确认签名，必要时在 `cute_ops.h` 中做适配 |
| Conv 参数中 `conv_oh_per_add` 等计算逻辑不正确 | Phase 2 只做 matmul（conv 的特例），conv 参数沿用现有 `issue_cute_config_MatMul` 的默认值 |
| D store trace 不稳定 | Phase 2 用 C 代码内嵌验证（直接比较 `d[][]` vs `gloden_c[][]`），不依赖 trace |
| Tensor layout 假设错误 | 先固定 row-major 和 INT8，这是现有测试的通用模式 |
| Golden 生成值与现有手工值不同 | 只要数学正确即可，不强求 seed 一致；后续可以替换为确定性测试 |

---

## 与 Phase 1 的衔接

- 复用 `cute_runtime.h` 的 query/wait/perf API
- 复用 `cute-run.py` 的 build/run/artifact 流程
- 在 runtime lib 上叠加 tensor op lib

## 与 Phase 3 的衔接

Phase 2 完成后，Phase 3 可以直接：
- 在 `cute_tensor.h` / `cute_ops.h` 上叠加 layer 抽象
- 增加 conv op 的完整支持
- 开始实现 `Trace.func F1_store`（从 trace 提取 D tensor）
- 为 layer test 提供可复用的 tensor op 调用
