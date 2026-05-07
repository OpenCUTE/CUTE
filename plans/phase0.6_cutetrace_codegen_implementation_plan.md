# Phase 0.6 Plan: CUTETrace Catalog Codegen 开工计划

## 目标

Phase 0.6 开始实现 Verilator CUTETrace 的第一版工程闭环：

```text
trace/catalogs/cute_trace.json
  -> Python codegen
  -> generated Scala typed trace API
  -> Verilator compact printf
  -> Python parser/decoder/renderer/checker
  -> trace filter validation
```

核心产物：

- catalog JSON 是 trace event / task / field / id 的唯一真相源。
- Python generator 从 catalog 生成 Scala typed API。
- CUTE 模块通过 `CUTETrace.AMLLoad.mmuReq(...)` 这种 API 打 trace。
- Python decoder 读取同一份 catalog 解码 compact printf。
- trace filter 通过 checker 校验引用的 level/module/task/event。
- Verilator 日志携带 `catalog_hash`，解码时校验 catalog 版本。

Phase 0.6 的目标是把 `F0_task` 跑通，再给 `F1_loadstore` 和 `F2_compute` 留好稳定扩展路径。

---

## 总体结构

### 文件布局

```text
trace/
  catalogs/
    cute_trace.json
  generated/
    cute_trace_catalog_hash.txt
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
      task_model.py
      loadstore_model.py
      compute_model.py
  tests/
    catalogs/
    logs/
    golden/

configs/
  schemas/
    cute_trace_catalog.schema.json
  trace_filters/
    func_task.yaml
    func_loadstore.yaml
    func_compute.yaml
    perf_topdown_status.yaml

scripts/
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
    CUTETraceCatalogHash.scala
```

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

Phase 0.6 先使用 Python codegen 和 checked generated Scala，保证 Chipyard 当前构建路径容易接入。sbt `sourceManaged` 进入第二步优化。

---

## Catalog JSON

### 基本格式

```json
{
  "version": 1,
  "catalog_id": "cute_trace_v1",
  "levels": [
    { "name": "F0_task", "id": 0, "description": "task lifecycle" },
    { "name": "F1_loadstore", "id": 1, "description": "load/store data flow" },
    { "name": "F2_compute", "id": 2, "description": "MTE compute result" }
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
      "description": "A tensor load task"
    }
  ],
  "events": [
    {
      "name": "AMLLoad.mmuReq",
      "method": "mmuReq",
      "id": 2,
      "task": "AMLLoad",
      "level": "F1_loadstore",
      "description": "AML issues LocalMMU request",
      "fields": [
        { "name": "ih", "width": 16, "type": "uint", "fmt": "dec" },
        { "name": "iw", "width": 16, "type": "uint", "fmt": "dec" },
        { "name": "m", "width": 16, "type": "uint", "fmt": "dec" },
        { "name": "k", "width": 16, "type": "uint", "fmt": "dec" },
        { "name": "vaddr", "width": 64, "type": "uint", "fmt": "hex" }
      ],
      "render": "ih={ih} iw={iw} m={m} k={k} vaddr=0x{vaddr:x}"
    }
  ]
}
```

### ID 规则

```text
level.id:
  small integer, stable

module.id:
  small integer, stable

task.id:
  stable UInt id in compact printf

event.id:
  stable inside task

field order:
  payload packing order
```

ID 管理策略：

- 新 task / event 分配新 id。
- 已发布 id 永久保留。
- 旧 event 退出使用时标记 `deprecated: true`。
- event 字段语义变化时新增 event 名称和 id。
- field 顺序作为 payload ABI 的一部分。
- catalog schema 校验 id 唯一性、field 名唯一性、method 名合法性。

---

## Generated Scala API

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
      val payload = Cat(
        CUTETracePrintf.fit(vaddr, 64),
        CUTETracePrintf.fit(k, 16),
        CUTETracePrintf.fit(m, 16),
        CUTETracePrintf.fit(iw, 16),
        CUTETracePrintf.fit(ih, 16)
      )

      CUTETracePrintf.emit(
        cond = cond,
        cycle = ctx.cycle,
        level = CUTETraceLevel.F1Loadstore,
        taskId = CUTETraceIds.Task.AMLLoad,
        eventId = CUTETraceIds.Event.AMLLoad_mmuReq,
        payload = payload
      )
    }
  }
}
```

生成器负责：

- 把 `method_group` 生成成 nested object。
- 把 `method` 生成成 Scala method。
- 把 catalog field 生成成 method 参数。
- 按 field 顺序生成 payload pack。
- 生成 task/event/level id 常量。
- 生成 catalog hash 常量。
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
  case object Off extends CUTETracePrintMode
  case object Compact extends CUTETracePrintMode
  case object Human extends CUTETracePrintMode
  case object Both extends CUTETracePrintMode
}

sealed trait CUTETraceLevel
object CUTETraceLevel {
  case object F0Task extends CUTETraceLevel
  case object F1Loadstore extends CUTETraceLevel
  case object F2Compute extends CUTETraceLevel
}

case class CUTETraceParams(
  enable: Boolean = false,
  mode: CUTETracePrintMode = CUTETracePrintMode.Compact,
  levels: Set[CUTETraceLevel] = Set(CUTETraceLevel.F0Task),
  catalogHash: BigInt = CUTETraceCatalogHash.value
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
  def fit(x: UInt, width: Int): UInt = {
    val w = x.getWidth
    if (w == width) x
    else if (w > width) x(width - 1, 0)
    else Cat(0.U((width - w).W), x)
  }

  def emit(
    cond: Bool,
    cycle: UInt,
    level: CUTETraceLevel,
    taskId: Int,
    eventId: Int,
    payload: UInt
  )(implicit ctx: CUTETraceContext): Unit = {
    val enabled = ctx.params.enable && ctx.params.levels.contains(level)

    if (enabled) {
      ctx.params.mode match {
        case CUTETracePrintMode.Compact =>
          when(cond) {
            printf(
              "CT v=1 h=%x c=%d t=%x e=%x p=%x\n",
              ctx.params.catalogHash.U,
              cycle,
              taskId.U,
              eventId.U,
              payload
            )
          }
        case CUTETracePrintMode.Human =>
          when(cond) {
            printf(
              "CTH c=%d task=%x event=%x payload=%x\n",
              cycle,
              taskId.U,
              eventId.U,
              payload
            )
          }
        case CUTETracePrintMode.Both =>
          when(cond) {
            printf("CT v=1 h=%x c=%d t=%x e=%x p=%x\n", ctx.params.catalogHash.U, cycle, taskId.U, eventId.U, payload)
            printf("CTH c=%d task=%x event=%x payload=%x\n", cycle, taskId.U, eventId.U, payload)
          }
        case CUTETracePrintMode.Off =>
      }
    }
  }
}
```

第一版 Scala runtime 聚焦 compact printf。Human mode 可以先用通用 `task/event/payload` 输出，漂亮字段级渲染交给 Python renderer。

---

## Python Codegen

### CLI

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

### Generator 步骤

```text
load JSON
validate JSON schema
normalize catalog
check id uniqueness
check method names
check field names / widths / types
compute stable catalog hash
emit normalized catalog JSON
emit Scala CUTETraceIds.scala
emit Scala CUTETraceCatalogHash.scala
emit Scala CUTETrace.scala
emit Python generated catalog module
emit summary report
```

### Catalog hash

hash 输入使用 normalized JSON：

```text
sort object keys
preserve event field order
remove comments / whitespace
include version / ids / fields / render templates
```

hash 输出：

```text
trace/generated/cute_trace_catalog_hash.txt
src/main/scala/trace/generated/CUTETraceCatalogHash.scala
trace/python/cutetrace/generated/cute_trace_catalog.py
```

Verilator compact log：

```text
CT v=1 h=<catalog_hash> c=<cycle> t=<task_id> e=<event_id> p=<hex_payload>
```

Python decoder 校验：

```text
log hash == catalog hash
```

---

## Filter 一致性

### Filter YAML

```yaml
version: 1
name: func_loadstore
purpose: func
description: load/store trace events for F1 checker
status: draft

include:
  levels: [F1_loadstore]
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

- filter 引用的 level 在 catalog 中存在。
- filter 引用的 module 在 catalog 中存在。
- filter 引用的 task 在 catalog 中存在。
- filter 引用的 event 在 catalog 中存在。
- filter 的 `purpose` 和 level 用途一致。
- stable filter 引用的 event 处于 active 状态。

输出：

```text
TRACE_CATALOG_OK
TRACE_FILTER_OK func_task
TRACE_FILTER_OK func_loadstore
TRACE_FILTER_OK func_compute
TRACE_FILTER_OK perf_topdown_status
```

---

## Decoder 与 Renderer

### Parser

输入：

```text
CT v=1 h=3c89... c=123456 t=21 e=02 p=00030007000c000180204000
```

输出结构：

```python
TraceRecord(
    cycle=123456,
    catalog_hash="3c89...",
    task_id=0x21,
    event_id=0x02,
    payload="00030007000c000180204000",
)
```

### Decoder

根据 catalog：

```python
DecodedTraceEvent(
    cycle=123456,
    level="F1_loadstore",
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

### Renderer

Pretty text：

```text
[123456][F1_loadstore][AML.AMLLoad.mmuReq] ih=3 iw=7 m=12 k=1 vaddr=0x80204000
```

JSONL：

```json
{"cycle":123456,"level":"F1_loadstore","module":"AML","task":"AMLLoad","event":"AMLLoad.mmuReq","ih":3,"iw":7,"m":12,"k":1,"vaddr":"0x80204000"}
```

---

## F0_task 第一版落点

Phase 0.6 优先实现 F0_task。

### Catalog events

```text
TaskController.macroInstInsert
TaskController.macroInstDecodeStart
TaskController.macroInstDecodeEnd
TaskController.microTaskIssue
TaskController.microTaskCommit

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

### F0 checker

`trace/python/func/task_model.py` 检查：

```text
task_start / task_end 配对
TaskController issue 与模块 task_start 对齐
模块 task_end 与 TaskController commit 对齐
同一 task_id 生命周期单调
缺失 task_end 输出 error
重复 task_start 输出 error
```

输出：

```text
F0_TASK_PASS
F0_TASK_FAIL <reason>
```

---

## F1_loadstore 与 F2_compute 扩展点

### F1_loadstore

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

checker 目标：

```text
load 请求/响应配对
store 写回数据重建
LocalMMU source id 生命周期检查
最小 D tensor 重建
```

### F2_compute

第一批 catalog 占位：

```text
MTECompute.computeStart
MTECompute.computeInput
MTECompute.computeResult
MTECompute.computeEnd
```

checker 目标：

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
  val mode = CUTETracePrintMode.Compact
  val levels = Set(CUTETraceLevel.F0Task)
}
```

后续接入 `CuteParams`：

```scala
case class CUTETraceParamsInCuteParams(
  enable: Boolean,
  mode: String,
  levels: Seq[String]
)
```

Phase 0.6 先让 F0_task 在 Verilator 中可见。

---

## 开发任务

### Task 1: Catalog schema 与 seed catalog

产物：

```text
configs/schemas/cute_trace_catalog.schema.json
trace/catalogs/cute_trace.json
```

验收：

- schema 覆盖 level/module/task/event/field。
- seed catalog 包含 F0_task 最小事件。
- catalog 中包含 F1_loadstore / F2_compute level 定义。

### Task 2: Python catalog loader/validator

产物：

```text
trace/python/cutetrace/catalog.py
scripts/trace/check_cute_trace.py
```

验收：

- 能读取 catalog。
- 能检查 id 唯一性。
- 能检查 event/task/module/level 引用。
- 能检查 field width/type/fmt。
- 能输出 normalized JSON 和 catalog hash。

### Task 3: Python -> Scala codegen

产物：

```text
scripts/trace/gen_cute_trace.py
src/main/scala/trace/generated/CUTETrace.scala
src/main/scala/trace/generated/CUTETraceIds.scala
src/main/scala/trace/generated/CUTETraceCatalogHash.scala
trace/python/cutetrace/generated/cute_trace_catalog.py
trace/generated/cute_trace_catalog.normalized.json
trace/generated/cute_trace_catalog_hash.txt
```

验收：

- 运行 generator 后生成 Scala typed API。
- `CUTETrace.AMLLoad.taskStart(...)` 这类 method 存在。
- 生成文件头包含 catalog path 和 hash。
- `--check` 能发现 generated file 过期。

### Task 4: Scala trace runtime

产物：

```text
src/main/scala/trace/CUTETraceContext.scala
src/main/scala/trace/CUTETraceParams.scala
src/main/scala/trace/CUTETracePrintf.scala
```

验收：

- compact printf 能输出 `CT v=1 h=... c=... t=... e=... p=...`。
- level enable 能在 Scala elaboration 时控制输出范围。
- payload field fit/pad/truncate 行为稳定。

### Task 5: F0_task PoC 插点

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
- Verilator 日志中能看到 F0_task compact trace。
- F0_task checker 能跑通一条最小 workload。

### Task 6: Decoder / renderer / JSONL

产物：

```text
trace/python/cutetrace/parser.py
trace/python/cutetrace/decoder.py
trace/python/cutetrace/render.py
```

验收：

- compact log 能解码成 decoded event。
- pretty text 可读。
- JSONL 每行一个 event。
- catalog hash mismatch 输出明确错误。

### Task 7: Filter checker

产物：

```text
configs/trace_filters/func_task.yaml
configs/trace_filters/func_loadstore.yaml
configs/trace_filters/func_compute.yaml
configs/trace_filters/perf_topdown_status.yaml
scripts/trace/check_cute_trace.py
```

验收：

- filter 引用 catalog 中存在的 level/module/task/event。
- stale filter 在 check 阶段报错。
- `func_task` 能选出 F0_task event。

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
- CI/本地 check 可以发现 catalog/filter/generated drift。

---

## 开工顺序

```text
1. 写 cute_trace_catalog.schema.json
2. 写 cute_trace.json 的 F0_task seed
3. 写 catalog.py loader + validator
4. 写 gen_cute_trace.py 生成 Scala ids/hash/API
5. 写 CUTETraceContext/Params/Printf runtime
6. 在 TaskController 插第一批 F0_task trace
7. 写 parser/decoder/render
8. 跑一个 Verilator 小日志并解码
9. 加 filter checker
10. 扩展 AML/BML/CML/MTE task_start/task_end
```

---

## 最终验收标准

Phase 0.6 完成时，应满足：

1. `trace/catalogs/cute_trace.json` 成为 CUTETrace 的唯一真相源。
2. Python generator 可以生成 Scala typed API。
3. CUTE 模块可以调用 `CUTETrace.<Task>.<event>(...)`。
4. Verilator 输出 compact `CT` 日志并携带 catalog hash。
5. Python decoder 可以解码 compact 日志。
6. Pretty text 和 JSONL renderer 可用。
7. Filter checker 可以校验 `configs/trace_filters/*.yaml`。
8. F0_task checker 可以检查最小 task lifecycle。
9. generated Scala / Python 文件可以通过 `--check` 防止漂移。
10. F1_loadstore / F2_compute 有 catalog 扩展点和 checker 文件骨架。
