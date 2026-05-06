# Phase 0.5 Plan: Verilator Trace 与 Top-Down Status 归因

## 目标

Phase 0.5 重新定义 `Trace` 和 `Status` 的边界：

- `Trace` 在 Verilator/仿真中实现，是更好的 `printf`。
- `Status` 用于每个 cycle 的瓶颈归因定性，是后续 FPGA profile 的真正主线。
- Chipyard 现有 `TraceIO` 提供 **status 聚合与 top-level plumbing** 的参考。

Phase 0.5 实施范围：

```text
Verilator Trace:
  用 task_id/event_id/field dictionary 降低日志字符量
  保留可读/可解析的 printf
  支持 parser/decoder 做功能验证

Top-Down Status:
  在模块内产生 status
  在更高层逐级聚合
  在 ChipTop/DigitalTop 层得到最终 bottleneck status
  前期在 Verilator 中直接 printf 聚合好的 status
  软件基于全量日志反复离线解析，打磨更好的归因结构
  归因结构成熟后，进入 FPGA 在线切片/profile 方案设计
```

一句话：

```text
Trace 是 Verilator-only 的语义日志。
Status 是面向 profile/瓶颈归因的体系结构状态分类。
```

---

## 为什么推倒重来

之前讨论过的“全局 event trace stream + FPGA/XDMA ring buffer”方案存在几个根本问题：

- FPGA 上持续 dump 每周期状态会快速超过可持续数据预算。
- Lossless FPGA event stream 会引入反压、pause、quiesce、memory controller 协同等复杂问题。
- verify 需要 lossless 语义。
- 512-bit raw status/event record 即使在 25 MHz 下每周期输出也约为 1.6 GB/s，长期运行的数据量预算会被迅速耗尽。
- FPGA profile 的核心目标是判断每个时间片的系统瓶颈归因。

因此新方案把两件事拆开：

```text
verify/debug:
  在 Verilator 用 printf 解决。

profile/attribution:
  用 status 分类表达瓶颈。
```

---

## 与现有 Chipyard TraceIO 的关系

### 现有 TraceIO 是什么

Chipyard/RocketChip 现有 `TraceIO` 主要服务 instruction commit trace。典型路径是：

```text
core.io.trace
  -> BaseTile.traceSourceNode / traceNode
  -> HasTiles.connectTrace
  -> Cluster.traceNodes
  -> RootContext.traceNodes sinks
  -> CanHaveTraceIO.traceIO
  -> WithTraceIOPunchthrough creates ChipTop trace port
  -> WithCospike connects SpikeCosim in harness
```

它的数据类型中心是：

```scala
class TraceBundle extends Bundle {
  val insns = Vec(coreParams.retireWidth, new TracedInstruction)
  val time = UInt(64.W)
  val custom = coreParams.traceCustom
}
```

也就是说：

```text
TraceIO = per-core commit instruction trace
```

它可以带 `traceCustom` sideband；主要语义仍是 commit trace。

### CUTE 当前如何借鉴

Phase 0.5 借鉴 `TraceIO` 的层级 wiring 思路：

CUTE `Trace` 采用 Verilator printf + 字典机制。CUTE `Status` 采用类似 `TraceIO` 的层级聚合思路。

```text
模块内部产生某类观测信号
  -> tile/domain source node
  -> hierarchical map
  -> root context 聚合
  -> top-level IO 或 harness consumer
```

这条链路更适合被 CUTE `Status` 借鉴：

```text
AML/BML/CML/cache/vector/core status
  -> tile/domain status node
  -> subsystem/root status 聚合
  -> ChipTop/DigitalTop final top-down status
```

结论：

```text
Chipyard TraceIO 为 Status 聚合 plumbing 提供参考。
CUTE Trace 采用 Verilator printf + 字典机制。
```

---

## 概念定义

### Trace

`Trace` 是 Verilator-only 的 printf 日志机制。

目标：

- 替代散落的长字符串 `printf`。
- 用 `task_id/event_id/field_id` 字典机制减少日志字符量。
- 保留可解析性，parser 可以还原漂亮日志。
- 服务 F0/F1/F2 功能验证。
- 综合边界限定在 Verilator/仿真。

示例：

```scala
vtrace(TraceTask.AMLLoad, TraceEvent.MmuReq, Request.fire)(
  TraceField("ih", Current_IH_Index),
  TraceField("iw", Current_IW_Index),
  TraceField("m", CurrentLoaded_BlockTensor_M),
  TraceField("k", CurrentLoaded_BlockTensor_K),
  TraceField("vaddr", Request.bits.RequestVirtualAddr)
)
```

仿真输出可以是紧凑格式：

```text
CT c=123456 t=0x21 e=0x02 p=0003_0007_000c_0001_80204000
```

软件 decoder 根据字典渲染为：

```text
[123456][AML.load][mmu_req] ih=3 iw=7 m=12 k=1 vaddr=0x80204000
```

### Status

`Status` 是面向 profile 和瓶颈归因的状态分类信号。

目标：

- 每个关键模块输出自己的微结构 status。
- 上层模块逐级聚合 status。
- ChipTop/DigitalTop 层得到最终 top-down attribution status。
- 前期 Verilator 直接 `printf` 聚合好的 status。
- 软件读取全量 Verilator trace/status 日志，反复尝试不同解析器和归因规则，得到更好、更漂亮的归因结构。
- Verilator 阶段通过全量日志离线重放打磨归因结构。
- FPGA 阶段通过 compact status logging / online slicing 支持 host 在线分析。

Status 回答的问题：

```text
这个 cycle，系统主要处于什么瓶颈状态？
```

---

## Verilator Trace 设计

### Trace 输出方式

第一版实现形态：

```text
backend:
  printf

encoding:
  task_id
  event_id
  field_id
  packed payload

software:
  Python parser/decoder
  pretty text renderer
  JSONL exporter
  functional-check model input
```

### 字典机制

Trace 字典包含：

```yaml
version: 1
tasks:
  AMLLoad:
    id: 0x21
    module: AML
    task: load_a

events:
  AML_MmuReq:
    task: AMLLoad
    id: 0x02
    level: F0_event
    fields:
      - { name: ih, width: 16, fmt: dec }
      - { name: iw, width: 16, fmt: dec }
      - { name: m, width: 16, fmt: dec }
      - { name: k, width: 16, fmt: dec }
      - { name: vaddr, width: 64, fmt: hex }
    render: "ih={ih} iw={iw} m={m} k={k} vaddr=0x{vaddr:x}"
```

生成产物：

```text
build/trace/trace_catalog.json
build/trace/TraceIds.scala
build/trace/trace_catalog_hash.txt
```

### printf 格式

建议先支持两种格式。

#### 紧凑格式

```text
CT v=1 h=<catalog_hash> c=<cycle> t=<task_id> e=<event_id> p=<hex_payload>
```

优点：

- 字符少。
- parser 简单。
- 比长 printf 更适合大日志。

#### 可读格式

```text
[cycle][module.task.event] field=value ...
```

优点：

- 人直接看舒服。
- 适合 bringup。

Config 中可以切：

```scala
CUTETracePrintMode.Compact
CUTETracePrintMode.Human
CUTETracePrintMode.Both
```

### Trace levels

沿用 Phase 0 的功能等级：

```text
F0_event:
  基础事件顺序、任务生命周期、MMU req/rsp。

F1_store:
  D/store tensor 提取和重建。

F2_tensor_op:
  tensor op 级功能验证。

F3_layer/F4_fused/F5_model:
  后续由软件模型聚合。
```

### 第一批 Trace 事件

优先迁移现有 printf 中最有功能验证价值的事件：

```text
TaskController:
  macro_inst_insert
  macro_inst_decode_start
  macro_inst_decode_end
  micro_task_issue
  micro_task_commit

LocalMMU / Cute2TL:
  mmu_req
  mmu_rsp
  source_id_alloc
  source_id_free

AML/BML/CML:
  task_start
  task_end
  mmu_req
  mmu_rsp

CML:
  d_store_start
  d_store_data
  d_store_end
```

### Trace parser

目录建议：

```text
trace/python/cutetrace/
  catalog.py
  parser.py
  decoder.py
  render.py
  func/
    event_model.py
    store_model.py
```

功能：

- 读取 compact printf 日志。
- 校验 catalog hash。
- 解码 task/event/payload。
- 输出漂亮 text。
- 输出 JSONL。
- 给 F0/F1/F2 功能模型提供结构化输入。

---

## Status 设计

### Status 的基本形态

每个关键模块输出一个 status bundle。

示例：

```scala
class AMLStatus extends Bundle {
  val state = UInt(4.W)
  val valid = Bool()
}
```

实际实现推荐先用结构化 `Bundle` 表达，便于修改：

```scala
class CUTEProfileStatus extends Bundle {
  val aml = new AMLStatus
  val bml = new BMLStatus
  val cml = new CMLStatus
  val mte = new MTEStatus
  val localMMU = new LocalMMUStatus
}
```

### Status 是状态分类

Phase 0.5 选择状态分类作为硬件观测量。

原因：

- 当前目标聚焦瓶颈归因定性。
- 精确计数留给后续定量分析扩展。
- 持续时间、占比、状态迁移可以先由离线解析器从全量日志中统计。

因此每个模块回答：

```text
我当前处于哪类状态？
```

### 模块 status 草案

#### AML/BML

```text
idle
has_task
working
wait_mmu_req_ready
wait_mmu_rsp
wait_scratchpad_write
wait_source_id
blocked
error
```

#### CML

```text
idle
load_c
store_d
wait_mmu_req_ready
wait_mmu_rsp
wait_scratchpad_read
wait_vector
blocked
error
```

#### MTE

```text
idle
waiting_input
compute
waiting_output
blocked_by_cdc
blocked_by_scale
error
```

#### LocalMMU / Cute2TL

```text
idle
has_request
source_id_full
tl_a_wait_ready
waiting_response
response_backpressure
blocked
error
```

#### Core

```text
running
frontend_stall
backend_stall
memory_stall
commit_empty
waiting_accelerator
interrupt_trap
unknown
```

#### Cache

```text
idle
hit
miss
refill
mshr_full
writeback
probe_or_coherence
blocked
```

#### Vector

```text
idle
issue
execute
memory
writeback
stalled
trap
unknown
```

这些枚举是草案，Phase 0.5 的重要任务就是让它们和真实微结构信号对齐。

---

## Status 聚合

### 聚合层级

参考 Chipyard `TraceIO` 的层级思想，但数据类型改成 status：

```text
leaf module status
  -> CUTE/local domain status
  -> tile/cache/vector domain status
  -> subsystem status
  -> ChipTop/DigitalTop final top-down status
```

### CUTE 内部聚合

CUTE 内部先聚合：

```text
AML/BML/CML/ASL/BSL
ADC/BDC/CDC
MTE
LocalMMU
TaskController
  -> CUTEStatus
```

`CUTEStatus` 可以包含：

```scala
class CUTEStatus extends Bundle {
  val task = new TaskControllerStatus
  val aml = new LoaderStatus
  val bml = new LoaderStatus
  val cml = new CMLStatus
  val mte = new MTEStatus
  val mmu = new LocalMMUStatus
  val global = UInt(4.W)
}
```

### ChipTop/DigitalTop 聚合

顶层聚合：

```text
core status
cache status
vector status
CUTE status
memory/bus status
  -> TopDownStatus
```

`TopDownStatus` 是最终要被 printf/后续 FPGA 记录的状态：

```scala
class TopDownStatus extends Bundle {
  val state = UInt(8.W)
  val reason = UInt(8.W)
  val source = UInt(8.W)
  val valid = Bool()
}
```

### 最终归因状态

第一版可以定义少数 hardcoded 状态：

```text
0 unknown
1 idle
2 host_or_core_feeding_bound
3 cute_load_bound
4 cute_compute_bound
5 cute_store_bound
6 memory_or_cache_bound
7 vector_bound
8 synchronization_bound
9 mixed
10 error
```

`reason` 进一步解释：

```text
cute_load_bound:
  aml_wait_mmu
  bml_wait_mmu
  loader_wait_scratchpad
  source_id_full

cute_compute_bound:
  mte_compute
  mte_wait_input
  mte_wait_output

cute_store_bound:
  cml_store
  cml_wait_mmu
  cml_wait_vector

memory_or_cache_bound:
  dcache_miss
  mshr_full
  tl_wait_ready
  memory_rsp_wait
```

---

## Status Verilator 输出

### 前期输出方式

前期直接在 Verilator 中 printf ChipTop/DigitalTop 聚合好的 status：

```text
ST c=<cycle> s=<state> r=<reason> src=<source>
```

可选输出更多 debug 字段：

```text
ST c=<cycle> s=<state> r=<reason> src=<source> cute=<cute_status> core=<core_status> cache=<cache_status>
```

当前阶段的日志目标是完整、稳定、易解析。软件基于 Verilator 日志反复离线尝试不同归因结构和规则。

### 输出粒度

前期可以从 every-cycle printf 开始，便于验证规则：

```text
每 cycle 输出 TopDownStatus
```

如果日志过大，再加：

```text
status change only
periodic heartbeat
```

这些是日志量优化项。

### 离线归因解释器

Verilator 当前阶段的软件工具读取全量日志：

```text
读取 CT trace printf 日志
读取 ST status printf 日志
按 cycle 对齐 trace event 与 top-level status
反复尝试不同 attribution rule/schema
输出更漂亮、更稳定的归因结构
```

当前阶段的关键能力是离线重放：

```text
same full log + rule version A -> attribution report A
same full log + rule version B -> attribution report B
compare A/B unknown ratio, mixed ratio, transition quality
```

解释器可以从全量日志中统计：

```text
state -> duration
reason -> duration
source -> duration
state transition graph
event/status correlation
```

最终画出：

```text
top-down attribution timeline
bottleneck percentage
state transition graph
unknown/mixed root-cause report
```

---

## 未来 FPGA Status 路线

Phase 0.5 产出 FPGA Status 路线规划。

当基于全量 Verilator 日志打磨出来的归因结构成熟后，才考虑把最终机制落到 FPGA。

### FPGA compact status record

FPGA profile 建议记录 compact status record：

```text
TopDownStatus every cycle
  -> status change detector
  -> run-length encoder
  -> compact status records
  -> DRAM ring buffer
  -> XDMA/host slice interpreter
```

设计目标：

- 数据量跟随状态变化次数增长。
- host 读取 compact records 后重建 status runs。
- 长时间 profile 使用 run-length 压缩后的状态区间。

### Compact record 格式

主记录：

```text
RunRecord:
  start_cycle
  duration
  state
  reason
  source
  flags
```

记录触发：

```text
status change
periodic heartbeat
explicit marker
```

### Host status slice interpreter

未来 host 工具：

```text
read compact status records
reconstruct status runs
slice into 0.5s window
refresh every 10ms
render top-down graph
```

这里的 0.5s/10ms 切片属于 FPGA 与 host 在线 profile 方案。这个设计的数据量取决于状态变化次数。

---

## Config 规划

### Trace config

```scala
case class CUTETraceParams(
  enable: Boolean = false,
  mode: CUTETraceMode = CUTETraceMode.CompactPrintf,
  levels: Set[CUTETraceLevel] = Set(F0Event),
  catalogHash: BigInt = 0
)
```

模式：

```text
Off
HumanPrintf
CompactPrintf
BothPrintf
```

### Status config

```scala
case class CUTEStatusParams(
  enable: Boolean = false,
  printMode: CUTEStatusPrintMode = CUTEStatusPrintMode.EveryCycle,
  includeDebugFields: Boolean = true
)
```

模式：

```text
Off
EveryCycle
OnChange
Heartbeat
```

### 后续 FPGA config

规划项：

```scala
case class CUTEStatusFPGAParams(
  enable: Boolean = false,
  recordMode: CUTEStatusRecordMode = RunLength,
  heartbeatCycles: Int = 1000000
)
```

Phase 0.5 记录该 config 的接口形态和参数含义；实际实现进入 FPGA profile 阶段。

---

## 文件与目录规划

### Verilator Trace

```text
src/main/scala/trace/CUTETraceIds.scala
src/main/scala/trace/CUTETracePrintf.scala
trace/catalogs/cute_trace.yaml
trace/python/cutetrace/parser.py
trace/python/cutetrace/decoder.py
trace/python/cutetrace/render.py
```

### Status

```text
src/main/scala/status/CUTEStatus.scala
src/main/scala/status/CUTEStatusEnums.scala
src/main/scala/status/CUTEStatusAggregator.scala
trace/python/status/status_parser.py
trace/python/status/topdown.py
trace/python/status/render.py
```

### 文档

```text
trace/status_spec.md
trace/trace_printf_spec.md
configs/schemas/cute_trace_catalog.schema.json
configs/schemas/cute_status.schema.json
```

---

## 实施任务

### Task 1: 重写 Trace/Status spec

产物：

```text
trace/trace_printf_spec.md
trace/status_spec.md
```

验收：

- 明确 Trace 是 Verilator-only printf。
- 明确 Status 是 profile attribution 主线。
- 明确 Chipyard TraceIO 为 status plumbing 提供参考。

### Task 2: Trace 字典与 compact printf

产物：

```text
trace/catalogs/cute_trace.yaml
scripts/generate-cute-trace-ids.py
src/main/scala/trace/CUTETraceIds.scala
src/main/scala/trace/CUTETracePrintf.scala
```

验收：

- 可以用 task/event id 输出 compact printf。
- 可以切换 compact/human printf。
- catalog hash 出现在日志头或日志行中。

### Task 3: Trace parser/decoder

产物：

```text
trace/python/cutetrace/parser.py
trace/python/cutetrace/decoder.py
trace/python/cutetrace/render.py
```

验收：

- compact printf 能还原成漂亮日志。
- 能输出 JSONL。
- 能为 F0/F1/F2 模型提供结构化事件。

### Task 4: CUTE 关键 Trace 事件 PoC

优先插点：

```text
TaskController macro/micro lifecycle
LocalMMU req/rsp
CML d_store_data
```

验收：

- 旧 printf 保留到 compact trace 覆盖同等信息。
- 新 compact trace 与旧 printf 可交叉确认。
- F0_event 能做最小顺序检查。
- F1_store 能重建最小 D tensor。

### Task 5: Status enum 草案

产物：

```text
src/main/scala/status/CUTEStatusEnums.scala
trace/status_spec.md
```

验收：

- AML/BML/CML/MTE/LocalMMU/core/cache/vector status 枚举都有初版。
- 每个 status 有语义描述。
- 硬件观测量保持为 status enum/bundle。

### Task 6: CUTE 内部 status 聚合

产物：

```text
src/main/scala/status/CUTEStatus.scala
src/main/scala/status/CUTEStatusAggregator.scala
```

验收：

- CUTE 内部模块可以输出 status。
- CUTE top 可以聚合出 `CUTEStatus`。
- 聚合路径独立于功能数据路径。

### Task 7: ChipTop/DigitalTop TopDownStatus PoC

产物：

```text
TopDownStatus Bundle
TopDownStatusAggregator
Verilator ST printf
```

验收：

- 在仿真中能看到每 cycle 或 on-change 的 `ST` 状态行。
- 初版归因规则能输出 `state/reason/source`。
- 验收范围限定在仿真内部观测。

### Task 8: 离线归因解释器

产物：

```text
trace/python/status/status_parser.py
trace/python/status/topdown.py
trace/python/status/render.py
trace/python/status/rule_compare.py
```

验收：

- 能读取 Verilator `ST` 日志。
- 能读取 Verilator `CT` trace 日志，并按 cycle 与 status 对齐。
- 能对同一份全量日志反复应用不同归因规则。
- 能输出 timeline / percentage / transition summary / unknown-mixed 分析。
- 能比较不同规则版本的归因结果，辅助打磨更漂亮的归因结构。

### Task 9: 归因规则迭代

产物：

```text
trace/status_rules.yaml
trace/tests/status_rules/*.log
```

验收：

- 归因规则在软件中修改，硬件镜像保持稳定。
- 对典型 workload 能给出可解释的瓶颈分类。
- 能基于全量日志反复重放和对比。
- unknown/mixed 状态比例可被统计，用于指导 status 枚举改进。

### Task 10: FPGA Status 可行性报告

产物：

```text
tools/perf/profile_status_budget.md
```

验收：

- 估算 raw per-cycle dump 的数据量。
- 估算 run-length compact status record 的数据量。
- 明确 FPGA 实现后置。
- 明确成熟条件：基于全量日志的离线归因结构稳定、status 枚举稳定、compact record 数据率可控。

---

## 第一版推荐范围

必须做：

```text
Trace compact printf
Trace catalog
Trace parser/decoder
CUTE 关键 trace PoC
Status enum 草案
CUTEStatus 聚合
TopDownStatus 初版归因
Verilator ST printf
Host status interpreter
```

暂缓：

```text
FPGA status logging
XDMA
AXI/DRAM writer
ChipTop profile external port
硬件 run-length encoder
硬件 status slice interpreter
```

---

## 风险与规避

### 风险: Trace 与 Status 再次混淆

规避：

- Trace 文件、包名、接口名全部带 `Trace`。
- Status 文件、包名、接口名全部带 `Status`。
- Trace 综合边界限定在 Verilator/仿真。
- Status 承载 profile attribution state。

### 风险: Status 归因规则过早硬编码

规避：

- Phase 0.5 归因规则先在 Python 中基于全量日志反复打磨。
- Chisel 中提供原始 status 和一个初版 TopDownStatus。
- unknown/mixed 保留为合法输出状态。

### 风险: 每 cycle ST printf 日志过大

规避：

- 第一版允许 every-cycle，便于验证。
- 如果日志过大，增加 on-change 或 heartbeat 模式。
- FPGA 后续方案采用 compact status records。

### 风险: Status 枚举偏离真实微结构

规避：

- 先从 AML/BML/CML/LocalMMU/MTE 这些 CUTE 内部模块做 PoC。
- 每个 status 必须绑定具体信号条件。
- host interpreter 统计 unknown/mixed，反向推动 status 枚举修正。

### 风险: 借鉴 Chipyard TraceIO 时误用 TraceBundle

规避：

- 借鉴 `BundleBridgeSource / traceNodes / top-level plumbing` 思路。
- CUTE Trace 采用 Verilator printf + 字典机制。
- CUTE Status 使用独立 status bundle。

---

## 最终验收标准

Phase 0.5 完成时，应满足：

1. 文档明确 Trace 是 Verilator-only printf，Status 是 profile/top-down 归因主线。
2. CUTE 关键模块可以输出 compact trace printf。
3. Trace decoder 可以把 compact printf 还原成漂亮日志和 JSONL。
4. F0_event 可以做最小任务/MMU 顺序检查。
5. F1_store 可以重建最小 D tensor。
6. AML/BML/CML/MTE/LocalMMU 至少有初版 status 枚举。
7. CUTE top 可以聚合出 `CUTEStatus`。
8. 仿真中可以 printf ChipTop/DigitalTop 聚合好的 `TopDownStatus`。
9. 离线归因解释器可以读取全量 Verilator trace/status 日志，反复重放并比较不同 top-down 归因规则。
10. FPGA/XDMA/status logging 明确后置，并有可行性分析和成熟条件。
