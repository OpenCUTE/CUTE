# Phase 4 Plan: FuseLayerTest -> Fuse Layer Op Lib

## 目标

Phase 4 的目标是在 layer op lib 基础上引入融合语义，形成第一个 `fuse_layer op lib`。

融合测试不是简单把多个 layer 放在一个 C 文件里，而是验证：

- 中间数据是否按预期被消除或复用。
- 最终输出是否与未融合 golden 对齐。
- target 范围是否明确变窄。
- trace.func 是否能解释融合路径的必要语义。

## 候选样板

建议选择已有代码基础和明确融合收益的样板：

| 候选 | 现有代码 | 融合语义 | 收益 |
|------|----------|----------|------|
| LLaMA FFN fused (gate + silu + up + down) | `transformer_test/llama/` | 3 次独立 matmul → 融合为 2 次 CUTE 调用 + RVV 中间 | 减少中间 tensor 写回 |
| Attention QKV fused | `transformer_test/bert/` | QKV 3 次 matmul → 融合为 1 次 batched matmul | 减少配置开销 |
| ResNet conv+bias+relu fused | `resnet50_test/` | conv + bias add + relu → 单次 CUTE conv + 向量任务 | 减少中间存储 |

**首选**: LLaMA FFN fused — 现有 `transformer_test/llama/` 已有代码基础，融合收益清晰。

## 主要产物

```text
cute-sdk/include/
└── cute_fuse_layer.h                   # Fuse layer op 公共头文件

cute-sdk/fuse_layer_ops/llama_ffn_fused/
├── project.yaml
├── include/
│   └── cute_llama_ffn_fused.h          # Fused FFN 实现
├── src/
│   └── main.c                          # Fuse layer test 驱动
├── golden/
│   ├── fused_ref.py                    # Fused golden（与未融合 golden 一致）
│   └── invariant_check.py             # 中间状态约束检查
├── data/
└── build_rules/
    └── Makefile

tools/trace/func/
└── fused_model.py                      # F4_fused_layer trace func model
```

---

## Task 4.1: 定义融合语义

### 4.1.1 LLaMA FFN 融合分析

```
未融合路径 (Phase 3):
  1. gate = matmul(input, w_gate)       [seq × intermediate]
  2. act  = silu(gate)                  [seq × intermediate]  ← 中间写回
  3. up   = matmul(input, w_up)         [seq × intermediate]
  4. mid  = act * up                    [seq × intermediate]  ← 中间写回
  5. out  = matmul(mid, w_down)         [seq × hidden]

融合路径:
  1. gate = matmul(input, w_gate)       [CUTE tensor op]
  2. up   = matmul(input, w_up)         [CUTE tensor op]
  3. mid  = silu(gate) * up             [RVV element-wise，不写回主存，利用 TCM/scratch]
  4. out  = matmul(mid, w_down)         [CUTE tensor op]

消除的中间写回:
  - gate 的 silu 结果不再写回主存
  - element-wise 乘积不再写回主存
  实际收益: 减少 2 × seq × intermediate × sizeof(int32) 的内存写
```

### 4.1.2 融合策略

```c
/* 融合策略描述 */
typedef struct {
    /* 融合前后对比 */
    uint64_t eliminated_stores;    /* 消除的中间写回次数 */
    uint64_t saved_bytes;          /* 节省的字节数 */

    /* 融合路径 */
    int use_tcm_for_intermediate;  /* 是否使用 TCM 存中间数据 */
    int pipeline_gate_up;          /* 是否流水 gate 和 up matmul */
} cute_fuse_strategy_t;
```

---

## Task 4.2: 实现 Fuse Layer Op

### 4.2.1 `cute-sdk/fuse_layer_ops/llama_ffn_fused/include/cute_llama_ffn_fused.h`

设计原则：
- 融合 op 调用下层 tensor op lib（`cute_matmul`），不重新实现
- 融合 op 负责中间 tensor 生命周期管理
- 融合 op 暴露与未融合 op 相同的外部接口（输入输出不变）

```c
#ifndef CUTE_LLAMA_FFN_FUSED_H
#define CUTE_LLAMA_FFN_FUSED_H

#include "cute_layer.h"

/* LLaMA FFN 融合描述符 */
typedef struct {
    cute_tensor_t input;       /* [seq × hidden] */
    cute_tensor_t w_gate;      /* [hidden × intermediate] */
    cute_tensor_t w_up;        /* [hidden × intermediate] */
    cute_tensor_t w_down;      /* [intermediate × hidden] */
    cute_tensor_t output;      /* [seq × hidden] */

    /* 中间 buffer — 由调用者分配 */
    void *gate_buf;            /* [seq × intermediate] (int32) */
    void *up_buf;              /* [seq × intermediate] (int32) */
    void *mid_buf;             /* [seq × intermediate] (int32) — 可选，若 TCM 足够可省 */

    uint64_t seq, hidden, intermediate;
    uint64_t dtype;

    /* 融合策略 */
    cute_fuse_strategy_t strategy;
} cute_llama_ffn_fused_desc_t;

/* 执行融合 LLaMA FFN */
int cute_llama_ffn_fused(const cute_llama_ffn_fused_desc_t *desc);

/* 验证融合正确性：与未融合结果对比 */
int cute_llama_ffn_fused_verify(
    const cute_llama_ffn_fused_desc_t *fused_desc,
    const cute_llama_ffn_desc_t *non_fused_desc  /* 未融合参考 */
);

#endif /* CUTE_LLAMA_FFN_FUSED_H */
```

### 4.2.2 实现逻辑

```c
int cute_llama_ffn_fused(const cute_llama_ffn_fused_desc_t *desc) {
    cute_tensor_t gate, up, mid;
    cute_tensor_init(&gate, desc->gate_buf, desc->seq, desc->intermediate, desc->dtype);
    cute_tensor_init(&up, desc->up_buf, desc->seq, desc->intermediate, desc->dtype);

    /* Step 1: gate = input @ w_gate^T */
    cute_matmul_desc_t gate_desc = {
        .A = desc->input, .B = desc->w_gate, .D = gate,
        .M = desc->seq, .N = desc->intermediate, .K = desc->hidden,
        .bias_mode = CUTE_BIAS_ZERO,
    };
    cute_matmul(&gate_desc);

    /* Step 2: up = input @ w_up^T */
    cute_matmul_desc_t up_desc = {
        .A = desc->input, .B = desc->w_up, .D = up,
        .M = desc->seq, .N = desc->intermediate, .K = desc->hidden,
        .bias_mode = CUTE_BIAS_ZERO,
    };
    cute_matmul(&up_desc);

    /* Step 3: mid = silu(gate) * up — RVV element-wise */
    /* 如果 strategy.use_tcm_for_intermediate，则 mid 放在 TCM */
    rvv_silu_mul(desc->mid_buf, desc->gate_buf, desc->up_buf,
                 desc->seq * desc->intermediate);

    /* Step 4: output = mid @ w_down^T */
    cute_tensor_init(&mid, desc->mid_buf, desc->seq, desc->intermediate, desc->dtype);
    cute_matmul_desc_t down_desc = {
        .A = mid, .B = desc->w_down, .D = desc->output,
        .M = desc->seq, .N = desc->hidden, .K = desc->intermediate,
        .bias_mode = CUTE_BIAS_ZERO,
    };
    cute_matmul(&down_desc);

    return 0;
}
```

### 4.2.3 验收

- 融合 op 内部调用 `cute_matmul()`，不直接调用 `CUTE_CONFIG_*`
- 融合 op 的外部接口与未融合 op 相同（输入输出不变）
- 中间 buffer 由调用者分配

---

## Task 4.3: Fuse Layer Test Driver

### 4.3.1 `cute-sdk/fuse_layer_ops/llama_ffn_fused/src/main.c`

```c
#include <stdio.h>
#include <stdint.h>
#include "cute_runtime.h"
#include "cute_layer.h"
#include "cute_llama_ffn_fused.h"
#include VARIANT_GOLDEN_HEADER

int main(void) {
    cute_print_config_info();
    printf("[CUTE_TEST] fuse_layer llama_ffn_fused variant=%s start\n", VARIANT_NAME);

    /* 分配中间 buffer */
    static int32_t gate_buf[SEQ * INTERMEDIATE] __attribute__((aligned(256)));
    static int32_t up_buf[SEQ * INTERMEDIATE] __attribute__((aligned(256)));
    static int32_t mid_buf[SEQ * INTERMEDIATE] __attribute__((aligned(256)));

    /* 初始化融合描述符 */
    cute_llama_ffn_fused_desc_t desc = {
        .input = ..., .w_gate = ..., .w_up = ..., .w_down = ..., .output = ...,
        .gate_buf = gate_buf, .up_buf = up_buf, .mid_buf = mid_buf,
        .seq = SEQ, .hidden = HIDDEN, .intermediate = INTERMEDIATE,
        .dtype = CUTEDataTypeI8I8I32,
    };

    /* 执行融合版本 */
    int ret = cute_llama_ffn_fused(&desc);

    /* 性能查询 */
    cute_perf_t perf = cute_perf_query();
    cute_perf_print(&perf);

    /* Golden 验证（与未融合 golden 相同） */
    int pass = verify_golden(output, golden_output, ...);

    printf("[CUTE_TEST] fuse_layer llama_ffn_fused %s\n", pass ? "PASS" : "FAIL");
    return pass ? 0 : -1;
}
```

### 4.3.2 project.yaml

```yaml
version: 1
id: fuse_layer.llama_ffn_fused
name: llama_ffn_fused
kind: fuse_layer_test
version_name: v0.1

target:
  hwconfigs:
    include_tags: [cute_tensor_v1]
  required_capability:
    datatypes: [i8i8i32]
    tensor_ops: [matmul]
    layer_ops: [llama_ffn]
    fused_ops: [llama_ffn_fused]
    trace_func_level: F4_fused_layer

code:
  entry: src/main.c
  build: make
  runtime_lib: runtime.cute_runtime
  op_lib: tensor.matmul
  variants:
    - name: small_fused
      seq: 1
      hidden: 256
      intermediate: 1024
      dtype: i8i8i32

golden:
  level: fused_layer
  source: python_reference
  compare:
    mode: exact

trace:
  required_func_level: F4_fused_layer
  default_filters: [func_store_tensor]
```

---

## Task 4.4: F4_fused_layer Trace Func Model

### 4.4.1 `tools/trace/func/fused_model.py`

```python
"""
Trace.func F4_fused_layer

目标:
  - 能验证融合版本的最终输出与未融合 golden 一致
  - 可选验证关键 intermediate invariant（如 silu 后的值范围）
  - 能区分 "运行成功但无法验证融合语义" 和 "融合语义 pass"
"""

class FusedLayerFuncModel:
    def verify_fused_output(
        self,
        events,          # List[TraceEvent]
        golden: np.ndarray,
        d_base_addr: int,
        M: int, N: int
    ) -> VerifyResult:
        """验证融合版本的最终输出"""
        # 复用 F1_store / F2_tensor_op 的重建逻辑
        from .tensor_model import TensorFuncModel
        model = TensorFuncModel()
        actual = model.reconstruct_d_tensor_from_trace(
            events, d_base_addr, M, N
        )
        if actual is None:
            return VerifyResult(passed=False, note="NO_STORE_EVENTS", ...)
        return verify_exact_int32(actual, golden)

    def verify_intermediate_invariant(
        self,
        events,
        intermediate_base_addr: int,
        size: int,
        expected_range: tuple = (0, 255)
    ) -> bool:
        """可选：验证中间数据满足不变量约束"""
        # 从 trace 中提取 intermediate store 数据
        # 检查值是否在预期范围内
        ...
```

### 4.4.2 状态定义

```text
RUN_OK                    — 运行完成，无 crash
FINAL_OUTPUT_PASS         — 最终输出与 golden 一致
INTERMEDIATE_INVARIANT_PASS — 中间约束也通过
FUNC_MODEL_NOT_READY      — trace func model 不支持
PASS                      — FINAL_OUTPUT_PASS + INTERMEDIATE_INVARIANT_PASS
FAIL                      — 输出不匹配
```

---

## Task 4.5: 融合 vs 非融合对比

### 4.5.1 `tools/verify/cute_fuse_compare.py`

```python
"""
融合 vs 非融合对比

确保融合版本的输出与未融合版本数学等价。
"""

def compare_fused_vs_nonfused(
    fused_artifact_dir: str,
    non_fused_artifact_dir: str
) -> dict:
    """对比两个 artifact 的 verify 结果"""
    fused_verify = load_json(f"{fused_artifact_dir}/func/verify.json")
    non_fused_verify = load_json(f"{non_fused_artifact_dir}/func/verify.json")

    return {
        "fused_status": fused_verify["status"],
        "non_fused_status": non_fused_verify["status"],
        "output_consistent": fused_verify["status"] == non_fused_verify["status"] == "PASS",
        "perf_comparison": compare_perf(fused_artifact_dir, non_fused_artifact_dir)
    }
```

---

## 验收标准总表

- [ ] FuseLayerTest 有明确 target，且比 LayerTest 更窄（需要 fused_ops capability）
- [ ] 融合 op 复用 layer/tensor/runtime lib，不重新实现 matmul
- [ ] 融合 op 的外部接口与未融合 op 相同
- [ ] 至少一个 fused variant 能运行
- [ ] 融合输出与未融合 golden 对齐（FINAL_OUTPUT_PASS）
- [ ] 不支持的 HWConfig 返回 `TARGET_UNSUPPORTED`
- [ ] artifact 包含 `verify.json` 记录 `FINAL_OUTPUT_PASS` 状态
- [ ] 有性能对比数据（fused vs non-fused cycle 数）

---

## 不做事项

- 不做 SOC-specific 最终优化（Phase 5）。
- 不要求完整 model test（Phase 6）。
- 不要求 perf bottleneck 完整解释（Phase 5）。
- 不要求所有融合路径（只做 LLaMA FFN）。

---

## 风险与应对

| 风险 | 应对 |
|------|------|
| 融合正确性难判断 | 先只要求最终输出与未融合 golden 一致，再逐步加 intermediate invariant |
| Target 过宽 | project.yaml 必须显式声明 fused_ops capability |
| 代码层级倒挂 | fuse op 不能绕过下层 lib 大量复制实现；code review 检查 |
| 中间 buffer 分配过大 | 先用小规模 variant (seq=1)，确认逻辑正确后再扩大 |
| RVV silu_mul 未实现 | Phase 4 可以先用标量实现验证正确性，后续替换为 RVV |

---

## 与 Phase 3 的衔接

- 复用 `cute_layer.h` 的 LLaMA FFN 描述符
- 复用 `tools/trace/func/tensor_model.py` 的 D tensor 重建逻辑
- 融合版本的 golden 与未融合版本相同（数学等价）

## 与 Phase 5 的衔接

Phase 4 完成后，Phase 5 可以直接：
- 在 fused layer op 上做 SOC-specific 优化（tiling、调度、buffer 策略）
- 使用 `Trace.perf` 分析融合前后的性能差异
- 形成 opt_op_lib 绑定特定 HWConfig family
