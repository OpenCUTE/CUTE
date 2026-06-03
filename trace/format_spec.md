# CUTE Trace 格式说明

## 范围

CUTE Trace 是面向 Verilator 的语义化 `printf` 机制。

Trace 描述可观测事件。功能验证消费不同的 trace 类别，并在这些事件之上定义验证等级。

trace catalog 是以下内容的唯一真相源：

- trace 类别
- trace 模块
- trace 任务
- trace 事件
- 字段列表
- Scala typed trace API 生成
- Python 解码与渲染
- trace 过滤器校验

当前 catalog 位于：

```text
trace/catalogs/cute_trace.json
```

---

## Trace 流水线

```text
trace/catalogs/cute_trace.json
  -> Python 代码生成
  -> 生成的 Scala typed trace API
  -> Verilator trace printf
  -> Python 解析 / 解码 / 渲染
  -> 功能验证检查器
```

生成后的 Scala API 示例：

```scala
CUTETrace.AMLLoad.taskStart(...)
CUTETrace.TaskControllerTrace.microTaskIssue(...)
CUTETrace.CMLStore.storeData(...)
CUTETrace.VectorStore.storeData(...)
CUTETrace.MTECompute.taskEnd(...)
```

Trace printf 支持三种模式：

| 模式 | 输出 |
|---|---|
| `Compact` | 只输出 compact 行 |
| `Human` | 只输出 human 行 |
| `Both` | 同时输出 compact 和 human 两行 |

compact 行：

```text
CT,1,<cycle_hex>,<task_id_hex>,<event_id_hex>,<field0_hex>,<field1_hex>,...
```

human 行：

```text
CTH c=<cycle_dec> task=<task_name> event=<event_name> field=value ...
```

字段含义：

| 字段 | 含义 |
|---|---|
| `CT` | compact trace 行前缀 |
| `1` | trace printf 格式版本 |
| `<cycle_hex>` | 产生 trace 的 cycle |
| `<task_id_hex>` | task id |
| `<event_id_hex>` | 全局唯一 event id |
| `<field*_hex>` | 按 catalog 字段顺序打印的字段值 |
| `CTH` | human trace 行前缀 |
| `task=<task_name>` | catalog 中的 task 名 |
| `event=<event_name>` | catalog 中的 event 方法名 |
| `field=value ...` | 带字段名的人类可读字段 |

Trace 当前只服务 Verilator 日志，因此字段不强制声明位宽。字段描述只需要 `name`、`type`、`fmt`，可选 `description`。

---

## Trace 类别

Trace 类别描述一个事件属于哪类观测。

| 类别 | 含义 |
|---|---|
| `cute_inst` | 发往 CUTE 的指令、完成、程序退出相关观测 |
| `cute_task` | CUTE 内部 task 的 issue、start、end、commit 生命周期 |
| `cute_loadstore` | CUTE 内部 load 读取和 store 写回 |
| `cute_compute` | CUTE/MTE 计算输入、输出和结果 |
| `vector_loadstore` | vector 与 CUTE 配合时的 vector 访存观测 |

trace 类别在 `trace/catalogs/cute_trace.json` 中定义：

```json
{
  "name": "AMLLoad.taskStart",
  "task": "AMLLoad",
  "category": "cute_task",
  "fields": []
}
```

---

## 文件布局

```text
trace/
  catalogs/
    cute_trace.json
  generated/
    cute_trace_catalog.normalized.json
  python/
    cutetrace/
      catalog.py
      parser.py
      decoder.py
      render.py
      rebuilder.py
      generated/
        cute_trace_catalog.py
    status/
      status_parser.py
      topdown.py
      rule_compare.py
  tests/
    catalogs/
    logs/
    golden/
```

```text
trace/cutetrace/src/main/scala/trace/
  CUTETraceContext.scala
  CUTETracePrintf.scala
  CUTETraceParams.scala
  generated/
    CUTETrace.scala
    CUTETraceIds.scala
```

关键文件职责：

| 文件 | 职责 |
|---|---|
| `trace/catalogs/cute_trace.json` | trace catalog 唯一真相源。 |
| `trace/generated/cute_trace_catalog.normalized.json` | 生成器输出的归一化 catalog，用于 review、diff 和工具输入。 |
| `trace/python/cutetrace/catalog.py` | catalog 加载、校验和查询索引。 |
| `trace/python/cutetrace/parser.py` | 解析 compact `CT,...` 行，得到 raw trace record。 |
| `trace/python/cutetrace/decoder.py` | 结合 catalog 把 raw record 解码成带名字和字段的事件。 |
| `trace/python/cutetrace/render.py` | 把 decoded event 渲染成可读文本、JSONL 或检查器输入。 |
| `trace/python/cutetrace/rebuilder.py` | 从 `CMLStore.storeData` / `VectorStore.storeData` 重建 memory image。 |
| `trace/python/cutetrace/generated/cute_trace_catalog.py` | 生成的 Python catalog 常量和静态索引。 |
| `configs/schemas/cute_trace_catalog.schema.json` | catalog JSON Schema。 |
| `tools/trace/gen_cute_trace.py` | catalog 到 Scala/Python 生成产物的代码生成入口。 |
| `tools/trace/check_cute_trace.py` | catalog、filter、生成产物的一致性检查入口。 |
| `trace/cutetrace/src/main/scala/trace/CUTETraceContext.scala` | Chisel trace 上下文。 |
| `trace/cutetrace/src/main/scala/trace/CUTETraceParams.scala` | trace 开关、打印模式和类别过滤参数。 |
| `trace/cutetrace/src/main/scala/trace/CUTETracePrintf.scala` | 统一 printf runtime。 |
| `trace/cutetrace/src/main/scala/trace/generated/CUTETrace.scala` | 生成的 typed trace API。 |
| `trace/cutetrace/src/main/scala/trace/generated/CUTETraceIds.scala` | 生成的 id 常量。 |
