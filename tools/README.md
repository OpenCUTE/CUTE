# CUTE tools 目录说明

`tools/` 是 CUTE 框架的 Host 端工具链（Python），运行在开发机上，不编译到 RISC-V 目标板。

## 目录结构

```text
tools/
├── runner/                              # Config runner / 代码生成
│   ├── cute-check-config.py             # Config schema / 引用检查
│   ├── cute-gen-config.py               # C 头文件和 ISA JSON 生成
│   └── cute-gen-scala-config.py         # Scala 配置生成 / 更新 / 漂移检查
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
