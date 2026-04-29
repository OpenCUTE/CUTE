# Phase 0 Plan: 冻结 ChipyardConfig / HWConfig / Test / Trace 抽象和 Schema

## 目标

Phase 0 的目标不是跑通完整测试，而是先把核心对象的手写入口定下来：

- `ChipyardConfig`: 由 `configs/chipyard_configs/*.yaml` 描述，和现有 Chipyard Scala Config class 一一对应。
- `CUTEFPEVersion`: 由 `configs/cute_fpe_versions/*.yaml` 描述，表示 CUTE/FPE 内部支持的计算格式版本。
- `CUTEISAVersion`: 由 `configs/cute_isa_versions/*.yaml` 描述，表示 CUTE/YGJK 内部支持的指令集版本。
- `HWConfig`: 由 `configs/hwconfigs/*.yaml` 描述，组合 `ChipyardConfig + memory model + simulator policy`。
- `Test`: 由 `cute-sdk/**/project.yaml` 描述。
- `Trace`: 本阶段只做占位 schema/spec，后续专题展开。

完成后，框架应能静态回答：

- 某个 `cute-sdk` project 是否支持某个 `HWConfig`。
- 某个 project 需要的 generated headers、capability、golden level、trace level 是什么。
- 哪些字段是人工维护真相源，哪些字段是自动生成产物。

## 设计约束

- 不恢复 `configs/tests/*.yaml` 作为人工维护入口。
- `cute-sdk/**/project.yaml` 是 Test 的主真相源。
- `generated_headers` 属于 `ChipyardConfig`，默认输出到 `build/chipyard_configs/<id>/generated_headers/`。
- `HWConfig` 不手写 SoC/core/bus/capability；这些从引用的 `ChipyardConfig` 解析得到。
- datatype 能力列表不在每个 `ChipyardConfig` 中重复维护；由 `cute.fpe.version` 引用 `configs/cute_fpe_versions/<version>.yaml`，再派生为 resolved software capability。
- instruction set 不在每个 `ChipyardConfig` 中重复维护；由 `cute.isa.version` 引用 `configs/cute_isa_versions/<version>.yaml`，后续由 `cute-check-config.py` 对齐 `CuteInstConfigs` 和 `YGJKInstConfigs`。
- Trace 只保留边界定义：`filter`、`func model`、`perf model`，不在本阶段细化事件 schema。
- catalog/index 如果需要，只能由工具扫描生成，不能作为人工维护真相源。

---

## 任务拆解

### Task 1: 创建目录骨架

创建 phase0 所需的所有目录结构（空目录放 `.gitkeep`）：

```
configs/
├── chipyard_configs/
├── cute_fpe_versions/
├── cute_isa_versions/
├── hwconfigs/
├── memconfigs/
│   └── dramsim2/
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

### Task 2: 定义 `chipyard_config.schema.json`

#### 2.1 设计边界

`ChipyardConfig` 是现有 `CuteConfig.scala` 中一个 Scala Config class 的结构化 contract。本阶段只支持 `mode: existing_class`，不生成 Scala。

字段分组：

```text
version                    # schema 版本，固定 1
id                         # ChipyardConfig 唯一标识 (如 cute2tops_scp64)
class                      # Chipyard Config 类全名 (如 chipyard.CUTE2TopsSCP64Config)
source_file                # class 定义文件，相对 CUTE 根目录
mode                       # existing_class

cute:
  params_symbol            # CuteParams 符号，如 CuteParams.CUTE_2Tops_64SCP
  instances                # WithCUTE(Seq(...)) 中挂载 CUTE 的 core id 列表
  fpe:
    version                # CUTE/FPE 内部计算格式版本
  isa:
    version                # CUTE/YGJK 内部指令集版本
  generated_headers:
    output_dir             # 默认 build/chipyard_configs/<id>/generated_headers
    mode                   # generate_from_chipyard_config | reuse_existing
    fingerprint            # auto | manual:<hash>

soc:
  core:
    kind                   # rocket | boom | shuttle | mixed
    count                  # int
    shuttle_tile_beat_bytes
    clusters               # mixed core config 占位
  bus:
    system_bits            # WithSystemBusWidth
    memory_bits            # WithNBitMemoryBus
  cache:
    inclusive_kb
    outer_latency_cycles
    banks
    cache_hash
    tl_monitors

capability:                # 由 ChipyardConfig/CUTE params 导出的软件可见能力
  tensor_ops
  layer_ops
  fused_ops

trace_capability:          # RTL trace 能力声明（占位，Phase 3 细化）
    structured_trace       # bool
    d_store_data           # bool
    mem_req_rsp            # bool
    perf_counter_snapshot  # bool
```

#### 2.2 Schema 校验规则

- `version` 必填，固定为 1。
- `id` 必填，唯一。
- `class` 必填，必须是现有 Scala Config class 全名。
- `mode` 必填，本阶段固定为 `existing_class`。
- `cute.params_symbol`、`cute.instances`、`cute.fpe.version`、`cute.isa.version`、`cute.generated_headers` 必填。
- `soc.core.kind/count`、`soc.bus.system_bits/memory_bits` 必填。
- `cute.fpe.version` 必须能解析到 `configs/cute_fpe_versions/<version>.yaml`。
- `cute.isa.version` 必须能解析到 `configs/cute_isa_versions/<version>.yaml`。

#### 2.3 产物

```
configs/schemas/chipyard_config.schema.json
```

---

### Task 2.5: 定义 `cute_fpe_version.schema.json`

`CUTEFPEVersion` 用于描述 CUTE/FPE 内部支持的计算格式版本，避免每个 `ChipyardConfig` 重复维护由这些格式派生出的 datatype 能力长列表。

```text
version                    # schema 版本，固定 1
id                         # FPE version id，如 cute_fpe_v1
description                # 说明
source:
  generated_header         # 如 cutetest/include/datatype.h.generated
  scala_object             # 如 cute.ElementDataType
datatypes                  # datatype name strings
```

产物：

```
configs/schemas/cute_fpe_version.schema.json
configs/cute_fpe_versions/cute_fpe_v1.yaml
```

---

### Task 2.6: 定义 `cute_isa_version.schema.json`

`CUTEISAVersion` 用于描述 CUTE/YGJK 内部支持的指令集版本，避免每个 `ChipyardConfig` 重复维护 instruction set。该对象必须和 `CUTEParameters.scala` 中的 `CuteInstConfigs`、`YGJKInstConfigs` 对齐。

```text
version                    # schema 版本，固定 1
id                         # ISA version id，如 cute_isa_v1
description                # 说明
source:
  scala_file               # 如 src/main/scala/CUTEParameters.scala
  scala_objects            # cute.CuteInstConfigs / cute.YGJKInstConfigs
  generated_header         # 如 cutetest/include/instruction.h.generated
rocc:
  opcode                   # RoCC opcode，当前为 0x0B
  cute_internal_offset     # CUTE internal 指令映射到 RoCC funct 时的 offset，当前为 64
groups:
  ygjk:
    scala_object
    description
    rocc_funct_offset
    instructions           # name / funct / rocc_funct / description / return_description
  cute:
    scala_object
    description
    rocc_funct_offset
    instructions           # name / funct / rocc_funct / description / return_description
```

产物：

```
configs/schemas/cute_isa_version.schema.json
configs/cute_isa_versions/cute_isa_v1.yaml
```

---

### Task 3: 定义 `hwconfig.schema.json`

#### 3.1 字段定义

`HWConfig` 是可运行硬件目标组合，不再手写 SoC/core/bus/capability。

```text
version                    # schema 版本，固定 1
name                       # HWConfig 唯一标识 (如 cute2tops_scp64_dramsim32)
tags                       # 标签列表，供 Test target matcher 使用
chipyard_config            # 引用 configs/chipyard_configs/<id>.yaml

memory:
  model                    # dramsim2 | none
  config                   # configs/memconfigs/<model>/<config>/ 下的配置目录名

simulator:
  backend                  # verilator | vcs | fpga
  binary                   # auto | <path>
  max_cycles               # 最大仿真周期
```

#### 3.2 Schema 校验规则

- `version` 必填，固定为 1。
- `name` 必填，唯一。
- `chipyard_config` 必填，必须能解析到 `configs/chipyard_configs/<id>.yaml`。
- `memory.model` 必填；如果 `model=dramsim2`，则 `config` 必填并指向 `configs/memconfigs/dramsim2/<config>/`。
- `simulator.backend/binary/max_cycles` 必填。

#### 3.3 产物

```
configs/schemas/hwconfig.schema.json
```

---

### Task 3.5: 创建样板 `chipyard_config.yaml` 和 `hwconfig.yaml`

基于现有 CUTE 代码库中的实际配置创建。

#### 3.5.1 `cute2tops_scp64.yaml`

这个配置对应 `chipyard.CUTE2TopsSCP64Config`，是当前默认 Chipyard Config contract。

参数来源（从 `validation.h.generated` 确认）：
- Tensor_M=64, Tensor_N=64, Tensor_K=64
- Matrix_M=4, Matrix_N=4
- outsideDataWidth=512, VectorWidth=256
- Shuttle core, 1 core, `WithShuttleTileBeatBytes(64)`
- `WithSystemBusWidth(512)`、`WithNBitMemoryBus(512)`

```yaml
version: 1
id: cute2tops_scp64
class: chipyard.CUTE2TopsSCP64Config
source_file: chipyard/generators/chipyard/src/main/scala/config/CuteConfig.scala
mode: existing_class

cute:
  params_symbol: CuteParams.CUTE_2Tops_64SCP
  instances: [0]
  fpe:
    version: cute_fpe_v1
  isa:
    version: cute_isa_v1
  generated_headers:
    output_dir: build/chipyard_configs/cute2tops_scp64/generated_headers
    mode: generate_from_chipyard_config
    fingerprint: auto

soc:
  core:
    kind: shuttle
    count: 1
    shuttle_tile_beat_bytes: 64
  bus:
    system_bits: 512
    memory_bits: 512

capability:
  tensor_ops: [matmul, conv]
  layer_ops: []
  fused_ops: []
```

#### 3.5.2 `cute2tops_scp64_dramsim32.yaml`

```yaml
version: 1
name: cute2tops_scp64_dramsim32
tags: [cute_tensor_v1, shuttle, small]

chipyard_config: cute2tops_scp64

memory:
  model: dramsim2
  config: dramsim2_ini_32GB_per_s

simulator:
  backend: verilator
  binary: auto
  max_cycles: 800000000
```

#### 3.5.3 `cute4tops_scp128` / `cute4tops_scp128_dramsim48`（可选，第二配置）

对应 `chipyard.CUTE4TopsSCP128Config`，Tensor_M=128，HWConfig 绑定 `dramsim2_ini_48GB_per_s`。

#### 3.5.4 产物

```
configs/chipyard_configs/cute2tops_scp64.yaml
configs/chipyard_configs/cute4tops_scp128.yaml  (可选)
configs/cute_fpe_versions/cute_fpe_v1.yaml
configs/cute_isa_versions/cute_isa_v1.yaml
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
    校验单个 hwconfig yaml 是否符合 schema，
    并检查 chipyard_config 引用和 memory config 目录是否存在

  tools/runner/cute-check-config.py --chipyard-config <path>
    校验单个 chipyard_config yaml 是否符合 schema，
    并检查 id/class/source_file 与现有 CuteConfig.scala contract 是否一致

  tools/runner/cute-check-config.py --project <path>
    校验单个 project.yaml 是否符合 schema

  tools/runner/cute-check-config.py --hwconfig <path> --project <path>
    校验两者，解析 HWConfig 引用的 ChipyardConfig，
    并判断 Test.target 是否匹配 resolved HWConfig

  tools/runner/cute-check-config.py --scan
    扫描 configs/chipyard_configs/、configs/hwconfigs/ 和 cute-sdk/**/project.yaml，
    输出所有 project × hwconfig 的 target 匹配矩阵
```

#### 7.2 引用解析逻辑

```text
解析步骤：
  1. 读取 HWConfig.chipyard_config = <id>
  2. 加载 configs/chipyard_configs/<id>.yaml
  3. 读取 ChipyardConfig.cute.fpe.version = <version>
  4. 加载 configs/cute_fpe_versions/<version>.yaml，派生并展开 resolved capability.datatypes
  5. 读取 ChipyardConfig.cute.isa.version = <version>
  6. 加载 configs/cute_isa_versions/<version>.yaml，派生并展开 resolved capability.instructions
  7. 如果 HWConfig.memory.model = dramsim2，
     检查 configs/memconfigs/dramsim2/<config>/system.ini 等必要文件存在
  8. 形成 resolved HWConfig:
     tags 来自 HWConfig
     capability.tensor_ops/layer_ops/fused_ops、trace_capability、generated_headers、soc 来自 ChipyardConfig
     capability.datatypes 来自 CUTEFPEVersion
     capability.instructions 来自 CUTEISAVersion
     memory / simulator 来自 HWConfig
```

#### 7.3 ChipyardConfig contract 检查（Phase 0 TODO）

本阶段脚本只做静态检查，不编译、不生成 Verilog。需要预留以下检查：

```text
existing_class 检查：
  1. source_file 存在
  2. class 能在 source_file 中找到 class <Name> extends Config
  3. cute.params_symbol 能在该 class 的 WithCuteCoustomParams(...) 中找到
  4. cute.instances 与 WithCUTE(Seq(...)) 一致
  5. soc.bus.system_bits 与 WithSystemBusWidth(...) 一致
  6. soc.bus.memory_bits 与 WithNBitMemoryBus(...) 一致
  7. soc.core.kind/count 与 WithNShuttleCores / WithNSmallBooms / WithNSmallCores 等片段一致
  8. cache 字段与 WithInclusiveCache / WithNBanks / WithCacheHash / WithoutTLMonitors 一致
  9. cute.fpe.version 能解析到 configs/cute_fpe_versions/<version>.yaml
  10. cute.isa.version 能解析到 configs/cute_isa_versions/<version>.yaml

CUTEFPEVersion 检查：
  1. CUTEFPEVersion.datatypes 与 ElementDataType/header 导出的 datatype set 一致

CUTEISAVersion 检查：
  1. groups.cute.instructions 的 name/funct/description/return_description 集合与 CuteInstConfigs.allInsts 一致
  2. groups.ygjk.instructions 的 name/funct/description/return_description 集合与 YGJKInstConfigs.allInsts 一致
  3. groups.cute.instructions[*].rocc_funct = funct + cute_internal_offset
  4. groups.ygjk.instructions[*].rocc_funct = funct + rocc_funct_offset
  5. instruction.h.generated 中 CUTE_INST_FUNCT_<name> 宏值与 rocc_funct 一致
```

后续可选增强：调用 `HeaderGenerator`/参数 extractor 生成临时 headers，确认 `CUTEFPEVersion.datatypes`、`CUTEISAVersion.instructions` 和 CUTE 参数确实来自真实 Config。

#### 7.4 Target 匹配逻辑

```text
匹配条件（全部满足才为 MATCH）：
  1. HWConfig.tags 与 project.target.hwconfigs.include_tags 有交集
  2. HWConfig.tags 与 project.target.hwconfigs.exclude_tags 无交集
  3. resolved capability.datatypes（由 CUTEFPEVersion 展开） ⊇ project.target.required_capability.datatypes
  4. resolved ChipyardConfig.capability.tensor_ops ⊇ project.target.required_capability.tensor_ops

输出:
  MATCH        — 全部满足
  TAG_MISS     — include/exclude 不满足
  CAP_MISS     — capability 不满足，列出缺失项
```

#### 7.5 Trace Level 检查

读取 `trace/format_spec.md` 中定义的占位 level 名称集合，检查 `project.trace.required_func_level` 是否在集合内。输出 `TRACE_LEVEL_KNOWN` 或 `TRACE_LEVEL_UNKNOWN`。

#### 7.6 依赖

- Python 3.8+
- `jsonschema` (pip)
- `pyyaml` (pip)
- 无其他外部依赖

#### 7.7 产物

```
tools/runner/cute-check-config.py
```

---

## 产物总览

```text
# Schema
configs/schemas/chipyard_config.schema.json
configs/schemas/cute_fpe_version.schema.json
configs/schemas/cute_isa_version.schema.json
configs/schemas/hwconfig.schema.json
configs/schemas/project.schema.json
configs/schemas/trace_filter.schema.json

# CUTE FPE version 样板
configs/cute_fpe_versions/cute_fpe_v1.yaml

# CUTE ISA version 样板
configs/cute_isa_versions/cute_isa_v1.yaml

# ChipyardConfig 样板
configs/chipyard_configs/cute2tops_scp64.yaml
configs/chipyard_configs/cute4tops_scp128.yaml  (可选)

# HWConfig 样板
configs/hwconfigs/cute2tops_scp64_dramsim32.yaml
configs/hwconfigs/cute4tops_scp128_dramsim48.yaml  (可选)

# Memory model 配置目录
configs/memconfigs/dramsim2/dramsim2_ini_32GB_per_s/
configs/memconfigs/dramsim2/dramsim2_ini_48GB_per_s/

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

- [ ] `cute-check-config.py --chipyard-config configs/chipyard_configs/cute2tops_scp64.yaml` 通过校验
- [ ] `cute-check-config.py` 能解析 `cute.fpe.version` 并展开 datatype set
- [ ] `cute-check-config.py` 能解析 `cute.isa.version` 并确认 instruction set 与 `CuteInstConfigs` / `YGJKInstConfigs` 一致
- [ ] `cute-check-config.py --hwconfig configs/hwconfigs/cute2tops_scp64_dramsim32.yaml` 通过校验
- [ ] `cute-check-config.py --project cute-sdk/runtime/cute_runtime/project.yaml` 通过校验
- [ ] `cute-check-config.py --project cute-sdk/tensor_ops/matmul/project.yaml` 通过校验
- [ ] `cute-check-config.py --hwconfig <hw> --project <proj>` 输出 MATCH 且理由正确
- [ ] `cute-check-config.py --scan` 输出 project × hwconfig 匹配矩阵
- [ ] `HWConfig`、`ChipyardConfig` 和 `project.yaml` 的字段边界清楚，人工字段和自动生成字段有文档区分
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
| HWConfig 字段与 CUTEParameters 不对齐 | HWConfig 不承载 CUTE 参数；`ChipyardConfig` contract 后续由 `cute-check-config.py` 对齐 `CuteConfig.scala` 和 generated headers；datatype set 由 `CUTEFPEVersion` 统一维护；instruction set 由 `CUTEISAVersion` 统一维护 |

---

## 与 Phase 1 的衔接

Phase 0 完成后，Phase 1 可以直接：

1. 读取 `configs/hwconfigs/cute2tops_scp64_dramsim32.yaml` 中的 `chipyard_config`，解析到 `configs/chipyard_configs/cute2tops_scp64.yaml`。
2. 使用 `ChipyardConfig.class` 调用 `generate-headers.sh`。
3. 读取 `cute-sdk/runtime/cute_runtime/project.yaml` 知道 entry file 和 target。
4. 用 `cute-check-config.py` 确认 target match 后进入 build/run 流程。
5. 在 artifact 中保存 `hwconfig.resolved.yaml` 和 `target_match.json`。
