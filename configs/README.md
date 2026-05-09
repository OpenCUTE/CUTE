# CUTE configs 目录说明

`configs/` 是 CUTE 框架的纯声明式配置层，定义硬件、版本、内存、过滤器和测试套件。不含可执行代码。

## 目录结构

```text
configs/
├── chipyard_configs/        # ChipyardConfig manifests — CUTE 硬件配置入口
│   ├── cute2tops_scp64.yaml
│   └── cute4tops_scp128.yaml
├── hwconfigs/               # HWConfig — 可运行硬件目标组合
│   ├── cute2tops_scp64_dramsim32.yaml
│   └── cute4tops_scp128_dramsim48.yaml
├── cute_fpe_versions/       # CUTE FPE datatype 版本
│   └── cute_fpe_v1.yaml
├── cute_isa_versions/       # CUTE/YGJK 指令集版本
│   └── cute_isa_v1.yaml
├── vector_versions/         # 向量扩展版本
│   ├── none.yaml
│   └── saturn_rvv.yaml
├── memconfigs/              # 内存模型配置
│   └── dramsim2/            # DRAMSim2 INI 文件
│       ├── dramsim2_ini_8GB_per_s/
│       ├── dramsim2_ini_16GB_per_s/
│       ├── dramsim2_ini_24GB_per_s/
│       ├── dramsim2_ini_32GB_per_s/
│       ├── dramsim2_ini_48GB_per_s/
│       └── dramsim2_ini_64GB_per_s/
├── trace_filters/           # Trace 过滤器
│   ├── func_level1_inst.yaml
│   ├── func_level2_mem_cute.yaml
│   ├── func_level2ex_all_cute.yaml
│   ├── func_level3_mem_vector.yaml
│   └── perf_topdown_status.yaml
├── suites/                  # 测试套件定义（待建设）
└── schemas/                 # JSON Schema 校验
    ├── chipyard_config.schema.json
    ├── hwconfig.schema.json
    ├── cute_fpe_version.schema.json
    ├── cute_isa_version.schema.json
    ├── vector_version.schema.json
    ├── project.schema.json
    └── trace_filter.schema.json
```

## 配置层级关系

```text
HWConfig（可运行目标）
  ├── 引用 → ChipyardConfig（CUTE 硬件结构）
  │            ├── 引用 → CUTEFPEVersion（datatype 能力）
  │            ├── 引用 → CUTEISAVersion（指令集能力）
  │            └── 引用 → VectorVersion（向量扩展能力）
  ├── 绑定 → MemoryConfig（DRAMSim2 INI）
  └── 绑定 → SimulatorPolicy（verilator/vcs/fpga + max_cycles）
```

### ChipyardConfig

定义 CUTE 硬件的结构事实：Scala Config class、CUTE 参数、SoC 配置（core/bus/cache/vector）、capability 标签。

```yaml
# configs/chipyard_configs/cute4tops_scp128.yaml
version: 1
id: cute4tops_scp128
class: chipyard.CUTE4TopsSCP128Config
source_file: chipyard/generators/chipyard/src/main/scala/config/CuteConfig.scala

cute:
  params_symbol: CuteParams.CUTE_4Tops_128SCP
  fpe: { version: cute_fpe_v1 }
  isa: { version: cute_isa_v1 }

soc:
  core: { kind: shuttle, count: 1, shuttle_tile_beat_bytes: 64 }
  bus: { system_bits: 512, memory_bits: 512 }
  cache: { inclusive_kb: 512 }
  vector: { version: none }

capability:
  tensor_ops: [matmul, conv]
```

### HWConfig

定义一个可运行目标 = ChipyardConfig + 内存模型 + 仿真策略。同一个 ChipyardConfig 可以搭配不同 DRAMSim 配置。

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

### 版本 manifests

| manifest | 内容 |
|----------|------|
| `cute_fpe_versions/` | 支持的 datatype 组合（如 `i8i8i32`、`fp16fp16fp32`、`mxfp8e4m3fp32`） |
| `cute_isa_versions/` | 指令集定义（YGJK 指令 + CUTE 内部指令的 funct 编码） |
| `vector_versions/` | 向量扩展能力（`none` = 无向量，`saturn_rvv` = Saturn RVV） |

## 校验

所有 YAML 文件都有对应的 JSON Schema：

```bash
python3 tools/runner/cute-check-config.py
```

校验内容：
- YAML 结构符合 schema
- 跨文件引用存在（HWConfig → ChipyardConfig → FPE/ISA/Vector versions）
- id/name 全局唯一
- 内存模型配置目录存在

---

## 从 Config 到硬件 — 构建流程

每个 ChipyardConfig 对应一个独立的构建目录。构建产物按 config id 组织：

```text
build/
└── chipyard_configs/
    └── <chipyard_config_id>/              # 例如 cute4tops_scp128
        ├── generated_headers/             # 从 Chipyard Config 提取的 C 头文件
        │   ├── datatype.h.generated
        │   ├── validation.h.generated
        │   ├── instruction.h.generated
        │   ├── cute_config.h.generated
        │   └── cute_layout.h.generated
        ├── chipyard_config.extracted.json # Chipyard 导出的结构事实
        ├── header_fingerprint.txt         # 头文件指纹（防漂移）
        └── simulator/                     # 编译好的仿真器
            └── simulator-verilator        # Verilator 可执行文件
```

### 步骤 1: 校验配置

```bash
# 校验所有 manifest 的 schema、引用、唯一性
python3 tools/runner/cute-check-config.py
```

### 步骤 2: 生成 C 头文件

从 Chipyard Config class 提取硬件参数，生成 C 头文件到对应 config 目录。

```bash
# 按 chipyard_config id 生成
bash scripts/generate-headers.sh chipyard.CUTE4TopsSCP128Config \
  build/chipyard_configs/cute4tops_scp128/generated_headers
```

生成的头文件（`*.h.generated`）是 cutelib 编译时的依赖，通过 `-I` 引入。

### 步骤 3: 编译 Verilator 仿真器

从 Chipyard Config 编译 Verilator 仿真器。

```bash
# 按 chipyard_config id 编译
bash scripts/build-simulator.sh CUTE4TopsSCP128Config
```

仿真器二进制存放在 `build/chipyard/simulator-<CONFIG>-<timestamp>`。

### 步骤 4: 运行测试

用指定 HWConfig 的仿真器运行测试二进制。

```bash
# 运行单个测试
bash scripts/run-simulator-test.sh CUTE4TopsShuttle512D512V512M512Sysbus512Membus1CoreConfig \
  cutetest/base_test/cute_Matmul_mnk_128_128_128_zeroinit.riscv
```

仿真输出（`.out` / `.log`）包含 Verilator printf 和 CUTETrace compact 行。

### 步骤 5: 解码 Trace

```bash
# 解码 compact trace
python3 tools/trace/decode_cute_trace.py \
  --log <output_file> \
  --mode jsonl \
  -o trace_output.jsonl
```

### 完整流程图

```text
configs/chipyard_configs/<id>.yaml
  │
  ├── cute-check-config.py ──→ 校验通过
  │
  ├── generate-headers.sh ──→ build/chipyard_configs/<id>/generated_headers/
  │                            ↑ cutelib 编译时 -I 引入
  │
  ├── build-simulator.sh ──→ build/chipyard/simulator-<CONFIG>-<ts>
  │
  └── run-simulator-test.sh ──→ <config>.out + <config>.log
                                  │
                                  └── decode_cute_trace.py ──→ events.jsonl
```

### TODO: 统一入口脚本

当前各步骤是独立脚本，需要手动传 Config class name。后续应提供统一入口：

```bash
# 理想用法（待实现）
python3 tools/runner/cute-build.py --hwconfig cute4tops_scp128_dramsim48 --step headers
python3 tools/runner/cute-build.py --hwconfig cute4tops_scp128_dramsim48 --step simulator
python3 tools/runner/cute-run.py   --hwconfig cute4tops_scp128_dramsim48 --test <test_binary>
```

统一入口从 HWConfig manifest 自动解析：
- `chipyard_config` → ChipyardConfig manifest → `class` 字段 → 传给现有脚本
- `memory.config` → DRAMSim INI 路径 → 传给仿真器
- `simulator.max_cycles` → 传给仿真器

这样用户只需记住 HWConfig name，不需要知道底层 Chipyard class name。

---

## 详细文档

| 文档 | 内容 |
|------|------|
| `doc/sdk-doc/hwconfig-schema.md` | HWConfig schema 字段说明、解析规则 |
| `doc/sdk-doc/chipyard-config-schema.md` | ChipyardConfig schema 字段说明 |
| `doc/sdk-doc/cute-fpe-version-schema.md` | FPE version schema 说明 |
| `doc/sdk-doc/cute-isa-version-schema.md` | ISA version schema 说明 |
