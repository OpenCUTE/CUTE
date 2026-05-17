# CUTE Trace 目录说明

CUTETrace 是面向 Verilator 仿真的语义化 trace 系统。以 catalog 为唯一真相源，驱动 Scala 代码生成、Python 解码和 trace 过滤。

## 目录结构

```text
trace/
├── catalogs/
│   └── cute_trace.json                  # 唯一真相源：category/module/task/event/field/id
│
├── cutetrace/                            # Scala trace runtime（编译进 CUTE 硬件）
│   └── src/main/scala/trace/
│       ├── CUTETraceContext.scala        # cycle + params 隐式上下文
│       ├── CUTETraceParams.scala         # enable/mode/category 开关
│       ├── CUTETracePrintf.scala         # compact/human 双模式 emit
│       └── generated/                    # 代码生成产物（勿手改）
│           ├── CUTETrace.scala           # CUTETrace.Task.method(...) typed API
│           └── CUTETraceIds.scala        # Category/Module/Task/Event id 常量
│
├── python/cutetrace/                     # Python trace 工具库
│   ├── catalog.py                       # catalog loader + validator
│   ├── parser.py                        # CT 行解析 → RawTraceLine
│   ├── decoder.py                       # RawTraceLine → DecodedEvent（typed fields）
│   ├── render.py                        # DecodedEvent → text / jsonl
│   ├── rebuilder.py                     # storeData trace → memory image
│   └── generated/                       # 代码生成产物（勿手改）
│       └── cute_trace_catalog.py        # Python catalog 索引 + EVENTS_BY_ID
│
├── generated/
│   └── cute_trace_catalog.normalized.json  # catalog 稳定镜像，用于 CI 漂移检查
│
└── format_spec.md                        # Trace 格式设计文档
```

## 数据流

```text
cute_trace.json（唯一真相源）
  │
  ├─→ gen_cute_trace.py
  │     ├─→ CUTETrace.scala / CUTETraceIds.scala（Scala typed API）
  │     ├─→ cute_trace_catalog.py（Python 索引）
  │     └─→ cute_trace_catalog.normalized.json（稳定镜像）
  │
  ├─→ CUTE 硬件（Chisel 编译）
  │     └─→ Verilator printf 输出 CT compact 行
  │
  └─→ decode_cute_trace.py
        └─→ parse → decode → render（text / jsonl）
```

## Compact 行格式

```text
CT,1,<cycle_hex>,<task_id_hex>,<event_id_hex>,<field_value>,...,<fieldN_value>
```

- uint/bool 字段：`%x`（hex）
- sint 字段：`%d`（signed decimal，保留符号）

## 用法

修改 catalog 后，重新生成并解码：

```bash
# 1. 校验 catalog
python3 tools/trace/check_cute_trace.py

# 2. 生成 Scala/Python
python3 tools/trace/gen_cute_trace.py \
  --catalog trace/catalogs/cute_trace.json \
  --scala-out trace/cutetrace/src/main/scala/trace/generated \
  --python-out trace/python/cutetrace/generated \
  --build-out trace/generated

# 3. 解码 Verilator 日志
python3 tools/trace/decode_cute_trace.py --log <log_file> --mode jsonl
```

## 详细文档

| 文档 | 内容 |
|------|------|
| `trace/format_spec.md` | Trace 格式设计文档 |
| `doc/sdk-doc/cute-trace-catalog.md` | Catalog 说明 |
| `doc/sdk-doc/cute-trace-usage.md` | 日常使用指南 |
| `doc/sdk-doc/cute-trace-parser.md` | Parser API |
| `doc/sdk-doc/cute-trace-decoder.md` | Decoder API |
| `doc/sdk-doc/cute-trace-render.md` | Render API |
| `doc/sdk-doc/cute-trace-decode-cli.md` | 解码 CLI 用法 |
| `tools/trace/README.md` | 工具链快速参考 |
