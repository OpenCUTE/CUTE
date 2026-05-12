# Config-Driven 构建流程实施计划

## 核心原则

**Config YAML 是唯一真相源。** 头文件从 Config 生成，不从 Chipyard 提取。Chipyard 的职责是验证：它的实际产物是否与 Config 声明一致。

```text
旧流程（废弃）:
  Chipyard Config class → HeaderGenerator → *.h.generated

新流程:
  Config YAML → codegen → *.h（头文件 / isa.json / 其他产物）
  Config YAML → codegen → CuteConfig.scala（Chipyard Config class 也是生成的）
  Chipyard 实际导出参数 → 与 Config YAML 比对（漂移检查）
```

## 现状

```text
当前产物散落位置：
  cutetest/include/*.generated          ← HeaderGenerator 生成的头文件（全局共享）
  build/chipyard/generated-src/          ← Verilog（按 Chipyard class name）
  build/chipyard/simulator-<CONFIG>-<ts> ← 仿真器（按 class name + 时间戳）
  build/chipyard/debug-logs/             ← 仿真输出（按 Chipyard class name）
```

当前 `configs/` 下的 YAML manifests 已经描述了：
- ChipyardConfig：class name、CUTE params、SoC 结构、capability
- CUTEISAVersion：指令编码、funct
- CUTEFPEVersion：datatype 组合
- HWConfig：ChipyardConfig + memory + simulator

## 目标产物布局

```text
build/chipyard_configs/<config_id>/          # 按 chipyard_config id 组织
  ├── generated/                              # Config codegen 产物
  │   ├── instruction.h                       # 指令编码宏（从 cute_isa_versions 生成）
  │   ├── cute_config.h                       # CUTE 参数宏（从 ChipyardConfig 生成）
  │   ├── cute_fpe.h                          # Datatype 宏（从 cute_fpe_versions 生成）
  │   └── isa.json                            # 结构化 ISA（从 cute_isa_versions 生成）
  ├── simulator-verilator                     # 编译好的仿真器
  └── config_fingerprint.txt                  # Config YAML 的 sha256（防漂移）

build/chipyard_runs/<hwconfig_name>/          # 运行产物按 hwconfig 组织
  ├── hwconfig.resolved.yaml
  └── <test_name>/
      ├── run.out
      ├── run.log
      └── events.jsonl
```

cutelib 编译时：

```text
-I build/chipyard_configs/<config_id>/generated/
```

## 已有 vs 待实现

| 功能 | 状态 | 说明 |
|------|------|------|
| ChipyardConfig / HWConfig / ISA / FPE / Vector YAML manifests | 已有 | `configs/` 下完整 |
| JSON Schema 校验 | 已有 | `cute-check-config.py` |
| Config Codegen | 已完成 | `cute-gen-config.py`，详见 `doc/sdk-doc/cute-gen-config.md` |
| 编译 Verilator 仿真器 | 已有脚本 | `scripts/build-simulator.sh` |
| 运行仿真测试 | 已有脚本 | `scripts/run-simulator-test.sh` |
| Trace 解码 | 已有 | `tools/trace/decode_cute_trace.py` |
| **参数目录 `chipyard_config_params.json`** | 已有 | 可用参数字典 |
| **ISA codegen**（YAML → `instruction.h` + `isa.json`） | 已完成 | `cute-gen-config.py` |
| **FPE codegen**（YAML → `cute_fpe.h`） | 已完成 | 从 `enums.ElementDataType` 生成 datatype 宏，不再需要单独 FPE YAML |
| **SoC config codegen**（YAML → `cute_config.h`） | 已完成 | 从 ChipyardConfig + CuteConfig 生成参数宏 |
| **Scala codegen**（YAML → `CuteConfig.scala`） | 待实现 | 从所有 chipyard_config YAML 生成 Chipyard Config class |
| **统一构建入口 `cute-build.py`** | 待实现 | 从 HWConfig name 出发，自动解析参数 |
| **统一运行入口 `cute-run.py`** | 待实现 | 自动找仿真器 + DRAMSim + 输出目录 |
| **Config vs Chipyard 漂移检查** | 待实现 | 比对 Config 声明与 Chipyard 实际导出值 |
| **头文件按 config id 组织** | 已完成 | 产物输出到 `build/chipyard_configs/<id>/generated/` |
| ~~HeaderGenerator~~ | 废弃 | 不再从 Chipyard 提取参数生成头文件 |

## 实施步骤

### Step 0: 参数目录 `configs/schemas/chipyard_config_params.json`

人可读、机器可解析的参数字典。写 chipyard_config.yaml 时从这里面选参数，codegen 读它校验和生成。

```json
{
  "core_kinds": {
    "shuttle": { "description": "Shuttle tile core", "default_tile_beat_bytes": 64 },
    "rocket":  { "description": "Rocket in-order core" },
    "boom":    { "description": "BOOM out-of-order core" }
  },
  "bus_widths": [64, 128, 256, 512],
  "cache_sizes_kb": [64, 128, 256, 512, 1024],
  "cute_params": {
    "CUTE_2Tops_64SCP":   { "Tensor_M": 64,  "Tensor_N": 64,  "Tensor_K": 64,  "description": "2-Tops 64x64x64" },
    "CUTE_4Tops_128SCP":  { "Tensor_M": 128, "Tensor_N": 128, "Tensor_K": 64,  "description": "4-Tops 128x128x64" },
    "CUTE_4TopsSCP128":   { "Tensor_M": 128, "Tensor_N": 128, "Tensor_K": 128, "description": "4-Tops 128x128x128" },
    "CUTE_8TopsSCP256":   { "Tensor_M": 256, "Tensor_N": 256, "Tensor_K": 64,  "description": "8-Tops 256x256x64" }
  },
  "fpe_versions": { "$ref": "configs/cute_fpe_versions/" },
  "isa_versions": { "$ref": "configs/cute_isa_versions/" },
  "vector_versions": { "$ref": "configs/vector_versions/" },
  "memory_models": {
    "dramsim2": { "configs_dir": "configs/memconfigs/dramsim2/" }
  }
}
```

用途：
- 人写 YAML 时参考（哪些 core_kind、bus_width 可用）
- `cute-check-config.py` 校验 ChipyardConfig 引用的参数是否合法
- `cute-gen-config.py` 从参数生成 Scala Config class 和 C 头文件
- `cute-update-chipyard-configs.py` 从参数目录 + YAML 生成完整 CuteConfig.scala

### Step 1: Config Codegen 工具链（已完成）

`tools/runner/cute-gen-config.py` 从 Config YAML 生成头文件和 JSON。详细文档见 `doc/sdk-doc/cute-gen-config.md`。

```bash
python3 tools/runner/cute-gen-config.py \
  --chipyard-config cute4tops_scp128 \
  --verbose
```

输入 YAML 自动从 chipyard_config 的引用链解析（`cute.config` → CuteConfig 预设，`cute.isa.version` → ISA YAML，`soc.vector.version` → Vector YAML）。

产物：

| 输入 | 产物 | 说明 |
|------|------|------|
| `cute_isa_versions/<isa>.yaml` | `instruction.h` | 指令 funct 编码、字段宏、RoCC 编码原语（内联）、wrapper 函数 |
| `cute_isa_versions/<isa>.yaml` | `isa.json` | 结构化 ISA 定义 |
| `cute_isa_versions/<isa>.yaml` 的 `enums.ElementDataType` | `cute_fpe.h` | datatype 枚举、A/B 位宽查询宏、名称字符串 |
| `cute_configs/<preset>.yaml` + `chipyard_configs/<id>.yaml` | `cute_config.h` | CUTE 加速器参数、tensor_task、MMU、FPE、SoC 参数宏 |
| 所有输入 | `config_fingerprint.txt` | SHA256 漂移检查 |

共享工具逻辑在 `tools/runner/cute_config_common.py`。`instruction.h` 是自包含的（内联 YGJK_INS_RRR，无需额外 include）。

### Step 1.5: `cute-update-chipyard-configs.py` — Scala Config 生成

从所有 `chipyard_config.yaml` 生成 `CuteConfig.scala`。Config YAML 是真相源，Scala Config class 是产物。

```bash
python3 tools/runner/cute-update-chipyard-configs.py \
  --output chipyard/generators/chipyard/src/main/scala/config/CuteConfig.scala
```

核心逻辑：

1. 读所有 `configs/chipyard_configs/*.yaml`
2. 读 `configs/schemas/chipyard_config_params.json`（获取参数定义）
3. 对每个 ChipyardConfig，生成对应的 Scala Config class（混入 CuteParams、SoC 参数、bus/cache 配置等）
4. 合并为一个 `CuteConfig.scala` 文件
5. 如果文件内容没变，不覆盖（避免触发不必要的 sbt 重编译）

新增 ChipyardConfig 的流程变为：

```text
1. 在 chipyard_config_params.json 中添加 cute_params 条目（如新的 Tensor_M/N/K 组合）
2. 创建 configs/chipyard_configs/<new_id>.yaml（从参数目录选参数拼接）
3. 运行 cute-update-chipyard-configs.py → 生成 CuteConfig.scala
4. sbt compile → 编译 Chipyard
5. cute-build.py --step simulator → 生成仿真器
```

不再需要手写 Scala Config class。

### Step 2: `cute-build.py` — 统一构建入口

```bash
# 生成头文件
python3 tools/runner/cute-build.py --hwconfig cute4tops_scp128_dramsim48 --step config

# 编译仿真器
python3 tools/runner/cute-build.py --hwconfig cute4tops_scp128_dramsim48 --step simulator

# 全部（config + simulator）
python3 tools/runner/cute-build.py --hwconfig cute4tops_scp128_dramsim48 --step all
```

核心逻辑：

1. 加载 `configs/hwconfigs/<name>.yaml`
2. 从 `chipyard_config` 字段加载 ChipyardConfig manifest
3. 从 `cute.isa.version` / `cute.fpe.version` 加载版本 manifests
4. `--step config`：调用 `cute-gen-config.py` 生成头文件到 `build/chipyard_configs/<id>/generated/`
5. `--step simulator`：调用 `scripts/build-simulator.sh`，复制仿真器到 `build/chipyard_configs/<id>/simulator-verilator`

### Step 3: `cute-run.py` — 统一运行入口

```bash
python3 tools/runner/cute-run.py --hwconfig cute4tops_scp128_dramsim48 --test <test_binary>
```

核心逻辑：

1. 加载 HWConfig manifest
2. 找到仿真器：`build/chipyard_configs/<id>/simulator-verilator`
3. 找到 DRAMSim INI：`configs/memconfigs/<model>/<config>/`
4. 运行仿真，输出到 `build/chipyard_runs/<hwconfig_name>/<test_name>/`
5. 自动调用 `decode_cute_trace.py` 生成 `events.jsonl`

### Step 4: Config vs Chipyard 漂移检查

写 `tools/runner/cute-check-drift.py`，比对 Config 声明与 Chipyard 实际值。

```bash
python3 tools/runner/cute-check-drift.py --chipyard-config cute4tops_scp128
```

检查方式：

1. 从 Chipyard Config class 导出实际参数（仍用一次 HeaderGenerator 或 sbt 提取）
2. 与 ChipyardConfig manifest 中的 `cute` / `soc` 字段比对
3. 不一致时报错并显示差异

这个检查不需要每次构建都跑。CI 或手动定期检查即可。

### Step 5: cutelib 编译路径

cutelib 编译时通过 config id 引入生成的头文件：

```makefile
# cutelib 编译时（由 cute-build.py 自动传入）
-I build/chipyard_configs/<config_id>/generated/
-I cute-sdk/cuteisa/<isa_version>/
```

现有 `cutetest/` 目录是旧测试，后续由 cutelib 替代。cutetest 的头文件搜索路径不需要迁移。

## 优先级

```text
Step 0:   参数目录 chipyard_config_params.json（人和工具的共同参考）
Step 1:   Config codegen（instruction.h / isa.json / cute_config.h）
Step 1.5: cute-update-chipyard-configs.py（Config YAML → CuteConfig.scala）
Step 2:   cute-build.py（构建入口）
Step 3:   cute-run.py（运行入口）
Step 4:   漂移检查（可后补，CI 需要）
Step 5:   cutelib 编译路径（Phase 4 cutelib 开发时落地）
```

Step 0 是基础中的基础——参数目录定义了所有合法选项。Step 1-1.5 让 Config YAML 成为真正的唯一真相源（生成 C 头文件 + Scala Config class）。Step 2-3 提供统一入口。Step 4 可后补。Step 5 随 cute-sdk 开发自然落地。
