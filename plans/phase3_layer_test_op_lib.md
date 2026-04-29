# Phase 3 Plan: LayerTest -> Layer Op Lib

## 目标

Phase 3 的目标是在 tensor op lib 上叠加向量任务和 layer 语义，形成第一个 layer op lib。

建议选择一个代表样板：

- **ResNet50 单层 conv**（有现有 `resnet50_test/` 代码和 golden）
- 或 **LLaMA FFN 非融合版本**（有现有 `transformer_test/` 代码）

选择标准：

- 已有测试代码或 golden 参考。
- 输入输出规模可控。
- 能复用 Phase 2 的 tensor op lib。
- 不依赖复杂融合。

本阶段还开始实现 `Trace.func F1_store`（从 trace 提取 D tensor），让验证第一次从 trace 驱动而非 C 代码内嵌比对。

## 主要产物

```text
cute-sdk/include/
└── cute_layer.h                        # Layer op 公共头文件

cute-sdk/layer_ops/<layer-project>/
├── project.yaml
├── include/
│   └── cute_<layer>.h                  # Layer op 头文件
├── src/
│   └── main.c                          # Layer test 驱动
├── golden/
│   └── golden_<layer>.py               # Layer golden 生成
├── data/
└── build_rules/
    └── Makefile

tools/trace/
├── parser.py                           # Trace parser
├── filter.py                           # Trace filter
└── func/
    ├── event_model.py                  # F0_event 检查
    └── tensor_model.py                 # F1_store / F2_tensor_op 重建

tools/verify/
└── cute_trace_golden.py                # 从 trace 提取 D tensor 并比对
```

---

## Task 3.1: 选择 Layer 样板

### 3.1.1 候选分析

| 候选 | 现有代码 | Golden 可获得性 | 复杂度 | Tensor op 依赖 |
|------|----------|----------------|--------|----------------|
| ResNet50 conv layer 1 (3×3, stride=1) | `resnet50_test/vec_ops_conv_2.c` | 有 `conv_2.h` 和 `compare_result.py` | 中 | conv + bias |
| ResNet50 conv layer 2 (1×1, stride=1) | `resnet50_test/vec_ops_conv_*.c` | 有 golden | 低 | conv + bias |
| LLaMA FFN (matmul + activate + matmul) | `transformer_test/llama/` | 有 `gloden/` | 高 | 2× matmul |
| BERT attention | `transformer_test/bert/` | 有 golden | 高 | 多次 matmul + softmax |

### 3.1.2 建议

**首选**: ResNet50 conv layer 2 (1×1 conv) — 复杂度最低，golden 最清楚。
**备选**: LLaMA FFN 非融合版 — 更有代表性，但需要两次 matmul 和中间激活。

本计划以 ResNet50 conv 为例，但结构设计要能覆盖 LLaMA FFN。

---

## Task 3.2: 实现 Layer Op 抽象

### 3.2.1 `cute-sdk/include/cute_layer.h`

设计原则：
- Layer op 由多个 tensor op + 向量任务（RVV）组合而成
- Layer op 不直接调用 `CUTE_CONFIG_*`，而是调用 `cute_ops.h` 的封装
- Layer op 负责管理中间 tensor 的内存布局和生命周期

```c
#ifndef CUTE_LAYER_H
#define CUTE_LAYER_H

#include "cute_tensor.h"
#include "cute_ops.h"
#include "cute_runtime.h"

/* ---- ResNet Conv Layer ---- */

typedef struct {
    cute_tensor_t input;     /* [oh*ow × ic] 展平后的输入 */
    cute_tensor_t weight;    /* [oc × kh*kw*ic] 权重 */
    cute_tensor_t bias;      /* [oc] 或 NULL */
    cute_tensor_t output;    /* [oh*ow × oc] 输出 */
    uint64_t input_h, input_w;   /* 原始输入空间维度 */
    uint64_t kernel_h, kernel_w; /* 卷积核空间维度 */
    uint64_t stride_h, stride_w;
    uint64_t pad_h, pad_w;
    uint64_t oc, ic;
    /* 预计算的 conv 参数（对齐现有 conv 逻辑） */
    uint64_t ohow;           /* oh * ow */
    uint64_t oh_max, ow_max;
    uint64_t oh_per_add, ow_per_add;
} cute_resnet_conv_desc_t;

/* 执行 ResNet conv layer：拆成 tiled conv 调用 */
int cute_resnet_conv_layer(const cute_resnet_conv_desc_t *desc);

/* ---- LLaMA FFN Layer ---- */

typedef struct {
    cute_tensor_t input;     /* [seq × hidden] */
    cute_tensor_t w_gate;    /* [hidden × intermediate] */
    cute_tensor_t w_up;      /* [hidden × intermediate] */
    cute_tensor_t w_down;    /* [intermediate × hidden] */
    cute_tensor_t output;    /* [seq × hidden] */
    /* 中间 buffer（由调用者分配） */
    void *gate_buf;          /* [seq × intermediate] */
    void *up_buf;            /* [seq × intermediate] */
    uint64_t seq, hidden, intermediate;
    uint64_t dtype;
} cute_llama_ffn_desc_t;

/* 执行 LLaMA FFN：gate_matmul + silu + element_mul + down_matmul */
int cute_llama_ffn_layer(const cute_llama_ffn_desc_t *desc);

#endif /* CUTE_LAYER_H */
```

### 3.2.2 Layer Op 实现示例

`cute-sdk/layer_ops/resnet_conv/include/cute_resnet_conv.h`:

```c
/* ResNet conv layer 实现 */
int cute_resnet_conv_layer(const cute_resnet_conv_desc_t *desc) {
    /* 将 conv 拆成 CUTE tiled conv 调用 */
    cute_conv_desc_t conv_desc = {
        .A = desc->input,
        .B = desc->weight,
        .C = desc->bias,
        .D = desc->output,
        .ohow = desc->ohow,
        .oc = desc->oc,
        .ic = desc->ic,
        .kernel_size = desc->kernel_h,  /* 假设正方形 */
        .conv_stride = desc->stride_h,
        .oh_max = desc->oh_max,
        .ow_max = desc->ow_max,
        .bias_mode = desc->bias.data ? CUTE_BIAS_REPEAT_ROW : CUTE_BIAS_ZERO,
        .transpose = 0,
    };

    uint64_t result = cute_conv(&conv_desc);
    if (result == 0) return -1;  /* timeout */
    return 0;
}
```

### 3.2.3 验收

- Layer op 内部调用 `cute_conv()` / `cute_matmul()`，不直接调用 `CUTE_CONFIG_*`
- Layer op 的 project.yaml 中 `code.op_lib` 指向 Phase 2 的 tensor op lib

---

## Task 3.3: 实现 Layer Test Driver

### 3.3.1 `cute-sdk/layer_ops/resnet_conv/src/main.c`

```c
#include <stdio.h>
#include <stdint.h>
#include "cute_runtime.h"
#include "cute_layer.h"
#include VARIANT_GOLDEN_HEADER  /* golden 数据，由 cute-gen-golden.py 生成 */

int main(void) {
    cute_print_config_info();
    printf("[CUTE_TEST] layer resnet_conv variant=%s start\n", VARIANT_NAME);

    /* 初始化 layer 描述符 */
    cute_resnet_conv_desc_t desc = { ... };  /* 从 golden header 中的宏填充 */

    /* 执行 */
    int ret = cute_resnet_conv_layer(&desc);
    if (ret != 0) {
        printf("[CUTE_TEST] layer FAIL (execution error)\n");
        return -1;
    }

    /* 性能查询 */
    cute_perf_t perf = cute_perf_query();
    cute_perf_print(&perf);

    /* Golden 验证 */
    int pass = verify_golden(output, golden_output, ...);

    printf("[CUTE_TEST] layer resnet_conv %s\n", pass ? "PASS" : "FAIL");
    return pass ? 0 : -1;
}
```

### 3.3.2 project.yaml

```yaml
version: 1
id: layer.resnet_conv
name: resnet_conv
kind: layer_test
version_name: v0.1

target:
  hwconfigs:
    include_tags: [cute_tensor_v1]
  required_capability:
    datatypes: [i8i8i32]
    tensor_ops: [matmul, conv]
    trace_func_level: F3_layer

code:
  entry: src/main.c
  build: make
  runtime_lib: runtime.cute_runtime
  op_lib: tensor.matmul
  variants:
    - name: conv1_3x3_s1
      input_h: 14
      input_w: 14
      ic: 256
      oc: 256
      kernel_size: 3
      stride: 1
      dtype: i8i8i32

golden:
  level: layer
  source: python_reference
  compare:
    mode: exact

trace:
  required_func_level: F3_layer
  default_filters: [func_store_tensor]
```

### 3.3.3 验收

- Layer test 复用 runtime lib 和 tensor op lib
- Project.yaml 的 target 范围比 TensorTest 更窄（需要 conv capability）
- Variant 参数从 project.yaml 传入 build

---

## Task 3.4: 实现 Trace Parser 和 Func Model

### 3.4.1 `tools/trace/parser.py`

```python
"""
CUTE Trace Parser

解析格式: [CYCLE:<cycle>] <MODULE>:<SUB_ID> <EVENT> <KEY=VALUE ...>

当前支持两种输入:
  1. 结构化 trace (RTL printf，Phase 3 添加后可用)
  2. Legacy log (现有 CMemoryLoader printf 格式)
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict
import re

@dataclass
class TraceEvent:
    cycle: int
    module: str
    sub_id: int
    event: str
    payload: Dict[str, str] = field(default_factory=dict)
    raw_line: str = ""

class CuteTraceParser:
    # 结构化 trace 正则
    STRUCTURED_RE = re.compile(
        r'\[CYCLE:(\d+)\]\s+(\w+):(\d+)\s+(\w+)\s+(.*)'
    )

    # Legacy CMemoryLoader printf 正则（对齐现有 compare_result.py）
    LEGACY_STORE_RE = re.compile(
        r'\[CMemoryLoader_Store<(\d+)>\]:\s+addr=0x([0-9a-fA-F]+)\s+data=(.*)'
    )

    def parse(self, text: str) -> List[TraceEvent]:
        events = []
        for line in text.strip().split('\n'):
            event = self._parse_line(line)
            if event:
                events.append(event)
        return events

    def _parse_line(self, line: str) -> Optional[TraceEvent]:
        # 先尝试结构化格式
        m = self.STRUCTURED_RE.match(line.strip())
        if m:
            return TraceEvent(
                cycle=int(m.group(1)),
                module=m.group(2),
                sub_id=int(m.group(3)),
                event=m.group(4),
                payload=self._parse_payload(m.group(5)),
                raw_line=line
            )
        # 尝试 legacy 格式
        m = self.LEGACY_STORE_RE.match(line.strip())
        if m:
            return TraceEvent(
                cycle=0,  # legacy 无 cycle
                module="CMemoryLoader",
                sub_id=int(m.group(1)),
                event="D_STORE",
                payload={"addr": m.group(2), "data": m.group(3)},
                raw_line=line
            )
        return None

    def _parse_payload(self, text: str) -> Dict[str, str]:
        result = {}
        for part in text.strip().split():
            if '=' in part:
                k, v = part.split('=', 1)
                result[k] = v
        return result
```

### 3.4.2 `tools/trace/func/tensor_model.py`

```python
"""
Trace.func F1_store / F2_tensor_op

F1_store:  从 D_STORE 事件重建 D tensor
F2_tensor_op: 重建完整 tensor op 输出并与 golden 对比
"""

import numpy as np
from typing import Optional

class TensorFuncModel:
    """从 trace 重建 D tensor"""

    def reconstruct_d_tensor_from_trace(
        self,
        events,           # List[TraceEvent]
        d_base_addr: int,  # D tensor 基地址
        M: int, N: int,
        dtype: str = "int32"
    ) -> Optional[np.ndarray]:
        """从 D_STORE 事件重建 D tensor"""
        store_events = [
            e for e in events
            if e.event == "D_STORE" or e.module == "CMemoryLoader"
        ]

        if not store_events:
            return None

        # 从 legacy 格式或结构化格式提取数据
        result = np.zeros((M, N), dtype=np.int32)
        for event in store_events:
            addr = int(event.payload.get("addr", "0"), 16)
            data_str = event.payload.get("data", "")
            # 解析 store data 并填入 result
            self._fill_store_data(result, addr, d_base_addr, data_str, N)

        return result

    def _fill_store_data(self, result, addr, base_addr, data_str, N):
        """将一次 store data 填入 result 数组"""
        # 实现与现有 compare_result.py 的地址计算逻辑对齐
        ...
```

### 3.4.3 验收

- Parser 能解析结构化 trace 格式
- Parser 能解析现有 legacy `CMemoryLoader_Store` 格式
- `TensorFuncModel` 能从 store 事件重建 D tensor

---

## Task 3.5: 实现 Golden 对比从 Trace 驱动

### 3.5.1 `tools/verify/cute_trace_golden.py`

```python
"""
从 trace 提取 D tensor 并与 golden 对比

这是第一次从 trace 驱动的验证（而非 C 代码内嵌比对）。
"""

def verify_from_trace(
    trace_path: str,
    golden: np.ndarray,
    d_base_addr: int,
    M: int, N: int,
    dtype: str = "int32"
) -> VerifyResult:
    """从 trace 文件重建 D tensor 并与 golden 比对"""
    parser = CuteTraceParser()
    with open(trace_path) as f:
        events = parser.parse(f.read())

    model = TensorFuncModel()
    actual = model.reconstruct_d_tensor_from_trace(
        events, d_base_addr, M, N, dtype
    )

    if actual is None:
        return VerifyResult(
            passed=False, total_elements=M*N, mismatch_count=M*N,
            max_abs_error=float('inf'), max_rel_error=float('inf'),
            first_mismatch=None,
            note="NO_STORE_EVENTS"
        )

    return verify_exact_int32(actual, golden)
```

### 3.5.2 Runner 扩展

在 Phase 2 Runner 基础上增加 trace-driven verify 路径：

```text
新增状态:
  PARSE_TRACE          → 调用 CuteTraceParser
  TRACE_FUNC_VERIFY    → 调用 cute_trace_golden.py

流程 (两个 verify 路径并存):
  ...
  → RUN
  → CAPTURE_LOG
  → PARSE_TRACE            # 新增
  → TRACE_FUNC_VERIFY      # 新增 (F1_store)
  → CHECK_PASS             # C 代码内嵌验证
  → SAVE_ARTIFACT
```

两条路径独立判断，artifact 记录两个结果：
```json
{
  "verify": {
    "c_embedded": {"status": "PASS"},
    "trace_func_f1_store": {"status": "PASS", "mismatch_count": 0}
  }
}
```

---

## 验收标准总表

- [ ] Layer op 复用 `cute_ops.h` 的 tensor op 封装，不直接调用 `CUTE_CONFIG_*`
- [ ] `project.yaml` 的 target 范围比 TensorTest 更窄（需要 conv/tensor capability）
- [ ] Trace parser 能解析 legacy `CMemoryLoader_Store` 格式
- [ ] `Trace.func F1_store` 能从 trace 重建 D tensor 并与 golden 对比
- [ ] 至少一个 layer variant 能运行
- [ ] Layer test 输出包含 `[CUTE_TEST] layer ... PASS/FAIL`
- [ ] 如果 `F3_layer` 未实现，状态标记为 `FUNC_MODEL_NOT_READY`
- [ ] artifact 包含 c_embedded 和 trace_func 两个 verify 结果

---

## 不做事项

- 不做 fused layer（Phase 4）。
- 不做 SOC-specific 优化（Phase 5）。
- 不要求完整模型（Phase 6）。
- 不要求最终 trace 设计定稿。
- 不要求 `F3_layer` 完整实现（`F1_store` + `F2_tensor_op` 即可）。

---

## 风险与应对

| 风险 | 应对 |
|------|------|
| Layer 代码复制 tensor 细节 | 强制通过 `cute_ops.h` 调用，code review 检查 |
| Golden 太复杂 | 选择最小 layer variant（1×1 conv） |
| Target 范围虚标 | target matcher 输出不支持原因 |
| Legacy trace 格式不稳定 | Parser 做容错处理，无法解析的行 skip 并计数 |
| D store 数据量太大 | 先对小矩阵测试（64×64），确认解析正确后再扩大 |

---

## 与 Phase 2 的衔接

- 复用 `cute_tensor.h` / `cute_ops.h` 的所有 API
- 复用 `cute-gen-golden.py` 和 `tools/verify/cute_verify.py`
- 在 TensorTest 的验证基础上增加 trace-driven 验证路径

## 与 Phase 4 的衔接

Phase 3 完成后，Phase 4 可以直接：
- 在 layer op 上叠加融合语义
- 复用 `F1_store` / `F2_tensor_op` 验证融合前后的输出一致性
- 增加 `F4_fused_layer` 的 trace func model
