# Trace 开发文档

cute-trace 承担的小愿望是：让其他组件知道系统执行时实际发生了什么。它接收硬件
观测点的事件，输出定义明确的记录；验证和诊断据此工作。对系统验证而言，事件身份、
顺序与完整性都属于接口承诺。整体角色见 [子项目协作](/modules/#trace)。

`trace/catalogs/cute_trace.json` 定义 category/module/task/event/field/id，是
事件身份和字段顺序的来源。Scala 发出事件，Python 用于检查/解码，host C++
消费系统访存事件。本文与 [事务协议](protocol.md)、[开发与诊断](development.md)
是当前模块文档；目录中的 `format_spec.md` 保留基础格式说明。

## 生成关系

| 来源 | 生成物 |
|---|---|
| catalog | `cutetrace/src/main/scala/trace/generated/CUTETrace.scala`、`CUTETraceIds.scala` |
| catalog | `python/cutetrace/generated/cute_trace_catalog.py` |
| catalog | `generated/cute_trace_catalog.normalized.json` |
| catalog | `generated/cute_trace_events.hpp`，提供 C++ event ID/task/arity |

```sh
python3 tools/trace/check_cute_trace.py
python3 tools/trace/gen_cute_trace.py
python3 tools/trace/gen_cute_trace.py --check
```

按 [系统级运行](/running/) 生成日志后，在同一终端解码；`RUN_DIR` 是该步骤
保存的运行目录：

```sh
python3 tools/trace/decode_cute_trace.py --log "$RUN_DIR/trace.log" --mode jsonl
```

生成 Scala/C++ 之后仍需重新构建相应 simulator/verifier。解码是诊断步骤，
不自动核查全部输出、缺失事件、初态和运行结束。

旧 `CMLStore.storeData`/`VectorStore.storeData` 位于发请求阶段；系统级比较用
真实客户端 A/D 握手事件。两者可以同时存在，内存重建只能选择一个权威更新层，
不能将同一写入重复应用。
