# Phase 0 Plan: 冻结 ChipyardConfig / HWConfig / Test / Trace 抽象和 Schema

## 目标

Phase 0 的目标不是跑通完整测试，而是先把核心对象的入口和边界定下来：

- `ChipyardConfig`: 由 `configs/chipyard_configs/*.yaml` 作为薄 manifest/catalog 入口，和现有 Chipyard Scala Config class 一一对应；长期结构事实由 Chipyard exporter 导出，不靠手抄。
- `CUTEFPEVersion`: 由 `configs/cute_fpe_versions/*.yaml` 描述，表示 CUTE/FPE 内部支持的计算格式版本。
- `CUTEISAVersion`: 由 `configs/cute_isa_versions/*.yaml` 描述，表示 CUTE/YGJK 内部支持的指令集版本。
- `VectorVersion`: 由 `configs/vector_versions/*.yaml` 描述，表示软件可见的向量实现版本和能力标签。
- `HWConfig`: 由 `configs/hwconfigs/*.yaml` 描述，组合 `ChipyardConfig + memory model + simulator policy`。
- `Test`: 由 `cute-sdk/**/project.yaml` 描述。
- `Trace`: 本阶段只做占位 schema/spec，后续专题展开。

完成后，框架应能静态回答：

- 某个 `cute-sdk` project 是否支持某个 `HWConfig`。
- 某个 project 需要的 generated headers、capability、golden level、trace level 是什么。
- 哪些字段是人工维护入口，哪些字段必须由 Chipyard/runner 自动导出。

## 设计约束

- 不恢复 `configs/tests/*.yaml` 作为人工维护入口。
- `cute-sdk/**/project.yaml` 是 Test 的主真相源。
- `generated_headers` 和 `chipyard_config.extracted.json` 都属于 ChipyardConfig 的生成产物，默认输出到 `build/chipyard_configs/<id>/`。
- `HWConfig` 不手写 SoC/core/bus/capability；这些长期应从引用的 Chipyard exported JSON 解析得到。Phase 0 在 exporter 未完成前允许 `configs/chipyard_configs/*.yaml` 暂存 bootstrap 字段，但它们不是长期真相源。
- datatype 能力列表不在每个 `ChipyardConfig` 中重复维护；由 FPE version manifest 和 Chipyard exporter 导出的 datatype facts 对齐后派生为 resolved software capability。
- instruction set 不在每个 `ChipyardConfig` 中重复维护；由 ISA version manifest 和 Chipyard exporter 导出的 instruction facts 对齐后派生为 resolved software capability。
- vector 能力列表不放宽到 `Project` target；`ChipyardConfig` manifest 只声明/引用 vector version id，具体 vector mixin/config-dependent 字段由 Chipyard exporter 输出，`Project.target.requires.vector_versions` 只匹配这些 version id。
- `cute-check-config.py` 不负责反向解析完整 Chipyard Scala Config；它只校验 manifest、引用和 target match。Chipyard Config 的结构事实由后续 exporter 负责导出。
- `none` 是一个真实的 `VectorVersion` manifest，不是缺省空值；无向量实现或无向量依赖时都显式写 `none`。
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
├── vector_versions/
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

`ChipyardConfig` manifest 是现有 `CuteConfig.scala` 中一个 Scala Config class 的**入口描述**，不是长期手抄结构事实。最终形态是：

```text
configs/chipyard_configs/<id>.yaml        # 人工维护的薄入口
Chipyard exporter                         # 从 class 实例化/参数中导出结构事实
build/chipyard_configs/<id>/chipyard_config.extracted.json
```

在 exporter 完成前，Phase 0 可以保留 `bootstrap_manual`/`existing_class` 过渡 manifest，把 SoC/core/bus/capability 等字段暂时写进 YAML，用来跑通 schema 和 target matcher。但这些字段只用于 bootstrap，不作为长期真相源，也不要求 Python checker 用正则完整证明它们等于 Scala Config。

长期薄 manifest 字段分组：

```text
version                    # schema 版本，固定 1
id                         # ChipyardConfig 唯一标识 (如 cute2tops_scp64)
class                      # Chipyard Config 类全名 (如 chipyard.CUTE2TopsSCP64Config)
source_file                # class 定义文件，相对 CUTE 根目录
mode                       # bootstrap_manual | exported_from_chipyard

export:
  artifact                 # 默认 build/chipyard_configs/<id>/chipyard_config.extracted.json
  generated_headers:
    output_dir             # 默认 build/chipyard_configs/<id>/generated_headers
    fingerprint            # auto | manual:<hash>

compatibility:
  fpe:
    version                # CUTE/FPE 内部计算格式版本
  isa:
    version                # CUTE/YGJK 内部指令集版本
  vector:
    version                # none | saturn_rvv | ...

capability_labels:         # 若 Chipyard exporter 暂不能推导，允许人工维护的框架标签
  tensor_ops
  layer_ops
  fused_ops

bootstrap_manual:          # 仅 exporter 未完成前的过渡字段，后续由 extracted JSON 取代
  cute.params_symbol
  cute.instances
  soc.core/bus/cache
  trace_capability
```

Chipyard exporter 输出的 `chipyard_config.extracted.json` 承担结构事实：

```text
cute:
  params_symbol
  params                 # CuteParams 展开后的关键参数
  instances
  datatypes
  instructions
soc:
  core
  bus
  cache
  vector                 # 具体 mixin、vLen/dLen/mLen 等 config-dependent facts
trace_capability:
    structured_trace       # bool
    d_store_data           # bool
    mem_req_rsp            # bool
    perf_counter_snapshot  # bool
```

#### 2.2 Schema 校验规则

- `version` 必填，固定为 1。
- `id` 必填，唯一。
- `class` 必填，必须是现有 Scala Config class 全名。
- `mode` 必填；长期为 `exported_from_chipyard`，Phase 0 过渡可用 `bootstrap_manual`/`existing_class`。
- `compatibility.fpe.version` 必须能解析到 `configs/cute_fpe_versions/<version>.yaml`。
- `compatibility.isa.version` 必须能解析到 `configs/cute_isa_versions/<version>.yaml`。
- `compatibility.vector.version` 必须能解析到 `configs/vector_versions/<version>.yaml`；无向量实现时写 `none`。
- `export.artifact` 和 `export.generated_headers.output_dir` 是后续生成产物路径元数据；Phase 0 checker 不要求这些文件已存在。
- `bootstrap_manual` 字段只用于 exporter 前的样板跑通；后续应删除或由 schema 限制在 legacy/bootstrap mode 下。

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
  generated_header         # 如 cutetest/include/datatype.h.generated；后续生成产物路径元数据，Phase 0 checker 不读取
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
  generated_header         # 如 cutetest/include/instruction.h.generated；后续生成产物路径元数据，Phase 0 checker 不读取
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

### Task 2.7: 定义 `vector_version.schema.json`

`VectorVersion` 用于描述软件可见的向量实现版本。`Project` 只引用 version id；具体这个 id 表示 RVV、Saturn、无向量、还是未来自定义向量实现，都在 `configs/vector_versions/*.yaml` 里展开。

```text
version                    # schema 版本，固定 1
id                         # Vector version id；none 是合法且真实的 id
description                # 说明
kind                       # none | rvv | custom
source:
  generator_path           # 如 chipyard/generators/saturn
  scala_files              # 定义向量实现/mixin 的 Scala 文件
  scala_mixins             # 启用该向量实现的 Config mixin
  docs                     # 本地文档
  tests                    # 可用于确认能力的测试或 benchmark 路径
features:
  vector_isa               # none | rvv | custom
  implementation           # none | saturn | ...
  spec                     # 如 rvv_1_0
  isa_extensions           # 如 v, zvbb
  ops                      # 软件/验证层可用的向量能力标签
  config_dependent_fields  # 由具体 Chipyard Config 决定的字段，如 vLen/dLen/mLen
  notes
```

产物：

```
configs/schemas/vector_version.schema.json
configs/vector_versions/none.yaml
configs/vector_versions/saturn_rvv.yaml
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

这个配置对应 `chipyard.CUTE2TopsSCP64Config`，是当前默认 Chipyard Config 入口。

长期推荐的薄 manifest：

```yaml
version: 1
id: cute2tops_scp64
class: chipyard.CUTE2TopsSCP64Config
source_file: chipyard/generators/chipyard/src/main/scala/config/CuteConfig.scala
mode: exported_from_chipyard

export:
  artifact: build/chipyard_configs/cute2tops_scp64/chipyard_config.extracted.json
  generated_headers:
    output_dir: build/chipyard_configs/cute2tops_scp64/generated_headers
    fingerprint: auto

compatibility:
  fpe:
    version: cute_fpe_v1
  isa:
    version: cute_isa_v1
  vector:
    version: none

capability_labels:
  tensor_ops: [matmul, conv]
  layer_ops: []
  fused_ops: []
```

Phase 0 若 exporter 尚未完成，可以临时保留 bootstrap 字段用于 target matcher：

```yaml
mode: bootstrap_manual
bootstrap_manual:
  cute:
    params_symbol: CuteParams.CUTE_2Tops_64SCP
    instances: [0]
  soc:
    core:
      kind: shuttle
      count: 1
      shuttle_tile_beat_bytes: 64
    bus:
      system_bits: 512
      memory_bits: 512
    cache:
      inclusive_kb: 512
      outer_latency_cycles: 40
      banks: 4
      cache_hash: true
      tl_monitors: false
  trace_capability:
    structured_trace: false
    d_store_data: false
    mem_req_rsp: false
    perf_counter_snapshot: true
```

bootstrap 字段来源（基于现有 Scala Config/CuteParams 约定整理；`validation.h.generated` 只作为历史参考，不作为 Phase 0 checker 输入）：
- Tensor_M=64, Tensor_N=64, Tensor_K=64
- Matrix_M=4, Matrix_N=4
- outsideDataWidth=512, VectorWidth=256
- Shuttle core, 1 core, `WithShuttleTileBeatBytes(64)`
- `WithSystemBusWidth(512)`、`WithNBitMemoryBus(512)`

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
configs/vector_versions/none.yaml
configs/vector_versions/saturn_rvv.yaml
configs/hwconfigs/cute2tops_scp64_dramsim32.yaml
configs/hwconfigs/cute4tops_scp128_dramsim48.yaml  (可选)
```

---

### Task 4: 定义 `project.schema.json`

#### 4.1 字段定义

`Project` 的 target 在 Phase 0 只承担两个职责：

- 用 `hwconfigs.include_tags/exclude_tags` 做轻量候选选择。
- 用 `requires.fpe_versions/isa_versions/vector_versions` 声明 CUTE 内部版本和向量实现版本兼容性。

当前 resolved HWConfig 已经能看到很多特征，但不都应该进入 `Project.schema`。SoC、memory、simulator、trace capability、ops、datatype/instruction 细项先不放进 Project target，避免把 schema 做成过宽的硬件查询语言。向量能力在 Project 里也只用 version id 表达：无向量依赖写 `none`，当前 Saturn RVV 路径写 `saturn_rvv`；二者都必须能解析到 `configs/vector_versions/<id>.yaml`。

当前两个 HWConfig 解析后已有这些特征，供后续讨论 `hwconfigs` 选择策略：

| 维度 | 来源 | 当前样例 |
|---|---|---|
| HWConfig identity | `configs/hwconfigs/*.yaml` | `cute2tops_scp64_dramsim32`, `cute4tops_scp128_dramsim48` |
| tags | `HWConfig.tags` | `cute_tensor_v1`, `shuttle`, `small` / `medium` |
| ChipyardConfig entry | `HWConfig.chipyard_config` + `configs/chipyard_configs/*.yaml` | `cute2tops_scp64`, `cute4tops_scp128` |
| CuteParams | Chipyard exporter；Phase 0 bootstrap 可来自 `bootstrap_manual.cute.params_symbol` | `CuteParams.CUTE_2Tops_64SCP`, `CuteParams.CUTE_4Tops_128SCP` |
| FPE version | `ChipyardConfig.compatibility.fpe.version` | `cute_fpe_v1` |
| ISA version | `ChipyardConfig.compatibility.isa.version` | `cute_isa_v1` |
| vector version | `ChipyardConfig.compatibility.vector.version` + `configs/vector_versions/*.yaml` | `none` / `saturn_rvv` |
| ops | `ChipyardConfig.capability_labels`；后续可由 exporter/capability JSON 取代 | `tensor_ops: [matmul, conv]` |
| SoC | Chipyard exporter；Phase 0 bootstrap 可来自 `bootstrap_manual.soc` | `shuttle x1`, `system_bits=512`, `memory_bits=512` |
| memory | `HWConfig.memory` | `dramsim2_ini_32GB_per_s`, `dramsim2_ini_48GB_per_s` |
| simulator | `HWConfig.simulator` | `verilator`, `max_cycles=800000000` |
| trace capability | Chipyard exporter；Phase 0 bootstrap 可来自 `bootstrap_manual.trace_capability` | `perf_counter_snapshot=true`, other trace switches false |

后续可能需要重新设计 `hwconfigs` selector，比如是否按 family、size、memory preset、sim backend 或 explicit name 选择。Phase 0 先只保留 tag include/exclude。

```text
version                    # schema 版本，固定 1
id                         # 全局唯一 project id (如 tensor.matmul)
name                       # 显示名 (如 matmul)
kind                       # base_test | tensor_test | layer_test | fuse_layer_test | soc_opt_test | model_test
version_name               # 人工维护的语义版本 (如 v0.3)

target:
  hwconfigs:
    include_tags           # 可选，HWConfig.tags allow-list
    exclude_tags           # 可选，HWConfig.tags deny-list
  requires:
    fpe_versions           # 可选，允许的 CUTEFPEVersion id
    isa_versions           # 可选，允许的 CUTEISAVersion id
    vector_versions        # 可选，允许的向量实现版本；无向量依赖写 none

code:
  entry                    # 主 C 文件路径 (相对于 project 目录)
  build                    # make | cmake | custom:<cmd>
  runtime_lib              # 依赖的 runtime lib project id
  op_lib                   # 依赖的 op lib project id
  op_libs                  # 可选，多个 op lib 依赖
  variants                 # list of variant objects
    - name                 # variant 唯一标识
      description
      params               # 编译/运行参数；不再在 variant 顶层自由加键
      target:
        hwconfigs          # 可选，variant 级 tag 过滤，与 project target 取交集
        requires           # 可选，variant 级 FPE/ISA/vector version 约束

golden:
  level                    # event | store_tensor | tensor_op | layer | fused_layer | model
  source                   # python_reference | c_reference | existing_checker | external
  compare:
    mode                   # exact | tolerance | semantic
    abs_err                # float (tolerance mode)
    rel_err                # float (tolerance mode)

trace:
  required_func_level      # 占位 level 名称
  required_perf_level      # 可选，占位 level 名称
  default_filters          # 占位 filter 名称 list
  required_events          # 可选，占位 event 名称 list
```

#### 4.2 Schema 校验规则

- `version` 必填，固定为 1。
- `id` 必填，全局唯一。
- `kind` 必填，枚举六种。
- `target.hwconfigs` 和 `target.requires` 必填，但内部字段可为空；空 `include_tags` 表示不按 tag 纳入，需要工具策略决定默认候选集合。
- `target.hwconfigs.exclude_tags` 优先级高于 `include_tags`。
- `target.requires.fpe_versions`、`target.requires.isa_versions` 匹配 resolved version id。
- `target.requires.vector_versions` 使用专门的 vector version id 规则：`none` 是显式合法值，其他版本名遵循普通 config id 格式，如 `saturn_rvv`。
- `target.requires.vector_versions[*]` 必须能解析到 `configs/vector_versions/<id>.yaml`；`none` 也通过 `configs/vector_versions/none.yaml` 解析。
- `code.entry` 必填。
- `code.variants` 必填，可为空；variant 参数必须放在 `params` 下。
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
  requires:
    fpe_versions: [cute_fpe_v1]
    isa_versions: [cute_isa_v1]
    vector_versions: [none]

code:
  entry: tests/rocc_hello.c
  build: make
  runtime_lib: null
  op_lib: null
  variants:
    - name: rocc_hello
      description: "Minimal RoCC/CUTE hello - query busy, print fingerprint"
      params: {}

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
  requires:
    fpe_versions: [cute_fpe_v1]
    isa_versions: [cute_isa_v1]
    vector_versions: [none]

code:
  entry: src/main.c
  build: make
  runtime_lib: runtime.cute_runtime
  op_lib: null
  variants:
    - name: i8_128
      params:
        M: 128
        N: 128
        K: 128
        dtype: i8i8i32
        bias_type: zero
    - name: i8_64
      params:
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

#### 7.1 Phase 0 边界

`cute-check-config.py` 是 Phase 0 的极简静态检查工具，不做编译、运行、Chipyard elaboration、Verilog 生成、header 生成或 Scala Config 实例化 dump。

Phase 0 的输入真相源只包括：

```text
1. 人工维护 manifests:
   configs/chipyard_configs/*.yaml
   configs/cute_fpe_versions/*.yaml
   configs/cute_isa_versions/*.yaml
   configs/vector_versions/*.yaml
   configs/hwconfigs/*.yaml
   cute-sdk/**/project.yaml
   configs/trace_filters/*.yaml

2. JSON Schema:
   configs/schemas/*.schema.json

3. 静态 Scala 源码文本:
   ChipyardConfig.source_file 指向的 CuteConfig.scala（只做 class 存在性 sanity check）
   CUTEISAVersion.source.scala_file 指向的 CUTEParameters.scala（用于 FPE/ISA version manifest 的源码对齐）

4. 文件系统存在性:
   memory config 目录
   VectorVersion.source 中列出的本地文件/目录
   trace/format_spec.md
```

Phase 0 明确不读取、不比较、不要求存在：

```text
instruction.h.generated
datatype.h.generated
validation.h.generated
build/chipyard_configs/**
chipyard_config.extracted.json
任何由 HeaderGenerator、Chipyard elaboration 或 runner 后续流程产生的文件
```

原因：`.h.generated` 和 extracted JSON 都是后续生成流程的产物。`cute-check-config.py` 第一版只能回答“当前人工 manifest 的 schema、引用、版本标签和轻量源码引用是否自洽”，不能反向依赖后续 build artifact。

后续 Phase 1/独立任务可以在 Chipyard 侧复用 HeaderGenerator 的参数提取思路，生成结构化 `chipyard_config.extracted.json`，再新增强一致性检查：

```text
manifest YAML
  vs 静态 Scala source contract
  vs Chipyard 实例化后 extracted JSON
  vs generated header fingerprint
```

这部分不属于 Task 7 第一版。

#### 7.2 职责和 CLI

```text
Usage:
  tools/runner/cute-check-config.py --hwconfig <path>
    校验单个 hwconfig yaml 是否符合 schema，
    并检查 chipyard_config 引用和 memory config 目录是否存在

  tools/runner/cute-check-config.py --chipyard-config <path>
    校验单个 chipyard_config yaml 是否符合 schema，
    并检查 id/class/source_file、compatibility 版本引用和 export 路径声明

  tools/runner/cute-check-config.py --project <path>
    校验单个 project.yaml 是否符合 schema

  tools/runner/cute-check-config.py --hwconfig <path> --project <path>
    校验两者，解析 HWConfig 引用的 ChipyardConfig，
    并判断 Test.target 是否匹配 resolved HWConfig

  tools/runner/cute-check-config.py --scan
    扫描 configs/chipyard_configs/、configs/hwconfigs/ 和 cute-sdk/**/project.yaml，
    输出所有 project × variant × hwconfig 的 target 匹配矩阵
```

#### 7.3 引用解析逻辑

```text
解析步骤：
  1. 读取 HWConfig.chipyard_config = <id>
  2. 加载 configs/chipyard_configs/<id>.yaml
  3. 读取 ChipyardConfig.compatibility.fpe.version = <version>
  4. 加载 configs/cute_fpe_versions/<version>.yaml，派生并展开 resolved capability.datatypes
  5. 读取 ChipyardConfig.compatibility.isa.version = <version>
  6. 加载 configs/cute_isa_versions/<version>.yaml，派生并展开 resolved capability.instructions
  7. 读取 ChipyardConfig.compatibility.vector.version = <version>
  8. 加载 configs/vector_versions/<version>.yaml，派生并展开 resolved vector features
  9. 如果 HWConfig.memory.model = dramsim2，
     检查 configs/memconfigs/dramsim2/<config>/system.ini 等必要文件存在
  10. 形成 resolved HWConfig:
     tags 来自 HWConfig
     capability.tensor_ops/layer_ops/fused_ops 来自 ChipyardConfig.capability_labels 或 exporter capability
     generated_headers 路径来自 ChipyardConfig.export
     soc/trace_capability 长期来自 chipyard_config.extracted.json；Phase 0 bootstrap 可来自 bootstrap_manual
     capability.datatypes 来自 CUTEFPEVersion
     capability.instructions 来自 CUTEISAVersion
     compatibility.vector.version / resolved vector features 来自 VectorVersion
     memory / simulator 来自 HWConfig
```

#### 7.4 静态 Contract 检查

本阶段脚本只做静态检查，不编译、不生成 Verilog、不读取 generated headers。需要预留以下检查：

```text
ChipyardConfig manifest 检查：
  1. source_file 存在
  2. class 能在 source_file 中找到 class <Name> extends Config（sanity check）
  3. export.artifact / generated_headers.output_dir 路径声明合法
  4. compatibility.fpe.version 能解析到 configs/cute_fpe_versions/<version>.yaml
  5. compatibility.isa.version 能解析到 configs/cute_isa_versions/<version>.yaml
  6. compatibility.vector.version 能解析到 configs/vector_versions/<version>.yaml
  7. 不用 Python 正则校验 WithCuteCoustomParams/WithCUTE/bus/core/cache；这些结构事实由后续 Chipyard exporter 输出

CUTEFPEVersion 检查：
  1. CUTEFPEVersion.datatypes 与 CUTEParameters.scala 中 ElementDataType 静态定义一致
  2. 只比较静态源码中能解析出的 datatype 名称/枚举，不比较 datatype.h.generated

CUTEISAVersion 检查：
  1. groups.cute.instructions 的 name/funct/description/return_description 集合与 CuteInstConfigs.allInsts 一致
  2. groups.ygjk.instructions 的 name/funct/description/return_description 集合与 YGJKInstConfigs.allInsts 一致
  3. groups.cute.instructions[*].rocc_funct = funct + cute_internal_offset
  4. groups.ygjk.instructions[*].rocc_funct = funct + rocc_funct_offset
  5. 不比较 instruction.h.generated；header 是后续生成流程产物

VectorVersion 检查：
  1. 文件名、id、Project.target.requires.vector_versions 引用一致
  2. none.yaml 的 kind/features 必须表示无向量实现
  3. saturn_rvv.yaml 中的 source.scala_files/source.scala_mixins 必须能在源码中找到
  4. 后续如果某个 ChipyardConfig.compatibility.vector.version != none，应由 Chipyard exporter 检查其 Config class 是否包含对应 VectorVersion.source.scala_mixins
```

#### 7.5 函数分层

第一版按下面的层次组织。这里是设计边界，不要求立即拆成多个 Python 模块；单文件实现也应保持这些职责边界。

```text
基础 IO / Schema:
  find_cute_root() -> Path
  load_yaml(path: Path) -> dict
  load_json(path: Path) -> dict
  validate_schema(doc: dict, schema_path: Path) -> list[Issue]
  resolve_manifest_path(kind: str, id: str) -> Path

Manifest 加载 / 引用展开:
  load_chipyard_config(path_or_id) -> dict
  load_fpe_version(version_id) -> dict
  load_isa_version(version_id) -> dict
  load_vector_version(version_id) -> dict
  resolve_hwconfig(hwconfig_path) -> ResolvedHWConfig

静态 Scala 文本提取:
  check_scala_class_declared(scala_file: Path, class_name: str) -> list[Issue]
  extract_scala_instruction_sets(scala_file: Path) -> dict
  extract_scala_datatypes(scala_file: Path) -> dict

Contract 检查:
  check_chipyard_config_manifest(chipyard_yaml: dict) -> list[Issue]
  check_fpe_contract(fpe_yaml: dict) -> list[Issue]
  check_isa_contract(isa_yaml: dict) -> list[Issue]
  check_vector_version_contract(vector_yaml: dict) -> list[Issue]
  check_hwconfig_references(hwconfig_yaml: dict) -> list[Issue]
  check_project_trace(project_yaml: dict) -> list[Issue]

Target 匹配:
  merge_variant_target(project_target: dict, variant_target: dict | None) -> dict
  match_project_variant(project: dict, variant: dict, resolved_hw: ResolvedHWConfig) -> MatchResult

CLI 编排:
  check_chipyard_config_cli(path: Path) -> int
  check_hwconfig_cli(path: Path) -> int
  check_project_cli(path: Path) -> int
  check_hw_project_cli(hw_path: Path, project_path: Path) -> int
  scan_cli() -> int
  main() -> int
```

不设置 `extract_header_instruction_functs()`、`extract_header_datatypes()`、`extract_chipyard_config_contract()` 或 `dump_chipyard_config_json()`。这些属于后续生成/强一致性阶段。

#### 7.6 调用关系

```text
--chipyard-config <path>
  load_yaml
  validate_schema(chipyard_config.schema.json)
  check_chipyard_config_manifest
    -> check_scala_class_declared
    -> load/check referenced FPE/ISA/Vector manifests

--hwconfig <path>
  load_yaml
  validate_schema(hwconfig.schema.json)
  check_hwconfig_references
  resolve_hwconfig
    -> load_chipyard_config
    -> load_fpe_version
    -> load_isa_version
    -> load_vector_version
  check_chipyard_config_manifest
  check_fpe_contract
    -> extract_scala_datatypes
  check_isa_contract
    -> extract_scala_instruction_sets
  check_vector_version_contract

--project <path>
  load_yaml
  validate_schema(project.schema.json)
  check_project_trace
    -> trace/format_spec.md
    -> configs/trace_filters/*.yaml

--hwconfig <path> --project <path>
  run --hwconfig checks
  run --project checks
  resolve_hwconfig
  for each project.code.variants[*]:
    merge_variant_target
    match_project_variant

--scan
  scan configs/hwconfigs/*.yaml
  scan cute-sdk/**/project.yaml
  for each hwconfig:
    resolve_hwconfig once
  for each project variant × resolved hwconfig:
    match_project_variant
```

#### 7.7 Target 匹配逻辑

```text
匹配条件（全部满足才为 MATCH）：
  1. 用 project.target.hwconfigs.include_tags/exclude_tags 选择 HWConfig 候选：
     - include_tags 为空时，默认候选集合暂由工具策略决定
     - include_tags 非空时，HWConfig.tags 命中任一 include_tags 即纳入
     - HWConfig.tags 命中任一 exclude_tags 即排除
  2. 对每个 variant，合并 project.target.requires 与 variant.target.requires
  3. CUTE/Vector 版本要求：
     - resolved compatibility.fpe.version ∈ requires.fpe_versions
     - resolved compatibility.isa.version ∈ requires.isa_versions
     - resolved ChipyardConfig.compatibility.vector.version ∈ requires.vector_versions；没有向量支持或依赖时为 none

输出:
  MATCH            — 全部满足
  HW_TAG_MISS      — include_tags/exclude_tags 不满足
  FPE_VERSION_MISS — FPE version 不满足
  ISA_VERSION_MISS — ISA version 不满足
  VECTOR_VERSION_MISS — vector version 不满足
```

#### 7.8 Trace Level 检查

读取 `trace/format_spec.md` 中定义的占位 level 名称集合，检查 `project.trace.required_func_level` 和 `project.trace.required_perf_level` 是否在集合内。输出 `TRACE_LEVEL_KNOWN` 或 `TRACE_LEVEL_UNKNOWN`。

#### 7.9 依赖

- Python 3.8+
- `jsonschema` (pip)
- `pyyaml` (pip)
- 无其他外部依赖

#### 7.10 产物

```
tools/runner/cute-check-config.py
```

---

### Task 8: Trace 实现任务占位（后续专题讨论）

Task 8 暂不在本轮实现，只把 Trace 实现从 Task 7 中剥离出来，后续单独讨论 `trace/func` 和 `trace/perf` 的边界、输入格式和模型责任。

候选实现范围：

```text
trace/parser.py                 # raw/legacy trace parser
trace/filter.py                 # filter manifest 到事件筛选逻辑
trace/func/event_model.py       # F0_event
trace/func/tensor_model.py      # F1_store / F2_tensor_op
trace/func/layer_model.py       # F3_layer
trace/func/fused_model.py       # F4_fused_layer
trace/perf/timeline.py          # task/stage timeline
trace/perf/stage_model.py       # stage breakdown
trace/perf/memory_model.py      # memory bandwidth model
trace/perf/utilization.py       # utilization model
```

本阶段只要求 Task 7 的 `cute-check-config.py` 能读取 `trace/format_spec.md` 和 `configs/trace_filters/*.yaml` 做名称存在性检查；不实现 parser/filter/model。

---

## 产物总览

```text
# Schema
configs/schemas/chipyard_config.schema.json
configs/schemas/cute_fpe_version.schema.json
configs/schemas/cute_isa_version.schema.json
configs/schemas/vector_version.schema.json
configs/schemas/hwconfig.schema.json
configs/schemas/project.schema.json
configs/schemas/trace_filter.schema.json

# CUTE FPE version 样板
configs/cute_fpe_versions/cute_fpe_v1.yaml

# CUTE ISA version 样板
configs/cute_isa_versions/cute_isa_v1.yaml

# Vector version 样板
configs/vector_versions/none.yaml
configs/vector_versions/saturn_rvv.yaml

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

- [ ] `cute-check-config.py --chipyard-config configs/chipyard_configs/cute2tops_scp64.yaml` 通过 manifest/reference 校验
- [ ] `cute-check-config.py` 能解析 `compatibility.fpe.version` 并展开 datatype set
- [ ] `cute-check-config.py` 能解析 `compatibility.isa.version` 并确认 instruction set 与 `CuteInstConfigs` / `YGJKInstConfigs` 一致
- [ ] `cute-check-config.py` 能解析 `compatibility.vector.version` 并展开 VectorVersion features
- [ ] `cute-check-config.py --hwconfig configs/hwconfigs/cute2tops_scp64_dramsim32.yaml` 通过校验
- [ ] `cute-check-config.py --project cute-sdk/runtime/cute_runtime/project.yaml` 通过校验
- [ ] `cute-check-config.py --project cute-sdk/tensor_ops/matmul/project.yaml` 通过校验
- [ ] `cute-check-config.py --hwconfig <hw> --project <proj>` 输出 MATCH 且理由正确
- [ ] `cute-check-config.py --scan` 输出 project × variant × hwconfig 匹配矩阵
- [ ] `HWConfig`、薄 `ChipyardConfig` manifest、Chipyard exported JSON 和 `project.yaml` 的字段边界清楚，人工入口和自动导出字段有文档区分
- [ ] Trace level 名称（F0-F5）已作为占位冻结，但具体 event schema 未承诺
- [ ] 文档明确：`configs/tests` 不作为人工维护入口

---

## 后续 TODO

- Chipyard exporter：在 Chipyard/Scala 侧复用 `HeaderGenerator.extractParamsFromConfig` 的思路，导出 `build/chipyard_configs/<id>/chipyard_config.extracted.json`。该 JSON 应包含 SoC/core/bus/cache、CuteParams、datatype facts、instruction facts、vector config-dependent facts、trace capability 和 fingerprint。完成后，`configs/chipyard_configs/*.yaml` 应瘦身为 `id/class/source_file/export/compatibility/capability_labels`，不再手写结构字段。
- 高级模板/模版编程：后续在 `cute-sdk/templates/` 和 tensor/runtime lib 稳定后，评估引入更强的模板机制，用于生成重复的 test driver、datatype/layout dispatch、variant 专用代码和 tensor/layer op wrapper。Phase 0 先不把它放进 `project.schema.json`；当前 `project.yaml` 只描述 `code.entry/build/variants`，未来如确有需要再讨论 `code.template`、`code.generator` 或模板参数 schema。

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
| project.yaml 过于自由 | schema 约束最小必填字段；variant 参数统一放入 `params`，只有 `params` 内允许自由键值 |
| HWConfig 字段与 CUTEParameters 不对齐 | HWConfig 不承载 CUTE 参数；薄 `ChipyardConfig` manifest 只承载 class/export/compatibility 入口；结构事实由后续 Chipyard exporter 导出；datatype set 由 `CUTEFPEVersion` 统一维护；instruction set 由 `CUTEISAVersion` 统一维护；vector feature set 由 `VectorVersion` 统一维护 |

---

## 与 Phase 1 的衔接

Phase 0 完成后，Phase 1 可以直接：

1. 读取 `configs/hwconfigs/cute2tops_scp64_dramsim32.yaml` 中的 `chipyard_config`，解析到 `configs/chipyard_configs/cute2tops_scp64.yaml`。
2. 使用 `ChipyardConfig.class` 调用 `generate-headers.sh` / Chipyard exporter，生成 headers 和 `chipyard_config.extracted.json`。
3. 读取 `cute-sdk/runtime/cute_runtime/project.yaml` 知道 entry file 和 target。
4. 用 `cute-check-config.py` 确认 target match 后进入 build/run 流程。
5. 在 artifact 中保存 `hwconfig.resolved.yaml` 和 `target_match.json`。
