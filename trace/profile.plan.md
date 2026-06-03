# CUTE Top-Down Performance Profiling Plan

## 0. Goal

本计划定义一套面向 AI workload 的 CUTE / SoC top-down 性能分析方法。

这套方法借鉴 CPU 传统 top-down 的分析思路，并在矩阵乘扩展的视野下做重构和增强；分析起点仍然回到 AI workload 最朴素的执行时间目标。

### 0.1 First-Principles Chain

第一性的起点先落在 workload 执行时间上：

```text
目标：让 workload 的总执行时间更短
```

对 AI workload 而言，总执行时间通常可以拆成：

```text
T_workload
= T_core_control
+ T_vector_prep_post
+ T_matrix_compute_related
+ T_memory_wait
+ T_sync_overheads
```

而在大多数以张量/矩阵乘为核心的 AI workload 中，决定总时间上限的主导项通常落在围绕矩阵乘计算链条展开的那一大块时间上：

```text
矩阵乘本体
+ 为矩阵乘服务的数据准备
+ 为矩阵乘服务的取数/回写/同步等待
```

所以如果继续往下追第一性，就会得到：

```text
让 workload 更快
  ->
矩阵乘计算量最高
  ->
让矩阵乘计算部件尽可能持续、尽可能满载地工作
  ->
提升矩阵乘计算部件利用率
```

因此，这套方法最终收敛到的核心硬件指标，会从 CPU 世界里常见的退休效率视角，转到矩阵乘执行部件利用率这一视角，也就是 `Matrix Peak Utilization` 这一类指标。

### 0.2 What This Top-Down Explains

因此，这里的 top-down 归因重点会从“某条 CPU 指令的退休效率”扩展到下面这些问题：

```text
为什么 workload 还没有结束
为什么矩阵乘相关时间这么长
为什么这一拍矩阵算力没有被充分释放
```

换句话说，矩阵乘部件利用率不是凭空挑出来的指标，它是从 workload 总执行时间这一最朴素目标顺着结构分解一路推导下来的核心观测量。

### 0.3 Performance Objective

因此，本计划围绕的新第一性问题是：

```text
如何让标称算力为 X ops/cycle 的矩阵执行单元，在有效工作窗口内尽量持续、尽量满载地工作。
```

---

## 1. Overall Method

这套方法分成两层：

1. **观测层**
   每个 cycle 记录一份 `物理资源 + 状态` 的向量，再叠加软件 marker 给出的 workload 上下文。

2. **解释层**
   host 侧根据：
   - 资源树
   - 资源依赖图
   - 每类资源的 local state 字典
   - 软件 marker 上下文

   对这些原始观测做 top-down 投影、热力图聚合和瓶颈归因。

核心原则：

```text
硬件 trace 保留事实
host 侧规则负责解释
```

也就是说：

- trace 不直接输出最终 top-down reason
- trace 不直接输出静态 dependency graph
- trace 输出的是“资源当前状态”和“共享资源仲裁/服务对象变化”
- host 侧再重建动态 dependency subgraph，并给出归因

---

## 2. Two Orthogonal Axes

每个 cycle 的信息拆成两条正交轴：

### 2.1 Context Axis

回答：

```text
我现在在 workload 的哪一段
```

这条轴主要来自软件 marker。

它用于切分：

- 整个 workload
- layer
- op
- phase

### 2.2 Attribution Axis

回答：

```text
这一拍为什么没有把矩阵算力吃满
```

这条轴主要来自硬件资源状态向量和 host 侧的投影规则。

最终每个 cycle 的基本表示是：

```text
(cycle) -> (workload_context, resource_state_vector)
```

然后 host 再从 `resource_state_vector` 投影出 top-down 归因。

---

## 3. Analysis Windows

当前定义 3 个分析窗口。

### 3.1 GlobalWorkloadWindow

定义：

从软件 marker 标记的 `WorkloadBegin` 到 `WorkloadEnd`。

作用：

回答整个 AI workload 的总时间分布，例如：

- Core 侧准备花了多少时间
- Vector 和 Matrix 有没有交叠
- SharedMemory / SharedInterconnect 哪一类资源最常成为瓶颈

### 3.2 SliceWindow

定义：

由软件 marker 切出来的语义片段。

典型例子：

- `QProj`
- `KProj`
- `VProj`
- `Softmax`
- `FFNUp`
- `FFNDown`

作用：

回答某一个功能片段内部为什么慢。

### 3.3 EngineActiveWindow

定义：

在某个 `SliceWindow` 内，矩阵执行引擎已经进入可持续推进该片段工作的活跃区间。

作用：

回答：

```text
既然这段工作已经进入矩阵引擎的责任域
为什么矩阵算力还是没有被持续、充分释放
```

注意：

`EngineActiveWindow` 不意味着 Core / Vector 必须静止不动。
它允许向量和矩阵异步交叠执行。

---

## 4. Primary Metrics

### 4.1 Matrix Peak Utilization

核心指标定义为矩阵峰值利用率（Matrix Peak Utilization）：

```text
MatrixPeakUtil = AchievedMatrixOps / TheoreticalPeakMatrixOps
```

在某个分析窗口 `W` 内，可以写成：

```text
MatrixPeakUtil(W) = sum(AchievedOps(c)) / sum(PeakOpsPerCycle(c))
```

为了强调它是按窗口统计的“峰值兑现程度”，也可以等价写成：

```text
MatrixPeakUtil = AchievedOps / (PeakOpsPerCycle * WindowCycles)
```

这里的 `PeakOpsPerCycle` 不应该强行写死为常数，而应允许按当前：

- mode
- dtype
- config
- shape

进行解释。也就是说，`Matrix Peak Utilization` 衡量的不是“忙了多少拍”这一件事，而是“在当前配置下，理论峰值有多少真正被兑现了”。

### 4.2 Loss Decomposition

为了把 `Matrix Peak Utilization` 进一步拆开，需要对损失做两类分解：

- `StallLoss`
  这一拍矩阵执行单元没有有效产出

- `UnderfillLoss`
  这一拍矩阵执行单元有产出，但没有跑满理论峰值

因此在一个窗口内：

```text
MatrixPeakUtil + StallLoss + UnderfillLoss = 1
```

这意味着：

- `UnderPeak` 必须被认真建模
- 不能只做“忙/闲”二值分析

### 4.3 Why Matrix Peak Utilization Is the Core But Not the Only View

虽然 `Matrix Peak Utilization` 是最终收敛出来的核心指标，但它不是唯一视图。

原因是：

- `Matrix Peak Utilization` 只能告诉我们矩阵部件利用率高不高
- 但不能直接告诉我们“为什么不高”

所以本计划采用的思路是：

```text
先用 workload 执行时间作为总目标
再用 `Matrix Peak Utilization` 作为矩阵主指标
再用资源状态向量 + 软件上下文去解释它为什么上不去
```

这也解释了为什么我们需要：

- `GlobalWorkloadWindow`
- `SliceWindow`
- `EngineActiveWindow`
- 软件 marker
- 资源状态热力图
- host 侧 top-down 投影

---

## 5. Step 1: Semantic Model Freeze

Step 1 的目标不是实现 trace，而是冻结语义模型。

需要冻结的对象包括：

1. `Context Axis` / `Attribution Axis`
2. `GlobalWorkloadWindow` / `SliceWindow` / `EngineActiveWindow`
3. 主指标和损失分解
4. `PhysicalResource` 资源树
5. `ResourceLocalState` 建模规则
6. host 侧 top-down 投影规则框架

### 5.1 PhysicalResource Taxonomy

当前顶层 5 类资源域定义为：

- `Core`
- `VectorEngine`
- `MatrixEngine`
- `MemorySubsystem`
- `SharedInterconnect`

这些资源域不是 RTL 行政分区，而是从完整 workload 的视角抽出的五类设计对象。

它们都服务于完整 workload 的推进，并共同决定矩阵算力最终能否被吃满。

#### 5.1.1 Core

表示 CPU core 侧负责控制、编排、同步和命令发起的资源。

第二层建议先挂：

- `ScalarExecution`
- `CommandIssue`
- `CoreSynchronization`

第三层可先包含：

- `ScalarPipe`
- `RoCCCmd`
- `RoCCResp`
- `IssueControl`
- `HostSync`

#### 5.1.2 VectorEngine

表示 workload 中负责向量准备、辅助计算和后处理的向量执行体系。

第二层建议按功能簇划分：

- `VectorFrontend`
- `VectorRegisterSubsystem`
- `VectorMemoryPath`
- `VectorPermutationPath`
- `VectorArithmeticPath`
- `VectorSpecialPath`
- `VectorWriteback`

第三层可先包含：

- `VREG`
- `VLoad`
- `VStore`
- `VectorLSU`
- `VectorMemQueue`
- `VPermutation`
- `VFMA`
- `VINTALU`
- `VDIV`
- `VSQRT`
- `VWBPort`
- `VScoreboard`

第二层用于默认聚合，第三层用于深挖具体瓶颈。

#### 5.1.3 MatrixEngine

表示 CUTE 私有的矩阵执行链条及其本地控制/本地存储资源。

第二层建议先挂：

- `ControlPlane`
- `LoadIngress`
- `LocalStorage`
- `ComputeCore`
- `StoreEgress`

第三层可先包含：

- `TaskController`
- `MicroTaskScheduler`
- `DependencyTracker`
- `CreditTracker`
- `IssueQueues`
- `AMLLoad`
- `BMLLoad`
- `CMLLoad`
- `ScaleLoad`
- `AScratchpad`
- `BScratchpad`
- `CScratchpad`
- `ScaleScratchpad`
- `DataController`
- `LocalMMU`
- `MTE`
- `CMLStore`
- `StoreQueue`

这里明确约定：

- `Scratchpad`
- `DataController`
- `LocalMMU`

都属于 `MatrixEngine`，因为它们是 CUTE 私有执行链条的一部分，而不是系统级共享存储。

#### 5.1.4 MemorySubsystem

表示系统级共享存储体系。

第二层建议先挂：

- `NearSharedMemory`
- `LastLevelCache`
- `OffChipMemory`

第三层可先包含：

- `TCM`
- `LLC`
- `DRAM`

后续如果需要更细化，可以继续扩展：

- `L2Bank`
- `MemCtrl`

#### 5.1.5 SharedInterconnect

表示系统级共享搬运与仲裁链路。

第二层建议先挂：

- `OnChipFabric`
- `Arbitration`

第三层可先包含：

- `SysBus`
- `NoC`
- `Crossbar`
- `Arbiter`

### 5.2 Resource Taxonomy vs Dependency Graph

需要明确区分：

1. `resource_taxonomy`
   用树表达“资源如何归组、如何聚合、热力图纵轴如何组织”

2. `resource_dependency_graph`
   用图表达“哪些路径依赖哪些共享资源、谁和谁会争用同一链路”

原因：

- `TCM / LLC / DRAM / SysBus` 这类资源是共享的
- 它们可能同时服务于：
  - Matrix load path
  - Matrix store path
  - Vector load/store path
  - Core 侧访问

因此：

- 树用于展示和聚合
- 图用于因果重建和依赖分析

### 5.3 ResourceLocalState

原始 trace 不记录最终 top-down reason。

原始 trace 只记录：

- `resource_id`
- `local_state_id`
- 可选数值字段，例如：
  - `util_num / util_den`
  - `queue_depth`
  - `credit`
  - `active_client_mask`

#### 5.3.1 建模原则

不定义统一的全局 flat state enum。

而是：

- 每类资源有自己的 `local_state` 字典
- host 侧根据 `resource_class + local_state` 去解释语义

#### 5.3.2 First-Cut State Schemas

第一版建议按资源域先定义如下状态集合。

##### Core.local_state

- `Idle`
- `Preparing`
- `Issuing`
- `Waiting`
- `Blocked`

##### VectorEngine.local_state

- `Idle`
- `Loading`
- `Executing`
- `Storing`
- `Blocked`

##### MatrixEngine.local_state

- `Idle`
- `Issuing`
- `Loading`
- `ComputingFull`
- `ComputingPartial`
- `Draining`
- `Blocked`

##### MemorySubsystem.local_state

- `Idle`
- `ServingRead`
- `ServingWrite`
- `Contention`
- `Backpressured`

##### SharedInterconnect.local_state

- `Idle`
- `Transferring`
- `Arbitrating`
- `Contended`
- `Backpressured`

### 5.4 Multi-Blocker Semantics

原始模型允许一个周期存在多个 blocker。

例如：

```text
APathNotReady
BPathNotReady
```

可以同时存在。

因此：

- 原始观测层保留多个 blocker
- 不要求硬件在 trace 中提前选出唯一真因

host 聚合时允许分数记账。

第一版默认规则：

```text
如果一个周期存在 N 个并发 blocker
则每个 blocker 先拿 1/N 的 credit
```

后续如果需要，可以升级成加权分摊，但第一版不在硬件里写死权重逻辑。

### 5.5 Top-Down Projection

top-down 归因不是 trace 原始字段，而是 host 侧投影结果。

投影输入：

- `resource_state_vector`
- `resource_taxonomy`
- `resource_dependency_graph`
- 软件 marker 上下文
- 分析窗口

投影输出：

- 热力图
- utilization 报表
- 层次化 top-down 归因

这一步是可演进的，不应被硬件 trace 格式锁死。

---

## 6. Step 2: Software Marker

Step 2 的目标是建立 `Context Axis`。

### 6.1 Marker Transport

需要增加一条新的 RoCC 指令，或者一组轻量 marker 指令，用于让软件把“当前 workload 上下文”写入 trace。

这一步不是可选项，而是软件 marker 真正能落地的基础。

### 6.2 Marker Semantics

软件 marker 只负责回答：

```text
我现在在 workload 的哪一段
我现在在做什么
```

软件 marker 不负责直接判断微结构瓶颈。

因此 marker 字典不在 Step 2 一开始就冻结死，而是做成可持续维护、可版本化扩展的字典。

第一版建议的软件作用域：

- `Workload`
- `Layer`
- `Op`
- `Phase`

支持：

- `Begin`
- `End`
- `Instant`

第一版 phase / op 字典内容可以逐步演进，不要求在 Step 2 一次性收束。

---

## 7. Step 3: Hardware Dynamic State Trace

Step 3 的目标是让关键物理资源对外暴露自己的 `local_state`。

原则：

- trace 记录资源局部状态变化
- trace 记录共享资源仲裁变化
- trace 不直接输出最终 top-down reason

默认模式使用 **change-driven** 输出：

- `resource_state_change(resource_id, state_id, ...)`
- `shared_resource_change(resource_id, granted_client, active_clients_mask, ...)`

不默认做每周期全量打印。

说明：

- 对于 `1M cycle`、`10GB` 以内这一量级，分析上是可接受的
- 但默认仍优先 change-driven，避免把 printf 开销本身引入为额外性能污染

如果后续需要小窗口调试，可以再补充 dense 模式。

---

## 8. Step 4: Dependency Graph Reconstruction

Step 4 的目标是在 host 侧根据：

- 静态拓扑
- 动态资源状态
- 软件 marker

重建 workload 某个窗口里的 dependency subgraph。

关键原则：

- dependency graph 不是原始 trace 直接输出
- dependency graph 是 host 侧重建结果

这样既能保留足够的真实性，又不需要硬件每周期直接打印整张图。

---

## 9. Step 5: Host-Side Top-Down Projection

Step 5 的目标是做 host 侧聚合和解释。

需要产出：

- `Workload View`
- `Slice View`
- `EngineActive View`
- 资源热力图
- top-down 归因报表

host 侧需要支持：

- 按窗口聚合
- 按资源树聚合
- 按 blocker 分数记账聚合
- 按软件 marker 切片聚合

---

## 10. Step 6: Calibration and Validation

Step 6 的目标是校准这套归因口径，验证其可信度。

建议准备几组专门压单一瓶颈的 microbench：

- 只压 Core prep
- 只压 Vector prep
- 只压 Matrix operand fetch
- 只压 store drain
- 只压共享链路争用
- 只压边界 tile / partial utilization

验证目标：

- 资源状态 trace 与预期一致
- blocker 分摊与预期一致
- 同一 workload 在不同窗口视图下结论一致
- top-down 输出具备可解释性

---

## 11. Current Freeze for Step 1

当前已冻结的 Step 1 结论：

1. 两条正交轴：
   - `Context Axis`
   - `Attribution Axis`

2. 三个窗口：
   - `GlobalWorkloadWindow`
   - `SliceWindow`
   - `EngineActiveWindow`

3. 主指标：
   - `MatrixPeakUtil`
   - `StallLoss`
   - `UnderfillLoss`

4. 顶层资源域：
   - `Core`
   - `VectorEngine`
   - `MatrixEngine`
   - `MemorySubsystem`
   - `SharedInterconnect`

5. 原始 trace 只记录：
   - 物理资源局部状态
   - 共享资源仲裁变化
   - 软件 marker 上下文

6. top-down 归因在 host 侧完成

7. 一个周期允许存在多个 blocker，host 侧可做分数记账
