# CUTE configs 目录说明

`configs/` 是 CUTE 的声明式配置层。这里的 YAML 描述 CUTE
加速器参数、Chipyard SoC 组合、ISA/datatype、向量能力、内存模型和运行策略。

当前方向是：**Config YAML 是真相源**。C 侧头文件已经由 YAML 生成；
Scala 侧配置由 `HardwareConfig.scala` 和 `InstConfig.scala` 承载，
并可由 YAML 直接检查或更新。

## 目录结构

```text
configs/
├── cute_configs/             # CuteConfig — CUTE 加速器硬件参数预设
│   ├── CUTE_2Tops_64SCP.yaml
│   └── CUTE_4Tops_128SCP.yaml
├── chipyard_configs/         # ChipyardConfig — SoC + CUTE 预设引用
│   ├── cute2tops_scp64.yaml
│   └── cute4tops_scp128.yaml
├── hwconfigs/                # HWConfig — 可运行目标组合
│   ├── cute2tops_scp64_dramsim32.yaml
│   └── cute4tops_scp128_dramsim48.yaml
├── cute_isa_versions/        # CUTE/YGJK ISA 版本，含指令、字段、datatype enum
│   └── cute_isa_v1.yaml
├── vector_versions/          # 向量扩展能力
│   ├── none.yaml
│   └── saturn_rvv.yaml
├── memconfigs/               # 内存模型配置
│   └── dramsim2/
│       ├── dramsim2_ini_8GB_per_s/
│       ├── dramsim2_ini_16GB_per_s/
│       ├── dramsim2_ini_24GB_per_s/
│       ├── dramsim2_ini_32GB_per_s/
│       ├── dramsim2_ini_48GB_per_s/
│       └── dramsim2_ini_64GB_per_s/
├── trace_filters/            # Trace 过滤器
├── suites/                   # 测试套件定义（待建设）
└── schemas/                  # JSON Schema 和参数字典
    ├── chipyard_config.schema.json
    ├── chipyard_config_params.json
    ├── cute_config.schema.json
    ├── cute_isa_version.schema.json
    ├── vector_version.schema.json
    ├── hwconfig.schema.json
    ├── project.schema.json
    └── trace_filter.schema.json
```

## 配置层级关系

```text
HWConfig（可运行目标）
  ├── 引用 → ChipyardConfig（SoC + CUTE 预设引用）
  │            ├── 引用 → CuteConfig（configs/cute_configs/<id>.yaml）
  │            ├── 引用 → CUTEISAVersion（指令 + datatype enum）
  │            └── 引用 → VectorVersion（none / saturn_rvv / ...）
  ├── 绑定 → MemoryConfig（DRAMSim2 INI）
  └── 绑定 → SimulatorPolicy（verilator/vcs/fpga + max_cycles）
```

### CuteConfig

`cute_configs/*.yaml` 描述 CUTE 加速器本体的硬件参数预设，是
`CuteParams` 静态预设的 YAML 版本。
字段名直接对齐 Scala `CuteParams` 参数名；二级对象用 schema 中的
`x-scala-constructor` 标注构造器，例如 `MMUParams = CuteMMUParams(...)`。

```yaml
# configs/cute_configs/CUTE_4Tops_128SCP.yaml
version: 1
id: CUTE_4Tops_128SCP
description: 4Tops + 128x128x64 tile

Tensor_M: 128
Tensor_N: 128
Tensor_K: 64
Matrix_M: 4
Matrix_N: 4
ReduceWidthByte: 64
outsideDataWidth: 512
ResultWidthByte: 4
MMUAddrWidth: 39
LLCSourceMaxNum: 64
ResultFIFODepth: 8
ApplicationMaxTensorSize: 65535
ConvolutionDIM_Max: 65535
Convolution_Input_Height_Weight_Dim_Max: 16383
KernelSizeMax: 15
StrideSizeMax: 3

MMUParams:
  vpnBits: 12
  ppnBits: 12
  pgIdxBits: 12
  vaddrBits: 39
  paddrBits: 39
  corePAddrBits: 64

FPEparams:
  MinGroupSize: 16
  MinDataTypeWidth: 4
  ScaleElementWidth: 8
  cmptreelayers: 4
  fp8cmptreelayers: 4
```

### ChipyardConfig

`chipyard_configs/*.yaml` 描述一个 Chipyard SoC 配置：它通过
`cute.config` 引用 CUTE 参数预设，通过 `cute.isa.version` 引用 ISA
版本，并声明 core/bus/cache/vector 等 SoC 事实。

```yaml
# configs/chipyard_configs/cute4tops_scp128.yaml
version: 1
id: cute4tops_scp128

cute:
  config: CUTE_4Tops_128SCP
  instances: [0]
  isa:
    version: cute_isa_v1

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
  vector:
    version: none

capability:
  tensor_ops: [matmul, conv]
  layer_ops: []
  fused_ops: []
```

### HWConfig

`hwconfigs/*.yaml` 定义一个可运行目标：
`ChipyardConfig + MemoryConfig + SimulatorPolicy`。同一个 ChipyardConfig
可以搭配不同 DRAMSim 配置。

```yaml
# configs/hwconfigs/cute4tops_scp128_dramsim48.yaml
version: 1
name: cute4tops_scp128_dramsim48
tags: [cute_tensor_v1, shuttle, medium]

chipyard_config: cute4tops_scp128

memory:
  model: dramsim2
  config: dramsim2_ini_48GB_per_s

simulator:
  backend: verilator
  binary: auto
  max_cycles: 800000000
```

### ISA 与 datatype

`cute_isa_versions/*.yaml` 同时描述：

- YGJK/RoCC 接口指令
- CUTE 内部控制指令
- 指令 funct / rocc_funct
- cfgData 字段布局
- enum，例如 `ElementDataType` 和 `CMemoryLoaderTaskType`

`ElementDataType` 是当前 datatype 的唯一数据源。C 侧 `cute_fpe.h`
和 Scala `ElementDataType` 都应从这里生成。

### VectorVersion

`vector_versions/*.yaml` 描述 SoC 中是否有软件可见的向量实现：

| id           | 含义                 |
|--------------|----------------------|
| `none`       | 不启用向量扩展       |
| `saturn_rvv` | 使用 Saturn RVV 路径 |

## 校验

所有 YAML manifest 都应通过 schema 和跨文件引用校验：

```bash
python3 tools/runner/cute-check-config.py --scan
```

校验内容：

- YAML 结构符合对应 schema
- 文件名和 `id` / `name` 匹配
- 跨文件引用存在：`HWConfig -> ChipyardConfig -> CuteConfig / ISA / Vector`
- `memory.config` 对应的 DRAMSim2 配置目录存在
- ISA 指令 funct、字段和 enum 基本一致性

常用细分检查：

```bash
# 检查所有 CuteConfig
python3 tools/runner/cute-check-config.py --cute-config --all

# 检查单个 CuteConfig
python3 tools/runner/cute-check-config.py --cute-config CUTE_2Tops_64SCP

# 检查所有 HWConfig，并递归检查引用的 config
python3 tools/runner/cute-check-config.py --hwconfig --all

# 检查单个 ChipyardConfig，并递归检查它引用的 config
python3 tools/runner/cute-check-config.py --chipyard-config cute4tops_scp128
```

`--all` 可用于 `--chipyard-config`、`--cute-config`、
`--cute-isa-version`、`--vector-version`、`--trace-filter`、
`--hwconfig` 和 `--project`。输出会列出本次检查过的 config/YAML
和使用到的 JSON schema。

## 关键脚本

- `tools/runner/cute-check-config.py`: 校验 config YAML、JSON schema
  和跨文件引用。
- `tools/runner/cute-gen-config.py`: 从 ChipyardConfig 生成 C 头文件和
  ISA JSON。
- `tools/runner/cute-gen-scala-config.py`: 生成、检查或更新 Scala 配置。
- `tools/runner/cute-build.py`: 从 HWConfig 生成头文件并编译 simulator。
- `tools/runner/cute-run.py`: 从 HWConfig 选择 simulator 并运行测试。
- `tools/trace/check_cute_trace.py`: 校验 trace catalog 和 trace filter。
- `tools/trace/gen_cute_trace.py`: 生成 Scala / Python trace API。
- `tools/trace/decode_cute_trace.py`: 解码 Verilator compact trace 日志。

## 从 Config 到产物

每个 ChipyardConfig 对应一个独立构建目录，按 config id 组织：

```text
build/
└── chipyard_configs/
    └── <chipyard_config_id>/          # 例如 cute4tops_scp128
        ├── generated/
        │   ├── instruction.h          # 从 cute_isa_versions 生成
        │   ├── isa.json               # 从 cute_isa_versions 生成
        │   ├── cute_fpe.h             # 从 enums.ElementDataType 生成
        │   ├── cute_config.h          # 从 CuteConfig + ChipyardConfig 生成
        │   └── config_fingerprint.txt # 输入 YAML 指纹
        └── simulator-verilator        # 编译好的仿真器（后续统一放置）
```

### 步骤 1: 校验配置

```bash
python3 tools/runner/cute-check-config.py --scan
```

### 步骤 2: 预览生成 Scala 配置

默认可以先生成到 review 目录：

```bash
python3 tools/runner/cute-gen-scala-config.py \
  --force \
  --verbose
```

默认输出：

```text
build/generated-scala/
├── HardwareConfig.scala
└── InstConfig.scala
```

当前源码树已经有生成版 Scala 配置时，可以直接检查是否漂移：

```bash
python3 tools/runner/cute-gen-scala-config.py --check
```

需要把 YAML 生成结果同步到 `src/main/scala` 时使用 `--update`：

```bash
python3 tools/runner/cute-gen-scala-config.py --update
```

`--update` 只会写入内容变化的文件；如果生成内容与现有文件一致，会输出
`[SKIP]` 并保持文件不变。比较时会忽略自动生成头里的 `Generated at` 时间戳。

`HardwareConfig.scala` 的字段顺序和二级对象构造器由
`configs/schemas/cute_config.schema.json` 描述。普通字段名直接等于 Scala
参数名；带 `x-scala-constructor` 的对象会生成嵌套构造器调用。

YAML 中没有显式出现的字段不会被写入生成结果；最终由 `CuteParams` case
class 自身的默认值接管。

### 步骤 3: 生成chipyard的config文件

Chipyard 侧 `CuteConfig.scala` 由 `configs/chipyard_configs/*.yaml`
生成，不再手写维护：

```bash
python3 tools/runner/cute-update-chipyard-configs.py \
  --output chipyard/generators/chipyard/src/main/scala/config/CuteConfig.scala
```

如果生成内容没有变化，脚本会输出 `[SKIP]` 并保持文件不变。检查当前
`CuteConfig.scala` 是否与 YAML 一致：

```bash
python3 tools/runner/cute-update-chipyard-configs.py \
  --output chipyard/generators/chipyard/src/main/scala/config/CuteConfig.scala \
  --check
```

### 步骤 4: 生成 C 头文件和 ISA JSON

```bash
python3 tools/runner/cute-gen-config.py \
  --chipyard-config cute4tops_scp128 \
  --verbose
```

默认输出：

```text
build/chipyard_configs/cute4tops_scp128/generated/
```

如果输入 YAML 的指纹没有变化，脚本会跳过重复生成；需要强制重生成时加 `--force`：

```bash
python3 tools/runner/cute-gen-config.py \
  --chipyard-config cute4tops_scp128 \
  --force
```

生成逻辑：

```text
chipyard_configs/<id>.yaml
  ├── cute.config       -> cute_configs/<cute_config_id>.yaml
  ├── cute.isa.version  -> cute_isa_versions/<isa_id>.yaml
  └── soc.vector.version -> vector_versions/<vector_id>.yaml
```

### 步骤 5: 生成仿真目标文件

```bash
python3 tools/runner/cute-build.py \
  --hwconfig cute4tops_scp128_dramsim48 \
  --step simulator
```

`cute-build.py` 会从 HWConfig 自动解析 `chipyard_config`，再从现有
Chipyard `CuteConfig.scala` 找到对应的 Scala config class，最后调用
Chipyard Verilator `make CONFIG=<class>`。生成出的仿真器会归档到：

```text
build/chipyard_configs/<chipyard_config_id>/simulator-verilator
```

也可以一次完成头文件生成和仿真器编译：

```bash
python3 tools/runner/cute-build.py \
  --hwconfig cute4tops_scp128_dramsim48 \
  --step all
```

### 步骤 6: 运行测试

```bash
python3 tools/runner/cute-run.py \
  --hwconfig cute4tops_scp128_dramsim48 \
  --test <test_binary>
```

运行产物默认写入：

```text
build/chipyard_runs/<hwconfig_name>/<test_name>/
├── hwconfig.yaml
├── run.log
└── run.out
```

`cute-run.py` 只运行 simulator，不会自动调用 trace 解码。需要解码时手动运行：

```bash
python3 tools/trace/decode_cute_trace.py \
  --log <output_file> \
  --mode jsonl \
  -o trace_output.jsonl
```

## 统一入口摘要

```bash
python3 tools/runner/cute-build.py \
  --hwconfig cute4tops_scp128_dramsim48 \
  --step genfiles

python3 tools/runner/cute-build.py \
  --hwconfig cute4tops_scp128_dramsim48 \
  --step simulator

python3 tools/runner/cute-run.py \
  --hwconfig cute4tops_scp128_dramsim48 \
  --test <test_binary>
```

统一入口应从 HWConfig 自动解析：

- `chipyard_config` -> `configs/chipyard_configs/<id>.yaml`
- `cute.config` -> `configs/cute_configs/<id>.yaml`
- `cute.isa.version` -> `configs/cute_isa_versions/<id>.yaml`
- `soc.vector.version` -> `configs/vector_versions/<id>.yaml`
- `memory.config` -> `configs/memconfigs/<model>/<config>/`
- `simulator.max_cycles` -> 仿真器运行参数

## 详细文档

- `configs/plan.md`: Config-driven 构建流程总计划。
- `plans/cx/cute_config_scala_refactor_plan.md`: README 与 Scala 参数拆分计划。
- `configs/schemas/cute_config.schema.json`: CuteConfig schema。
- `configs/schemas/chipyard_config.schema.json`: ChipyardConfig schema。
- `configs/schemas/cute_isa_version.schema.json`: ISA/datatype schema。
- `configs/schemas/hwconfig.schema.json`: HWConfig schema。
