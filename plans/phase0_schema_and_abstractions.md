# Phase 0 Plan: 冻结 HWConfig / Test / Trace 抽象和 Schema

## 目标

Phase 0 的目标不是跑通完整测试，而是先把三大对象的手写入口定下来：

- `HWConfig`: 由 `configs/hwconfigs/*.yaml` 描述。
- `Test`: 由 `cute-sdk/**/project.yaml` 描述。
- `Trace`: 本阶段只做占位 schema/spec，后续专题展开。

完成后，框架应能静态回答：

- 某个 `cute-sdk` project 是否支持某个 `HWConfig`。
- 某个 project 需要的 generated headers、capability、golden level、trace level 是什么。
- 哪些字段是人工维护真相源，哪些字段是自动生成产物。

## 设计约束

- 不恢复 `configs/tests/*.yaml` 作为人工维护入口。
- `cute-sdk/**/project.yaml` 是 Test 的主真相源。
- `generated_headers` 属于 `HWConfig`，默认输出到 `build/hwconfigs/<name>/generated_headers/`。
- Trace 只保留边界定义：`filter`、`func model`、`perf model`，不在本阶段细化事件 schema。
- catalog/index 如果需要，只能由工具扫描生成，不能作为人工维护真相源。

---

## 任务拆解

### Task 1: 创建目录骨架

创建 phase0 所需的所有目录结构（空目录放 `.gitkeep`）：

```
configs/
├── hwconfigs/
│   └── schemas/
├── schemas/
├── trace_filters/
└── suites/

cute-sdk/
├── runtime/
│   └── cute_runtime/
│       ├── include/
│       ├── src/
│       ├── tests/
│       └── build_rules/
├── tensor_ops/
│   └── matmul/
│       ├── src/
│       ├── golden/
│       ├── data/
│       └── build_rules/
├── include/
├── templates/
└── legacy/

trace/
├── python/
│   ├── func/
│   └── perf/
└── tests/

scripts/

tools/verify/
tools/perf/
```

**验收**: 所有目录存在，`legacy/` 下暂放 `.gitkeep`。

---

### Task 2: 定义 `hwconfig.schema.json`

#### 2.1 字段定义（与 CUTEParameters.scala 对齐）

Schema 必须与现有 `HeaderGenerator` 能提取的参数一一对应。

字段分组：

```text
version                    # schema 版本，固定 1
name                       # HWConfig 唯一标识 (如 cute2tops_scp64_dramsim32)
tags                       # 标签列表，供 Test target matcher 使用

cute:
  chipyard_config          # chipyard Config 类全名 (如 chipyard.CUTE2TopsSCP64Config)
  generated_headers:
    output_dir             # 生成头文件输出目录 (默认 build/hwconfigs/<name>/generated_headers)
    mode                   # generate_from_hwconfig | reuse_existing
    fingerprint            # auto | manual:<hash>
  trace_capability:        # RTL trace 能力声明（占位，Phase 3 细化）
    structured_trace       # bool
    d_store_data           # bool
    mem_req_rsp            # bool
    perf_counter_snapshot  # bool

soc:
  core                     # rocket | boom | shuttle
  core_count               # int
  sysbus_width             # bit (如 64)
  membus_width             # bit (如 64)
  dramsim:
    enabled                # bool
    preset                 # dramsim preset 名
  simulator:
    backend                # verilator | vcs | fpga
    binary                 # auto | <path>
    max_cycles             # 最大仿真周期

capability:                # 由 HWConfig 导出的软件可见能力
  datatypes                # list of datatype name strings
  tensor_ops               # list of op name strings
  layer_ops                # list
  fused_ops                # list
```

#### 2.2 Schema 校验规则

- `version` 必填，固定为 1。
- `name` 必填，唯一。
- `cute.chipyard_config` 必填。
- `soc.core` 必填，枚举 `rocket | boom | shuttle`。
- `capability.datatypes` 必填，至少包含一个。
- `capability.tensor_ops` 选填，默认 `[]`。
- `cute.trace_capability` 整体选填，默认全部 false。

#### 2.3 产物

```
configs/schemas/hwconfig.schema.json
```

---

### Task 3: 创建样板 `hwconfig.yaml`

基于现有 CUTE 代码库中的实际配置创建。

#### 3.1 `cute2tops_scp64_dramsim32.yaml`

这个配置对应 `chipyard.CUTE2TopsSCP64Config`，是当前默认配置。

参数来源（从 `validation.h.generated` 确认）：
- Tensor_M=64, Tensor_N=64, Tensor_K=64
- Matrix_M=4, Matrix_N=4
- outsideDataWidth=512, VectorWidth=256
- Shuttle core, 1 core
- DRAMSim 32GB preset

```yaml
version: 1
name: cute2tops_scp64_dramsim32
tags: [cute_tensor_v1, shuttle, small]

cute:
  chipyard_config: chipyard.CUTE2TopsSCP64Config
  generated_headers:
    output_dir: build/hwconfigs/cute2tops_scp64_dramsim32/generated_headers
    mode: generate_from_hwconfig
    fingerprint: auto
  trace_capability:
    structured_trace: false
    d_store_data: false
    mem_req_rsp: false
    perf_counter_snapshot: true

soc:
  core: shuttle
  core_count: 1
  sysbus_width: 64
  membus_width: 64
  dramsim:
    enabled: true
    preset: dramsim2_ini_32GB_per_s
  simulator:
    backend: verilator
    binary: auto
    max_cycles: 800000000

capability:
  datatypes: [i8i8i32, fp16fp16fp32, bf16bf16fp32, tf32tf32fp32,
              i8u8i32, u8i8i32, u8u8i32,
              mxfp8e4m3fp32, mxfp8e5m2fp32, nvfp4fp32, mxfp4fp32,
              fp8e4m3fp32, fp8e5m2fp32]
  tensor_ops: [matmul, conv]
  layer_ops: []
  fused_ops: []
```

#### 3.2 `cute4tops_scp128_dramsim48.yaml`（可选，第二配置）

对应 `chipyard.CUTE4TopsSCP128Config`，Tensor_M=128。

#### 3.3 产物

```
configs/hwconfigs/cute2tops_scp64_dramsim32.yaml
configs/hwconfigs/cute4tops_scp128_dramsim48.yaml  (可选)
```

---

### Task 4: 定义 `project.schema.json`

#### 4.1 字段定义

```text
version                    # schema 版本，固定 1
id                         # 全局唯一 project id (如 tensor.matmul)
name                       # 显示名 (如 matmul)
kind                       # base_test | tensor_test | layer_test | fuse_layer_test | soc_opt_test | model_test
version_name               # 人工维护的语义版本 (如 v0.3)

target:
  hwconfigs:
    include_tags           # 匹配 HWConfig.tags，满足任一即纳入
    exclude_tags           # 排除，优先级高于 include
  required_capability:
    datatypes              # 至少需要支持的 datatype list
    tensor_ops             # 至少需要支持的 tensor op list
    layer_ops              # list
    fused_ops              # list
    trace_func_level       # 需要的最低 Trace.func level (占位名称)

code:
  entry                    # 主 C 文件路径 (相对于 project 目录)
  build                    # make | cmake | custom:<cmd>
  runtime_lib              # 依赖的 runtime lib project id
  op_lib                   # 依赖的 op lib project id
  variants                 # list of variant objects
    - name                 # variant 唯一标识
      <param>: <value>     # 自由键值对，编译时传入

golden:
  level                    # event | store_tensor | tensor_op | layer | fused_layer | model
  source                   # python_reference | c_reference | existing_checker | external
  compare:
    mode                   # exact | tolerance | semantic
    abs_err                # float (tolerance mode)
    rel_err                # float (tolerance mode)

trace:
  required_func_level      # 占位 level 名称
  default_filters          # 占位 filter 名称 list
```

#### 4.2 Schema 校验规则

- `version` 必填，固定为 1。
- `id` 必填，全局唯一。
- `kind` 必填，枚举六种。
- `code.entry` 必填。
- `code.variants` 可为空（单 variant 场景隐含 default）。
- `golden.level` 必填，枚举六种。
- `trace.required_func_level` 必填，但本阶段值仅为占位字符串。

#### 4.3 产物

```
configs/schemas/project.schema.json
```

---

### Task 5: 创建两个样板 `project.yaml`

#### 5.1 `cute-sdk/runtime/cute_runtime/project.yaml`

```yaml
version: 1
id: runtime.cute_runtime
name: cute_runtime
kind: base_test
version_name: v0.1

target:
  hwconfigs:
    include_tags: [cute_tensor_v1]
  required_capability:
    datatypes: [i8i8i32]
    tensor_ops: []
    trace_func_level: F0_event

code:
  entry: tests/rocc_hello.c
  build: make
  runtime_lib: null
  op_lib: null
  variants:
    - name: rocc_hello
      description: "Minimal RoCC/CUTE hello - query busy, print fingerprint"

golden:
  level: event
  source: existing_checker
  compare:
    mode: exact

trace:
  required_func_level: F0_event
  default_filters: [func_event]
```

#### 5.2 `cute-sdk/tensor_ops/matmul/project.yaml`

```yaml
version: 1
id: tensor.matmul
name: matmul
kind: tensor_test
version_name: v0.1

target:
  hwconfigs:
    include_tags: [cute_tensor_v1]
  required_capability:
    datatypes: [i8i8i32]
    tensor_ops: [matmul]
    trace_func_level: F2_tensor_op

code:
  entry: src/main.c
  build: make
  runtime_lib: runtime.cute_runtime
  op_lib: null
  variants:
    - name: i8_128
      M: 128
      N: 128
      K: 128
      dtype: i8i8i32
      bias_type: zero
    - name: i8_64
      M: 64
      N: 64
      K: 64
      dtype: i8i8i32
      bias_type: zero

golden:
  level: tensor_op
  source: python_reference
  compare:
    mode: exact

trace:
  required_func_level: F2_tensor_op
  default_filters: [func_store_tensor]
```

#### 5.3 产物

```
cute-sdk/runtime/cute_runtime/project.yaml
cute-sdk/tensor_ops/matmul/project.yaml
```

---

### Task 6: 定义 Trace 占位文件

#### 6.1 `trace_filter.schema.json`

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "CUTE Trace Filter",
  "type": "object",
  "required": ["version", "name", "purpose", "description", "status"],
  "properties": {
    "version": { "type": "integer", "const": 1 },
    "name": { "type": "string" },
    "purpose": { "type": "string", "enum": ["func", "perf", "debug"] },
    "description": { "type": "string" },
    "status": { "type": "string", "enum": ["placeholder", "draft", "stable"] }
  }
}
```

本阶段 **不定义** 具体 filter 条件（event/module/cycle window 等），只声明存在性和 purpose。

#### 6.2 `trace/format_spec.md`

只记录以下内容：

- Trace 是一级抽象，和 HWConfig、Test 并列。
- `Trace.filter`、`Trace.func`、`Trace.perf` 待后续专题展开。
- 本阶段所有 trace level 名称只作为接口占位：
  - `F0_event` — 基础事件顺序检查
  - `F1_store` — D_STORE_DATA 提取
  - `F2_tensor_op` — tensor op 级功能验证
  - `F3_layer` — layer 级
  - `F4_fused_layer` — fused layer 级
  - `F5_model` — model 级
- Level 名称接口冻结，具体 event schema 未冻结。

#### 6.3 占位 filter 文件

```
configs/trace_filters/func_event.yaml        # purpose: func, status: placeholder
configs/trace_filters/func_store_tensor.yaml  # purpose: func, status: placeholder
configs/trace_filters/perf_task_stage.yaml    # purpose: perf, status: placeholder
```

每个文件只包含最小字段（version, name, purpose, description, status: placeholder），不定义实际 filter 逻辑。

#### 6.4 产物

```
configs/schemas/trace_filter.schema.json
trace/format_spec.md
configs/trace_filters/func_event.yaml
configs/trace_filters/func_store_tensor.yaml
configs/trace_filters/perf_task_stage.yaml
```

---

### Task 7: 实现 `tools/runner/cute-check-config.py`

#### 7.1 职责

极简静态检查工具，不做编译/运行，只做 YAML 校验和 target 匹配。

```text
Usage:
  tools/runner/cute-check-config.py --hwconfig <path>
    校验单个 hwconfig yaml 是否符合 schema

  tools/runner/cute-check-config.py --project <path>
    校验单个 project.yaml 是否符合 schema

  tools/runner/cute-check-config.py --hwconfig <path> --project <path>
    校验两者，并判断 Test.target 是否匹配 HWConfig

  tools/runner/cute-check-config.py --scan
    扫描 configs/hwconfigs/ 和 cute-sdk/**/project.yaml，
    输出所有 project × hwconfig 的 target 匹配矩阵
```

#### 7.2 Target 匹配逻辑

```text
匹配条件（全部满足才为 MATCH）：
  1. HWConfig.tags 与 project.target.hwconfigs.include_tags 有交集
  2. HWConfig.tags 与 project.target.hwconfigs.exclude_tags 无交集
  3. HWConfig.capability.datatypes ⊇ project.target.required_capability.datatypes
  4. HWConfig.capability.tensor_ops ⊇ project.target.required_capability.tensor_ops

输出:
  MATCH        — 全部满足
  TAG_MISS     — include/exclude 不满足
  CAP_MISS     — capability 不满足，列出缺失项
```

#### 7.3 Trace Level 检查

读取 `trace/format_spec.md` 中定义的占位 level 名称集合，检查 `project.trace.required_func_level` 是否在集合内。输出 `TRACE_LEVEL_KNOWN` 或 `TRACE_LEVEL_UNKNOWN`。

#### 7.4 依赖

- Python 3.8+
- `jsonschema` (pip)
- `pyyaml` (pip)
- 无其他外部依赖

#### 7.5 产物

```
tools/runner/cute-check-config.py
```

---

## 产物总览

```text
# Schema
configs/schemas/hwconfig.schema.json
configs/schemas/project.schema.json
configs/schemas/trace_filter.schema.json

# HWConfig 样板
configs/hwconfigs/cute2tops_scp64_dramsim32.yaml
configs/hwconfigs/cute4tops_scp128_dramsim48.yaml  (可选)

# Test 样板
cute-sdk/runtime/cute_runtime/project.yaml
cute-sdk/tensor_ops/matmul/project.yaml

# Trace 占位
trace/format_spec.md
configs/trace_filters/func_event.yaml
configs/trace_filters/func_store_tensor.yaml
configs/trace_filters/perf_task_stage.yaml

# 工具
tools/runner/cute-check-config.py

# 目录骨架
(所有上述目录 + .gitkeep)
```

---

## 验收标准

- [ ] `cute-check-config.py --hwconfig configs/hwconfigs/cute2tops_scp64_dramsim32.yaml` 通过校验
- [ ] `cute-check-config.py --project cute-sdk/runtime/cute_runtime/project.yaml` 通过校验
- [ ] `cute-check-config.py --project cute-sdk/tensor_ops/matmul/project.yaml` 通过校验
- [ ] `cute-check-config.py --hwconfig <hw> --project <proj>` 输出 MATCH 且理由正确
- [ ] `cute-check-config.py --scan` 输出 project × hwconfig 匹配矩阵
- [ ] `HWConfig` 和 `project.yaml` 的字段边界清楚，人工字段和自动生成字段有文档区分
- [ ] Trace level 名称（F0-F5）已作为占位冻结，但具体 event schema 未承诺
- [ ] 文档明确：`configs/tests` 不作为人工维护入口

---

## 不做事项

- 不编译/运行任何 C 代码。
- 不实现 Runner（Phase 1）。
- 不实现 Trace parser/analyzer。
- 不写 golden generator。
- 不迁移旧测试。
- 不修改 RTL。

---

## 风险与应对

| 风险 | 应对 |
|------|------|
| Schema 过早复杂化 | 本阶段只保留 Phase 1/2 需要的字段；不确定的字段用 `*_TODO` 标注或直接省略 |
| Trace 过早展开 | 只做占位；level 名称冻结但内容为空 |
| project.yaml 过于自由 | schema 约束最小必填字段，variant 内部允许自由键值对 |
| HWConfig 字段与 CUTEParameters 不对齐 | `hwconfig.yaml` 的 `capability` 字段从 `validation.h.generated` 实际值推导，不从记忆中猜测 |

---

## 与 Phase 1 的衔接

Phase 0 完成后，Phase 1 可以直接：

1. 读取 `configs/hwconfigs/cute2tops_scp64_dramsim32.yaml` 中的 `cute.chipyard_config` 调用 `generate-headers.sh`。
2. 读取 `cute-sdk/runtime/cute_runtime/project.yaml` 知道 entry file 和 target。
3. 用 `cute-check-config.py` 确认 target match 后进入 build/run 流程。
4. 在 artifact 中保存 `hwconfig.resolved.yaml` 和 `target_match.json`。
