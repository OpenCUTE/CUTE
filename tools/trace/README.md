# CUTETrace 工具链

CUTETrace 提供 catalog-driven 的 trace 定义、代码生成、校验和解码工具链。

## 快速开始

```bash
cd /root/opencute/CUTE
```

### 1. 校验 catalog

```bash
python3 tools/trace/check_cute_trace.py
```

输出：

```text
TRACE_CATALOG_OK catalog=trace/catalogs/cute_trace.json categories=5 modules=6 tasks=6 events=15
```

### 2. 生成 Scala / Python 产物

```bash
python3 tools/trace/gen_cute_trace.py \
  --catalog trace/catalogs/cute_trace.json \
  --scala-out trace/cutetrace/src/main/scala/trace/generated \
  --python-out trace/python/cutetrace/generated \
  --build-out trace/generated
```

产物：

| 文件 | 用途 |
|------|------|
| `trace/cutetrace/.../CUTETrace.scala` | Scala typed trace API，CUTE 模块调用 |
| `trace/cutetrace/.../CUTETraceIds.scala` | Scala id 常量 |
| `trace/python/cutetrace/generated/cute_trace_catalog.py` | Python catalog 索引 |
| `trace/generated/cute_trace_catalog.normalized.json` | catalog 稳定镜像 |

### 3. 检查生成文件是否漂移

```bash
python3 tools/trace/gen_cute_trace.py \
  --catalog trace/catalogs/cute_trace.json \
  --scala-out trace/cutetrace/src/main/scala/trace/generated \
  --python-out trace/python/cutetrace/generated \
  --build-out trace/generated \
  --check
```

不写文件，只比较。不一致返回非 0。

### 4. 解码 Verilator 日志

```bash
# text 模式（可读）
python3 tools/trace/decode_cute_trace.py \
  --log <verilator_log_file>

# JSONL 模式（结构化）
python3 tools/trace/decode_cute_trace.py \
  --log <verilator_log_file> \
  --mode jsonl \
  -o trace_output.jsonl
```

## 文件说明

| 入口 | 用途 |
|------|------|
| `tools/trace/gen_cute_trace.py` | catalog → Scala/Python codegen |
| `tools/trace/check_cute_trace.py` | catalog schema + 语义校验 |
| `tools/trace/decode_cute_trace.py` | compact 日志 → decoded event |
| `trace/catalogs/cute_trace.json` | 唯一真相源 |
| `trace/python/cutetrace/parser.py` | CT 行解析 |
| `trace/python/cutetrace/decoder.py` | event 解码 |
| `trace/python/cutetrace/render.py` | text/jsonl 渲染 |
| `trace/python/cutetrace/catalog.py` | catalog loader + validator |

详细文档见 `doc/sdk-doc/`。

## 工作流

```text
修改 cute_trace.json
  → check_cute_trace.py 校验
  → gen_cute_trace.py 生成 Scala/Python
  → Scala 编译进 CUTE 硬件
  → Verilator 仿真输出 CT compact 日志
  → decode_cute_trace.py 解码
```
