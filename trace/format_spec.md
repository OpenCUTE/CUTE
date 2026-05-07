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

## 功能验证等级

功能验证等级描述检查器的目标，以及它依赖哪些 trace 类别。

| 验证等级 | 含义 | 依赖 | Trace 类别 |
|---|---|---|---|
| `Level1_Inst` | 所有发往 CUTE 的指令正常，程序正常退出，所有 `cute_inst` 和 `cute_task` 正常 | 无 | `cute_inst`, `cute_task` |
| `Level2_mem_cute` | 所有 CUTE 的访存请求正常 | `Level1_Inst` | `cute_loadstore` |
| `Level2ex_all_cute` | CUTE 计算符合 golden 定义，用于定位包含计算路径的问题 | `Level1_Inst` | `cute_loadstore`, `cute_compute` |
| `Level3_mem_vector` | 所有和 vector 配合的任务访存请求正常 | `Level2_mem_cute` | `vector_loadstore` |

`Level2ex_all_cute` 是扩展检查器路径。当调试目标需要定位更宽的 CUTE 侧错误时，可以启用它。

---

## 功能检查器布局

```text
trace/python/func/
  level1_inst.py
  level2_mem_cute.py
  level2ex_all_cute.py
  level3_mem_vector.py
```

每个检查器都消费由过滤器 manifest 选出的 decoded trace event。

---

## 过滤器 Manifest

Phase 0.6 定义这些可复用的过滤器标识：

| 过滤器 | 用途 | 验证等级 | Trace 类别 |
|---|---|---|---|
| `func_level1_inst` | 功能验证 | `Level1_Inst` | `cute_inst`, `cute_task` |
| `func_level2_mem_cute` | 功能验证 | `Level2_mem_cute` | `cute_loadstore` |
| `func_level2ex_all_cute` | 功能验证 | `Level2ex_all_cute` | `cute_loadstore`, `cute_compute` |
| `func_level3_mem_vector` | 功能验证 | `Level3_mem_vector` | `vector_loadstore` |
| `perf_topdown_status` | 性能归因 | status / profile | TopDownStatus |

过滤器 manifest 位于：

```text
configs/trace_filters/*.yaml
```

过滤器引用会对照 `trace/catalogs/cute_trace.json` 校验。

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
      generated/
        cute_trace_catalog.py
    func/
      level1_inst.py
      level2_mem_cute.py
      level2ex_all_cute.py
      level3_mem_vector.py
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
src/main/scala/trace/
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
| `trace/python/cutetrace/generated/cute_trace_catalog.py` | 生成的 Python catalog 常量和静态索引。 |
| `trace/python/func/*.py` | 功能验证等级检查器。 |
| `configs/schemas/cute_trace_catalog.schema.json` | catalog JSON Schema。 |
| `configs/trace_filters/*.yaml` | trace 过滤器 manifest。 |
| `scripts/trace/gen_cute_trace.py` | catalog 到 Scala/Python 生成产物的代码生成入口。 |
| `scripts/trace/check_cute_trace.py` | catalog、filter、生成产物的一致性检查入口。 |
| `src/main/scala/trace/CUTETraceContext.scala` | Chisel trace 上下文。 |
| `src/main/scala/trace/CUTETraceParams.scala` | trace 开关、打印模式和类别过滤参数。 |
| `src/main/scala/trace/CUTETracePrintf.scala` | 统一 printf runtime。 |
| `src/main/scala/trace/generated/CUTETrace.scala` | 生成的 typed trace API。 |
| `src/main/scala/trace/generated/CUTETraceIds.scala` | 生成的 id 常量。 |
