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

## 详细文档

| 文档 | 内容 |
|------|------|
| `doc/sdk-doc/hwconfig-schema.md` | HWConfig schema 字段说明、解析规则 |
| `doc/sdk-doc/chipyard-config-schema.md` | ChipyardConfig schema 字段说明 |
| `doc/sdk-doc/cute-fpe-version-schema.md` | FPE version schema 说明 |
| `doc/sdk-doc/cute-isa-version-schema.md` | ISA version schema 说明 |
