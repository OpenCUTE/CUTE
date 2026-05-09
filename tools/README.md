# CUTE tools 目录说明

`tools/` 是 CUTE 框架的 Host 端工具链（Python），运行在开发机上，不编译到 RISC-V 目标板。

## 目录结构

```text
tools/
├── runner/                              # Runner / 配置校验
│   └── cute-check-config.py             # 静态配置检查
└── trace/                               # Trace 工具链
    ├── README.md                        # Trace 工具链详细用法
    ├── gen_cute_trace.py                # catalog → Scala/Python codegen
    ├── check_cute_trace.py              # catalog + filter 校验
    └── decode_cute_trace.py             # compact 日志解码 CLI
```

## 工具说明

### `runner/cute-check-config.py`

校验 `configs/` 下所有 YAML manifest 的 schema 合法性和跨文件引用。

```bash
python3 tools/runner/cute-check-config.py
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
- 脚本内部通过 `REPO_ROOT` 定位 CUTE 根目录，不需要手动设置环境变量。
- 退出码：`0` 成功，`1` 失败。stdout 输出结果，stderr 输出错误和状态摘要。
