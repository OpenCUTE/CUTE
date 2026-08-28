# CUTE 项目阶段性工作汇报

## 摘要

围绕 CUTE 加速器的性能扩展与标准化，本阶段完成了四项耦合工作：**(1)** 将 CUTE 的私有宏指令 ISA 迁移到标准 RISC-V Matrix Extension (AME) 提案上 —— 新建 AME 译码器、重构 taskcontroller 从宏指令展开改为微指令直发，并将原硬件自管的 scratchpad 按 AME 语义重构为软件可命名调度的 tile register（4×tr + 4×acc），完成从 ISA、微架构到编程模型的全栈对齐；**(2)** 引入"提交后异步执行"的 RoCC 模型，通过 fence 类同步指令控制内存一致性；**(3)** 提出**"复用 L2 缓存 SRAM 作 TCM"**的核心 idea：在不新增存储硬件的前提下，让 CUTE / Saturn 的访存获得单周期确定性延迟与全宽带宽；**(4)** 在香山 HuanCun L2 上落地该思想 —— 利用 HuanCun 独有的双 stack SRAM 结构改造出真正的双端口 L2+TCM，并配套 DMA 引擎实现 DRAM ↔ TCM 的高效搬运，最终形成 CPU / Saturn / CUTE / DMA 四方共享 TCM 的统一数据总线。

---

## 一、AME 指令集支持与流水线重构

### 出发点

RISC-V 生态正在标准化矩阵扩展（Matrix Extension v0.6，简称 AME）。该提案定义了一套与 RVV 解耦的矩阵计算指令，涵盖矩阵加载/存储、矩阵乘累加、配置、栅栏等类别，是未来 RISC-V AI 加速器的通用软件接口。原 CUTE 采用私有 YGJK 宏指令（opcode 0x0B），一条指令描述完整 GEMM/Conv，硬件层内嵌任务 FIFO，软件生态封闭。为了对齐上游标准，本工作将 CUTE 迁移到 AME 的 opcode 0x2B 微指令模型。

### 关键设计与实现

**(1) AME 译码器（`AMEDecoder`）**

新增独立模块 `AMEDecoder.scala`，按 AME v0.6 native encoding 从 32-bit 指令中提取以下字段并做分类：

- `func4 [31:28]`：指令子类型
- `uop [27:26]`：主类别（00 Config / 01 Load-Store / 10 MatMul / 11 Misc）
- `d_size, s_size [1:0]`：元素位宽（8/16/32/64）
- `md, ms1, ms2 [2:0]`：矩阵寄存器索引（tr0-tr3 / acc0-acc3）
- 转置位、符号位、size_sup 等

产出 6 类命中信号（`is_config` / `is_load_a/b/c` / `is_store_*` / `is_matmul_*` / `is_misc_*` / `is_release` / `is_fence`），供下游发射逻辑使用。

**(2) TaskController 流水线重构**

原 CUTE 的路径是"上层软件构造宏指令 → 硬件宏指令 FIFO → 硬件微指令分解 → 计算单元"，微指令由硬件从宏指令展开。重构后改为"软件按 AME 单条微指令发射 → RoCC cmd → AMEDecoder → 直接进对应功能单元的微指令队列 → 计算单元"，去掉了硬件宏指令展开层。收益：

- 前端更薄：编译器/软件可以按标准 AME 指令生成代码，无需 CUTE 私有汇编
- 指令粒度可控：软件可精细调度 tile 级并行，不受宏指令原子性约束
- 兼容性：CUTE 的老宏指令 YGJK 路径保留（opcode 0x0B），迁移期两套并存

**(3) Scratchpad → Tile Register 重构**

原 CUTE 内部有一块由硬件全权管理的 scratchpad：bank 分配、双 buffer 轮转、生产者/消费者匹配等策略全部隐式在硬件流水线里做。这套设计对宏指令是自然的（宏指令描述一整个 GEMM，硬件自己拆微指令并挑 bank），但与 AME 语义正交 —— AME 把矩阵中间存储显式建模为**架构级的 tile register**：4 个 `tr`（左/右矩阵操作数）+ 4 个 `acc`（累加器输出），每条指令通过 `md`/`ms1`/`ms2` 字段命名操作对象，语义上是"软件可寻址的命名寄存器"。

本次重构把原硬件 scratchpad 按 AME 视角切片重映射：

- 硬件 bank / 存储条被切成 4 组 `tr` + 4 组 `acc`，每组暴露成 AME 架构定义的一个 tile register
- 硬件不再做 bank 分配决策；执行时哪个 bank 参与由指令的 `md`/`ms1`/`ms2` 直接选中，硬件只做地址译码
- 双 buffer / ping-pong 从"硬件隐式行为"变为"软件显式选择"：软件通过交替使用 tr0/tr1（或 acc0/acc1）实现 load 与 compute 重叠

**这一重构的三个价值**：

1. **语义完全对齐 AME 标准**：软件层看到的就是 AME v0.6 spec 描述的 8 个 tile register，指令语义与提案完全一致
2. **提升软件调度灵活度**：编译器/手写代码可以自主决定 tile register 分配策略（例如把权重锁定在 tr2/tr3，激活轮转扫过 tr0/tr1；或前一层输出用 acc0，下一层输入用 acc1），不再受硬件 rotation 策略约束
3. **减少硬件复杂度**：删除了原 scratchpad 里的 bank 仲裁 / hazard 检测 / rotation FSM 等隐式逻辑；bank 选择现在是纯组合译码，硬件路径更浅、时序更好

配合前两点（AME 译码器 + 微指令直发），最终形成"标准 ISA + 软件调度 + 命名寄存器"的完整 AME 语义栈。

**(4) 软件支持**

- 新建 [ame.h](cutetest/ame_test/ame.h) 提供 encoding 宏（如 `AME_MLAE`、`AME_MMACC_W_B`、`AME_MFMACC_S_H`）和高层 inline helper（`ame_mlae8` / `ame_mmacc_w_b` / `ame_settilem` 等），共约 60 组指令覆盖 config / load / store / int matmul / float matmul (fp16/fp32/fp64/bf16/fp8e4/fp8e5) / misc
- 编写 baremetal 测试：`ame_matmul_128x128x64`、`ame_matmul_256x256x128`、`ame_matmul_512x512x512` 三档 GEMM 正确性测试，覆盖 tile 大小、双 buffer、fusion 场景
- 顺便修复原有测试的两处 latent bug（`c` 数组指针类型 stride 不匹配、verify 循环误比对 `c[0][j]` 导致只校验 row 0）

---

## 二、异步执行模型

### 设计动机

AME 指令粒度较细（一条 `mlae` 只加载一个 tile row，一条 `mmacc` 只做一个 tile-level MAC），若走同步 blocking RoCC 每条指令都要 stall CPU 到执行完成，会导致 CPU 与加速器交替空转。为发挥 CUTE 的吞吐，需要"提交后异步执行"（fire-and-forget）语义。

### 实现

**(1) 提交路径**

- 普通 AME 指令（load/store/config/matmul/misc）：RoCC `io.cmd.fire` 后立刻返回，指令排入 CUTE 内部的 AMEDecoder 微指令 FIFO，硬件后台执行
- CPU 不 stall，可以继续跑标量代码或紧接下一条 AME 指令，只要 FIFO 未满即可持续提交

**(2) 同步指令**

引入两条 RoCC 格式的控制指令：

| 名字 | funct7 | xd | 语义 |
|------|--------|----|----|
| `fence.m` | `0x70` | 1 | RoCC 拉低 `io.cmd.ready` 直到 `acc.io.ame_all_idle` 为真；相当于 memory fence 保证前面所有 AME 指令完成 |
| `mstatus.m` | `0x71` | 1 | 立即返回 `acc.io.ame_all_idle` 值给 rd 寄存器；轮询用 |

配对的 C API：`ame_fence()`、`ame_is_idle()`，与 x86 `sfence` / RVV `vsetvl` 风格一致。

**(3) 内存一致性契约**

- 同一 tile register（TR/ACC）上的 RAW/WAR/WAW 由 CUTE 内部依赖跟踪保序（无需软件干预）
- 跨 memory 的顺序（比如 CUTE 写完某段内存后 CPU 立刻读）由软件插 `ame_fence()` 保证
- 与 RISC-V `fence rw, rw` 组合使用可实现完整的 memory ordering

---

## 三、核心 idea：L2 缓存复用为 TCM 的完美故事

### 观察到的矛盾

以 Shuttle + CUTE + Saturn 的 tile 为例，AI workload 的数据流呈现如下矛盾：

1. **AME 的 tile register 空间极小**：架构定义 8 个矩阵寄存器（4 个 tr + 4 个 acc），每个几 KB，加起来只有几十 KB。放不下一层 GEMM 的完整权重（Llama3-1B 一个 proj_q 权重就是 256KB）
2. **GEMM 工作集与权重都远大于 tile register**：需要频繁 load/store，反复从 DRAM 或 L1D 反刍数据
3. **传统 L1D 缓存路径不适合矩阵工作集**：
   - 端口窄（Rocket/Shuttle DCache 一次 8B）
   - 大工作集会污染 cache，把 CPU 的标量数据挤出去
   - L1D miss 走 L2 → DRAM，延迟不确定（30-50 cycle 抖动）
4. **加更多 SRAM？** 芯片面积昂贵，加 100KB SRAM 意味着显著的成本，投入产出比低

### 关键洞察

**现代高性能处理器**（Rocket-only 之外）**普遍带 L2 缓存**，SRAM 容量 128KB - 1MB 级别；而对典型 AI kernel（一层 transformer）而言，一次可以放下的工作集恰好也是这个量级。

**如果能把 L2 SRAM 里的一部分"切"下来直接作 TCM（tightly-coupled memory）使用**，就能：

- **单周期确定性延迟**：TCM 直接以物理地址寻址 SRAM，不做 tag 比对，也不参与 coherence，读一个 block 只需要一次 SRAM lookup
- **全宽 SRAM 端口带宽**：现代 L2 的 SRAM 端口位宽通常是 cache line（64B），刚好匹配 AME 的 tile row 宽度、Saturn 的 vector register 宽度
- **不新增任何存储硬件**：只是把 L2 的一部分容量从 cache 用途重新划分为 scratchpad 用途，本质上是 SRAM 的**用途切换**而非**容量扩充**
- **面积成本为零，仅需少量控制逻辑**：新增的只是 TCM 路径的地址译码 + 访问控制状态机

### 与 AME 的天然契合

AME 提供了极细粒度的 tile 级 load/store（`mlae`, `mlbe`, `mlce`, `msae` 等），每次 64B。这些指令**对存储的三个要求**：

| AME 对访存的诉求 | 传统 L1D 是否满足 | L2-TCM 是否满足 |
|-----------|--------------|-------------|
| 单周期访问、无抖动 | ✗ hit 4 cyc，miss 30+ cyc | ✓ 恒定 3-5 cyc |
| 带宽匹配 tile 宽度 (64B) | ✗ 一般 8B 端口 | ✓ SRAM 端口就是 64B |
| 不污染 cache | ✗ 权重会挤走 CPU 数据 | ✓ 完全独立地址空间 |

**在 AME 提交后异步执行模型下**，CPU 可以：
1. 通过 DMA 或标量搬把权重从 DRAM 送进 L2-TCM（几十/上百 KB 一次搬完）
2. 提交一串 AME 指令让 CUTE 后台从 TCM 反复取数做 GEMM
3. 同时 Saturn 也从 TCM 做 epilogue（dequant / activation / softmax）
4. 只在最终结果需要落 DRAM 时才走 memory

**"权重进 TCM 一次，AME/Saturn 反复复用"** 是这个 idea 的最直接受益场景。测算：一个 512×512 fp32 GEMM 权重 = 1MB，若从 DRAM 反复读 8192 个 tile 需要 ~200K cycle 的 DRAM 延迟；从 TCM 反复读只要 ~40K cycle，**5× 加速**，且不占 L2 cache 空间。

### 该 idea 对硬件层要求

1. L2 内部要有可以"切出来单独用"的 SRAM 结构 —— 大部分 monolithic cache 做不到（因为 SRAM 与 tag array 耦合，路径共用），需要**结构性支持双 SRAM 组**
2. 该 TCM 需要**独立 TL 端口**，避免和 cache 数据通道抢仲裁
3. 需要**软件可编程的 TCM 地址范围**，以便 driver 灵活配置

这三点在下一节由 HuanCun 提供支撑。

---

## 四、基于香山 HuanCun L2 的双端口 TCM 实现

### 为什么选 HuanCun

- 开源、成熟（香山北大版本）
- 支持 non-inclusive L2（保留 L1D 空间）
- 关键：**HuanCun 的 DataStorage 天然把 SRAM banks 分成 2 个 stack**，这是本设计得以在几乎零改动 SRAM 层的前提下落地的关键结构

### HuanCun 双 stack 结构的原本用意

HuanCun `DataStorage.scala` 里 SRAM 组织方式：

```
一整行 cache line (64B) ==  ******** ******** ******** ********
                         └── stack 0 ──┘└── stack 1 ──┘
                        (banks 0..7)   (banks 8..15)
```

- 一整行由 16 个 8B bank 组成，被划分为 2 个 stack × 8 bank
- 一个物理 stack = 8 bank，是一个独立的 SRAM 组，一周期能独立完成一次读或写

**原始设计目的：消除多请求源之间的结构冒险。**

L2 的 DataStorage 在同一周期需要仲裁**5 个并发访问源**（都在 `req()` 函数里排队）：

| 请求源 | 方向 | 触发场景 |
|-------|-----|---------|
| `sourceC_raddr` | 读 | Release/ProbeAck 需要读 dirty block 送上游 |
| `sourceD_raddr` | 读 | Grant 上游读命中的 block |
| `sourceD_waddr` | 写 | Grant path 里 way-transition / update-in-place |
| `sinkD_waddr` | 写 | 下游 refill 数据回来写入 |
| `sinkC_waddr` | 写 | 下游 Release 携带的 dirty data 写入 |

如果 SRAM 是 monolithic 单体的，这 5 个源同一周期只能有 1 个跑，其他 4 个都要等 —— **结构冒险**导致流水线气泡。分成 2 个 stack 之后，`req()` 按 `innerAddr = {way, set, beat}` 的低位选 stack，两个请求只要地址落在不同 stack 就能**同一周期并行执行**。所以 stack 化的本质是**用 SRAM 分组换消掉结构冒险**，是一种典型的 banking 优化。

### 观察到的冗余：双 stack 并发很少被真正用满

我们的观察是：**这份"每周期 2 stack 并发"的峰值带宽在真实 workload 里几乎榨不干**。原因：

1. **L2 请求速率被上游节流**：CPU DCache miss 大约几个到几十个 cycle 才发一个，加上 MSHR 数量和 refill 延迟，L2 的入口每周期新增请求 ≪ 2
2. **TL D 通道单端口**：即使 SRAM 侧同 cycle 读出 2 份数据，D 通道每周期只能 send 一 beat，多余读的数据也发不出去
3. **不同源天然错峰**：sinkD refill 和 sourceD read 通常在流水线的不同阶段，5 源同时命中同一 cycle 极少
4. **命中率主导延迟**：真实 workload 的 L2 平均延迟 ≫ 单周期 SRAM lookup，SRAM 带宽从来不是瓶颈

换句话说：**"每周期能 2 stack 并发"的能力在实际访存 profile 下大部分时间只用到 1 stack，另一个 stack 是名副其实的冗余资源**。

### 我们的改造：把冗余的一半 stack 榨成 TCM

**核心操作**：在 `HCCacheParameters` 里加一个开关 `tcmBaseAddr`。当它有值：

```
tcmEnabled=true:
  nrCacheStacks     = 1                   (原来 2，改成 1)
  effectiveCacheWays = ways / 2           (SRAM 深度保持不变，只是 ways 减半)
  另一 stack (8 banks × 8B) → repurpose 为 TCM SRAM，独立走 TcmSinkA/TcmSourceD
```

**Cache 侧的"代价"**：`nrCacheStacks = 1` 意味着 cache 的 5 个请求源现在共享单 stack，同一周期最多 1 个能跑，其余走 priority mux 排队。理论峰值 SRAM 吞吐减半。但按上一节的分析，**这个理论峰值本来就用不满**，真实命中率、真实延迟几乎不变（预期性能损失 < 5%，具体待跑 workload 验证）。同时容量 `effectiveCacheWays = ways/2` 是显式的软件参数，如需可以通过增加 `sets` 来把容量补回来。

**TCM 侧的收益**：
- 容量 = 原 L2 的一半，testL2 配置里是 **1MB**（`ways/2 × sets × 64B = 4 × 4096 × 64`）
- 访问延迟 = **单周期 SRAM lookup**（跳过所有 cache tag 比对 / MSHR / directory）
- 带宽 = **满 SRAM 端口 512-bit**，跟 L2 cacheNode 完全对等
- 访问路径 = 独立走 `TcmSinkA` / `TcmSourceD` / 独立 `tcmNode`，跟 cache 路径**物理隔离**

**这就是关键 trade：把"5 个 cache 源峰值并发 2"降级为"5 个 cache 源峰值并发 1"，换来一份 1MB / 单周期 / 512-bit / 独立端口的 scratchpad —— 用一份几乎榨不干的冗余带宽，兑换出一份 CUTE / Saturn / DMA 极其渴求的确定性存储资源。**

### 双端口 Diplomacy 拆分

从 tile 内部看，L2 现在暴露**两条独立 TL edge**：

| 端口 | 位宽 | 语义 | 用途 |
|------|------|------|------|
| `cacheNode` | TL-C 512-bit（A/B/C/D/E 五通道） | Cacheable, Acquire/Grant/Release | 常规 CPU DCache/ICache miss 请求 |
| `tcmNode`   | TL-UL 512-bit（只 A/D 两通道） | UNCACHED, Get/PutFull 只读写 | AME / Saturn / DMA 的 TCM 访问 |

**为什么这个是有意义的双端口，而不是简单地在 L2 前面加个 xbar？**

因为改造后 cacheNode 只服务 cache addr，tcmNode 只服务 TCM addr，两条路在 L2 内部走**完全独立的 SRAM 组**（不同 stack），**完全独立的 D 通道**（无仲裁）。原 HuanCun 的 D 通道之前设计里 cache 和 TCM 共用，触发了一个 hold-register 补丁 bug（cache SourceD 总是优先，TCM 响应会被静默丢弃），彻底重构后这个 bug 从设计层消失。

### Diplomacy 层的关键突破

在实现"cacheNode 走上游 Xbar → sbus，tcmNode 直接挂 tile.tlMasterXbar"这个拓扑时，遇到 Diplomacy 的 identity node star-binding 约束（`oStars + iStars ≤ 1`）。这是因为原本的 `injectNode` 单端口注入机制只允许 tile → sbus 一条 star 绑定。

**解决方案**：让 `tcmNode` 完全**绕过** `crossingParams.master.injectNode()` 通道，直接绑到 `ShuttleTile.tlMasterXbar`（一个 TLNexusNode，支持任意 fan-out）。为此在 `ShuttleTile` 上暴露了公有方法 `attachSlaveToMasterXbar(slave: TLNode)`，`WithHuanCunL2` 的 `injectNode` 里通过 `context.totalTiles(tileId)` 查到当前 tile 再调用。这一改动使 HuanCun L2 变成了对外真正意义上的双 TL 端口。

### 完整数据总线布局

```
                      ShuttleTile
    ┌─────────────────────────────────────────────────────┐
    │                                                     │
    │   Shuttle CPU DCache ─┐                             │
    │   Shuttle Frontend  ──┤                             │
    │   Saturn.atlNode ────┤                              │
    │   CUTE.atlNode  ─────┤ ── tlMasterXbar              │
    │   TCM DMA.memRead ───┤        │                     │
    │   TCM DMA.tcmWrite ──┘        │                     │
    │                               │                     │
    │                               ├──▶ tcmNode ─────────┤
    │                               │   (HuanCun TCM SRAM)│
    │                               │                     │
    │                               └──▶ crossMasterPort  │
    │                                    │                │
    └────────────────────────────────────┼────────────────┘
                                         ▼
                                       sbus → cacheNode → LLC → DRAM
```

**所有 tile 内 master 都能透明访问 HuanCun TCM**，地址在 0x81000000 以上直接路由到 tcmNode。仲裁由 `tlMasterXbar` 的 RRArbiter 公平处理，避免任何一个 master 饿死。

### TCM DMA 引擎

为了让 CPU 不亲自搬运大块数据（DRAM 权重进 TCM），设计了独立的 DMA 引擎，一并加入 tile：

- **三条 TL 边**：`memReadNode`（读 DRAM）+ `tcmWriteNode`（写 TCM）+ `ctrlNode`（MMIO 控制寄存器，挂 PBUS）
- **MMIO 寄存器组**（8 个 32-bit，映射到 0x2000_0000+）：`SRC_LO/HI`、`DST_LO/HI`、`LENGTH`、`CTRL`（bit0=start）、`STATUS`（bit0=busy, bit1=done, bit2=err）、`IRQ_CLR`
- **软件访问方式**：既可以从 CPU 直接写 MMIO，也可以通过 AME 自定义指令 `ame_dma_load(src, dst, len)`（RoCC funct7=0x72）触发 —— 指令内部由 CUTE 帮软件敲一遍 MMIO 序列

**FSM 演进**：

- **v1（串行）**：`ISSUE_READ → WAIT_RESP → ISSUE_WRITE → WAIT_ACK → …`，每块 ~52 cycle（DRAM 延迟串行暴露）
- **v2（多 outstanding + 读写解耦）**：4 outstanding read（用 source ID 0-3 作 tag），4 slot reorder buffer 保序，读写侧独立跑，预期 ~10 cycle/block，**5-7× 加速**

### 验证测试

编写了完整的 baremetal 测试栈：

| 测试 | 覆盖 |
|-----|-----|
| `dma_tcm_smoke.riscv` | MMIO 直接触发 DMA，64B/128B/512B 三档 |
| `dma_tcm_ame_test.riscv` | AME `ame_dma_load` 指令触发 DMA |
| `dma_tcm_roundtrip.riscv` | 反向：TCM → DRAM，验证 DMA 双向 |
| `saturn_tcm_test.riscv` | Saturn `vle32/vse32` 直接访问 HuanCun TCM |
| `ame_matmul_512x512x512_dma.riscv` | DMA 权重进 TCM + CUTE 从 TCM 做 GEMM，端到端矩阵乘正确性 |
| `tcm_pingpong_skel.riscv` | 双缓冲 pattern，为将来非阻塞 DMA 铺路 |

外加原有 llama3_1B 系列测试用作压测和最终 workload 目标。

---

## 五、当前状态与主要成果

**硬件设计**

- HuanCun L2 完成双端口拆分，通过 `sbt firrtl CONFIG=testL2Dma` 完整 elaboration
- 生成的 FIRRTL 里可以看到 `cacheNodeIn`（TL-C 512b）和 `tcmNodeIn`（TL-UL 512b）两个完全独立的端口
- Chisel 编译干净，两个 sub-project（huancun / cute）无 error
- 兼容性：无 TCM 的配置（`tcmBaseAddr = None`）不受影响，回归 elaboration 通过

**软件生态**

- `ame.h`：60+ 指令 helper 覆盖完整 AME 指令集
- baremetal 测试 6 个 DMA/TCM 测试 + 3 个 AME GEMM 测试全部编译通过
- DMA MMIO 版本、AME 指令版本、Saturn 向量版本三种访问方式经仿真验证 PASS

**已知遗留**

- DMA v2（多 outstanding）在多次连续调用场景发现 hang，通过增加 Chisel printf 已完成定位，待用户手动重仿验证修复
- CUTE 与 Saturn 通过新 TCM 协作的 LLM workload 集成（把 llama3_1B 里的 `TCM_BUFF` 从 shuttle TCM 迁移到 HuanCun TCM）尚未做

**版本快照**

阶段性成果按 tag 固化，可一键回退：

- `tcm-复用cachesram-共用端口`：早期方案（cache 和 TCM 共享 D 通道 + hold register 补丁）
- `tcm-复用cachesram-独立端口`：当前主线（真正双端口 512b + 512b）

---

## 六、后续工作

按优先级排列：

1. **修复 v2 DMA 的多次连发 hang**，实现完整的 ~10 cyc/block DMA 吞吐
2. **实现真正的非阻塞 DMA**：现在 `ame_dma_load` 会拉低 `io.cmd.ready` 到完成，虽然简单但不能让 CPU 边搬边算；引入 `ame_dma_wait` 或让 `ame_fence` 感知 DMA 忙即可解耦
3. **将 llama3_1B 迁移到 HuanCun TCM**：
   - 权重 staging pass：每层开始前用 DMA 把该层权重搬进 0x81000000
   - CUTE 的 `matmul_cute` 里 B tensor 地址改成 TCM 地址
   - 对比传统"从 DRAM 反刍权重"vs"从 TCM 反刍权重"的整层耗时
4. **激活的层间闭环**：CUTE 输出 → TCM → Saturn epilogue → TCM → 下一层 CUTE 输入，构建 activation 从不落 DRAM 的 pipeline，进一步提升带宽利用率
5. **多 tile 场景**：目前 TCM 是 per-tile 私有的，多核 scale-up 时需要评估 TCM 地址空间的共享/独占策略

---

## 附录：核心代码/文件索引

**Chisel 侧**

| 文件 | 作用 |
|------|-----|
| [chipyard/generators/huancun/src/main/scala/huancun/HuanCun.scala](chipyard/generators/huancun/src/main/scala/huancun/HuanCun.scala) | cacheNode + tcmNode 双端口声明，HuanCunImp 顶层实例化 TcmSinkA/TcmSourceD |
| [chipyard/generators/huancun/src/main/scala/huancun/TcmSinkA.scala](chipyard/generators/huancun/src/main/scala/huancun/TcmSinkA.scala) | TCM 端 A 通道消化、读写状态机、reorder |
| [chipyard/generators/huancun/src/main/scala/huancun/TcmSourceD.scala](chipyard/generators/huancun/src/main/scala/huancun/TcmSourceD.scala) | TCM 端 D 通道 burst 输出 |
| [chipyard/generators/huancun/src/main/scala/huancun/DataStorage.scala](chipyard/generators/huancun/src/main/scala/huancun/DataStorage.scala) | 一半 SRAM banks 划为 TCM，独立端口 |
| [chipyard/generators/huancun/src/main/scala/huancun/HCCacheParameters.scala](chipyard/generators/huancun/src/main/scala/huancun/HCCacheParameters.scala) | tcmBaseAddr / tcmSizeBytesOpt / tcmAddressSet |
| [src/main/scala/WithHuanCunL2.scala](src/main/scala/WithHuanCunL2.scala) | injectNode 拆分，tcmNode 挂 tile.tlMasterXbar |
| [src/main/scala/TcmDmaEngine.scala](src/main/scala/TcmDmaEngine.scala) | DMA 引擎（memRead + tcmWrite + ctrlNode）+ FSM v2 |
| [src/main/scala/TcmDmaCtrl.scala](src/main/scala/TcmDmaCtrl.scala) | CUTE 内部 MMIO 序列化 controller，处理 AME_DMA_LOAD |
| [src/main/scala/AMEInstConfigs.scala](src/main/scala/AMEInstConfigs.scala) | AME funct7 常量表（FUNCT_FENCE_M=0x70 / MSTATUS=0x71 / DMA_LOAD=0x72 ...） |
| [src/main/scala/AMEDecoder.scala](src/main/scala/AMEDecoder.scala) | AME 微指令译码器 |
| [src/main/scala/CUTE2YGJK.scala](src/main/scala/CUTE2YGJK.scala) | RoCC 端 CUTE tile，dispatch AME/fence/mstatus/dma_load |
| [CPU/shuttle/src/main/scala/common/Tile.scala](CPU/shuttle/src/main/scala/common/Tile.scala) | `attachSlaveToMasterXbar` / `attachMasterToMasterXbar` 公有方法 |
| [chipyard/generators/chipyard/src/main/scala/config/fragments/TcmDmaFragment.scala](chipyard/generators/chipyard/src/main/scala/config/fragments/TcmDmaFragment.scala) | `WithTcmDma` config fragment |

**软件测试侧**

| 文件 | 作用 |
|------|-----|
| [cutetest/ame_test/ame.h](cutetest/ame_test/ame.h) | 完整 AME 指令 encoding + 高层 API |
| [cutetest/ame_test/dma_tcm_smoke.c](cutetest/ame_test/dma_tcm_smoke.c) | DMA MMIO 冒烟测试 |
| [cutetest/ame_test/dma_tcm_ame_test.c](cutetest/ame_test/dma_tcm_ame_test.c) | AME 指令触发 DMA |
| [cutetest/ame_test/dma_tcm_roundtrip.c](cutetest/ame_test/dma_tcm_roundtrip.c) | DMA 双向 (TCM ↔ DRAM) |
| [cutetest/ame_test/saturn_tcm_test.c](cutetest/ame_test/saturn_tcm_test.c) | Saturn 向量指令访问 HuanCun TCM |
| [cutetest/ame_test/ame_matmul_512x512x512_dma.c](cutetest/ame_test/ame_matmul_512x512x512_dma.c) | 完整 DMA + GEMM 端到端 |
| [cutetest/ame_test/tcm_pingpong_skel.c](cutetest/ame_test/tcm_pingpong_skel.c) | 双缓冲骨架，非阻塞 DMA 就位后可扩展 |
| [L2_TCM_DMA_Refactor_Plan.md](L2_TCM_DMA_Refactor_Plan.md) | 完整设计文档（分层、Phase、验证策略、风险回退） |
