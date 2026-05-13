# CUTE tools 目录说明

`tools/` 是 CUTE 框架的 Host 端工具链（Python），运行在开发机上，不编译到 RISC-V 目标板。

## 目录结构

```text
tools/
├── runner/                              # Config runner / 代码生成
│   ├── cute-check-config.py             # Config schema / 引用检查
│   ├── cute-gen-config.py               # C 头文件和 ISA JSON 生成
│   ├── cute-gen-cuteisa.py              # cute-sdk/cuteisa ISA artifacts 生成
│   ├── cute-gen-scala-config.py         # Scala 配置生成 / 更新 / 漂移检查
│   ├── cute-update-chipyard-configs.py  # Chipyard CuteConfig.scala 生成
│   ├── cute-build.py                    # HWConfig → genfiles / simulator
│   └── cute-run.py                      # HWConfig → simulator run
└── trace/                               # Trace 工具链
    ├── README.md                        # Trace 工具链详细用法
    ├── gen_cute_trace.py                # catalog → Scala/Python codegen
    ├── check_cute_trace.py              # catalog + filter 校验
    └── decode_cute_trace.py             # compact 日志解码 CLI
```

## 工具说明

### Runner / Config 工具

### `runner/cute-check-config.py`

校验 `configs/` 下所有 YAML manifest 的 schema 合法性和跨文件引用。

```bash
# 扫描所有输入，并打印 HWConfig / Project 匹配矩阵
python3 tools/runner/cute-check-config.py --scan

# 按类型检查全部 manifest
python3 tools/runner/cute-check-config.py --cute-config --all
python3 tools/runner/cute-check-config.py --chipyard-config --all
python3 tools/runner/cute-check-config.py --hwconfig --all

# 检查单个 manifest
python3 tools/runner/cute-check-config.py --cute-config CUTE_2Tops_64SCP
python3 tools/runner/cute-check-config.py --chipyard-config cute4tops_scp128
python3 tools/runner/cute-check-config.py --hwconfig cute4tops_scp128_dramsim48
```

`--all` 也支持 `--cute-isa-version`、`--vector-version`、
`--trace-filter` 和 `--project`。输出会列出本次检查过的 config/YAML，以及使用到的 JSON schema。

### `runner/cute-gen-config.py`

从 `configs/chipyard_configs/<id>.yaml` 解析引用链，并生成 C 侧配置产物：

```text
build/chipyard_configs/<chipyard_config_id>/generated/
├── instruction.h
├── isa.json
├── cute_fpe.h
├── cute_config.h
└── config_fingerprint.txt
```

常用命令：

```bash
python3 tools/runner/cute-gen-config.py \
  --chipyard-config cute4tops_scp128 \
  --verbose

# 输入指纹未变化时会跳过；需要强制重生成时：
python3 tools/runner/cute-gen-config.py \
  --chipyard-config cute4tops_scp128 \
  --force

# 指定输出目录
python3 tools/runner/cute-gen-config.py \
  --chipyard-config cute4tops_scp128 \
  --output /tmp/cute-generated
```

### `runner/cute-gen-cuteisa.py`

从 `configs/cute_isa_versions/*.yaml` 生成 SDK 侧共享 ISA artifacts：

```text
cute-sdk/cuteisa/<isa_version>/
├── instruction.h
├── isa.json
├── cute_fpe.h
└── isa_summary.md
```

默认扫描全部 ISA version：

```bash
python3 tools/runner/cute-gen-cuteisa.py --verbose
```

只生成指定版本：

```bash
python3 tools/runner/cute-gen-cuteisa.py \
  --isa-version cute_isa_v1
```

该脚本不依赖 ChipyardConfig；`configs/cute_isa_versions/<isa>.yaml` 是
`cuteisa` 产物的唯一真相源。

### `runner/cute-gen-scala-config.py`

从 `configs/cute_configs/*.yaml` 和 `configs/cute_isa_versions/<id>.yaml`
生成 Scala 配置文件：

```text
HardwareConfig.scala
InstConfig.scala
```

预览生成到 `build/generated-scala/`：

```bash
python3 tools/runner/cute-gen-scala-config.py \
  --force \
  --verbose
```

检查 `src/main/scala` 中的生成文件是否与 YAML 一致：

```bash
python3 tools/runner/cute-gen-scala-config.py --check
```

直接更新 `src/main/scala/HardwareConfig.scala` 和
`src/main/scala/InstConfig.scala`：

```bash
python3 tools/runner/cute-gen-scala-config.py --update
```

`--update` 会跳过内容没有变化的文件，避免无意义改动；比较时忽略自动生成头里的
`Generated at` 时间戳。需要生成其它 ISA 版本时可加：

```bash
python3 tools/runner/cute-gen-scala-config.py \
  --isa-version cute_isa_v1 \
  --check
```

### `runner/cute-update-chipyard-configs.py`

从 `configs/chipyard_configs/*.yaml` 生成 Chipyard 侧的
`CuteConfig.scala`。生成文件把 `HardwareConfig.<cute_config>` 作为 CUTE
参数源，使 Chipyard Config class 跟随 YAML 更新。

```bash
# 预览到 stdout
python3 tools/runner/cute-update-chipyard-configs.py

# 更新 Chipyard CuteConfig.scala，内容不变时跳过写入
python3 tools/runner/cute-update-chipyard-configs.py \
  --output chipyard/generators/chipyard/src/main/scala/config/CuteConfig.scala

# CI / 本地漂移检查
python3 tools/runner/cute-update-chipyard-configs.py \
  --output chipyard/generators/chipyard/src/main/scala/config/CuteConfig.scala \
  --check
```

### `runner/cute-build.py`

从 `configs/hwconfigs/<name>.yaml` 出发，统一执行构建步骤：

```bash
# 生成 C 头文件和 ISA JSON
python3 tools/runner/cute-build.py \
  --hwconfig cute4tops_scp128_dramsim48 \
  --step genfiles

# 编译 Verilator simulator，并归档到 build/chipyard_configs/<id>/
python3 tools/runner/cute-build.py \
  --hwconfig cute4tops_scp128_dramsim48 \
  --step simulator

# 生成文件 + 编译 simulator
python3 tools/runner/cute-build.py \
  --hwconfig cute4tops_scp128_dramsim48 \
  --step all

# 遍历所有 HWConfig，生成每个唯一 chipyard_config 的文件
python3 tools/runner/cute-build.py \
  --all \
  --step genfiles
```

`--hwconfig` 和 `--all` 二选一使用。`--all` 会扫描
`configs/hwconfigs/*.yaml`，并按 `chipyard_config` 去重执行构建，避免同一个
Chipyard 配置重复生成或重复编译。`--step config` 是 `--step genfiles` 的兼容别名。
Simulator 输出位置：

```text
build/chipyard_configs/<chipyard_config_id>/simulator-verilator
```

### `runner/cute-run.py`

从 HWConfig 自动选择 simulator、DRAMSim 配置和 max-cycles，运行测试二进制：

```bash
python3 tools/runner/cute-run.py \
  --hwconfig cute4tops_scp128_dramsim48 \
  --test <test_binary>

# 只保留 simulator stdout，隐藏 runner 自己的 [CMD]/[OK] 等状态行
python3 tools/runner/cute-run.py \
  --quiet \
  --hwconfig cute4tops_scp128_dramsim48 \
  --test <test_binary>
```

默认输出：

```text
build/chipyard_runs/<hwconfig_name>/<test_name>/
├── hwconfig.yaml
├── run.log
└── run.out
```

输出流约定：

- simulator `stdout` 会实时打印到终端，并写入 `run.log`。
- simulator `stderr` 会单独写入 `run.out`。
- `--quiet` 只隐藏 runner 自己的状态行，例如 `[HWCONFIG]`、`[SIM]`、`[CMD]`、
  `[LOG]`、`[OUT]`、`[OK]` / `[FAIL]`；不会隐藏 simulator `stdout`。

`cute-run.py` 不会自动调用 trace 解码；需要解码时手动运行
`tools/trace/decode_cute_trace.py`。

### `trace/` 工具链

Trace 工具链的详细用法见 `tools/trace/README.md`。

快速参考：

```bash
# 校验 catalog
python3 tools/trace/check_cute_trace.py

# 生成 Scala/Python 产物
python3 tools/trace/gen_cute_trace.py \
  --catalog trace/catalogs/cute_trace.json \
  --scala-out trace/cutetrace/src/main/scala/trace/generated \
  --python-out trace/python/cutetrace/generated \
  --build-out trace/generated

# 检查生成文件是否漂移
python3 tools/trace/gen_cute_trace.py \
  --catalog trace/catalogs/cute_trace.json \
  --scala-out trace/cutetrace/src/main/scala/trace/generated \
  --python-out trace/python/cutetrace/generated \
  --build-out trace/generated \
  --check

# 解码 Verilator 日志
python3 tools/trace/decode_cute_trace.py --log <log_file>
python3 tools/trace/decode_cute_trace.py --log <log_file> --mode jsonl -o out.jsonl
```

## 约定

- 所有脚本支持 `python3 <script>` 直接运行，也支持 `./<script>`（有 shebang）。
- Runner 脚本通过 `--root` 或自动搜索定位 CUTE 根目录。
- 退出码：`0` 成功，`1` 表示检查失败或生成文件漂移，`2` 表示参数或输入错误。stdout 输出结果，stderr 输出错误。
