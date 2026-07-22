# HuanCun L2 双端口化 + TCM DMA 引擎 改造计划

## 0. 目标概述

本计划包含两项紧密相关的改造：

1. **HuanCun L2 双端口拆分**：将当前"cache 请求和 TCM 请求共享流水线"的架构，重构为"cache 和 TCM 使用完全独立的 TileLink 通道"，实现零竞争、零仲裁。
2. **TCM DMA 引擎**：新增 tile 内的 DMA 加速器,支持从主存批量拷贝数据进 TCM,避免 CPU 逐字 load 的性能瓶颈。

两项存在强依赖:DMA 写 TCM 的通路直接使用双端口化后的 `tcmNode`,因此**必须先完成 L2 双端口改造**。

## 1. 现状回顾

### 1.1 关键组件与位置

| 组件 | 位置 | 角色 |
|------|------|------|
| Shuttle Core | [CPU/shuttle/](CPU/shuttle/) | 6-wide 顺序超标量 CPU |
| Saturn RVV | [chipyard/generators/saturn/](chipyard/generators/saturn/) | 向量单元,嵌入 ShuttleTile |
| CUTE | [src/main/scala/CUTE2YGJK.scala](src/main/scala/CUTE2YGJK.scala) | RoCC 加速器 |
| HuanCun L2 | [chipyard/generators/huancun/](chipyard/generators/huancun/) | tile 私有 L2,含 TCM |

### 1.2 当前 L2 内部结构（改造前）

```
上游 Xbar ────► HuanCun.node (单一 TLAdapterNode)
                    │
                    ▼
                 SinkA (共享 put-buffer, 三口 pop)
                    │
              isTcmRequest() 译码
                    │
        ┌───────────┴───────────┐
        │ (cache)               │ (TCM)
        ▼                       ▼
   RequestBuffer            TCM 旁路 SM
   MSHRAlloc                (tcmReadAccept/
   MainPipe                  tcmWriteAccept)
        │                       │
        ▼                       ▼
   Cache SRAM (8 banks)     TCM SRAM (8 banks)
        │                       │
        └───────────┬───────────┘
                    ▼
                  dArb (cache 优先)
                    ▼
              上游 D 通道
```

### 1.3 共享/冲突点清单

- **A 通道单一入口**:cache/TCM 请求混流进 SinkA
- **PutBuffer 共享**:`d_pb_pop`/`a_pb_pop`/`tcm_pb_pop` 三口仲裁 ([SinkA.scala:39-42, 133-137](chipyard/generators/huancun/src/main/scala/huancun/SinkA.scala#L39-L137))
- **地址译码开销**:每周期跑 `isTcmRequest()` ([Slice.scala:140-153](chipyard/generators/huancun/src/main/scala/huancun/Slice.scala#L140-L153))
- **D 通道 dArb**:cache 优先,TCM 用 hold reg 保命 ([Slice.scala:343-346](chipyard/generators/huancun/src/main/scala/huancun/Slice.scala#L343-L346))
- **`tcmRdHoldValid/tcmRdHoldData`**:完全是为了应对 dArb 抢不到而存在的补丁

SRAM 层已经是分离的 ([DataStorage.scala:299-336](chipyard/generators/huancun/src/main/scala/huancun/DataStorage.scala#L299-L336)),两组 bank 互不干扰,**不需要动**。

## 2. 改造 A:HuanCun L2 双端口化

### 2.1 核心思路（一句话）

把 HuanCun 对外的单一 `TLAdapterNode` 拆成两个独立节点:
- `cacheNode: TLAdapterNode` — cache 段,保留完整 coherence 语义
- `tcmNode: TLManagerNode` — TCM 段,`RegionType.UNCACHED`,纯 Get/Put slave

上游 `tlMasterXbar` 按 `AddressSet` 自动路由,**上游几乎不用改**。

### 2.2 改造后架构

```
上游 Xbar ─┬─ TL(cache 段) ──► cacheNode ──► SinkA ─► MSHR/MainPipe ─► SourceD ──► cacheNode.D
           │
           └─ TL(TCM 段)   ──► tcmNode ────► TcmSinkA ─► TCM SRAM ─► TcmSourceD ──► tcmNode.D

(两条通路除时钟外无任何 valid/ready 交互)
```

### 2.3 分层实施

**Layer 1: Diplomacy 边界拆分**

修改 [HuanCun.scala:217-245](chipyard/generators/huancun/src/main/scala/huancun/HuanCun.scala#L217):

```scala
val cacheNode = TLAdapterNode(
  clientFn  = { _ => clientPortParams },
  managerFn = { m => m.v1copy(managers = m.managers.map { mgr =>
    mgr.v1copy(address = mgr.address.flatMap(_.subtract(tcmAddressSet)))
  })}
)

val tcmNode = TLManagerNode(Seq(TLSlavePortParameters.v1(
  managers = Seq(TLSlaveParameters.v1(
    address            = Seq(tcmAddressSet),
    regionType         = RegionType.UNCACHED,
    executable         = true,
    supportsGet        = TransferSizes(1, blockBytes),
    supportsPutFull    = TransferSizes(1, blockBytes),
    supportsPutPartial = TransferSizes(1, blockBytes),
    fifoId             = Some(0)
  )),
  beatBytes = beatBytes
)))
```

**Layer 2: 内部数据通路拆分**

- 抽出 `TcmSinkA`(把 [Slice.scala:202-306](chipyard/generators/huancun/src/main/scala/huancun/Slice.scala#L202-L306) 内容独立成模块)
- 删除所有 `isTcm` 分支([Slice.scala:140-282](chipyard/generators/huancun/src/main/scala/huancun/Slice.scala#L140-L282))
- 删除 `dArb` 和 `tcmRdHold*` 寄存器([Slice.scala:343-346](chipyard/generators/huancun/src/main/scala/huancun/Slice.scala#L343-L346))
- 恢复 `a_req.valid := sinkAAlloc.valid`(去掉 `!isTcm` gating)
- 新建 `TcmSourceD` 独立驱动 `tcmNode` 的 D 通道

**Layer 3: SRAM 层**

不动。可选优化:把 TCM SRAM 从 [DataStorage.scala](chipyard/generators/huancun/src/main/scala/huancun/DataStorage.scala) 抽到独立的 `TcmStorage.scala`,纯代码组织清理。

**Layer 4: 参数调整**

[HCCacheParameters.scala:125-146](chipyard/generators/huancun/src/main/scala/huancun/HCCacheParameters.scala#L125-L146):
- `tcmBaseAddr` 语义变为"`tcmNode` 地址基"
- `tcmSizeBytes` 改为显式参数,不再依赖 `effectiveCacheWays`
- 保留 `nrCacheStacks` 让容量策略为可选

### 2.4 需要改动的文件

| 文件 | 改动 |
|------|------|
| [HuanCun.scala](chipyard/generators/huancun/src/main/scala/huancun/HuanCun.scala) | 拆 node → cacheNode + tcmNode |
| [Slice.scala](chipyard/generators/huancun/src/main/scala/huancun/Slice.scala) | 删 isTcm 分支、dArb、hold reg |
| [SinkA.scala](chipyard/generators/huancun/src/main/scala/huancun/SinkA.scala) | 去掉 tcm_pb_pop |
| TcmSinkA.scala(新) | TCM 独立 A 通道接收 |
| TcmSourceD.scala(新) | TCM 独立 D 通道发送 |
| [DataStorage.scala](chipyard/generators/huancun/src/main/scala/huancun/DataStorage.scala) | tcm_req 驱动源换成 TcmSinkA |
| [HCCacheParameters.scala](chipyard/generators/huancun/src/main/scala/huancun/HCCacheParameters.scala) | tcmSizeBytes 显式,语义调整 |
| [WithHuanCunL2.scala](src/main/scala/WithHuanCunL2.scala) | injectNode 处理两个 client 端口 |

### 2.5 关键设计决策与坑

1. **地址集不重叠**:cacheNode 和 tcmNode 的 `AddressSet` 必须严格不重叠,Diplomacy 会检查。
2. **UNCACHED 语义**:tcmNode 声明后,上游发 Acquire 会被 TL monitor 拒。要确保 CUTE/Saturn 用 Get/Put 而不是 Acquire 访问 TCM。
3. **"零仲裁"的严格性**:D 通道回上游后,上游 Xbar 层面仍有 arbitration。真正做到全链路无争用需要 CUTE/Saturn 各自独立 TL master 直连 tcmNode,绕过 tlMasterXbar。看设计目标决定是否走到这一步。
4. **Coherence 边界**:TCM 段 PMA 必须标 Uncacheable,防 L1D 缓存 stale 数据。
5. **`tcmAdjusterNode` 逻辑不变**:per-hart 地址偏移在 tile 层已完成,L2 收到的是最终地址。

## 3. 改造 B:TCM DMA 引擎

### 3.1 放置位置

**Tile 内独立 LazyModule**。理由:
- HuanCun 保持干净
- 复用刚拆好的 tcmNode 独立通路
- DMA 读内存那一路直接走 tlMasterXbar → cacheNode → L3 → DRAM

### 3.2 架构

```
┌────────── Tile ────────────────────────────┐
│  Shuttle   Saturn   CUTE                    │
│     │        │        │                     │
│     ▼        ▼        ▼                     │
│  ┌───────── tlMasterXbar ───────────┐       │
│  └─┬───────┬────────┬───────────────┘       │
│    │       │        │                       │
│    │   ┌───▼────────▼───┐                   │
│    │   │  TcmDmaEngine  │◄── ctrlNode(MMIO) │
│    │   │  FSM: IDLE→    │                   │
│    │   │  READ→WRITE... │                   │
│    │   │ memRead tcmWr  │                   │
│    │   └─┬────────┬─────┘                   │
│    │     │        │                         │
│    ▼     ▼        ▼                         │
│  cacheNode      tcmNode                     │
│  (HuanCun L2 双端口)                         │
└─────────────────────────────────────────────┘
```

### 3.3 三个 TL 节点

- `memReadNode: TLClientNode` — Get 主存(挂 tlMasterXbar,命中 cacheNode)
- `tcmWriteNode: TLClientNode` — PutFull 到 tcmNode(挂 tlMasterXbar)
- `ctrlNode: TLManagerNode` — MMIO 控制寄存器(挂 PBUS 或 tlSlaveXbar)

### 3.4 控制寄存器（MMIO 基址 `0x2000_0000`）

| 偏移 | 名字 | 位宽 | 语义 |
|------|------|------|------|
| 0x00 | SRC_ADDR | 64 | 内存源地址(物理地址) |
| 0x08 | DST_ADDR | 64 | TCM 目标地址 |
| 0x10 | LENGTH | 32 | 字节数(64B 对齐) |
| 0x14 | CTRL | 32 | bit0=start, bit1=irq_en, bit2=dir |
| 0x18 | STATUS | 32 | bit0=busy, bit1=done, bit2=error |
| 0x1C | IRQ_CLR | 32 | 写 1 清中断 |

### 3.5 C 驱动示例

```c
volatile struct {
    uint64_t src, dst;
    uint32_t len, ctrl, status, irq_clr;
} *dma = (void*)0x20000000ULL;

void tcm_load(void *tcm_dst, void *mem_src, size_t nbytes) {
    dma->src = (uint64_t)mem_src;
    dma->dst = (uint64_t)tcm_dst;
    dma->len = nbytes;
    dma->ctrl = 0x1;                    // start
    while (!(dma->status & 0x2)) { }    // poll done
    dma->irq_clr = 1;
}
```

### 3.6 状态机

```
IDLE ──start──► ISSUE_READ ──a.fire──► WAIT_RESP ──block collected──► ISSUE_WRITE
  ▲                                                                        │
  │                                                                        ▼
  │       DONE ◄──remain==0── ADVANCE ◄─────────────── WAIT_ACK ◄──────────┘
  │        │
  │       IRQ
  └────────┘
```

优化路线:
- 支持 64B burst(TL `size=6` Get)
- 多 outstanding(用 TL source 字段管 credit)
- Read/Write pipeline 重叠

### 3.7 新建文件

- [src/main/scala/TcmDmaEngine.scala](src/main/scala/TcmDmaEngine.scala) — DMA 引擎主模块
- [chipyard/generators/chipyard/src/main/scala/config/fragments/TcmDmaFragment.scala](chipyard/generators/chipyard/src/main/scala/config/fragments/TcmDmaFragment.scala) — `WithTcmDma` config fragment

### 3.8 关键决策

1. **地址空间**:先用物理地址,driver 保证物理连续或单页对齐。后续可接 PTW 实现虚拟地址。
2. **Cache 污染**:DMA 读内存会经过 L2 allocate。先跑起来看真实污染,治理方案二选一:
   - TL user 字段带 NoAlloc hint,HuanCun 识别并跳过 allocate
   - DMA 独立下游端口绕开 cacheNode
3. **DMA 源数据 coherence**:driver 在启动前显式 `cbo.flush` / `cbo.inval`(Zicbom)刷 L1D。硬件走 acquire 太复杂,不做。
4. **TCM SRAM 写口仲裁**:CPU/CUTE/DMA 可能都写 TCM。需要在 `io.tcm_req` 处加 arbiter。软件语义保证不并发,round-robin 即可。
5. **CUTE 集成**:让 CUTE 内部通过 custom 指令触发 DMA(CUTE 状态机戳 MMIO),对外仍是单个 RoCC。

## 4. 整合实施顺序

按依赖关系和风险递增排序。每个 Phase 独立 commit,失败可回退。

### Phase 1: L2 双端口化基础
1. [HuanCun.scala](chipyard/generators/huancun/src/main/scala/huancun/HuanCun.scala) 拆 cacheNode/tcmNode,保留原 node 作为兼容层
2. 跑通 `sbt compile`,TL monitor 无 fire
3. 改 [WithHuanCunL2.scala](src/main/scala/WithHuanCunL2.scala) 的 injectNode,处理两个 client 端口

### Phase 2: L2 内部拆分
4. 抽 `TcmSinkA`,独立于原 SinkA
5. 删 `isTcm` 分支、`dArb`、`tcmRdHold*` 寄存器
6. `TcmSourceD` 独立驱动 tcmNode.D
7. 单元测试:从 CPU 分别读写 cache 段和 TCM 段,确认响应正确

### Phase 3: DMA 引擎骨架
8. 新建 [TcmDmaEngine.scala](src/main/scala/TcmDmaEngine.scala):单 outstanding、单 beat、无 burst
9. 挂 tile,跑 baremetal 测试:`dma_copy(0x8000_0000 → TCM, 64B)` 验证正确
10. `WithTcmDma` config fragment,加入 CUTE config stack

### Phase 4: DMA 性能优化
11. 加 64B burst
12. 多 outstanding(4~8)
13. Read/Write pipeline 重叠
14. 目标吞吐:接近 1 beat/cycle

### Phase 5: TCM SRAM 写口 arbiter
15. 在 `Slice.scala` 的 `io.tcm_req` 前加 2-input Arbiter(TcmSinkA + DMA)
16. 并发写压测

### Phase 6: 生态整合
17. Cache 污染治理(NoAlloc hint 或独立下游端口)
18. CUTE 加 `LOAD_WEIGHTS` custom 指令触发 DMA
19. Linux driver(可选)

### Phase 7: 高级功能（长期）
20. 虚拟地址支持(接 PTW)
21. Descriptor ring / scatter-gather
22. 中断驱动完成通知

## 5. 完整文件改动矩阵

| 文件 | Phase | 改动摘要 |
|------|-------|---------|
| [HuanCun.scala](chipyard/generators/huancun/src/main/scala/huancun/HuanCun.scala) | 1 | 拆 node → cacheNode + tcmNode |
| [WithHuanCunL2.scala](src/main/scala/WithHuanCunL2.scala) | 1 | injectNode 双端口 |
| [HCCacheParameters.scala](chipyard/generators/huancun/src/main/scala/huancun/HCCacheParameters.scala) | 1 | tcmSizeBytes 显式化 |
| [Slice.scala](chipyard/generators/huancun/src/main/scala/huancun/Slice.scala) | 2, 5 | 删共享路径;加 TCM 写口 arbiter |
| [SinkA.scala](chipyard/generators/huancun/src/main/scala/huancun/SinkA.scala) | 2 | 去 tcm_pb_pop |
| TcmSinkA.scala | 2 | 新建 |
| TcmSourceD.scala | 2 | 新建 |
| [DataStorage.scala](chipyard/generators/huancun/src/main/scala/huancun/DataStorage.scala) | 2 | tcm_req 换源 |
| TcmDmaEngine.scala | 3, 4 | 新建 |
| TcmDmaFragment.scala | 3 | 新建 |
| [Tile.scala](CPU/shuttle/src/main/scala/common/Tile.scala) | 3 | 挂 DMA node |
| [CuteConfig.scala](chipyard/generators/chipyard/src/main/scala/config/CuteConfig.scala) | 3 | 加 WithTcmDma |
| [CUTE2YGJK.scala](src/main/scala/CUTE2YGJK.scala) | 6 | LOAD_WEIGHTS 指令 |

## 6. 验证策略

- **RTL 编译**:`sbt "runMain ..."` 生成 Verilog
- **TL Monitor**:elaboration 时开启 `TLMonitor`,确保协议不违规
- **Baremetal 单元测试**:
  - `cache-only rw` — 只走 cacheNode 的读写
  - `tcm-only rw` — 只走 tcmNode 的读写
  - `dma-copy small/large` — 64B / 64KB 拷贝正确性
  - `并发访问 TCM` — CPU + DMA 同时写不同 TCM 地址
- **性能基准**:DMA 吞吐率、cache 命中率、L2 miss latency(改造前后对比)
- **FPGA 上板**(如有):跑完整 CUTE workload,测端到端加速比

## 7. 风险与回退

| 风险 | 缓解 |
|------|------|
| Diplomacy 地址集冲突 | Phase 1 就把 tcmAddressSet 单独测过 |
| tcmNode 收到 Acquire | 上游 client node 限制 `supportsProbe = none` |
| DMA cache 污染严重 | Phase 6 加 NoAlloc hint 或独立下游端口 |
| SRAM 写口并发 bug | Phase 5 前用 SW fence 保证不并发 |
| 破坏原有 workload | 每个 Phase 保留旧代码做兼容层,回归测试通过再删 |

回退策略:每个 Phase 独立 commit,如某阶段出问题可 revert 到上一 Phase 稳定点。

---

**Version**: 2026-07-21 初稿
**Owner**: (待填)
**Status**: 待评审 → 待启动

