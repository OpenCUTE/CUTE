# Phase 0.6 Plan: CUTETrace Catalog 代码生成开工计划

## 目标

Phase 0.6 开始实现 Verilator CUTETrace 的第一版工程闭环：

```text
trace/catalogs/cute_trace.json
  -> Python 代码生成
  -> 生成 Scala typed trace API
  -> Verilator trace printf
  -> Python 解析 / 解码 / 渲染 / 检查
  -> trace 过滤器校验
```

核心产物：

- catalog JSON 是 trace event、task、field、id 的唯一真相源。
- Python 生成器从 catalog 生成 Scala typed API。
- CUTE 模块通过 `CUTETrace.AMLLoad.mmuReq(...)` 这种 API 打 trace。
- Python 解码器读取同一份 catalog 解码逗号分隔紧凑 printf。
- trace 过滤器通过检查器校验引用的 category、module、task、event。
- 解码时由命令行或 runner 显式指定 catalog。

Phase 0.6 的目标是把 `Level1_Inst` 跑通，并为 `Level2_mem_cute`、`Level2ex_all_cute`、`Level3_mem_vector` 留好稳定扩展路径。

---

## 总体结构

### 文件布局

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
  tests/
    catalogs/
    logs/
    golden/

configs/
  schemas/
    cute_trace_catalog.schema.json
  trace_filters/
    func_level1_inst.yaml
    func_level2_mem_cute.yaml
    func_level2ex_all_cute.yaml
    func_level3_mem_vector.yaml
    perf_topdown_status.yaml

tools/
  trace/
    gen_cute_trace.py
    check_cute_trace.py

src/main/scala/trace/
  CUTETraceContext.scala
  CUTETracePrintf.scala
  CUTETraceParams.scala
  generated/
    CUTETrace.scala
    CUTETraceIds.scala
```

### 文件职责

Catalog 与生成产物：

| 文件 | 职责 |
|---|---|
| `trace/catalogs/cute_trace.json` | 手写维护的 trace catalog，是 category、module、task、event、field、id 的唯一真相源。 |
| `trace/generated/cute_trace_catalog.normalized.json` | 由生成器输出的归一化 catalog，用于 review、diff、CI 检查和解码器稳定输入。 |
| `trace/python/cutetrace/generated/cute_trace_catalog.py` | 由 catalog 生成的 Python 常量和静态索引，供 Python 工具快速引用 id、名称和字段定义。 |

Python 工具库：

| 文件 | 职责 |
|---|---|
| `trace/python/cutetrace/catalog.py` | 读取 catalog，做结构校验、引用校验、id 唯一性校验，并建立按 id/name 查询的索引。 |
| `trace/python/cutetrace/parser.py` | 解析 compact `CT,...` 日志行，输出只包含 version、cycle、task_id、event_id、raw values 的原始记录。 |
| `trace/python/cutetrace/decoder.py` | 用 `catalog.py` 提供的字典把原始记录解码成带 category、module、task、event、field name 的 decoded event。 |
| `trace/python/cutetrace/render.py` | 把 decoded event 渲染成离线可读文本、JSONL 或功能验证检查器需要的输入格式。 |

功能验证检查器：

| 文件 | 职责 |
|---|---|
| `trace/python/func/level1_inst.py` | 检查 CUTE 指令、程序退出、task 生命周期。 |
| `trace/python/func/level2_mem_cute.py` | 在 Level1 正常的基础上检查 CUTE 内部 load/store 访存事件。 |
| `trace/python/func/level2ex_all_cute.py` | 检查 CUTE 计算路径，用于定位包含计算结果的问题。 |
| `trace/python/func/level3_mem_vector.py` | 检查 vector 与 CUTE 配合时的访存事件。 |

配置与脚本：

| 文件 | 职责 |
|---|---|
| `configs/schemas/cute_trace_catalog.schema.json` | JSON Schema，校验 catalog 的基础结构和字段类型。 |
| `configs/trace_filters/*.yaml` | 功能验证或 profile 工具使用的 trace 选择规则。 |
| `scripts/trace/gen_cute_trace.py` | 从 catalog 生成 Scala typed API、Scala id 常量、Python generated catalog 和 normalized catalog。 |
| `scripts/trace/check_cute_trace.py` | 校验 catalog、filter、生成文件之间的一致性。 |

Scala 侧：

| 文件 | 职责 |
|---|---|
| `src/main/scala/trace/CUTETraceContext.scala` | 保存 trace 输出需要的上下文，例如 cycle 和 `CUTETraceParams`。 |
| `src/main/scala/trace/CUTETraceParams.scala` | 定义 trace 开关、`Compact/Human/Both` 打印模式和 category 过滤参数。 |
| `src/main/scala/trace/CUTETracePrintf.scala` | 提供统一 printf runtime，根据参数选择 compact、human 或 both 输出。 |
| `src/main/scala/trace/generated/CUTETrace.scala` | 由 catalog 生成的 typed trace API，例如 `CUTETrace.AMLLoad.mmuReq(...)`。 |
| `src/main/scala/trace/generated/CUTETraceIds.scala` | 由 catalog 生成的 category/task/event id 常量。 |

### 第一版生成策略

第一版采用显式脚本生成：

```bash
python3 scripts/trace/gen_cute_trace.py \
  --catalog trace/catalogs/cute_trace.json \
  --scala-out src/main/scala/trace/generated \
  --python-out trace/python/cutetrace/generated \
  --build-out trace/generated
```

后续接入 `build.sbt`：

```scala
Compile / sourceGenerators += Def.task {
  val catalog = baseDirectory.value / "trace" / "catalogs" / "cute_trace.json"
  val outDir = (Compile / sourceManaged).value / "cute" / "trace" / "generated"
  val generated = CUTETraceCodegen.generate(catalog, outDir)
  generated
}.taskValue
```

Phase 0.6 先使用 Python 代码生成和 checked generated Scala，保证 Chipyard 当前构建路径容易接入。sbt `sourceManaged` 进入第二步优化。

---

## Catalog JSON

### 基本格式

```json
{
  "version": 1,
  "catalog_id": "cute_trace_v1",
  "categories": [
    { "name": "cute_inst", "id": 0, "description": "发往 CUTE 的指令、完成、程序退出相关观测" },
    { "name": "cute_task", "id": 1, "description": "CUTE 内部 task 生命周期观测" },
    { "name": "cute_loadstore", "id": 2, "description": "CUTE 内部访存数据流观测" },
    { "name": "cute_compute", "id": 3, "description": "MTE 计算结果观测" },
    { "name": "vector_loadstore", "id": 4, "description": "vector 访存数据流观测" }
  ],
  "modules": [
    { "name": "TaskController", "id": 1 },
    { "name": "AML", "id": 2 },
    { "name": "BML", "id": 3 },
    { "name": "CML", "id": 4 },
    { "name": "MTE", "id": 5 },
    { "name": "LocalMMU", "id": 6 }
  ],
  "tasks": [
    {
      "name": "AMLLoad",
      "id": 33,
      "module": "AML",
      "method_group": "AMLLoad",
      "description": "A 张量加载任务"
    }
  ],
  "events": [
    {
      "name": "AMLLoad.mmuReq",
      "method": "mmuReq",
      "id": 2,
      "task": "AMLLoad",
      "category": "cute_loadstore",
      "description": "AML 发起 LocalMMU 请求",
      "fields": [
        { "name": "ih", "type": "uint", "fmt": "dec" },
        { "name": "iw", "type": "uint", "fmt": "dec" },
        { "name": "m", "type": "uint", "fmt": "dec" },
        { "name": "k", "type": "uint", "fmt": "dec" },
        { "name": "vaddr", "type": "uint", "fmt": "hex" }
      ],
      "render": "ih={ih} iw={iw} m={m} k={k} vaddr=0x{vaddr:x}"
    }
  ]
}
```

### 字段规则

Phase 0.6 的 Trace 只面向 Verilator 日志，不做硬件侧二进制打包。

因此字段不强制写位宽：

```json
{ "name": "vaddr", "type": "uint", "fmt": "hex" }
```

字段含义：

```text
name:
  字段名，也是 renderer、JSONL、功能验证检查器看到的 key

type:
  解码语义，当前为 uint / sint / bool

fmt:
  默认打印和可读文本渲染格式，当前为 dec / hex / bin / bool

description:
  可选的人类说明
```

第一版生成器不生成 `Cat(...)`，不做 `fit/pad/truncate`，也不把多个字段拼成无分隔的十六进制 payload。

### ID 规则

```text
category.id:
  小整数，保持稳定

module.id:
  小整数，保持稳定

task.id:
  紧凑 printf 中使用的稳定 UInt id

event.id:
  全局唯一，保持稳定

field order:
  compact 日志中的字段值顺序
```

ID 管理策略：

- 新 task / event 分配新 id。
- 已发布 id 永久保留。
- 旧 event 退出使用时标记 `deprecated: true`。
- event 字段语义变化时新增 event 名称和 id。
- field 顺序作为日志 ABI 的一部分。日志里不打印字段名，解码器用 catalog field 顺序还原字段名。
- catalog schema 和检查脚本校验 category/module/task/event id 唯一性、field 名唯一性、method 名合法性。

---

## 生成的 Scala API

### 使用方式

CUTE 模块中写：

```scala
import cute.trace._

class AMemoryLoader(...)(implicit p: Parameters) extends CuteModule {
  implicit val traceCtx: CUTETraceContext =
    CUTETraceContext(cycle = io.DebugInfo.DebugTimeStampe, params = CUTETraceParams.default)

  CUTETrace.AMLLoad.mmuReq(
    cond = Request.fire,
    ih = Current_IH_Index,
    iw = Current_IW_Index,
    m = CurrentLoaded_BlockTensor_M,
    k = CurrentLoaded_BlockTensor_K,
    vaddr = Request.bits.RequestVirtualAddr
  )
}
```

### 生成后的 API 形态

```scala
package cute.trace.generated

import chisel3._
import cute.trace._

object CUTETrace {
  object AMLLoad {
    def mmuReq(
      cond: Bool,
      ih: UInt,
      iw: UInt,
      m: UInt,
      k: UInt,
      vaddr: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_loadstore
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.AMLLoad.U,
            CUTETraceIds.Event.AMLLoad_mmuReq.U,
            ih, iw, m, k, vaddr
          )
        },
        human = {
          printf(
            "CTH c=%d task=AMLLoad event=mmuReq ih=%d iw=%d m=%d k=%d vaddr=0x%x\n",
            ctx.cycle, ih, iw, m, k, vaddr
          )
        }
      )
    }
  }
}
```

生成器负责：

- 把 `method_group` 生成成嵌套 object。
- 把 `method` 生成成 Scala 方法。
- 把 catalog field 生成成方法参数。
- 按 field 顺序生成 compact printf 参数。
- 按 field 名称和 `fmt` 生成 human printf 格式串。
- 生成 category/task/event id 常量。
- 在文件头写入 `AUTO-GENERATED FROM trace/catalogs/cute_trace.json`。

### 手写 Scala runtime

`CUTETraceContext.scala`：

```scala
package cute.trace

import chisel3._

case class CUTETraceContext(
  cycle: UInt,
  params: CUTETraceParams
)
```

`CUTETraceParams.scala`：

```scala
package cute.trace

sealed trait CUTETracePrintMode
object CUTETracePrintMode {
  case object Compact extends CUTETracePrintMode
  case object Human extends CUTETracePrintMode
  case object Both extends CUTETracePrintMode
}

case class CUTETraceParams(
  enable: Boolean = false,
  printMode: CUTETracePrintMode = CUTETracePrintMode.Compact,
  enabledCategories: Set[Int] = Set.empty
)

object CUTETraceParams {
  val default: CUTETraceParams = CUTETraceParams()
}
```

`CUTETracePrintf.scala`：

```scala
package cute.trace

import chisel3._
import chisel3.util._

object CUTETracePrintf {
  def emit(
    cond: Bool,
    categoryId: Int
  )(
    compact: => Unit,
    human: => Unit
  )(implicit ctx: CUTETraceContext): Unit = {
    val enabled = ctx.params.enable &&
      (ctx.params.enabledCategories.isEmpty || ctx.params.enabledCategories.contains(categoryId))

    ctx.params.printMode match {
      case CUTETracePrintMode.Compact =>
        if (enabled) {
          when(cond) {
            compact
          }
        }
      case CUTETracePrintMode.Human =>
        if (enabled) {
          when(cond) {
            human
          }
        }
      case CUTETracePrintMode.Both =>
        if (enabled) {
          when(cond) {
            compact
            human
          }
        }
    }
  }
}
```

`Compact` 输出给 parser 和功能验证使用，`Human` 输出给人直接看，`Both` 在 bringup 时同时输出两行。具体 task name、event name、字段名、字段格式都由 catalog 生成到 Scala API 中，模块作者只调用 `CUTETrace.AMLLoad.mmuReq(...)`。

---

## Python 代码生成

### 命令行入口

```bash
python3 scripts/trace/gen_cute_trace.py \
  --catalog trace/catalogs/cute_trace.json \
  --scala-out src/main/scala/trace/generated \
  --python-out trace/python/cutetrace/generated \
  --build-out trace/generated
```

可选检查模式：

```bash
python3 scripts/trace/gen_cute_trace.py \
  --catalog trace/catalogs/cute_trace.json \
  --scala-out src/main/scala/trace/generated \
  --python-out trace/python/cutetrace/generated \
  --build-out trace/generated \
  --check
```

`--check` 做 dry-run，比较生成结果和工作区文件内容，用于 CI。

### 生成器步骤

```text
读取 JSON
校验 JSON schema
归一化 catalog
检查 id 唯一性
检查 method 名称
检查 field 名称 / 类型 / fmt
输出归一化 catalog JSON
输出 Scala CUTETraceIds.scala
输出 Scala CUTETrace.scala
输出 Python generated catalog module
输出摘要报告
```

### Catalog 归一化

生成器输出 normalized catalog，供 review、diff 和 Python 解码器使用。日志解码时由命令行或 runner 显式指定 catalog 文件。

Verilator compact 日志：

```text
CT,1,<cycle_hex>,<task_id_hex>,<event_id_hex>,<field0_hex>,<field1_hex>,...
```

Verilator human 日志：

```text
CTH c=<cycle_dec> task=<task_name> event=<event_name> field=value ...
```

---

## 过滤器一致性

### 过滤器 YAML

```yaml
version: 1
name: func_level2_mem_cute
purpose: func
description: Level2_mem_cute 功能验证使用的过滤器，选择 CUTE load/store 事件。
status: draft

include:
  categories: [cute_loadstore]
  modules: [AML, BML, CML, LocalMMU]
  tasks: []
  events:
    - AMLLoad.mmuReq
    - CMLStore.storeData

exclude:
  deprecated: true
```

### 校验规则

`scripts/trace/check_cute_trace.py` 读取：

```text
trace/catalogs/cute_trace.json
configs/trace_filters/*.yaml
```

检查：

- 过滤器引用的 category 在 catalog 中存在。
- 过滤器引用的 module 在 catalog 中存在。
- 过滤器引用的 task 在 catalog 中存在。
- 过滤器引用的 event 在 catalog 中存在。
- 过滤器的 `purpose` 和功能验证等级用途一致。
- stable 过滤器引用的 event 处于 active 状态。

输出：

```text
TRACE_CATALOG_OK
TRACE_FILTER_OK func_level1_inst
TRACE_FILTER_OK func_level2_mem_cute
TRACE_FILTER_OK func_level2ex_all_cute
TRACE_FILTER_OK func_level3_mem_vector
TRACE_FILTER_OK perf_topdown_status
```

---

## 解码器与渲染器

### 解析器

输入：

```text
CT,1,1e240,21,02,3,7,c,1,80204000
```

输出结构：

```python
TraceRecord(
    version=1,
    cycle=123456,
    task_id=0x21,
    event_id=0x02,
    values=[0x3, 0x7, 0xc, 0x1, 0x80204000],
)
```

### 解码器

根据 catalog：

```python
DecodedTraceEvent(
    cycle=123456,
    category="cute_loadstore",
    module="AML",
    task="AMLLoad",
    event="AMLLoad.mmuReq",
    fields={
        "ih": 3,
        "iw": 7,
        "m": 12,
        "k": 1,
        "vaddr": 0x80204000,
    },
)
```

### 渲染器

可读文本：

```text
[123456][cute_loadstore][AML.AMLLoad.mmuReq] ih=3 iw=7 m=12 k=1 vaddr=0x80204000
```

JSONL：

```json
{"cycle":123456,"category":"cute_loadstore","module":"AML","task":"AMLLoad","event":"AMLLoad.mmuReq","ih":3,"iw":7,"m":12,"k":1,"vaddr":"0x80204000"}
```

---

## Level1_Inst 第一版落点

Phase 0.6 优先实现 Level1_Inst。

### Catalog 事件

```text
TaskControllerTrace.macroInstInsert
TaskControllerTrace.macroInstDecodeStart
TaskControllerTrace.macroInstDecodeEnd
TaskControllerTrace.microTaskIssue
TaskControllerTrace.microTaskCommit

AMLLoad.taskStart
AMLLoad.taskEnd
BMLLoad.taskStart
BMLLoad.taskEnd
CMLLoad.taskStart
CMLLoad.taskEnd
CMLStore.taskStart
CMLStore.taskEnd
MTECompute.taskStart
MTECompute.taskEnd
```

### Level1_Inst 检查器

`trace/python/func/level1_inst.py` 检查：

```text
task_start / task_end 配对
TaskController issue 与模块 task_start 对齐
模块 task_end 与 TaskController commit 对齐
同一 task_id 生命周期单调
缺失 task_end 输出错误
重复 task_start 输出错误
```

输出：

```text
LEVEL1_INST_PASS
LEVEL1_INST_FAIL <reason>
```

---

## Level2/Level2ex/Level3 扩展点

### Level2_mem_cute

第一批 catalog 占位：

```text
AMLLoad.loadReq
AMLLoad.loadRsp
AMLLoad.loadData
BMLLoad.loadReq
BMLLoad.loadRsp
BMLLoad.loadData
CMLStore.storeReq
CMLStore.storeData
CMLStore.storeAck
LocalMMU.mmuReq
LocalMMU.mmuRsp
```

检查器目标：

```text
load 请求/响应配对
store 写回数据重建
LocalMMU source id 生命周期检查
最小 D tensor 重建
```

### Level2ex_all_cute

第一批 catalog 占位：

```text
MTECompute.computeStart
MTECompute.computeInput
MTECompute.computeResult
MTECompute.computeEnd
```

检查器目标：

```text
MTE compute result 提取
result fragment 对齐
参考模型对比
```

---

## 与现有 CUTE 代码接入

### Import 路径

Scala 源码路径可以是：

```text
src/main/scala/trace/CUTETraceContext.scala
src/main/scala/trace/generated/CUTETrace.scala
```

实际 package 由文件内声明决定：

生成包名：

```scala
package cute.trace.generated
```

手写 runtime 包名：

```scala
package cute.trace
```

模块使用：

```scala
import cute.trace._
import cute.trace.generated.CUTETrace
```

### Context 接入

已有模块中普遍有：

```scala
io.DebugInfo.DebugTimeStampe
```

第一版用它作为 trace cycle：

```scala
implicit val traceCtx =
  CUTETraceContext(io.DebugInfo.DebugTimeStampe, CUTETraceParams.default)
```

后续可以在 `CuteModule` 增加 helper：

```scala
def cuteTraceContext(cycle: UInt): CUTETraceContext =
  CUTETraceContext(cycle, CUTETraceParams.default)
```

### Config 接入

Phase 0.6 的最小接入：

```scala
object CUTETraceBuildConfig {
  val enable = true
  val printMode = CUTETracePrintMode.Compact
  val enabledCategories = Set(CUTETraceIds.Category.cute_inst, CUTETraceIds.Category.cute_task)
}
```

后续接入 `CuteParams`：

```scala
case class CUTETraceParamsInCuteParams(
  enable: Boolean,
  printMode: String,
  enabledCategories: Seq[String]
)
```

Phase 0.6 先让 cute_inst 和 cute_task 在 Verilator 中可见。

---

## 开发任务

### Task 1: Catalog schema 与 seed catalog

产物：

```text
configs/schemas/cute_trace_catalog.schema.json
trace/catalogs/cute_trace.json
```

验收：

- schema 覆盖 category/module/task/event/field。
- seed catalog 包含 cute_inst 和 cute_task 最小事件。
- catalog 中包含 cute_loadstore、cute_compute、vector_loadstore category 定义。

### Task 2: Python catalog loader/validator

产物：

```text
trace/python/cutetrace/catalog.py
scripts/trace/check_cute_trace.py
```

验收：

- 能读取 catalog。
- 能检查 id 唯一性。
- 能检查 event/task/module/category 引用。
- 能检查 field type/fmt。
- 能输出 normalized JSON。

### Task 3: Python 到 Scala 代码生成

产物：

```text
scripts/trace/gen_cute_trace.py
src/main/scala/trace/generated/CUTETrace.scala
src/main/scala/trace/generated/CUTETraceIds.scala
trace/python/cutetrace/generated/cute_trace_catalog.py
trace/generated/cute_trace_catalog.normalized.json
```

验收：

- 运行生成器后生成 Scala typed API。
- `CUTETrace.AMLLoad.taskStart(...)` 这类方法存在。
- 生成文件头包含 catalog path。
- `--check` 能发现生成文件过期。

### Task 4: Scala trace runtime

产物：

```text
src/main/scala/trace/CUTETraceContext.scala
src/main/scala/trace/CUTETraceParams.scala
src/main/scala/trace/CUTETracePrintf.scala
```

验收：

- Compact printf 能输出 `CT,1,<cycle>,<task>,<event>,...`。
- Human printf 能输出 `CTH c=... task=... event=... field=value ...`。
- Both 模式能同时输出 compact 和 human 两行。
- category enable 能在 Scala elaboration 时控制输出范围。
- 字段顺序和打印格式行为稳定。

### Task 5: Level1_Inst PoC 插点

优先模块：

```text
TaskController.scala
AMemoryLoader.scala
BMemoryLoader.scala
CMemoryLoader.scala
MatrixTE.scala
```

验收：

- TaskController 输出 macro/micro lifecycle。
- AML/BML/CML/MTE 输出 task_start/task_end。
- Verilator 日志中能看到 cute_inst 和 cute_task compact trace。
- Level1_Inst 检查器能跑通一条最小 workload。

### Task 6: 解码器 / 渲染器 / JSONL

产物：

```text
trace/python/cutetrace/parser.py
trace/python/cutetrace/decoder.py
trace/python/cutetrace/render.py
```

验收：

- 紧凑日志能解码成 decoded event。
- 可读文本输出清晰。
- JSONL 每行一个 event。
- catalog 文件缺失或版本不兼容时输出明确错误。

### Task 7: 过滤器检查器

产物：

```text
configs/trace_filters/func_level1_inst.yaml
configs/trace_filters/func_level2_mem_cute.yaml
configs/trace_filters/func_level2ex_all_cute.yaml
configs/trace_filters/func_level3_mem_vector.yaml
configs/trace_filters/perf_topdown_status.yaml
scripts/trace/check_cute_trace.py
```

验收：

- 过滤器引用 catalog 中存在的 category/module/task/event。
- 过期过滤器在检查阶段报错。
- `func_level1_inst` 能选出 cute_inst 和 cute_task event。

### Task 8: 构建入口

产物：

```text
Makefile 或 scripts/trace/README.md
```

推荐命令：

```bash
python3 scripts/trace/gen_cute_trace.py --catalog trace/catalogs/cute_trace.json --scala-out src/main/scala/trace/generated --python-out trace/python/cutetrace/generated --build-out trace/generated
python3 scripts/trace/check_cute_trace.py --catalog trace/catalogs/cute_trace.json --filters configs/trace_filters
```

验收：

- 新人按 README 可以生成 trace API。
- CI / 本地检查可以发现 catalog、filter、生成文件之间的漂移。

---

## 开工顺序

```text
1. 写 cute_trace_catalog.schema.json
2. 写 cute_trace.json 的 cute_inst/cute_task seed
3. 写 catalog.py loader + validator
4. 写 gen_cute_trace.py 生成 Scala ids / API / Python generated catalog
5. 写 CUTETraceContext/Params/Printf runtime
6. 在 TaskController 插第一批 cute_inst/cute_task trace
7. 写 parser / decoder / render
8. 跑一个 Verilator 小日志并解码
9. 加过滤器检查器
10. 扩展 AML/BML/CML/MTE task_start/task_end
```

---

## 最终验收标准

Phase 0.6 完成时，应满足：

1. `trace/catalogs/cute_trace.json` 成为 CUTETrace 的唯一真相源。
2. Python 生成器可以生成 Scala typed API。
3. CUTE 模块可以调用 `CUTETrace.<Task>.<event>(...)`。
4. Verilator 输出 compact `CT` 日志，解码时由 runner 或命令行指定 catalog。
5. Python 解码器可以解码紧凑日志。
6. 可读文本和 JSONL 渲染器可用。
7. 过滤器检查器可以校验 `configs/trace_filters/*.yaml`。
8. Level1_Inst 检查器可以检查最小 inst/task 生命周期。
9. generated Scala / Python 文件可以通过 `--check` 防止漂移。
10. Level2_mem_cute、Level2ex_all_cute、Level3_mem_vector 有 catalog 扩展点和检查器文件骨架。
