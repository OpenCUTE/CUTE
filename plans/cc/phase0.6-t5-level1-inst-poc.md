# Phase 0.6 Task 5: Level1_Inst PoC 插点详细步骤

## 目标

在 5 个 CUTE 模块中插入 CUTETrace 调用，使 Verilator 仿真日志中输出 `cute_inst` 和 `cute_task` 的 compact trace，Level1_Inst 检查器可校验 task 生命周期。

## 设计原则

- **各模块用本地计数器描述自己的事件**，不跨模块传递 trace ID
- TaskController 用 `macroInstCount` 记录收到的宏指令数量，用 `microTaskIssueCount` 记录发出的微任务数量
- AML/BML/CML/MTE 用 `taskCount` 记录各自接收到的 micro task 数量
- **不修改任何 MicroTaskConfigIO Bundle**，不改 MicroInst Bundle

## 涉及文件

| 文件 | 操作 |
|---|---|
| `trace/catalogs/cute_trace.json` | 修改 AML/BML/CML/MTE event fields: `macro_id/micro_id/scp_id` → `task_count` |
| `trace/cutetrace/src/main/scala/trace/generated/CUTETrace.scala` | 重新生成 |
| `trace/cutetrace/src/main/scala/trace/generated/CUTETraceIds.scala` | 重新生成 |
| `src/main/scala/TaskController.scala` | 加 2 个计数器 + 5 个 trace event |
| `src/main/scala/AMemoryLoader.scala` | 加 1 个计数器 + 2 个 trace event |
| `src/main/scala/BMemoryLoader.scala` | 加 1 个计数器 + 2 个 trace event |
| `src/main/scala/CMemoryLoader.scala` | 加 2 个计数器 + 4 个 trace event |
| `src/main/scala/MatrixTE.scala` | 加 1 个计数器 + 2 个 trace event |

路径相对于 `/root/opencute/CUTE/`。

---

## Step 1: 修改 catalog JSON 中的 event fields

文件：`trace/catalogs/cute_trace.json`

### 1.1 TaskController 事件 — 保持不变

TaskController 自己管理 `macro_id` 和 `micro_id`，这些字段对 TC 有意义：

```
TaskControllerTrace.macroInstInsert  → macro_id, opcode
TaskControllerTrace.macroInstDecodeStart → macro_id, opcode
TaskControllerTrace.macroInstDecodeEnd → macro_id, load_tasks, compute_tasks, store_tasks
TaskControllerTrace.microTaskIssue → macro_id, micro_id, target_task_id
TaskControllerTrace.microTaskCommit → macro_id, micro_id, target_task_id
```

不需要改。

### 1.2 AML/BML/CML/MTE 事件 — 改为 `task_count`

将所有 MemoryLoader 和 MTE 事件的 fields 从 `macro_id, micro_id, scp_id`（或 `macro_id, micro_id, a_scp_id, b_scp_id, c_scp_id`）改为单一字段 `task_count`：

**AMLLoad.taskStart 和 AMLLoad.taskEnd:**

```json
"fields": [
  { "name": "task_count", "type": "uint", "fmt": "dec" }
],
"render": "task_count={task_count}"
```

**BMLLoad.taskStart 和 BMLLoad.taskEnd:** 同上。

**CMLLoad.taskStart 和 CMLLoad.taskEnd:** 同上。

**CMLStore.taskStart 和 CMLStore.taskEnd:** 同上。

**MTECompute.taskStart 和 MTECompute.taskEnd:** 同上。

每个模块内的 `task_count` 是该模块本地维护的计数器寄存器，每接受一个 micro task +1。不同模块的 `task_count` 独立计数。

---

## Step 2: 重新生成 Scala API

```bash
python3 tools/trace/gen_cute_trace.py \
  --catalog trace/catalogs/cute_trace.json \
  --scala-out trace/cutetrace/src/main/scala/trace/generated \
  --python-out trace/python/cutetrace/generated \
  --build-out trace/generated
```

生成后的 API 形态示例：

```scala
object AMLLoad {
  def taskStart(cond: Bool, task_count: UInt)(implicit ctx: CUTETraceContext): Unit = {
    CUTETracePrintf.emit(cond = cond, categoryId = CUTETraceIds.Category.cute_task)(
      compact = {
        printf("CT,1,%x,%x,%x,%x\n", ctx.cycle,
               CUTETraceIds.Task.AMLLoad.U,
               CUTETraceIds.Event.AMLLoad_taskStart.U,
               task_count)
      },
      human = {
        printf("CTH c=%d task=AMLLoad event=taskStart task_count=%d\n",
               ctx.cycle, task_count)
      }
    )
  }
  def taskEnd(cond: Bool, task_count: UInt)(implicit ctx: CUTETraceContext): Unit = { ... }
}
```

---

## Step 3: TaskController 插入 5 个 trace event

文件：`src/main/scala/TaskController.scala`

### 3.1 添加 import 和 implicit traceCtx

文件头部 import 区（~L6）：

```scala
import cute.trace._
import cute.trace.generated.{CUTETrace, CUTETraceIds}
```

class body 中（`io` 定义之后，~L38）：

```scala
implicit val traceCtx: CUTETraceContext = CUTETraceContext(
  cycle = io.DebugTimeStampe,
  params = CUTETraceParams(
    enable = true,
    printMode = CUTETracePrintMode.Compact,
    enabledCategories = Set.empty[Int]  // Set.empty = 所有 category 都输出
  )
)
```

### 3.2 添加本地计数器

```scala
val macroInstCount = RegInit(0.U(8.W))   // 收到的宏指令总数
val microTaskIssueCount = RegInit(0.U(16.W))  // 发出的微任务总数
```

### 3.3 macroInstInsert

**位置**: ~L325, `when(funct === CuteInstConfigs.SendMacroInst.funct.U)` 内部，`when(!MacroInst_FIFO_Full)` 开始处。

```scala
CUTETrace.TaskControllerTrace.macroInstInsert(
  cond = true.B,
  macro_id = macroInstCount,
  opcode = MacroInst_Reg.asTypeOf(new MacroInst).element_type
)
macroInstCount := macroInstCount + 1.U
```

### 3.4 macroInstDecodeStart

**位置**: ~L628, `when(Decoding_MarcoInst_Going === false.B)` 内部，`Decoding_MarcoInst_Going := true.B` 之前。

```scala
CUTETrace.TaskControllerTrace.macroInstDecodeStart(
  cond = true.B,
  macro_id = macroInstCount - 1.U,  // 最近插入的 macro
  opcode = Decoding_MacroInst.element_type
)
```

### 3.5 macroInstDecodeEnd

**位置**: ~L759, `Decoding_MarcoInst_Going := false.B` 之前。

需要维护 decode 阶段生成的 load/compute/store 计数。在 decode 循环中加计数寄存器：

```scala
val decodeLoadCount = RegInit(0.U(8.W))
val decodeComputeCount = RegInit(0.U(8.W))
val decodeStoreCount = RegInit(0.U(8.W))
```

在 decode 开始时（`Decoding_MarcoInst_Going === false.B`）清零，在每次生成对应微指令时 +1。

decode 结束时打 trace：

```scala
CUTETrace.TaskControllerTrace.macroInstDecodeEnd(
  cond = true.B,
  macro_id = macroInstCount - 1.U,
  load_tasks = decodeLoadCount,
  compute_tasks = decodeComputeCount,
  store_tasks = decodeStoreCount
)
```

### 3.6 microTaskIssue

在 Load/Compute/Store issue 的各自分支中打 trace。三个 issue 点共享 `microTaskIssueCount`。

**Load issue** (~L1022, `when(Can_Issue_Load_Micro_Inst && ...)` 内部):

```scala
CUTETrace.TaskControllerTrace.microTaskIssue(
  cond = true.B,
  macro_id = macroInstCount - 1.U,
  micro_id = microTaskIssueCount,
  target_task_id = 0.U  // 0=Load
)
microTaskIssueCount := microTaskIssueCount + 1.U
```

**Compute issue** (~L1206):

```scala
CUTETrace.TaskControllerTrace.microTaskIssue(
  cond = true.B,
  macro_id = macroInstCount - 1.U,
  micro_id = microTaskIssueCount,
  target_task_id = 1.U  // 1=Compute
)
microTaskIssueCount := microTaskIssueCount + 1.U
```

**Store issue** (~L1401):

```scala
CUTETrace.TaskControllerTrace.microTaskIssue(
  cond = true.B,
  macro_id = macroInstCount - 1.U,
  micro_id = microTaskIssueCount,
  target_task_id = 2.U  // 2=Store
)
microTaskIssueCount := microTaskIssueCount + 1.U
```

### 3.7 microTaskCommit

**Load commit** (~L1152):

```scala
CUTETrace.TaskControllerTrace.microTaskCommit(
  cond = true.B,
  macro_id = macroInstCount - 1.U,
  micro_id = Load_MicroInst_FIFO_Tail,
  target_task_id = 0.U
)
```

**Compute commit** (~L1366):

```scala
CUTETrace.TaskControllerTrace.microTaskCommit(
  cond = true.B,
  macro_id = macroInstCount - 1.U,
  micro_id = Compute_MicroInst_FIFO_Tail,
  target_task_id = 1.U
)
```

**Store commit** (~L1434, `when(!Store_Micro_Inst_Wait_C_Finish)` 内部):

```scala
CUTETrace.TaskControllerTrace.microTaskCommit(
  cond = true.B,
  macro_id = macroInstCount - 1.U,
  micro_id = Store_MicroInst_FIFO_Tail,
  target_task_id = 2.U
)
```

> **注意**: `macroInstCount - 1.U` 是简化处理。如果多条宏指令同时在流水线中，需要更精确地追踪每条微指令属于哪条宏指令。PoC 阶段用这个简化方案足够。

---

## Step 4: AMemoryLoader 插入 taskStart / taskEnd

文件：`src/main/scala/AMemoryLoader.scala`

### 4.1 添加 import、traceCtx、taskCount

文件头部：

```scala
import cute.trace._
import cute.trace.generated.{CUTETrace, CUTETraceIds}
```

class body 中（~L68）：

```scala
implicit val traceCtx: CUTETraceContext = CUTETraceContext(
  cycle = io.DebugInfo.DebugTimeStampe,
  params = CUTETraceParams(
    enable = true,
    printMode = CUTETracePrintMode.Compact,
    enabledCategories = Set(CUTETraceIds.Category.cute_task)
  )
)

val taskCount = RegInit(0.U(16.W))  // AML 接收到的 micro task 总数
```

### 4.2 taskStart

**位置**: ~L134, `when(ConfigInfo.MicroTaskReady && ConfigInfo.MicroTaskValid)` 内部。

```scala
CUTETrace.AMLLoad.taskStart(cond = true.B, task_count = taskCount)
taskCount := taskCount + 1.U
```

### 4.3 taskEnd

**位置**: ~L654, `when(ConfigInfo.MicroTaskEndValid && ConfigInfo.MicroTaskEndReady)` 内部。

```scala
CUTETrace.AMLLoad.taskEnd(cond = true.B, task_count = taskCount - 1.U)
```

---

## Step 5: BMemoryLoader 插入 taskStart / taskEnd

文件：`src/main/scala/BMemoryLoader.scala`

同 Step 4 模式。

### 5.1 添加 import、traceCtx、taskCount

### 5.2 taskStart

**位置**: ~L81, `when(ConfigInfo.MicroTaskReady && ConfigInfo.MicroTaskValid)` 内部。

```scala
CUTETrace.BMLLoad.taskStart(cond = true.B, task_count = taskCount)
taskCount := taskCount + 1.U
```

### 5.3 taskEnd

**位置**: ~L347, `when(io.ConfigInfo.MicroTaskEndValid && io.ConfigInfo.MicroTaskEndReady)` 内部。

```scala
CUTETrace.BMLLoad.taskEnd(cond = true.B, task_count = taskCount - 1.U)
```

---

## Step 6: CMemoryLoader 插入 CMLLoad + CMLStore 各 2 个 event

文件：`src/main/scala/CMemoryLoader.scala`

CML 同时承担 Load 和 Store 任务。用两个独立计数器。

### 6.1 添加 import、traceCtx、taskCount

```scala
import cute.trace._
import cute.trace.generated.{CUTETrace, CUTETraceIds}

implicit val traceCtx: CUTETraceContext = CUTETraceContext(
  cycle = io.DebugInfo.DebugTimeStampe,
  params = CUTETraceParams(
    enable = true,
    printMode = CUTETracePrintMode.Compact,
    enabledCategories = Set(CUTETraceIds.Category.cute_task)
  )
)

val loadTaskCount = RegInit(0.U(16.W))   // CML Load 任务计数
val storeTaskCount = RegInit(0.U(16.W))  // CML Store 任务计数
```

### 6.2 CMLLoad.taskStart

**位置**: ~L94-133, `when(io.ConfigInfo.IsLoadMicroTask === true.B)` 分支中，MicroTaskReady && MicroTaskValid 内部。

```scala
CUTETrace.CMLLoad.taskStart(cond = true.B, task_count = loadTaskCount)
loadTaskCount := loadTaskCount + 1.U
```

### 6.3 CMLLoad.taskEnd

**位置**: ~L596, load task 结束处。

需要区分 load 结束还是 store 结束。用一个 Reg 记录当前任务类型：

```scala
val isLoadTask = RegInit(false.B)
```

在 taskStart 的 load 分支中 `isLoadTask := true.B`，store 分支中 `isLoadTask := false.B`。

```scala
when(isLoadTask) {
  CUTETrace.CMLLoad.taskEnd(cond = true.B, task_count = loadTaskCount - 1.U)
}
```

### 6.4 CMLStore.taskStart

**位置**: ~L115-126, `when(io.ConfigInfo.IsStoreMicroTask === true.B)` 分支中。

```scala
CUTETrace.CMLStore.taskStart(cond = true.B, task_count = storeTaskCount)
storeTaskCount := storeTaskCount + 1.U
isLoadTask := false.B
```

### 6.5 CMLStore.taskEnd

**位置**: ~L883, store task 结束处。

```scala
when(!isLoadTask) {
  CUTETrace.CMLStore.taskEnd(cond = true.B, task_count = storeTaskCount - 1.U)
}
```

---

## Step 7: MatrixTE 插入 MTECompute taskStart / taskEnd

文件：`src/main/scala/MatrixTE.scala`

### 7.1 添加 import、traceCtx、taskCount

```scala
import cute.trace._
import cute.trace.generated.{CUTETrace, CUTETraceIds}

implicit val traceCtx: CUTETraceContext = CUTETraceContext(
  cycle = io.DebugInfo.DebugTimeStampe,
  params = CUTETraceParams(
    enable = true,
    printMode = CUTETracePrintMode.Compact,
    enabledCategories = Set(CUTETraceIds.Category.cute_task)
  )
)

val taskCount = RegInit(0.U(16.W))
val taskActive = RegInit(false.B)
```

### 7.2 taskStart

**位置**: 在 `io.ConfigInfo.MicroTaskValid` 有效的处理逻辑中。

```scala
when(io.ConfigInfo.MicroTaskValid && !taskActive) {
  taskActive := true.B
  CUTETrace.MTECompute.taskStart(cond = true.B, task_count = taskCount)
  taskCount := taskCount + 1.U
}
```

### 7.3 taskEnd

MatrixTE 是纯组合逻辑流水线，没有明确的 "计算完成" 信号。

**PoC 方案**: 在 TaskController 的 Compute 完成回调处（~L1339，所有 Wait 都完成时）打 taskEnd：

```scala
// TaskController 中 Compute 完成时
CUTETrace.MTECompute.taskEnd(cond = true.B, task_count = /* MTE 的 taskCount */)
```

但 TC 无法直接读 MTE 的 `taskCount`。替代方案：**把 MTECompute.taskEnd 也放在 MTE 内部**，用下一个 `ConfigInfo.MicroTaskValid` 到来时触发上一个 task 的 end：

```scala
when(io.ConfigInfo.MicroTaskValid && taskActive) {
  // 上一个 task 结束
  CUTETrace.MTECompute.taskEnd(cond = true.B, task_count = taskCount - 1.U)
  // 新 task 开始
  CUTETrace.MTECompute.taskStart(cond = true.B, task_count = taskCount)
  taskCount := taskCount + 1.U
}
```

这样 MTE 的 trace 完全自包含，不依赖外部信号。最后一个 MTE task 的 end 可以不加（或者加一个 reset 时的清理逻辑）。对 PoC 足够。

---

## Step 8: 编译验证

### 8.1 编译检查

```bash
cd /root/opencute/CUTE
sbt compile
```

### 8.2 Verilator 仿真

运行最小 workload（Level1_Inst 的 matmul），检查日志中是否出现：

```
CT,1,<cycle_hex>,<task_id_hex>,<event_id_hex>,<field0_hex>,...
```

验证项：

1. `CT,1,...,0001,...,0001,...` — macroInstInsert (task=TaskControllerTrace, event=macroInstInsert)
2. `CT,1,...,0001,...,0002,...` — macroInstDecodeStart
3. `CT,1,...,0001,...,0003,...` — macroInstDecodeEnd
4. `CT,1,...,0001,...,0004,...` — microTaskIssue
5. `CT,1,...,0001,...,0005,...` — microTaskCommit
6. `CT,1,...,0002,...,0006,...` — AMLLoad.taskStart (task=AMLLoad, event=taskStart, field=task_count)
7. `CT,1,...,0002,...,0007,...` — AMLLoad.taskEnd
8. 类似检查 BML/CMLLoad/CMLStore/MTECompute 的 taskStart/taskEnd

### 8.3 Level1_Inst 检查器验证

用 Task 6 的解码器解析日志，用 Level1_Inst 检查器校验：

- 同一模块的 task_start / task_end 配对（通过 task_count 单调递增验证）
- TC microTaskIssue 和模块 taskStart 的 cycle 顺序一致性

---

## 执行顺序

```
Step 1: 修改 cute_trace.json — AML/BML/CML/MTE 的 fields 改为 task_count
Step 2: 重新运行 gen_cute_trace.py 生成 Scala API
Step 3: 修改 TaskController.scala — 加 import、traceCtx、2 个计数器、5 个 trace event
Step 4: 修改 AMemoryLoader.scala — 加 import、traceCtx、taskCount、2 个 trace event
Step 5: 修改 BMemoryLoader.scala — 同上
Step 6: 修改 CMemoryLoader.scala — 加 import、traceCtx、2 个计数器、4 个 trace event
Step 7: 修改 MatrixTE.scala — 加 import、traceCtx、taskCount、2 个 trace event
Step 8: 编译 + Verilator 仿真验证
```

Step 4/5/6/7 互相独立，可以并行。

## 与旧 plan 的关键差异

| | 旧 plan | 新 plan |
|---|---|---|
| ConfigIO 修改 | 加 traceMacroId/traceMicroId 到 4 个 Bundle | **不修改** |
| MicroInst Bundle 修改 | 加 traceMacroId 到 3 个 Bundle | **不修改** |
| AML/BML/CML trace fields | macro_id, micro_id, scp_id (需跨模块传递) | **task_count (本地计数器)** |
| MTE trace fields | macro_id, micro_id, a/b/c_scp_id | **task_count (本地计数器)** |
| TaskController 传递 | 需要向 config 端口写 trace 元数据 | **不需要传递** |
| 涉及文件数 | 6 个 Scala 文件 | 5 个 Scala 文件 + 1 个 JSON + 重新生成 |

## 风险和注意事项

1. **task_count 配对**: 同一模块内的 taskStart.task_count 和 taskEnd.task_count 通过时序配对（taskEnd 时 task_count - 1）。Level1 检查器需要理解这个语义。
2. **跨模块 ID 关联**: 检查器通过 cycle 顺序来关联 TC 的 microTaskIssue 和 AML 的 taskStart，而不是通过共享 ID。这对 Level1 足够，后续 Phase 如需精确 ID 关联可再加。
3. **Chisel printf 在 Verilator 中的行为**: `CUTETracePrintf.emit` 中的 `when(cond)` 在 Verilator 中正常工作。
4. **CUTETraceParams enable**: 硬编码 `enable = true`，后续应接入 CuteParams 配置系统。
5. **macro_id in TC**: PoC 中用 `macroInstCount - 1.U`，多条宏指令在流水线中时不精确。可通过给微指令 Bundle 加 `traceMacroId` 来解决，但 PoC 不需要。
