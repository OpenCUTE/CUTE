# CUTE 软件测试框架重构 Big Plan

> 核心目标：围绕 `HWConfig / Test / Trace` 三个一级抽象，重构 CUTE 的软件测试、trace-based verify、trace-based profile、CONFIG-driven flow。  
> 本计划用于继续讨论和细化，不是一次性全部实现的任务清单。

---

## 0. 总体抽象：HWConfig / Test / Trace

当前框架的核心对象应从原来的“配置、软件、日志”重新组织为三个一等抽象：

```text
HWConfig -> 定义测试运行在哪个具体硬件/SoC/仿真环境上
Test     -> 定义要测试什么、支持哪些 HWConfig、代码是什么、golden 是什么
Trace    -> 定义如何观察一次运行，并用功能模型/性能模型解释它
```

三者关系：

```text
RunArtifact = run(Test.code, HWConfig)

ObservedTrace = Trace.filter(RunArtifact.raw_trace)

FunctionalPass =
  Trace.func(ObservedTrace, HWConfig, Test) == Test.golden(level)

PerformanceProfile =
  Trace.perf(ObservedTrace, HWConfig, Test)

TestPass =
  HWConfig in Test.target
  AND build/run succeeds
  AND FunctionalPass
```

也就是说，一个 test 不是“能编译、能跑完”就 pass。一个 test pass 必须满足：

1. 当前 `HWConfig` 在 `Test.target` 的支持范围内。
2. `Test.code` 能在该 `HWConfig` 上构建并运行。
3. 在某个 `Trace.filter` 下得到的 trace，经过 `Trace.func` 功能模型解释后，与 `Test.golden` 对齐。

性能分析不决定 correctness pass，但它使用同一个 run artifact 和同一份 filtered trace：

```text
Correctness path: Trace.filter -> Trace.func -> Test.golden
Performance path: Trace.filter -> Trace.perf -> profile/report
```

`Trace.func` 和 `Trace.perf` 是两条基本独立的设计路线：它们共享 trace 格式、filter、artifact，但模型目标不同。`Trace.func` 追求功能等价；`Trace.perf` 追求瓶颈解释。

---

## 1. 三个一级对象的二级抽象

### 1.1 HWConfig

`HWConfig` 定义一个完整运行目标，不只是 CUTE 参数。

```text
HWConfig
├── CUTE
│   ├── tensor tile 参数
│   ├── matrix/PE/reduce 参数
│   ├── datatype / FPE / scale 参数
│   ├── instruction field / funct 定义
│   ├── memory loader / scratchpad / MMU 参数
│   └── trace capability 开关
└── SOC
    ├── Chipyard Config
    ├── core config: Rocket / BOOM / Shuttle / core count
    ├── bus config: sysbus / membus / cache / L2 width
    ├── DRAMSim config
    ├── simulator config: Verilator / VCS / FPGA
    └── platform config: baremetal / workload loader / max cycles
```

`HWConfig` 的职责：

- 固定一台具体 CUTE 硬件实体。
- 固定它所在的 SoC、内存、总线、仿真环境。
- 导出软件可见的 capability。
- 决定哪些 `Test.target` 可以匹配它。
- 为 `Trace.func` 和 `Trace.perf` 提供解释上下文。

### 1.2 Test

`Test` 是测试实体，包含目标范围、代码和 golden。

```text
Test
├── target
│   ├── 支持哪些 HWConfig
│   ├── 需要哪些 CUTE capability
│   ├── 需要哪些 SOC capability
│   ├── 是否允许 DRAMSim preset sweep
│   └── 是否允许 simulator / FPGA / multi-core 变体
├── code
│   ├── C source
│   ├── template source
│   ├── runtime lib dependency
│   ├── tensor op lib dependency
│   ├── layer op lib dependency
│   ├── fuse layer op lib dependency
│   └── opt op lib dependency
└── golden
    ├── level
    ├── source: python / C reference / existing checker / external
    ├── compare rule: exact / tolerance / semantic
    └── required Trace.func level
```

`Test` 的职责：

- 定义“测什么”。
- 声明“在哪些 HWConfig 上可测”。
- 携带或生成实质代码。
- 定义 golden 的语义层级。
- 声明需要 `Trace.func` 支持到哪一级，才能判断 pass。

### 1.3 Trace

`Trace` 是观察和解释运行事实的实体。

```text
Trace
├── raw trace
│   ├── RTL printf
│   ├── structured CUTE_TRACE
│   ├── UART/debug log
│   ├── memory/store trace
│   └── counter snapshot
├── filter
│   ├── event filter
│   ├── module filter
│   ├── task/layer/tile filter
│   ├── time window filter
│   └── trace level filter
├── func model
│   ├── event order model
│   ├── tensor reconstruction model
│   ├── operator functional model
│   ├── layer functional model
│   └── fused/model semantic model
└── perf model
    ├── task timeline model
    ├── stage breakdown model
    ├── memory bandwidth model
    ├── utilization model
    ├── stall/bottleneck model
    └── regression/baseline model
```

`Trace` 的职责：

- 从 run artifact 中提取事实。
- 用 filter 控制观察范围。
- 用 func model 支撑 correctness。
- 用 perf model 支撑 profile。
- 让 verify 和 profile 使用同一份事实，但保持两条建模路线独立。

---

## 2. HWConfig 规划

本章推进 `HWConfig` 抽象，使它成为硬件、SoC、内存、仿真环境和软件 capability 的统一入口。

### 2.1 HWConfig 不等于 CUTE Config

当前已有 `HeaderGenerator` 能从 Chipyard Config 提取 `CuteParams`。为了避免在 HWConfig 中手抄 SoC/core/bus 字段，配置拆成两层：

建议区分：

| 层级 | 示例 | 作用 |
|---|---|---|
| `ChipyardConfig.CUTE` | `Tensor_M/N/K`、`ReduceWidthByte`、FPE、scale layout、instruction field | 决定 CUTE 本体 capability |
| `ChipyardConfig.SOC` | `chipyard.CUTE2TopsSCP64Config`、core、bus、cache | 决定 SoC 集成形态和软件可见能力 |
| `HWConfig.memory` | `dramsim2_ini_32GB_per_s` | 决定 memory model 配置 |
| `HWConfig.simulator` | Verilator binary、max cycles、wave/trace mode | 决定 run policy |

### 2.2 ChipyardConfig / HWConfig Manifest

建议新增：

```text
configs/chipyard_configs/
├── cute2tops_scp64.yaml
└── cute4tops_scp128.yaml
configs/hwconfigs/
├── cute2tops_scp64_dramsim32.yaml
├── cute4tops_scp128_dramsim48.yaml
└── cute4tops_shuttle512_dramsim48.yaml
configs/memconfigs/dramsim2/
├── dramsim2_ini_32GB_per_s/
└── dramsim2_ini_48GB_per_s/
```

ChipyardConfig 示例：

```yaml
version: 1
id: cute2tops_scp64
class: chipyard.CUTE2TopsSCP64Config
source_file: chipyard/generators/chipyard/src/main/scala/config/CuteConfig.scala
mode: existing_class

cute:
  params_symbol: CuteParams.CUTE_2Tops_64SCP
  instances: [0]
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
  datatypes: [i8i8i32, fp16fp16fp32, mxfp8e4m3, nvfp4]
  tensor_ops: [matmul]
  layer_ops: []
  fused_ops: []
```

HWConfig 示例：

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

### 2.3 Generated Headers 与 Capability 导出

现有生成链路保留：

```text
Chipyard Config
  -> HeaderGenerator.extractParamsFromConfig
  -> ChipyardConfig.generated_headers/*.generated
```

需要增强为：

```text
ChipyardConfig
  -> generated C headers under this ChipyardConfig
  -> generated capability json
  -> generated software constraints
```

建议生成：

```text
build/chipyard_configs/<chipyard-config-id>/
├── chipyard_config.resolved.yaml
├── cute_params.json
├── capability.json
├── header_fingerprint.txt
└── generated_headers/
    ├── datatype.h.generated
    ├── validation.h.generated
    ├── instruction.h.generated
    ├── cute_config.h.generated
    └── cute_layout.h.generated
```

`generated_headers` 应被视为 `ChipyardConfig` 的固化产物，而不是 `Test` 或 `cute-sdk/runtime` 的全局状态。`Test.code` 编译时只通过 include path 引用当前匹配 `HWConfig` 解析出的 `ChipyardConfig` headers：

```text
build(Test.code, HWConfig):
  -I cute-sdk/include
  -I build/chipyard_configs/<chipyard-config-id>/generated_headers
```

这样可以避免“用 A 配置生成的 header 编译，却在 B 配置 simulator 上运行”的隐式错配。`cute-sdk/include` 只放稳定 runtime wrapper 和手写公共头；`.generated` 文件默认不再作为全局共享输入。

`capability.json` 要服务 `Test.target` 匹配：

```json
{
  "hwconfig": "cute2tops_scp64_dramsim32",
  "cute": {
    "tensor_m": 64,
    "tensor_n": 64,
    "tensor_k": 64,
    "datatypes": ["i8i8i32", "fp16fp16fp32"],
    "trace_events": ["TASK", "D_STORE_DATA", "MEM_REQ_RSP"]
  },
  "soc": {
    "core": "rocket",
    "memory_model": "dramsim2",
    "memory_config": "dramsim2_ini_32GB_per_s",
    "sysbus_width": 64,
    "membus_width": 64
  }
}
```

### 2.4 HWConfig 成熟标准

短期：

- 能从一个 `HWConfig` manifest 生成 C headers。
- 能保存 resolved config 和 fingerprint。
- 能判断一个 test target 是否支持该 HWConfig。

中期：

- 能表达 CUTE + SoC + DRAMSim + simulator 的组合。
- 能支持多 HWConfig sweep。
- 能为 trace perf model 提供理论峰值、bus width、memory preset 等上下文。

长期：

- 新增硬件配置后，不需要手改 C 测试常量。
- `HWConfig` 成为 test target、build、run、verify、perf 的共同入口。

---

## 3. Test 规划

本章推进 `Test` 抽象。Test 不是单个 C 文件，而是 `target + code + golden` 的组合。Test 层级越高，依赖的 runtime/lib 越多，target 范围越窄。

### 3.1 Test Pass 定义

一个 test 的最小语义由 `cute-sdk/**/project.yaml` 描述。也就是说，Test 的第一抽象不是 `configs/tests/*.yaml`，而是 code project 自己的 `project.yaml`：

```yaml
version: 1
id: tensor.matmul
name: matmul
kind: tensor_test
version_name: v0.3

target:
  hwconfigs:
    include_tags: [cute_tensor_v1]
  required_capability:
    datatypes: [i8i8i32]
    tensor_ops: [matmul]
    trace_func_level: tensor_store

code:
  entry: src/main.c
  build: make
  runtime_lib: runtime_v1
  op_lib: tensor_op_v1
  variants:
    - name: i8_128
      M: 128
      N: 128
      K: 128
      dtype: i8i8i32
    - name: fp16_128
      M: 128
      N: 128
      K: 128
      dtype: fp16fp16fp32

golden:
  level: tensor_op
  source: python_reference
  compare:
    mode: exact
```

Pass 规则：

```text
HWConfig matches Test.target
AND build(Test.code, HWConfig) succeeds
AND run(Test.code, HWConfig) succeeds
AND Trace.func(Trace.filter(raw_trace), HWConfig, Test) == Test.golden
```

### 3.2 Test 层级和 Lib 成长路线

Test 不只是验证用例，它会沉淀软件库。建议按以下路线演进：

```text
BaseTest
  -> runtime lib

TensorTest
  -> tensor config wrapper
  -> tensor op lib

LayerTest
  -> vector task composition
  -> layer op lib

FuseLayerTest
  -> fused layer scheduling
  -> fuse_layer op lib

SOCOptTest
  -> soc-specific optimization
  -> opt_op_lib

ModelTest
  -> model-level validation/profile
```

对应关系：

| Test 层级 | 目标 | 产出的软件库 | target 范围 |
|---|---|---|---|
| `BaseTest` | 验证最基础 RoCC/CUTE 通信、query、启动、结束、trace 基础事件 | `runtime lib` | 最宽，几乎所有 HWConfig |
| `TensorTest` | 验证 tensor config、layout、stride、matmul/conv 等基础 tensor op | `tensor op lib` | 需要支持对应 tensor capability |
| `LayerTest` | 验证 NN layer 由 tensor op + vector task 组合的语义 | `layer op lib` | 需要支持 tensor op、vector task、layer 所需 dtype/layout |
| `FuseLayerTest` | 验证多 layer 或 layer 内融合、减少中间读写 | `fuse_layer op lib` | 更窄，依赖融合路径和 trace.func 支持 |
| `SOCOptTest` | 针对特定 SoC、DRAM、core、bus 做足量优化 | `opt_op_lib` | 很窄，通常绑定少数 HWConfig |
| `ModelTest` | 验证完整模型或模型片段的 correctness/profile | model runner / benchmark | 最窄，通常绑定特定 HWConfig 族 |

这个结构的关键点：

- `BaseTest` 先稳定，才能沉淀可靠 runtime lib。
- `TensorTest` 不应该直接绕过 runtime lib，而是在 runtime 上包装 tensor config。
- `LayerTest` 不能只是更大的 C 文件，而应该复用 tensor op lib 并叠加 vector task。
- `FuseLayerTest` 是新的语义层，不应该和普通 layer test 混在一起。
- `SOCOptTest` 的 target 本来就很窄，不应该强行要求所有 HWConfig 都支持。
- `ModelTest` 应尽量复用下层 lib，而不是复制所有实现。

### 3.3 Target 范围逐层变窄

从下到上，test 的 target 服务范围不断变小：

```text
BaseTest target:
  all HWConfig with minimal CUTE runtime capability

TensorTest target:
  HWConfig with required tensor shape/datatype/layout capability

LayerTest target:
  HWConfig with required tensor op + vector task + memory capacity

FuseLayerTest target:
  HWConfig with required fusion capability + trace.func support

SOCOptTest target:
  specific SOC/core/bus/dram family

ModelTest target:
  specific model + specific HWConfig family + enough memory/perf capability
```

这会反过来指导 suite 设计：

- smoke suite 应以 `BaseTest + 少量 TensorTest` 为主，target 宽。
- correctness suite 可以覆盖更多 Tensor/Layer/Fuse。
- perf suite 应明确绑定 HWConfig family。
- model suite 本来就应该窄，不要追求所有硬件都跑。

### 3.4 Golden Level 与 Trace.func Level

`Test.golden.level` 必须对应 `Trace.func` 已经完成的功能模型层级。

建议定义：

| Golden Level | 需要的 Trace.func 能力 | 适用 Test |
|---|---|---|
| `event` | 检查 task/inst/order 是否符合预期 | BaseTest |
| `store_tensor` | 从 D_STORE_DATA 重建 tensor | TensorTest |
| `tensor_op` | 将 trace 重建为 tensor op 输出并比较 golden | TensorTest |
| `layer` | 解释 vector task + tensor op 组合后的 layer 输出 | LayerTest |
| `fused_layer` | 解释融合 layer 的中间消除和最终输出 | FuseLayerTest |
| `model` | 解释完整模型或模型片段输出 | ModelTest |

如果某个 test 的 golden level 高于当前 `Trace.func` 支持级别，它不能标记为 full pass，只能标记为：

```text
RUN_OK / TRACE_OK / FUNC_MODEL_NOT_READY
```

这可以避免“代码跑了但无法验证”的测试被误判为 pass。

### 3.5 Test 与 cute-sdk/project.yaml

`cute-sdk` 是 Test 的主工作区。每一个可维护的 Test/code project 都应有自己的 `project.yaml`：

```text
cute-sdk/.../<project>/project.yaml = Test spec + code project metadata
cute-sdk/.../<project>/src/         = Test.code 实现
cute-sdk/.../<project>/golden/      = golden 或 golden generator
cute-sdk/.../<project>/data/        = 输入数据或数据生成脚本
```

也就是说，一个可运行 Test 不再拆成 `configs/tests/*.yaml + cute-sdk project` 两个真相源，而是由 code project 自己描述：

```text
Test
└── code_project: cute-sdk/<level-or-lib>/<project-name>/
    ├── project.yaml        # Test 的主描述：target/code/golden/trace requirement
    ├── src/
    ├── include/
    ├── data/
    ├── golden/
    └── build_rules/
```

`project.yaml` 是测试的“身份证/规格书”，同时贴着代码放，方便人手工维护。Runner 扫描 `cute-sdk/**/project.yaml`，选择匹配 `HWConfig` 的 project 和 variant，再进入该 project 构建。

示例：

```yaml
id: tensor.matmul
name: matmul
version: 0.3
kind: tensor_test

target:
  required_capability:
    datatypes: [i8i8i32]
    tensor_ops: [matmul]
    trace_func_level: tensor_op

code:
  entry: src/main.c
  build: make
  variants:
    - name: i8_128
      dtype: i8i8i32
      M: 128
      N: 128
      K: 128
    - name: fp16_128
      dtype: fp16fp16fp32
      M: 128
      N: 128
      K: 128

golden:
  level: tensor_op
  source: python_reference
```

一个 code project 可以包含多个 variant，它们共同属于同一个 Test project：

```text
cute-sdk/tensor_ops/matmul/
├── project.yaml
├── src/main.c
└── variants:
    ├── i8_128
    ├── fp16_128
    └── k_sweep
```

第一阶段建议采用“一 project 一个主 Test，project 内多个 variants”。这比维护大量 `configs/tests/*.yaml` 更容易人工管理。后续如果确实需要细分，也应优先在 `project.yaml` 里组织，而不是重新引入一堆分散 test yaml。

Test 的版本迭代不只是代码变更，也包括 target 和 trace 能力的扩展：

```text
Test.version =
  Test.target coverage
  + Test.code maturity
  + Test.golden level
  + required Trace.func level
```

例如同一个 `matmul_i8_128` test 可以这样成熟：

```text
v0.1: 只支持一个 HWConfig，只检查 RUN_OK
v0.2: 支持 F0_event，能验证 task/inst 顺序
v0.3: 支持 F1_store/F2_tensor_op，能重建 D tensor 并比较 golden
v0.4: 扩展更多 HWConfig target
v0.5: 支持 perf filter/profile，但 correctness pass 仍由 Trace.func 决定
```

因此，`cute-sdk` 不是单纯“测试文件堆放目录”，而是 `Test project workspace`。它里面的 project 会随着 `project.yaml` 一起迭代，并逐层沉淀出 runtime lib、tensor op lib、layer op lib、fuse layer op lib、opt op lib。

```text
cute-sdk/
├── runtime/
│   └── cute_runtime/
│       ├── project.yaml
│       ├── include/
│       ├── src/
│       └── tests/
├── tensor_ops/
│   └── matmul/
│       ├── project.yaml
│       ├── src/
│       ├── include/
│       ├── data/
│       ├── golden/
│       └── build_rules/
├── layer_ops/
│   └── llama_ffn/
│       ├── project.yaml
│       ├── src/
│       ├── include/
│       ├── data/
│       └── golden/
├── fuse_layer_ops/
│   └── llama_ffn_fused/
├── opt_ops/
│   └── shuttle512_dram48/
├── model_tests/
│   └── llama3_1b/
├── templates/
└── legacy/
```

---

## 4. Trace 规划（待定，后续专题展开）

本章暂时只确定 `Trace` 的边界，不在本版 plan 中细化设计。Trace 设计会很大，需要后续单独讨论。

当前只保留三个判断：

1. `Trace` 是一级抽象，和 `HWConfig`、`Test` 并列。
2. `Trace` 至少包含 `filter`、`func model`、`perf model` 三个二级抽象。
3. `Trace.func` 和 `Trace.perf` 是两条基本独立的设计路线：它们共享 raw trace、parser、filter 和 artifact，但不能混成一个 analyzer。

暂定结构：

```text
Trace
├── raw trace
├── filter          # 待定：如何选择 event/module/task/tile/time/payload
├── func model      # 待定：如何从 trace 重建功能语义并对齐 Test.golden
└── perf model      # 待定：如何从 trace 解释性能、瓶颈、利用率
```

### 4.1 Trace.filter（待定）

待后续专题明确：

- filter 的配置格式。
- func/perf/debug 是否使用不同 filter。
- 是否按 event、module、task、layer、tile、cycle window、payload 控制。
- filter 结果是否保存为独立 artifact。

### 4.2 Trace.func（待定）

待后续专题明确：

- func model 的 level 如何定义。
- `Test.golden.level` 如何映射到 `Trace.func` 能力。
- BaseTest/TensorTest/LayerTest/FuseLayerTest/ModelTest 分别需要哪些 functional trace。
- `D_STORE_DATA` 是否作为 TensorTest 的第一个强制 trace 事件。

### 4.3 Trace.perf（待定）

待后续专题明确：

- perf model 的 level 如何定义。
- top-down profile 的 stage、memory、utilization、bottleneck 口径。
- perf trace 与 func trace 是否使用不同 payload 策略。
- baseline/regression 如何保存和比较。

本版 plan 后续章节如果提到 `Trace.func`、`Trace.perf`、`Trace.filter`，都只表示接口占位，不表示具体 trace schema 已经定稿。

---

## 5. Runner 与 Artifact

Runner 和 Artifact 不是新的一级抽象，它们是工程执行层的两个概念：

```text
Runner  = 负责“怎么把 HWConfig + Test + TracePolicy 跑起来”的执行编排器
Artifact = 负责“这一次到底跑了什么、产生了什么证据”的结果快照目录
```

换句话说：

- `HWConfig / Test / Trace` 是框架的核心对象。
- `Runner` 是动作流程，类似一个自动化实验员。
- `Artifact` 是实验记录，类似一次实验的完整证据包。

Runner 不定义测试语义，也不定义硬件语义；它只做编排：

```text
给定 HWConfig + cute-sdk project + variant + Trace.filter
  -> 检查 target 是否匹配
  -> 解析 HWConfig.chipyard_config
  -> 准备 ChipyardConfig.generated_headers
  -> 编译 Test.code
  -> 选择 simulator
  -> 运行
  -> 收集 raw trace/log
  -> 调用 Trace.filter / Trace.func / Trace.perf
  -> 保存 Artifact
```

Artifact 的意义是让一次 run 可复盘、可比较、可 debug：

```text
没有 Artifact:
  只知道“刚才好像跑过一个测试”，但不知道用的哪个 config/header/binary/log。

有 Artifact:
  能准确回答“这个 pass/fail/perf 数字是由哪个 HWConfig、哪个 Test、哪份代码、哪份 trace 得到的”。
```

因此，Runner 是“执行者”，Artifact 是“证据包”。它们服务三大抽象，但不替代三大抽象。

### 5.1 Runner 状态机

Runner 的状态机可以先理解为一条自动化流水线：

```text
RESOLVE_HWCONFIG
  -> RESOLVE_TEST_TARGET
  -> GENERATE_HEADERS
  -> BUILD_TEST_CODE
  -> SELECT_OR_BUILD_SIMULATOR
  -> RUN
  -> PARSE_TRACE
  -> APPLY_TRACE_FILTER
  -> TRACE_FUNC_VERIFY
  -> TRACE_PERF_PROFILE
  -> REPORT
```

每一步的含义：

| 阶段 | 做什么 | 对应对象 |
|---|---|---|
| `RESOLVE_HWCONFIG` | 解析 HWConfig，生成 resolved config、capability、headers | `HWConfig` |
| `RESOLVE_TEST_TARGET` | 判断 Test.target 是否支持当前 HWConfig | `HWConfig + Test` |
| `GENERATE_HEADERS` | 生成或复用该 HWConfig 的 generated headers | `HWConfig` |
| `BUILD_TEST_CODE` | 用该 HWConfig 的 headers 编译 Test.code | `Test + HWConfig` |
| `SELECT_OR_BUILD_SIMULATOR` | 找到或生成对应 simulator | `HWConfig.SOC` |
| `RUN` | 运行二进制，产生 raw log/trace | `HWConfig + Test` |
| `PARSE_TRACE` | 从 raw log/trace 中提取结构化 trace | `Trace` |
| `APPLY_TRACE_FILTER` | 选择 func/perf/debug 需要的 trace 子集 | `Trace.filter` |
| `TRACE_FUNC_VERIFY` | 用功能模型对齐 Test.golden | `Trace.func + Test.golden` |
| `TRACE_PERF_PROFILE` | 用性能模型生成 profile | `Trace.perf + HWConfig` |
| `REPORT` | 汇总状态、verify、perf、路径 | Artifact |

### 5.2 Run Artifact

一次 run 的 artifact 必须能回答：

- 用了哪个 `HWConfig`。
- 跑了哪个 `Test`。
- `Test.target` 为什么匹配这个 `HWConfig`。
- 实际编译的 code 是什么。
- raw trace 是什么。
- filter 后 trace 是什么。
- `Trace.func` 结果是什么。
- `Trace.perf` 结果是什么。

Artifact 建议满足两个原则：

1. **不可变**：一个 run-id 目录生成后不再原地覆盖。新的运行产生新的 run-id。
2. **自解释**：只看 artifact 目录，就能知道这次 run 的输入、过程、输出和判断依据。

建议目录：

```text
build/cute-runs/<run-id>/
├── hwconfig/
│   ├── hwconfig.resolved.yaml
│   ├── chipyard_config.resolved.yaml
│   ├── capability.json
│   ├── header_fingerprint.txt
│   └── generated_headers/
│       ├── datatype.h.generated
│       ├── validation.h.generated
│       ├── instruction.h.generated
│       ├── cute_config.h.generated
│       └── cute_layout.h.generated
├── test/
│   ├── project.resolved.yaml
│   ├── target_match.json
│   ├── code/
│   │   ├── test.c
│   │   ├── test.riscv
│   │   └── test.dump
│   └── golden/
│       ├── golden.npy
│       └── golden.meta.json
├── run/
│   ├── simulator.cmd.txt
│   ├── uart.log
│   ├── debug.out
│   └── raw.log
├── trace/
│   ├── raw.trace
│   ├── events.jsonl
│   ├── filter.func.yaml
│   ├── filtered.func.jsonl
│   ├── filter.perf.yaml
│   └── filtered.perf.jsonl
├── func/
│   ├── actual.npy
│   ├── mismatch.csv
│   └── verify.json
├── perf/
│   ├── perf.json
│   ├── topdown.md
│   └── timeline.csv
├── status.json
└── report.md
```

### 5.3 CLI 建议

第一阶段可先用 scripts，成熟后转为 `tools/cutecli`：

```text
tools/runner/cute-run.py --hw configs/hwconfigs/cute2tops_scp64_dramsim32.yaml --project cute-sdk/tensor_ops/matmul --variant i8_128
tools/runner/cute-verify.py --artifact build/cute-runs/<run-id>
tools/runner/cute-perf.py --artifact build/cute-runs/<run-id>
tools/runner/cute-suite.py --suite configs/suites/smoke.yaml
```

---

## 6. 目录与模块建议

目录要服务三个对象，而不是按“脚本随手放哪里”组织。

```text
CUTE/
├── cute-sdk/                          # 目标板软件栈（C，编译为 .riscv）
│   ├── include/                       # 公共头文件
│   │   ├── ygjk.h                     # 底层 inline asm（保留）
│   │   ├── cute_runtime.h             # Runtime lib API
│   │   ├── cute_tensor.h              # Tensor 描述符
│   │   ├── cute_ops.h                 # Tensor op 封装
│   │   ├── cute_layer.h               # Layer op 封装
│   │   └── cute_fuse_layer.h          # Fuse layer op 封装
│   ├── runtime/                       # Runtime lib project
│   ├── tensor_ops/                    # Tensor op projects
│   ├── layer_ops/                     # Layer op projects
│   ├── fuse_layer_ops/                # Fuse layer op projects
│   ├── opt_ops/                       # SOC-specific opt projects
│   ├── model_tests/                   # Model test projects
│   ├── templates/                     # C 代码模板
│   └── legacy/                        # 旧测试（逐步迁移）
│
├── tools/                             # Host 端工具链（Python）
│   ├── trace/                         # Trace parser + func/perf model
│   │   ├── format_spec.md
│   │   ├── func/
│   │   │   ├── event_model.py         # F0_event
│   │   │   ├── tensor_model.py        # F1_store / F2_tensor_op
│   │   │   ├── layer_model.py         # F3_layer
│   │   │   └── fused_model.py         # F4_fused_layer
│   │   └── perf/
│   │       ├── timeline.py            # 时间线模型
│   │       ├── stage_model.py         # Stage 分解
│   │       ├── memory_model.py        # 带宽模型
│   │       └── utilization.py         # 利用率模型
│   ├── verify/                        # Golden 生成 + 比对
│   │   ├── cute_golden.py             # Golden 参考生成引擎
│   │   ├── cute_verify.py             # 数值比对引擎
│   │   └── cute_trace_golden.py       # 从 trace 提取 D tensor
│   ├── perf/                          # Top-Down + Roofline
│   │   ├── cute_perf_analyzer.py      # Top-Down 分析引擎
│   │   ├── cute_perf_model.py         # Roofline 模型
│   │   └── cute_perf_report.py        # 报告生成器
│   └── runner/                        # Runner + CLI
│       ├── cute-run.py                # 主 Runner
│       ├── cute-check-config.py       # 静态配置检查
│       ├── cute-gen-headers.py        # Header 生成
│       ├── cute-gen-golden.py         # Golden 生成
│       ├── cute-perf.py               # 性能分析 CLI
│       └── cute-model-report.py       # 模型级报告
│
├── configs/                           # 配置和 schema
│   ├── hwconfigs/                     # HWConfig manifests
│   │   ├── cute2tops_scp64_dramsim32.yaml
│   │   └── schemas/
│   ├── trace_filters/                 # 可复用 Trace filter
│   ├── suites/                        # 测试 suite 定义
│   └── schemas/                       # JSON Schema
│       ├── hwconfig.schema.json
│       ├── project.schema.json
│       └── trace_filter.schema.json
│
├── scripts/                           # 薄包装脚本（调用 tools/）
├── build/                             # 构建产物 + artifact
│   ├── hwconfigs/<name>/              # 生成的 headers + capability
│   ├── cute-runs/<run-id>/            # Run artifact
│   └── cute-reports/                  # 报告归档
└── plans/                             # 设计文档
```

原则：

- `cute-sdk/` 只放**编译后跑在 RISC-V 上**的东西：C 头文件、op lib、test driver。
- `tools/` 只放**运行在 host 上**的东西：Python 脚本、trace parser、golden generator、runner。
- `configs/` 是纯声明式配置，不属于任何一侧。
- `configs/chipyard_configs` 承载 `ChipyardConfig`。
- `configs/hwconfigs` 承载 `HWConfig`。
- `cute-sdk/**/project.yaml` 承载 `Test`。
- `configs/trace_filters` 承载可复用 `Trace.filter`。
- `tools/trace/func` 与 `tools/trace/perf` 分开演进。
- `build/cute-runs` 承载三者组合后的事实快照。

---

## 7. 分阶段实施路线

### Phase 0: 冻结抽象和 schema

目标：先让 `HWConfig / Test / Trace` 都可描述。

任务：

- 定义 `hwconfig.schema.json`。
- 定义 `project.schema.json`，明确 cute-sdk project 的 `target/code/golden`。
- 定义 `trace_filter.schema.json`。
- 定义 `trace/format_spec.md`。
- 写一个 base test、一个 tensor test 的 `project.yaml`。

验收：

- 能静态判断 `Test.target` 是否匹配某个 `HWConfig`。
- 能静态判断某个 test 需要的 `Trace.func level` 是否存在。

### Phase 1: BaseTest -> runtime lib 最小闭环

目标：用 base test 跑通最小 runtime lib。

任务：

- 选择一个最小 RoCC/CUTE hello test。
- 按 HWConfig 生成 headers。
- 编译 base test。
- 运行仿真。
- 生成 raw trace。
- 用 `Trace.func F0_event` 判断基础事件正确。

验收：

- BaseTest pass。
- runtime lib 有最小可用 API。
- artifact 保存 HWConfig/Test/Trace 三类快照。

### Phase 2: TensorTest -> tensor op lib

目标：在 runtime lib 上包装 Tensor Config，形成 tensor op lib。

任务：

- 实现 tensor descriptor / tensor config wrapper。
- 实现 matmul tensor test。
- 插入或解析 `D_STORE_DATA`。
- 实现 `Trace.func F1_store/F2_tensor_op`。
- 生成 tensor-level golden。

验收：

- TensorTest pass。
- tensor op lib 可复用。
- trace 能重建 D tensor。

### Phase 3: LayerTest -> layer op lib

目标：在 tensor op lib 上叠加向量任务，形成 layer op lib。

任务：

- 选择 ResNet conv layer 或 LLaMA FFN 作为样板。
- 描述 layer test target。
- 支持 vector task trace。
- 实现 `Trace.func F3_layer`。
- 生成 layer-level golden。

验收：

- LayerTest pass。
- layer op lib 可复用。
- target 范围比 TensorTest 更窄，并能被 schema 表达。

### Phase 4: FuseLayerTest -> fuse_layer op lib

目标：在 layer op lib 上增加层融合语义。

任务：

- 选择一个融合路径，例如 FFN fused 或 attention QKV fused。
- 定义 fused layer test。
- 定义 fused trace filter。
- 实现 `Trace.func F4_fused_layer`。
- 输出 fused correctness 和 intermediate invariant。

验收：

- FuseLayerTest pass。
- fuse_layer op lib 可复用。
- trace.func 能解释最终输出和必要中间约束。

### Phase 5: SOCOptTest -> opt_op_lib

目标：结合特定 SoC 做足量优化。

任务：

- 选择特定 HWConfig family，如 Shuttle512 + DRAM48。
- 定义 soc_opt target。
- 使用 `Trace.perf P2/P3/P4/P5` 做 profile。
- 形成 opt_op_lib。

验收：

- 能解释优化前后性能差异。
- perf report 能定位 bottleneck。
- opt_op_lib 明确绑定目标 HWConfig family。

### Phase 6: ModelTest

目标：用下层 lib 组合完整模型测试。

任务：

- 选择 ResNet/BERT/LLaMA 一个模型或模型片段。
- 定义 model test target。
- 使用 layer/fuse/opt lib 组合。
- 使用 `Trace.func F5_model` 或外部 checker。
- 使用 `Trace.perf` 做端到端 profile。

验收：

- ModelTest pass 或标记为可运行但 func model 未完成。
- model report 同时包含 correctness 和 performance。

---

## 8. 第一批落地文件

第一批不要追求全量，只追求抽象闭环。

```text
# ChipyardConfig / HWConfig
configs/chipyard_configs/cute2tops_scp64.yaml
configs/schemas/chipyard_config.schema.json
configs/hwconfigs/cute2tops_scp64_dramsim32.yaml
configs/schemas/hwconfig.schema.json

# Test
cute-sdk/runtime/cute_runtime/project.yaml
cute-sdk/tensor_ops/matmul/project.yaml
configs/schemas/project.schema.json

# Trace
tools/trace/format_spec.md
configs/trace_filters/func_event.yaml
configs/trace_filters/func_store_tensor.yaml
configs/trace_filters/perf_task_stage.yaml
configs/schemas/trace_filter.schema.json

# Runtime/Test code
cute-sdk/runtime/cute_runtime/include/cute_runtime.h
cute-sdk/runtime/cute_runtime/src/cute_runtime.c
cute-sdk/templates/base_rocc_hello.c.j2
cute-sdk/templates/tensor_matmul.c.j2

# Trace implementation
tools/trace/parser.py
tools/trace/filter.py
tools/trace/func/event_model.py
tools/trace/func/tensor_model.py
tools/trace/perf/timeline.py

# Runner
tools/runner/cute-run.py
tools/runner/cute-suite.py
```

---

## 9. 风险与处理

### 9.1 HWConfig 边界不清

风险：CUTE 参数、Chipyard Config、DRAMSim、simulator policy 混在 test 脚本里。

处理：

- 所有硬件/SoC/DRAM/sim 环境先进入 `HWConfig`。
- `Test` 只能声明 target requirement，不能暗中修改 HWConfig。

### 9.2 Test target 过宽

风险：高层 test 假装支持所有 HWConfig，实际只在一个 SoC 上成立。

处理：

- 每个 test 必须声明 target。
- target matcher 必须输出 `target_match.json`。
- 不匹配时标记 `TARGET_UNSUPPORTED`，不是 FAIL。

### 9.3 Trace.func 和 Trace.perf 混淆

风险：为了性能分析加的事件污染 correctness，或者为了 correctness dump 的 data 让 perf trace 爆炸。

处理：

- filter 分 purpose: `func/perf/debug`。
- func/perf 模型分目录、分报告。
- payload 默认按 filter purpose 控制。

### 9.4 Golden Level 超过 Trace.func 能力

风险：test 有 golden，但 trace.func 无法重建 actual，导致错误 pass 或错误 fail。

处理：

- `Test.golden.required_trace_func_level` 必填。
- 当前 func model 不支持时标记 `FUNC_MODEL_NOT_READY`。

### 9.5 高层 lib 过早固化

风险：Base/Tensor 还没稳定，就开始写 fuse/model，导致上层代码复制底层细节。

处理：

- 按 Test 层级沉淀 lib。
- 每一级至少有一个 pass 的 test 后，再推广该级 lib。

---

## 10. 成功标准

短期成功：

- 一个 `HWConfig` 能生成 headers、capability 和 fingerprint。
- 一个 `BaseTest` 能匹配 target、编译、运行，并通过 `Trace.func F0_event`。
- 一个 `TensorTest` 能通过 `Trace.func F1/F2` 重建输出并比较 golden。
- artifact 能保存 HWConfig/Test/Trace 三者快照。

中期成功：

- runtime lib、tensor op lib、layer op lib 由对应 test 沉淀出来。
- suite 能按 HWConfig/Test target 做 matrix 展开。
- `Trace.func` 和 `Trace.perf` 使用同一份 structured trace，但独立演进。
- perf report 能解释 stage、memory、utilization、bottleneck。

长期成功：

- 新增 HWConfig 不需要手改 C 测试常量。
- 新增 Test 主要写 target/code/golden manifest，而不是复制旧 C 文件。
- target 范围从 BaseTest 到 ModelTest 逐级变窄，并能被框架显式理解。
- correctness、profile、regression 都基于 run artifact 和 trace，而不是人工读日志。

---

## 11. 下一步讨论顺序

建议继续按下面顺序细化：

1. **HWConfig schema**
   - CUTE 和 SOC 各放哪些字段。
   - DRAMSim 和 Chipyard Config 如何命名。
   - capability 如何导出。

2. **Test schema**
   - `target/code/golden` 的最小字段。
   - Test 层级命名是否采用 `base/tensor/layer/fuse_layer/soc_opt/model`。
   - Golden level 与 required Trace.func level 的对应关系。

3. **Trace schema**
   - filter 的最小表达能力。
   - func/perf 的第一批 event。
   - `D_STORE_DATA` 是否作为 TensorTest 的第一个强制事件。

4. **最小闭环**
   - 先做 `BaseTest -> runtime lib`。
   - 再做 `TensorTest -> tensor op lib`。
   - 每一级都必须先 pass 一个代表测试，再向上叠。
