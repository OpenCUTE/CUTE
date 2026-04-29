# Phase 6 Plan: ModelTest

## 目标

Phase 6 的目标是用下层 lib 组合完整模型或模型片段测试，形成 model-level correctness/profile。

ModelTest 是最上层测试，target 最窄，不追求所有 HWConfig 都支持。

本阶段的核心挑战：

- 模型规模可能超出单次仿真的承受能力 → 先做模型片段（单 block）。
- Golden 数据量巨大 → 使用外部 checker 或分段 golden。
- 端到端性能分析 → 复用 Phase 5 的 Top-Down + Roofline。

## 候选模型

建议选择一个优先目标：

| 模型 | 已有代码 | 可拆分性 | 运行时间 | Golden |
|------|----------|----------|----------|--------|
| ResNet50 完整推理 | `resnet50_test/` | 按 layer | 中 | 有 layer 级 golden |
| BERT attention block | `transformer_test/bert/` | 按 layer | 中 | 有 |
| LLaMA3 1B 单 block | `transformer_test/llama/` | 按 block | 高 | 有 |

**首选**: LLaMA3 1B 单 block — 最有代表性，能完整复用 tensor/layer/fuse/opt 四层 lib。
**备选**: ResNet50 子集 — 运行时间可控，golden 最清楚。

本计划以 LLaMA3 为例。

## 主要产物

```text
cute-sdk/model_tests/llama3_1b_block/
├── project.yaml
├── include/
│   └── cute_llama3_model.h             # 模型定义
├── src/
│   ├── main.c                          # Model test driver
│   ├── llama3_block.c                  # Transformer block 实现
│   └── llama3_weights.c                # 权重加载/生成
├── golden/
│   ├── golden_block.py                 # Block 级 golden 生成
│   └── golden_utils.py                 # 辅助工具
├── data/
│   ├── weights/                        # 模型权重数据
│   └── inputs/                         # 输入数据
├── reports/
│   └── perf_baseline.json              # 性能基线
└── build_rules/
    └── Makefile

scripts/
└── cute-model-report.py                # 模型级报告生成
```

---

## Task 6.1: 定义 Model Test 结构

### 6.1.1 LLaMA3 Transformer Block 分解

```
LLaMA3 Block (simplified):
  1. RMSNorm(input)                     → norm1    [RVV]
  2. Attention(norm1, Wq, Wk, Wv, Wo)   → attn_out [CUTE tensor ops]
     - Q = norm1 @ Wq^T                 [CUTE matmul]
     - K = norm1 @ Wk^T                 [CUTE matmul]
     - V = norm1 @ Wv^T                 [CUTE matmul]
     - attn = softmax(Q @ K^T / sqrt(d))[RVV]
     - attn_out = attn @ V              [CUTE matmul]
     - attn_out = attn_out @ Wo^T       [CUTE matmul]
  3. Residual Add(input, attn_out)      → res1     [RVV]
  4. RMSNorm(res1)                      → norm2    [RVV]
  5. FFN(norm2, W_gate, W_up, W_down)   → ffn_out  [CUTE + RVV]
     - 可用 Phase 4 的 fused FFN
  6. Residual Add(res1, ffn_out)        → output   [RVV]

依赖关系:
  Phase 1: runtime lib (query, wait, perf)
  Phase 2: tensor op lib (matmul)
  Phase 3: layer op lib (attention, ffn)
  Phase 4: fuse layer op lib (fused ffn)
  Phase 5: opt op lib (soc-specific optimization)
```

### 6.1.2 project.yaml

```yaml
version: 1
id: model.llama3_1b_block
name: llama3_1b_block
kind: model_test
version_name: v0.1

target:
  hwconfigs:
    include_tags: [cute_tensor_v1, shuttle]
  required_capability:
    datatypes: [fp16fp16fp32, bf16bf16fp32]
    tensor_ops: [matmul]
    layer_ops: [llama_ffn, llama_attention]
    fused_ops: [llama_ffn_fused]
    trace_func_level: F5_model

code:
  entry: src/main.c
  build: make
  runtime_lib: runtime.cute_runtime
  op_lib: tensor.matmul
  variants:
    - name: block0_fp16
      model: llama3_1b
      block_index: 0
      seq: 1
      hidden: 2048
      heads: 32
      intermediate: 5632
      dtype: fp16fp16fp32
      use_fused_ffn: true
    - name: block0_fp16_nofuse
      model: llama3_1b
      block_index: 0
      seq: 1
      hidden: 2048
      heads: 32
      intermediate: 5632
      dtype: fp16fp16fp32
      use_fused_ffn: false
    - name: block0_bf16
      model: llama3_1b
      block_index: 0
      seq: 1
      hidden: 2048
      heads: 32
      intermediate: 5632
      dtype: bf16bf16fp32
      use_fused_ffn: true

golden:
  level: model
  source: python_reference
  compare:
    mode: tolerance
    abs_err: 0.01
    rel_err: 0.001

trace:
  required_func_level: F5_model
  default_filters: [func_store_tensor, perf_task_stage]
```

---

## Task 6.2: 实现 Model Driver

### 6.2.1 `cute-sdk/model_tests/llama3_1b_block/include/cute_llama3_model.h`

```c
#ifndef CUTE_LLAMA3_MODEL_H
#define CUTE_LLAMA3_MODEL_H

#include "cute_tensor.h"
#include "cute_layer.h"
#include "cute_llama_ffn_fused.h"

/* LLaMA3 Block 权重 */
typedef struct {
    cute_tensor_t w_q, w_k, w_v, w_o;   /* Attention 权重 */
    cute_tensor_t w_gate, w_up, w_down;  /* FFN 权重 */
    cute_tensor_t norm1_weight;          /* RMSNorm 1 */
    cute_tensor_t norm2_weight;          /* RMSNorm 2 */
} cute_llama3_weights_t;

/* LLaMA3 Block 描述符 */
typedef struct {
    cute_tensor_t input;                 /* [seq × hidden] */
    cute_tensor_t output;                /* [seq × hidden] */
    cute_llama3_weights_t weights;

    /* 中间 buffer（由调用者分配） */
    void *norm1_buf;                     /* [seq × hidden] */
    void *attn_out_buf;                  /* [seq × hidden] */
    void *res1_buf;                      /* [seq × hidden] */
    void *norm2_buf;                     /* [seq × hidden] */
    void *ffn_gate_buf;                  /* [seq × intermediate] */
    void *ffn_up_buf;                    /* [seq × intermediate] */
    void *ffn_mid_buf;                   /* [seq × intermediate] */
    /* Attention 中间 buffer */
    void *q_buf, *k_buf, *v_buf;         /* [seq × head_dim] per head */

    uint64_t seq, hidden, heads, head_dim, intermediate;
    uint64_t dtype;
    int use_fused_ffn;
} cute_llama3_block_desc_t;

/* 执行单个 Transformer block */
int cute_llama3_block_forward(const cute_llama3_block_desc_t *desc);

#endif /* CUTE_LLAMA3_MODEL_H */
```

### 6.2.2 `cute-sdk/model_tests/llama3_1b_block/src/main.c`

```c
#include <stdio.h>
#include <stdint.h>
#include "cute_runtime.h"
#include "cute_llama3_model.h"
#include VARIANT_CONFIG_HEADER  /* 权重布局、维度等 */

int main(void) {
    cute_print_config_info();
    printf("[CUTE_TEST] model llama3_1b_block variant=%s start\n", VARIANT_NAME);

    /* 分配所有 buffer */
    static int32_t input_buf[SEQ * HIDDEN] __attribute__((aligned(256)));
    static int32_t output_buf[SEQ * HIDDEN] __attribute__((aligned(256)));
    /* ... 其他中间 buffer ... */

    /* 加载权重和输入数据 */
    load_weights(&weights, ...);
    load_input(input_buf, ...);

    /* 初始化 block 描述符 */
    cute_llama3_block_desc_t desc = { ... };

    /* 执行 */
    uint64_t t0 = cute_rdcycle();
    int ret = cute_llama3_block_forward(&desc);
    uint64_t total_cycles = cute_rdcycle() - t0;

    /* 性能报告 */
    cute_perf_t perf = cute_perf_query();
    cute_perf_print(&perf);
    printf("[CUTE_PERF] block total=%lu cycles\n", total_cycles);

    /* Golden 验证（浮点 tolerance） */
    int pass = verify_golden_tolerance(output_buf, golden_output, ...);

    printf("[CUTE_TEST] model llama3_1b_block %s\n", pass ? "PASS" : "FAIL");
    return pass ? 0 : -1;
}
```

---

## Task 6.3: Model Golden 策略

### 6.3.1 Golden 生成

模型级 golden 的挑战：
- 权重数据量大（LLaMA3 1B 单 block ~50MB）
- 浮点累积误差
- 需要与 CUTE 的数值行为对齐

策略：

```text
Phase 6.1: 小规模验证
  - seq=1, hidden=256 (缩小版)
  - 精确 golden（小规模误差可控）
  - 确认 block 实现逻辑正确

Phase 6.2: 实际规模验证
  - seq=1, hidden=2048 (实际 LLaMA3 1B 参数)
  - Tolerance golden (abs_err, rel_err)
  - 确认数值行为可接受

Phase 6.3: 端到端验证
  - 多 block 连续运行
  - 分段 golden（每 block 输出独立验证）
```

### 6.3.2 `golden/golden_block.py`

```python
"""
LLaMA3 block golden 生成

使用 PyTorch/HuggingFace 生成参考输出：
  1. 加载模型权重
  2. 执行单个 block forward
  3. 导出每层中间输出作为 invariant
  4. 导出最终输出作为 golden
"""

import torch
import numpy as np

def generate_block_golden(
    model_name: str,
    block_index: int,
    input_tensor: np.ndarray,
    dtype: str = "fp16"
) -> dict:
    """生成单个 block 的 golden 数据"""
    # 加载模型
    from transformers import AutoModelForCausalLM
    model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype=torch.float16)

    # 提取单个 block
    block = model.model.layers[block_index]

    # 执行 forward
    with torch.no_grad():
        hidden_states = torch.from_numpy(input_tensor).unsqueeze(0)
        output = block(hidden_states)

    return {
        "output": output[0].numpy(),
        "norm1": ...,    # 中间 invariant
        "attn_out": ..., # 中间 invariant
        "res1": ...,     # 中间 invariant
        "norm2": ...,    # 中间 invariant
    }
```

---

## Task 6.4: Model 性能分析

### 6.4.1 端到端 Profile

复用 Phase 5 的 `CutePerfAnalyzer`，但增加模型级视角：

```python
class ModelPerfAnalyzer:
    def analyze_model_block(
        self,
        events: List[TraceEvent],
        hwconfig: dict,
        block_desc: dict
    ) -> dict:
        """分析单个 block 的端到端性能"""
        # 拆分为 layer 级时间线
        attention_timeline = extract_attention_timeline(events)
        ffn_timeline = extract_ffn_timeline(events)

        # 计算各层占比
        return {
            "total_cycles": ...,
            "attention_pct": attention_timeline.cycles / total,
            "ffn_pct": ffn_timeline.cycles / total,
            "norm_pct": ...,
            "residual_pct": ...,
            "breakdown": {
                "matmul_calls": ...,     # CUTE matmul 调用次数
                "rvv_calls": ...,        # RVV 操作次数
                "data_movement_bytes": ...,
            },
            "roofline": compute_roofline(hwconfig, block_desc, perf_data),
        }
```

### 6.4.2 Fused vs Non-Fused 对比

```text
block0_fp16 (fused FFN):
  Total: 45,000 cycles
  Attention: 28,000 cycles (62%)
  FFN: 15,000 cycles (33%) ← fused
  Norm/Residual: 2,000 cycles (5%)

block0_fp16_nofuse:
  Total: 52,000 cycles
  Attention: 28,000 cycles (54%)
  FFN: 22,000 cycles (42%) ← non-fused
  Norm/Residual: 2,000 cycles (4%)

Speedup from fusion: 1.16x
```

---

## Task 6.5: Model 报告

### 6.5.1 `tools/runner/cute-model-report.py`

```text
Usage:
  tools/runner/cute-model-report.py --artifact build/cute-runs/<run-id>
    生成单个 run 的模型级报告

  tools/runner/cute-model-report.py --compare-fuse <fused-artifact> <non-fused-artifact>
    对比融合 vs 非融合

  tools/runner/cute-model-report.py --compare-opt <baseline-artifact> <optimized-artifact>
    对比优化前后
```

### 6.5.2 报告格式

```text
═══════════════════════════════════════════════════
  CUTE Model Test Report
  Model: llama3_1b_block (block 0)
  Config: cute2tops_scp64_dramsim32
═══════════════════════════════════════════════════

Correctness
  Status: PASS (tolerance mode)
  Max Abs Error: 0.0032
  Max Rel Error: 0.00012
  Mismatch Elements: 0 / 2048

Performance
  Total Cycles: 45,230
  Estimated Time @ 1GHz: 45.23 μs

  Layer Breakdown:
    RMSNorm 1:     450 cycles ( 1.0%)  ██
    Attention:   28,100 cycles (62.1%)  ████████████████████████████████
    Residual:      120 cycles ( 0.3%)  █
    RMSNorm 2:     430 cycles ( 1.0%)  ██
    FFN (fused): 15,900 cycles (35.2%)  ██████████████████████████████
    Residual:      130 cycles ( 0.3%)  █

  Top-Down:
    Compute Util:  72.3%
    Memory Util:   88.1%
    Stall:         19.7%

  Roofline:
    Arithmetic Intensity: 18.4 FLOP/Byte
    Actual: 3.78 TOPS  |  Roofline: 3.92 TOPS
    Bound: COMPUTE

  Comparison:
    vs Non-Fused FFN: 1.16x speedup
    vs Baseline Matmul: 1.08x speedup
═══════════════════════════════════════════════════
```

---

## 验收标准总表

- [ ] 至少一个 model variant 能运行（seq=1 最小规模）
- [ ] Target 明确绑定 HWConfig family
- [ ] 正确性状态明确（PASS / FAIL / TOLERANCE_PASS）
- [ ] 不将 `RUN_OK` 误判为 pass
- [ ] Golden 验证使用 tolerance 模式（浮点）
- [ ] Report 同时包含 correctness 和 performance summary
- [ ] Layer breakdown 能显示各层 cycle 占比
- [ ] 下层 lib 复用关系清晰（不复制实现）
- [ ] Fused vs Non-Fused 对比有数据
- [ ] Artifact 包含完整证据（weights、inputs、outputs、golden、perf）

---

## 不做事项

- 不追求所有模型（只做 LLaMA3 或 ResNet50）。
- 不追求所有 HWConfig（明确绑定 shuttle family）。
- 不要求 `F5_model` trace func 完整实现（允许 external checker）。
- 不要求最终 perf visualization（先做 console 报告）。
- 不做多 block 连续执行（先做单 block）。
- 不做真实推理引擎（只做正确性+性能验证）。

---

## 风险与应对

| 风险 | 应对 |
|------|------|
| 模型测试过重 | 先做 seq=1 最小规模，确认逻辑正确后扩大 |
| 浮点 golden 累积误差 | 使用 tolerance 模式，先在 PyTorch float32 参考，再折算到 CUTE 精度 |
| External golden 难维护 | 记录 checker 版本、模型权重 hash、输入种子 |
| 上层复制底层代码 | 强制通过 deps 调用下层 lib，code review 检查 |
| 内存不足 | 先做缩小版（hidden=256），确认后用实际参数 |
| 仿真时间过长 | 固定 seq=1，减少仿真 cycles |

---

## 与 Phase 5 的衔接

- 复用 `CutePerfAnalyzer` 做 Top-Down 分析
- 复用 `CutePerfModel` 做 Roofline
- 复用 opt op lib 做模型级优化
- 性能对比数据延续 Phase 5 的 baseline

## 后续方向

Phase 6 完成后，框架已具备完整能力：

- **多 block 连续执行**: 将单 block 扩展为多 block pipeline
- **RVV+CUTE 混合推理引擎**: Phase 5 的 opt op lib 扩展为通用推理引擎
- **FPGA 部署验证**: 将仿真 trace 替换为 FPGA trace（Phase 5 的 BRAM buffer）
- **CI 集成**: 将 Runner 和 suite 集成到 CI pipeline
- **性能回归监控**: 自动比较每次提交的性能变化
