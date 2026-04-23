# CUTE 私有 L2 缓存与 AME 指令集集成设计提案

> 版本: v0.4
> 日期: 2026-04-23
> 状态: Draft (新增 TMA 后台搬运引擎)

---

## 目录

1. [背景与动机](#1-背景与动机)
2. [设计目标](#2-设计目标)
3. [扩展一：Tile 内私有 L2 缓存系统](#3-扩展一tile-内私有-l2-缓存系统)
   - 3.1 [总体架构](#31-总体架构)
   - 3.2 [L2 Cache 微架构](#32-l2-cache-微架构)
   - 3.3 [TCM 分区机制](#33-tcm-分区机制)
   - 3.4 [TCM 访问接口](#34-tcm-访问接口)
   - 3.5 [一致性协议](#35-一致性协议)
   - 3.6 [数据流变化](#36-数据流变化)
   - 3.7 [参数化配置](#37-参数化配置)
4. [扩展二：AME 矩阵扩展指令集兼容](#4-扩展二ame-矩阵扩展指令集兼容)
   - 4.1 [指令集概述](#41-指令集概述)
   - 4.2 [Tile Register 与 Scratchpad 映射](#42-tile-register-与-scratchpad-映射)
   - 4.3 [指令编码](#43-指令编码)
   - 4.4 [指令语义与 CUTE 微指令映射](#44-指令语义与-cute-微指令映射)
   - 4.5 [配置寄存器 (CSR)](#45-配置寄存器-csr)
   - 4.6 [与现有 YGJK 指令的关系](#46-与现有-ygjk-指令的关系)
5. [系统集成方案](#5-系统集成方案)
6. [性能分析](#6-性能分析)
7. [实现计划](#7-实现计划)
8. [风险与开放问题](#8-风险与开放问题)

---

## 1. 背景与动机

### 1.1 现有架构的瓶颈

CUTE 当前的存储层次结构如下：

```
DRAM → System L2 (TileLink, 512KB inclusive) → LocalMMU → MemoryLoader (AML/BML/CML) → Scratchpad → DataController → MTE
```

存在以下关键问题：

| 问题 | 描述 | 影响 |
|------|------|------|
| **Load 延迟高** | 每次微指令均需通过 AML/BML 经 TileLink 从内存加载到 ASCP/BSCP | 每个 K 维迭代都触发内存访问，高延迟 |
| **CPU-CUTE 无数据共享** | CPU 通过 ROCC 配置 CUTE，但无法共享中间结果 | 中间数据必须写回内存再由 CUTE 重新加载 |
| **数据复用率低** | Scratchpad 容量有限，K 维迭代间同一矩阵块被反复加载 | 大量冗余内存流量，带宽浪费 |
| **独立 TCM 与缓存隔离** | 现有 Shuttle TCM (2MB @ 0x70000000) 独立于缓存层次 | TCM 与 Cache 之间的数据搬运开销大 |

### 1.2 动机

高性能处理器普遍具备私有 L2 缓存（如 BOOM v3 的 L2、Apple M 系列的 L2 per cluster）。CUTE 作为高性能矩阵加速器，需要向这一架构范式看齐：

- **减少内存访问延迟**：L2 命中可消除对 System L2 的依赖
- **提高数据复用**：缓存自然保留跨 K 维迭代的复用数据
- **统一存储层次**：CPU、RVV、CUTE 共享 L2，消除数据孤岛
- **灵活的 TCM 分区**：从 L2 data array 中分配独立 Bank 作为 TCM，对程序员透明

### 1.3 与现有设计的对照

| 特性 | 现有设计 (v2/v3) | 新设计提案 |
|------|-------------------|-----------|
| CPU-CUTE 数据交互 | ROCC 配置 → 内存 → CUTE 重加载 | 共享 L2 缓存，直接命中 |
| 私有存储 | Scratchpad (SRAM) | L2 Cache + TCM 分区 |
| TCM 实现 | 独立 SRAM (Shuttle WithTCM) | L2 data array 中独立的 TCM Banks |
| 编程模型 | YGJK 自定义指令 | YGJK + AME (RISC-V Matrix 兼容) |
| 数据加载 | AML/BML 通过 LocalMMU→TileLink→DRAM | 优先 L2 命中，未命中才访问 System L2 |

---

## 2. 设计目标

### 2.1 核心目标

1. **共享私有 L2**：CPU Core、RVV、CUTE 三者共享一个 Tile 内私有 L2 缓存
2. **TileLink 一致性**：私有 L2 通过 TileLink 与系统 L2 (LLC) 保持缓存一致性
3. **可配置 TCM 分区**：L2 data array 中部分 Bank 被配置为 TCM（物理独立 SRAM），直连 CUTE，对程序员不可见
4. **AME 指令兼容**：实现修改版 RISC-V Matrix Extension，将 SCP 组织方式改为 tile register，使 CUTE 可通过标准矩阵指令编程

### 2.2 非目标

- 不替代现有 Scratchpad：SCP 仍然是 CUTE 计算核心的高带宽暂存，L2/TCM 用于预取和数据交换
- 不改变 MTE 计算引擎的微架构
- 不支持多 Tile 之间的 L2 共享（本阶段）

---

## 3. 扩展一：Tile 内私有 L2 缓存系统

### 3.1 总体架构

```mermaid
graph TB
    subgraph TILE["CUTE Tile"]
        subgraph CORE["CPU Core"]
            PIPE["CPU Pipeline"]
            ROCC_IF["RoCC Interface"]
        end

        subgraph RVV_SUB["RVV"]
            VREG["Vector Register File"]
            VPU["Vector Processing Unit"]
        end

        subgraph CUTE_SUB["CUTE Accelerator"]
            TC["TaskController"]
            subgraph MEM_SYS["存储系统"]
                ASP["ASCP ×2 (双缓冲)"]
                BSP["BSCP ×2"]
                CSP["CSCP ×2"]
                DC_A["ADataController"]
                DC_B["BDataController"]
                DC_C["CDataController"]
            end
            MTE["MatrixTE (M×N PE)"]
        end

        subgraph PL2["Private L2 Cache + TMA"]
            PL2_CTRL["L2 Controller"]
            PL2_TAG["Tag Store"]
            PL2_CACHE_DATA["Cache Banks (Bank N~M)"]
            PL2_TCM_DATA["TCM Banks (Bank 0~N-1)<br/>直连 CUTE"]
            TCM_CTRL["TCM Controller"]
            TMA["TMA<br/>(Tensor Memory Accelerator)<br/>后台搬运引擎"]
        end
    end

    subgraph SOC["片上系统"]
        SYS_L2["System L2 (LLC)<br/>512KB Inclusive"]
        DRAM["DRAM"]
    end

    PIPE ---|D/I Cache miss| PL2
    VREG ---|Vector Load/Store| PL2
    ROCC_IF ---|配置 / TMA 描述符| TC

    TC ---|TCM 直连 (低延迟)| TCM_CTRL
    TC ---|L2 读取 (优先)| PL2_CTRL
    DC_A ---|Compute 读| ASP
    DC_B ---|Compute 读| BSP
    DC_C ---|Compute 读写| CSP

    ASP ---|预取/L2 填充| PL2_CTRL
    BSP ---|预取/L2 填充| PL2_CTRL
    CSP ---|回写/L2 填充| PL2_CTRL

    TCM_CTRL ---|CUTE/RVV 直连| PL2_TCM_DATA
    TCM_CTRL ---|TMA 搬运| TMA
    PL2_CTRL ---|Cache 访问| PL2_CACHE_DATA

    TMA ---|TileLink Client (独立)| SYS_L2
    PL2_CTRL ---|TileLink Client| SYS_L2
    SYS_L2 --- DRAM
```

### 3.2 L2 Cache 微架构

#### 3.2.1 基本参数

| 参数 | 建议值 | 说明 |
|------|--------|------|
| 总容量 | 256KB ~ 1MB | 可参数化配置，典型 512KB |
| Cache 部分 | Cache Banks 占用的容量 | Set-associative，仅 Cache Banks 参与 |
| TCM 部分 | TCM Banks 占用的容量 | 独立 SRAM Bank，直连 CUTE，无 Tag |
| 总 Bank 数 | 8 ~ 16 | 物理 SRAM 实例数，所有 Bank 统一编址 |
| TCM Bank 数 | 总 Bank 数的 1/4 ~ 1/2 | 例: 8 Banks 中 4 个作为 TCM |
| Associativity | 8-way ~ 16-way | 与 Rocket/BOOM L2 对齐 |
| Line Size | 64B (标准) | 与系统 L2 一致 |
| 端口数 | 2~4 读端口 + 1~2 写端口 | 服务 CPU / RVV / CUTE |
| Tag Store | 独立 SRAM | 仅覆盖 Cache Banks，TCM Banks 无 Tag |
| Data Array | 统一 SRAM Bank 编址 | TCM Banks 与 Cache Banks 物理独立 |

#### 3.2.2 微架构细节

**Bank 组织**：Data Array 采用 N-bank 交织结构，Bank 按用途分为两组：

- **TCM Banks (Bank 0 ~ N_tcm-1)**：整体作为 TCM，**物理上独立的 SRAM 实例**，无 Tag、无替换逻辑，直连 CUTE 和 RVV，提供确定性低延迟访问
- **Cache Banks (Bank N_tcm ~ N_total-1)**：组成 Set-associative Cache，有 Tag Store，参与 TileLink 一致性协议，服务 CPU L1D miss / RVV / CUTE MemoryLoader

**关键设计**：当 RVV 或 CPU 需要更宽数据通路（如向量突发访问）时，可跨越 **全部 Bank（TCM + Cache）聚合** 获取更高带宽。但 TCM Banks 在聚合模式下仍保持无 Tag 访问的语义——Cache Banks 的聚合走正常 cache 通路，TCM Banks 的聚合走直连通路，两者在输出端 Mux 合并。

**TMA (Tensor Memory Accelerator)**：TMA 是独立的后台搬运引擎，拥有**独立的 TileLink Client 端口**连接 LLC。TMA 负责 TCM 与 DRAM 之间的批量数据搬运，软件下发一条"搬运描述指令"（Transfer Descriptor），TMA 在后台自动完成全部搬运，不占用 CPU 或 CUTE 的计算资源。TMA 与 Private L2 Controller 的 TileLink 端口独立，两者互不干扰。

```
Data Array Layout (以 8 Bank、4 TCM + 4 Cache 为例):
┌──────────────────────────────────────────────────────────────────┐
│                        物理 Bank 编号                             │
│  Bank 0    Bank 1    Bank 2    Bank 3    Bank 4    ...   Bank 7 │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐       ┌──────┐  │
│  │      │ │      │ │      │ │      │ │Cache │       │Cache │  │
│  │ TCM  │ │ TCM  │ │ TCM  │ │ TCM  │ │Set 0 │       │Set 0 │  │
│  │      │ │      │ │      │ │      │ │Set 1 │       │Set 1 │  │
│  │      │ │      │ │      │ │      │ │ ...  │       │ ...  │  │
│  │      │ │      │ │      │ │      │ │Set S │       │Set S │  │
│  └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘       └──┬───┘  │
│     │        │        │        │        │               │       │
│  ←──┴────────┴────────┴────────┴──┐    ├───────────────┘       │
│     TCM Controller (直连 CUTE)      │    L2 Cache Controller    │
│     低延迟, 无 Tag 查找             │    有 Tag + Way 选择       │
│     带宽: N_tcm × DataWidth        │    Bank 交织, TileLink     │
└─────────────────────────────────────┴───────────────────────────┘

CUTE 专用路径 (TCM 直连):
  CUTE/RVV → TCM Controller → TCM Banks (Bank 0~3)
  延迟: 1 cycle (read) / 1 cycle (write)
  带宽: 4 × 512bit = 2048 bit/cycle

L1D/RVV 正常路径 (Cache 访问):
  CPU L1 miss → L2 Controller → Cache Banks (Bank 4~7)
  延迟: 5~15 cycles (tag lookup + data read)

RVV 宽向量聚合路径 (跨 Bank):
  RVV burst → Cache Banks + TCM Banks → Mux 聚合 → RVV
  带宽: 8 × 512bit = 4096 bit/cycle (全聚合)
```

**请求优先级**（从高到低）：

1. **TCM 直连访问**（CUTE ↔ RVV 数据交换）—— 独立 Bank，不与 Cache 竞争，固定 1 cycle 延迟
2. **CUTE L2 读取**（MemoryLoader 从 Cache Banks 加载到 SCP）
3. **CPU L1 miss 填充**
4. **RVV Vector Load/Store**（走 Cache Banks，或聚合全部 Banks）
5. **L2 写回 / Eviction**

**替换策略**：仅 Cache Banks 参与 LRU/PLRU 替换。TCM Banks 作为专用 SRAM，不参与任何替换策略。

### 3.3 TCM 分区机制

#### 3.3.1 设计原则

TCM 由 Data Array 中**物理独立的 Bank** 组成（非从 Cache Bank 中切分），具有以下特性：

- **对程序员不可见**：TCM 不是内存映射地址空间，CPU/VPU 不通过 Load/Store 指令访问
- **硬件管理**：由 CUTE TaskController 和 RVV 控制逻辑通过专用端口访问
- **物理独立**：TCM Banks 与 Cache Banks 是独立的 SRAM 实例，无地址空间重叠
- **直连 CUTE**：TCM Banks 有专用数据通路直连 CUTE，不经过 L2 Cache Controller 的 Tag 查找和替换逻辑
- **固定低延迟**：无 tag 查找、无 Mux 冲突、无替换逻辑，访问延迟确定且极低 (1 cycle)

#### 3.3.2 Bank 分配策略

Bank 分配采用**静态分区**：在编译时确定哪些 Bank 作为 TCM，哪些作为 Cache：

```
Bank 分配规则:
  Bank 0        ~ Bank (TCMBanks-1)     → TCM Banks (直连 CUTE)
  Bank TCMBanks ~ Bank (L2NBanks-1)    → Cache Banks (Set-associative)

示例 (L2NBanks=8, TCMBanks=4):
  Bank 0~3 → TCM (4 × 16KB = 64KB, 或 4 × 32KB = 128KB)
  Bank 4~7 → Cache (4-way interleaved, Set-associative)

示例 (L2NBanks=16, TCMBanks=8):
  Bank 0~7  → TCM (8 × 32KB = 256KB)
  Bank 8~15 → Cache (8-way interleaved, Set-associative)
```

**TCMBanks 数量选择建议**：
- TCM 总容量应 ≥ 2 × max(AScratchpadSize, BScratchpadSize)，以容纳 A/B 双缓冲数据交换
- 建议 TCMBanks ≥ Matrix_M 且 ≥ Matrix_N，便于 MTE 供数时无 bank 冲突
- Cache Banks 数量应保证足够的关联度和 set 数量以维持 cache 命中率

#### 3.3.3 TCM 容量配置

TCM 容量通过编译时参数配置（参数化在 `CuteParams` 中）：

```scala
case class CuteL2TCMParams(
    val L2NBanks: Int = 8,               // Data Array 总 bank 数 (物理 SRAM 实例数)
    val TCMBanks: Int = 4,               // TCM bank 数量 (Bank 0 ~ TCMBanks-1)
    val L2NWays: Int = 8,                // Cache 关联度
    val L2LineSizeBytes: Int = 64,       // Cache Line 大小
    val TCMDataWidthBits: Int = 512,     // 每个 TCM Bank 的数据端口宽度
    val BankSizeKB: Int = 32,            // 每个 Bank 的容量 (KB)

    // === TMA (Tensor Memory Accelerator) 参数 ===
    val TMAEnable: Boolean = true,       // 是否启用 TMA
    val TMADescriptorQueueDepth: Int = 4,// TMA 描述符队列深度
    val TMAFIFODepth: Int = 8,           // TMA 数据 FIFO 深度 (line 数)
    val TMASourceMaxNum: Int = 8,        // TMA TileLink source ID 数量
) {
    val CacheNBanks = L2NBanks - TCMBanks
    val L2TotalSizeKB = L2NBanks * BankSizeKB
    val TCMSizeKB = TCMBanks * BankSizeKB
    val CacheSizeKB = CacheNBanks * BankSizeKB
    val L2NSets = CacheSizeKB / (CacheNBanks * L2NWays * L2LineSizeBytes)
    // 注: 每个 Cache Bank 内的 Set 数 = CacheSizeKB / CacheNBanks / (L2NWays * L2LineSizeBytes)
    require(TCMBanks < L2NBanks, "TCM banks must be less than total banks")
    require(TCMBanks >= 2, "At least 2 TCM banks for double buffering")
    require(isPow2(L2NBanks) && isPow2(TCMBanks), "Bank counts must be power of 2")
}
```

#### 3.3.4 TCM 寻址模型

TCM 在逻辑上被组织为一个线性地址空间，由 CUTE 内部地址寻址。地址直接译码为 Bank ID + Word Address：

```
TCM Address:
┌──────────────┬──────────┬──────────┐
│ Word Addr    │ Bank ID  │ Byte Off │
│ (高位)       │ (log2(TCMBanks)) │ (log2(TCMDataWidthBits/8)) │
└──────────────┴──────────┴──────────┘

物理映射:
  Bank ID = addr[log2(TCMBanks)+log2(TCMDataWidthBits/8)-1 : log2(TCMDataWidthBits/8)]
  → 直接选择 Bank 0 ~ TCMBanks-1 中的一个 SRAM 实例

  Word Addr = addr[高位]
  → 选中 Bank 内的字地址

优势: Bank 选择和字地址译码在同一周期完成，无需 Tag 查找
```

TCM 的逻辑地址空间映射到 tile register 机制，详见第 4 节。

### 3.4 TCM 访问接口

#### 3.4.1 接口定义

TCM Controller 直接管理 TCM Banks (Bank 0 ~ TCMBanks-1)，提供多端口并发访问。TMA 作为独立模块通过 TCM Controller 的 Port D 访问 TCM Banks：

```
┌──────────────────────────────────────────────────────────┐
│                    TCM Controller                          │
├────────────┬─────────────────────────────────────────────┤
│ Port A     │ CUTE → TCM (直连路径, 最高优先级)            │
│            │ - 写 TCM (CSCP → TCM)                        │
│            │ - 读 TCM (TCM → ASCP/BSCP)                   │
│            │ 延迟: 1 cycle (直接 SRAM 读写)                │
├────────────┼─────────────────────────────────────────────┤
│ Port B     │ RVV → TCM (Vector path, 直连路径)            │
│            │ - 写 TCM (VRF → TCM)                         │
│            │ - 读 TCM (TCM → VRF)                         │
│            │ 延迟: 1 cycle                                 │
├────────────┼─────────────────────────────────────────────┤
│ Port C     │ 聚合路径 (Cache Banks + TCM Banks → L1D/RVV) │
│            │ - RVV 宽向量 burst 跨 Bank 聚合读取           │
│            │ - 带宽: 全部 N_banks × DataWidth             │
│            │ 延迟: Cache 部分 5~15 cycles, TCM 部分 1 cyc  │
├────────────┼─────────────────────────────────────────────┤
│ Port D     │ TMA → TCM (Tensor Memory Accelerator)        │
│            │ - TMA 写 TCM (DRAM → LLC → TMA → TCM, Load)  │
│            │ - TMA 读 TCM (TCM → TMA → LLC → DRAM, Store) │
│            │ 延迟: 1~2 cycles (TMA FIFO → TCM SRAM)       │
│            │ 独立 TileLink 端口到 LLC，不经过 L2 Controller│
└────────────┴─────────────────────────────────────────────┘

端口仲裁:
  Port A (CUTE) > Port B (RVV) > Port D (TMA)  // Port C 走独立聚合通路
  同一 cycle 内不同 Port 可访问不同 Bank，无冲突
  同一 Port 同时访问同一 Bank 时，Port A 优先
  Port D (TMA) 与 Port A/B 的 Bank 冲突时，TMA 自动 stall (不影响 CUTE/RVV)
```

#### 3.4.2 CUTE 侧访问 (Port A)

CUTE 通过 MemoryLoader 与 TCM 交互，替代部分从内存加载的路径。TCM Banks 通过**专用数据通路**直连 CUTE，不经过 L2 Cache Controller：

```scala
class TCMControllerIO extends Bundle {
    // CUTE → TCM (写入：将数据放入 TCM 供 RVV 读取)
    val cute_write = Flipped(Decoupled(new Bundle {
        val addr = UInt(TCMAddrWidth.W)  // TCM 内部地址
        val data = UInt(TCMDataWidthBits.W)
        val strb = UInt((TCMDataWidthBits / 8).W)  // Byte strobe
    }))

    // CUTE ← TCM (读取：从 TCM 获取 RVV 放入的数据)
    val cute_read = Decoupled(new Bundle {
        val addr = UInt(TCMAddrWidth.W)
    })
    val cute_read_data = Input(UInt(TCMDataWidthBits.W))

    // RVV → TCM (写入：向量寄存器 → TCM)
    val rvv_write = Flipped(Decoupled(new Bundle {
        val addr = UInt(TCMAddrWidth.W)
        val data = UInt(TCMDataWidthBits.W)
        val strb = UInt((TCMDataWidthBits / 8).W)
    }))

    // RVV ← TCM (读取：TCM → 向量寄存器)
    val rvv_read = Decoupled(new Bundle {
        val addr = UInt(TCMAddrWidth.W)
    })
    val rvv_read_data = Output(UInt(TCMDataWidthBits.W))
}
```

#### 3.4.3 访问时序

| 操作 | 延迟 (cycles) | 说明 |
|------|--------------|------|
| CUTE → TCM 写 | 1 | 直连路径，直接写入 TCM Bank SRAM |
| CUTE ← TCM 读 | 1 | 直连路径，无 Tag 查找，Bank 读取即返回 |
| RVV → TCM 写 | 1 | 直连路径，直接写入 TCM Bank SRAM |
| RVV ← TCM 读 | 1 | 直连路径，同上 |
| RVV 宽向量读取 (全 Bank 聚合) | 5~15 | Cache Banks 走 Tag 查找 + TCM Banks 直连，最后 Mux 合并 |
| TMA → TCM 写 (DRAM→TCM) | 1~2 | TMA FIFO → TCM Bank SRAM (TMA 独立 TileLink 端口) |
| TCM → TMA 读 (TCM→DRAM) | 1~2 | TCM Bank SRAM → TMA FIFO → TileLink |
| CPU L1 miss → L2 (Cache Banks) | 5~15 | 标准缓存访问，仅访问 Cache Banks |
| **TMA 后台搬运总延迟** | **T_fill + N×T_line** | T_fill 为首字延迟，N 为 line 数，T_line 为每 line 间隔 |

#### 3.4.4 TMA (Tensor Memory Accelerator) 接口

TMA 是独立的硬件搬运引擎，接收软件下发的**搬运描述符**后在后台自动完成 TCM ↔ DRAM 的数据搬运。

**TMA 功能特性：**
- 支持 **1D/2D/3D 张量搬运**（带 stride 的非连续地址访问）
- 支持 **多描述符队列**，可同时排队多条搬运任务
- **独立 TileLink Client 端口**连接 LLC，与 Private L2 Controller 的 TileLink 端口独立
- 支持 **Load (DRAM→TCM)** 和 **Store (TCM→DRAM)** 两个方向
- **后台异步执行**：软件下发描述符后立即返回，通过 CSR 状态位或中断查询完成
- **Bank 冲突避让**：当 TMA 访问的 TCM Bank 与 CUTE/RVV 冲突时，TMA 自动 stall

**搬运描述符格式 (TMADescriptor, 256-bit)：**

```
TMADescriptor:
┌──────────────────────────────────────────────────────────────┐
│ Bit 255:192 (64-bit) - src_addr: 源物理地址                  │
│   Load: DRAM 物理地址 (经 MMU 转换后)                        │
│   Store: TCM 偏移地址                                        │
├──────────────────────────────────────────────────────────────┤
│ Bit 191:128 (64-bit) - dst_addr: 目标地址                    │
│   Load: TCM 偏移地址                                        │
│   Store: DRAM 物理地址                                       │
├──────────────────────────────────────────────────────────────┤
│ Bit 127:96  (32-bit) - byte_count: 总搬运字节数 (对齐到 line)│
├──────────────────────────────────────────────────────────────┤
│ Bit 95:64   (32-bit) - config: 搬运配置                      │
│   [31:28] direction  - 0=Load(DRAM→TCM), 1=Store(TCM→DRAM)  │
│   [27:16] src_stride - 源行步长 (bytes), 0=连续              │
│   [15:4]  dst_stride - 目标行步长 (bytes), 0=连续            │
│   [3:0]   flags      - [0]=完成中断使能                      │
├──────────────────────────────────────────────────────────────┤
│ Bit 63:32   (32-bit) - tensor_shape: 张量形状                │
│   [31:16] width      - 每行搬运字节数 (bytes)                │
│   [15:0]  height     - 行数                                  │
└──────────────────────────────────────────────────────────────┘
```

**TMA 状态机：**

```
                    ┌─────────┐
           描述符写入│  IDLE   │
           ────────→│  等待   │
                    └────┬────┘
                         │ 收到有效描述符
                    ┌────▼────┐
                    │ ISSUING │
                    │ 发起    │──── 首次 TileLink 请求
                    │ TileLink│──── (AcquireBlock / Get)
                    └────┬────┘
                         │ 数据开始返回
                    ┌────▼────┐
            ┌──────→│ XFER    │
            │       │ 搬运中  │──── 逐 line 搬运
            │       └────┬────┘    (TMA FIFO ↔ TCM Banks)
            │            │ byte_count 搬完
            │       ┌────▼────┐
            │       │  DONE   │──── 置完成标志 / 发中断
            │       └────┬────┘
            │            │
            └────────────┘ 取下一条描述符 (如有)
```

**TMA CSR 接口：**

```scala
// TMA 通过 CSR 接收描述符和查询状态
class TMAIO extends Bundle {
    // 描述符提交 (CPU 通过 RoCC custom command 写入)
    val descriptor = Flipped(Decoupled(UInt(256.W)))  // 256-bit 描述符

    // TCM 端口 (连接到 TCM Controller Port D)
    val tcm_read = Decoupled(new Bundle {
        val addr = UInt(TCMAddrWidth.W)
    })
    val tcm_read_data = Input(UInt(TCMDataWidthBits.W))
    val tcm_write = Decoupled(new Bundle {
        val addr = UInt(TCMAddrWidth.W)
        val data = UInt(TCMDataWidthBits.W)
        val strb = UInt((TCMDataWidthBits / 8).W)
    })

    // TileLink 端口 (独立连接到 LLC)
    val tilelink = new TLClientPort

    // 状态查询
    val status = Output(UInt(8.W))  // queue_depth[3:0], busy[4], error[5:7]
    val completion_irq = Output(Bool())  // 搬运完成中断
}
```

**软件使用流程：**

```c
// 1. 构造搬运描述符 (DRAM → TCM)
struct tma_desc desc = {
    .src_addr   = dram_matrix_addr,     // DRAM 物理地址
    .dst_addr   = tcm_offset_0,         // TCM 偏移
    .byte_count = 128 * 64,             // 128×64 INT8 矩阵 = 8KB
    .config     = TMA_LOAD | TMA_IRQ_EN,
    .shape      = {.width = 64, .height = 128}
};

// 2. 提交描述符 (一条 RoCC 指令，立即返回)
submit_tma_desc(&desc);   // non-blocking，TMA 在后台搬运

// 3. CPU 继续做其他工作...
// 4. 检查完成或等待中断
while (!tma_done()) { /* yield or do other work */ }
// 5. 现在 TCM 中已有数据，CUTE 可以直接从 TCM 读取 (1 cycle)
```

### 3.5 一致性协议

#### 3.5.1 一致性层次

```
                    ┌──────────────┐
                    │  DRAM        │
                    └──────┬───────┘
                           │
                    ┌──────▼───────┐
                    │ System L2    │  ← TileLink Manager
                    │ (LLC, 512KB) │
                    └──────┬───────┘
                           │ TileLink (Coherence)
              ┌────────────┼────────────┐
              │            │            │
       ┌──────▼──────┐    │     ┌──────▼──────┐
       │ Private L2  │    │     │ Private L2  │
       │ (Tile 0)    │    │     │ (Tile 1)    │
       │ + TCM       │    │     │ + TCM       │
       └─────────────┘    │     └─────────────┘
```

#### 3.5.2 TCM 一致性语义

TCM Banks 是**独立的物理 SRAM**，不直接参与 TileLink 缓存一致性协议。TCM 的数据进出通过 **TMA 的独立 TileLink 端口**进行，保证一致性：

- **TCM ↔ DRAM (via TMA)**：TMA 拥有独立 TileLink Client 端口连接 LLC。Load 时 TMA 发起 AcquireBlock 从 LLC/DRAM 获取数据；Store 时 TMA 发起 ReleaseData 将脏数据写回 LLC/DRAM。所有操作遵循 TileLink 一致性协议，确保 TCM 数据与系统一致
- **TCM ↔ CUTE/RVV (直连)**：TCM Banks 与 CUTE/RVV 之间的直连路径不经过 TileLink。这些是 Tile 内部的数据交换，由软件通过 fence.m 保证时序
- **TCM 内部一致性**：TCM 是 CUTE 和 RVV 的共享暂存，由软件/固件保证访问顺序（fence.m 同步）
- **TMA 与 L2 Controller 端口独立**：TMA 的 TileLink 端口与 Private L2 Controller 的 TileLink 端口是两个独立的 TileLink Client，两者在片上互连上互不干扰。TMA 的大量数据搬运不会阻塞 CPU/RVV 的正常缓存访问

#### 3.5.3 Cache 部分的一致性

Cache 部分通过 TileLink 协议与 System L2 保持一致性：

- 使用 **TileLink Client** 接口连接到片上互连
- 支持的 TileLink 消息类型：
  - **Acquire/Release**：正常缓存读写
  - **Probe**：响应系统 L2 的无效化请求
  - **Grant**：数据授权
- 推荐使用 **TileLink Coherence Protocol** 中的 MESI 或 MOESI 变体

### 3.6 数据流变化

#### 3.6.1 现有数据流 (v2)

```
Load Phase:
  DRAM → System L2 → TileLink → LocalMMU → AML → ASCP
  DRAM → System L2 → TileLink → LocalMMU → BML → BSCP

Compute Phase:
  ASCP → ADC → MTE → CDC → CSCP

Store Phase:
  CSCP → CML → LocalMMU → TileLink → System L2 → DRAM
```

#### 3.6.2 新数据流 (v4 with L2 + TCM + TMA)

```
Load Phase (L2 命中):
  Private L2 → AML → ASCP              ← 省去 TileLink + System L2 往返
  Private L2 → BML → BSCP

Load Phase (L2 未命中):
  DRAM → System L2 → TileLink → Private L2 → AML → ASCP

TCM 预填充 (TMA 后台搬运, 与 Compute 重叠):
  DRAM → System L2 → TileLink(TMA端口) → TMA → TCM Banks
  软件提交描述符后立即返回，TMA 在后台自动完成
  TMA 独立 TileLink 端口，不阻塞 CPU/RVV/CUTE 的正常缓存访问

TCM 回写 (TMA 后台搬运):
  TCM Banks → TMA → TileLink(TMA端口) → System L2 → DRAM

RVV → CUTE 数据交换 (通过 TCM 直连):
  VRF → TCM Controller → TCM Banks      ← RVV 写入 (直连, 1 cycle)
  TCM Banks → TCM Controller → AML → ASCP ← CUTE 读取 (直连, 1 cycle)

CUTE → RVV 数据交换 (通过 TCM 直连):
  CSCP → CML → TCM Controller → TCM Banks ← CUTE 写入 (直连, 1 cycle)
  TCM Banks → TCM Controller → VRF          ← RVV 读取 (直连, 1 cycle)

Compute Phase (不变):
  ASCP → ADC → MTE → CDC → CSCP

Store Phase (写回 L2):
  CSCP → CML → Private L2               ← 写回 Private L2 而非直接 DRAM
  Private L2 → (eviction) → System L2 → DRAM
```

#### 3.6.3 关键优化场景

**场景 1：K 维迭代的跨轮复用**

```
现有: K=0: DRAM→ASCP[BSCP] → Compute → K=1: DRAM→ASCP[BSCP] → Compute → ...
新:   K=0: DRAM→Private L2→ASCP[BSCP] → Compute → K=1: Private L2→ASCP[BSCP] → ...
                                         ↑ L2 命中，无需访问 DRAM
```

**场景 2：CPU 预处理 → CUTE 计算**

```
现有: CPU 计算(ROCC) → Store to DRAM → CUTE Load from DRAM
新:   CPU 计算(ROCC) → Write to Private L2 → CUTE Load from Private L2 (L2 hit)
```

**场景 3：RVV element-wise → CUTE matmul**

```
现有: RVV(vadd/vmul) → Store to DRAM → CUTE Load from DRAM → Compute
新:   RVV(vadd/vmul) → Write to TCM (1 cycle) → CUTE Load from TCM (1 cycle!) → Compute
```

**场景 4：TMA 后台预取与计算重叠 (关键新场景)**

```
时间线:
  t0: CPU 提交 TMA 描述符 (DRAM→TCM, A 矩阵)       ← 1 cycle, 立即返回
  t1: CPU 提交 TMA 描述符 (DRAM→TCM, B 矩阵)       ← 排队等待
  t2: CPU 继续其他工作 (配置 CSR, 启动其他任务...)
  ...
  t_N: TMA 完成搬运 → 置完成标志
  t_N+1: CUTE 直接从 TCM 读取 (1 cycle!) → Compute

对比无 TMA:
  无 TMA: CUTE 等待 AML Load (DRAM→ASCP) → 40~100 cycles 空闲等待
  有 TMA: CUTE 从 TCM 读取 → 1 cycle，搬运在后台已完成
```

**场景 5：TMA 流水线化多轮搬运**

```
TMA 描述符队列:
  [desc0] DRAM addr0 → TCM offset0 (8KB, A 矩阵)    ← 正在搬运
  [desc1] DRAM addr1 → TCM offset1 (8KB, B 矩阵)    ← 排队
  [desc2] DRAM addr2 → TCM offset2 (64KB, C 初始值)  ← 排队

TMA 逐条执行，CPU 只提交一次，后续搬运完全硬件自动完成
可与 CUTE 计算当前 tile 的同时预取下一个 tile 的数据
```

### 3.7 参数化配置

#### 3.7.1 CuteParams 扩展

```scala
case class CuteParams(
    // ... 现有参数保持不变 ...

    // === 新增：私有 L2 + TCM + TMA 参数 ===
    val EnablePrivateL2: Boolean = false,              // 是否启用私有 L2
    val PrivateL2Params: Option[CuteL2TCMParams] = None, // L2/TCM/TMA 参数
) {
    // ... 现有 require 保持不变 ...

    // TCM 容量推导 (基于 Bank 分配)
    def tcmSizeBytes = PrivateL2Params.map(_.TCMSizeKB * 1024).getOrElse(0)
    def tcmAddrWidth = log2Ceil(tcmSizeBytes)
    def privateL2CacheSizeBytes = PrivateL2Params.map(_.CacheSizeKB * 1024).getOrElse(0)
    def tcmAggBandwidthBits = PrivateL2Params.map(_.L2NBanks * _.TCMDataWidthBits).getOrElse(0)
}
```

#### 3.7.2 预设配置

```scala
object CuteParams {
    // ... 现有配置保持不变 ...

    // 带私有 L2 + TCM + TMA 的配置 (4Tops, 128SCP)
    // 总计 8 Bank: 4 TCM + 4 Cache, 每 Bank 32KB
    // TCM = 128KB (直连 CUTE), Cache = 128KB (Set-associative)
    def CUTE_4Tops_128SCP_L2TCM = CUTE_4Tops_128SCP.copy(
        EnablePrivateL2 = true,
        PrivateL2Params = Some(CuteL2TCMParams(
            L2NBanks = 8,
            TCMBanks = 4,
            L2NWays = 4,
            L2LineSizeBytes = 64,
            TCMDataWidthBits = 512,
            BankSizeKB = 32,
            TMAEnable = true,
            TMADescriptorQueueDepth = 4,
            TMAFIFODepth = 8,
            TMASourceMaxNum = 8,
        ))
    )

    // 带私有 L2 + TCM + TMA 的配置 (8Tops, 256SCP)
    // 总计 16 Bank: 8 TCM + 8 Cache, 每 Bank 64KB
    // TCM = 512KB (直连 CUTE), Cache = 512KB (Set-associative)
    def CUTE_8Tops_256SCP_L2TCM = CUTE_8Tops_256SCP.copy(
        EnablePrivateL2 = true,
        PrivateL2Params = Some(CuteL2TCMParams(
            L2NBanks = 16,
            TCMBanks = 8,
            L2NWays = 8,
            L2LineSizeBytes = 64,
            TCMDataWidthBits = 512,
            BankSizeKB = 64,
            TMAEnable = true,
            TMADescriptorQueueDepth = 8,
            TMAFIFODepth = 16,
            TMASourceMaxNum = 16,
        ))
    )
}
```

---

## 4. 扩展二：AME 矩阵扩展指令集兼容

> 本节基于 AME 提案文档 `docs/riscv_matrix_extension_proposal.pdf` (v0.6.0) 设计。
> AME 定义了 **tr0-3**（Tile Register，输入矩阵）和 **acc0-3**（Accumulator Register，累加器）两类寄存器。

### 4.1 指令集概述

AME (Accelerator Matrix Extension) 是基于 RISC-V Matrix Extension 的修改版提案 (v0.6.0)，针对 CUTE 的硬件特性进行适配。

#### 4.1.1 AME 寄存器模型

AME 提案定义了两类矩阵寄存器：

| 寄存器 | 数量 | 用途 | 逻辑结构 |
|--------|------|------|---------|
| **tr0~tr3** | 4 个 | Tile Register，输入矩阵 (A/B) | ROWNUM 行 × TRLEN bits/row，共 TLEN bits |
| **acc0~acc3** | 4 个 | Accumulator Register，累加输出 (C/D) | ROWNUM 行 × ARLEN bits/row，共 ALEN bits |

**关键参数定义：**

| 参数 | 含义 | 约束 | CUTE 默认值 |
|------|------|------|------------|
| `ELEN` | 最大元素宽度 (bit) | ≥8, 2 的幂 | 32 (FP32) |
| `TLEN` | 每个 tr 的总位宽 | 2 的幂, ≤2³² | 65536 (8KB) |
| `TRLEN` | 每个 tr 每行的位宽 | 2 的幂, ≤2¹⁶ | 512 (64B) |
| `ROWNUM` | tr 的行数 = TLEN / TRLEN | ROWNUM = TLEN / TRLEN | 128 |
| `ARLEN` | 每个 acc 每行的位宽 = ROWNUM × ELEN | ARLEN = ROWNUM × ELEN | 4096 (512B) |
| `ALEN` | 每个 acc 的总位宽 = ARLEN × ROWNUM | ALEN = ARLEN × ROWNUM | 524288 (64KB) |

#### 4.1.2 与标准 RISC-V Matrix Extension 的差异

| 特性 | RISC-V Matrix Extension | AME (CUTE 适配) |
|------|------------------------|-----------------|
| Tile Register | 逻辑 tile register | **tr0-3** 映射到 ASCP/BSCP |
| Accumulator | 逻辑 accumulator | **acc0-3** 映射到 CSCP |
| Tile 尺寸 | 运行时可配 (cfgcsr) | 编译时固定 (Tensor_M, Tensor_N, Tensor_K) |
| 矩阵乘法操作 | madd, sub, add 等 | madd, sub, add + CUTE 特有操作 |
| 数据搬运 | Load/Store tile (memory) | Load/Store tile (memory) + TCM (CUTE↔RVV) |
| 累加 | acc 驻留 | CSCP 双缓冲 |
| 配置 | mcfgcsr, cfgctl | xmcscr + mtilem/mtilek/mtilen + CUTE 扩展 CSR |
| Scale Factor | 不支持 | 支持 MXFP8/MXFP4 block-scale (CUTE 扩展) |
| 数据类型 | 统一 SEW | 支持 13 种数据类型 (CUTE 扩展) |

#### 4.1.3 设计原则

1. **兼容 AME 提案**：遵循 `docs/riscv_matrix_extension_proposal.pdf` v0.6.0 定义的 tr0-3/acc0-3 寄存器模型和 CSR 地址空间
2. **CUTE 硬件约束透明化**：Tile 尺寸、数据类型等通过 CSR 暴露给软件
3. **保留 YGJK 指令集**：AME 作为编程接口的上层，底层仍可使用 YGJK 微指令

### 4.2 Tile Register 与 Scratchpad 映射

#### 4.2.1 映射关系

AME 的 **tr0-3** 和 **acc0-3** 映射到 CUTE 的 Scratchpad 系统，利用 CUTE 的双缓冲机制实现计算与加载的重叠：

```
AME Tile Register / Accumulator → CUTE Scratchpad 映射:
┌──────────────────────────────────────────────────────────────────┐
│  tr0  ─→  ASCP[0] (A matrix, bank 0)     [Input A, 双缓冲]     │
│  tr1  ─→  ASCP[1] (A matrix, bank 1)     [Input A, 双缓冲]     │
│  tr2  ─→  BSCP[0] (B matrix, bank 0)     [Input B, 双缓冲]     │
│  tr3  ─→  BSCP[1] (B matrix, bank 1)     [Input B, 双缓冲]     │
│                                                                  │
│  acc0 ─→  CSCP[0] (C/D accumulator, bank 0)  [I/O C/D, 双缓冲] │
│  acc1 ─→  CSCP[1] (C/D accumulator, bank 1)  [I/O C/D, 双缓冲] │
│  acc2 ─→  CSCP 扩展 / Reserved             [未来扩展]          │
│  acc3 ─→  CSCP 扩展 / Reserved             [未来扩展]          │
└──────────────────────────────────────────────────────────────────┘

物理存储容量 (CUTE_8Tops_128SCP 默认参数):
  ASCP: Tensor_M × ReduceGroupSize × ReduceWidthByte = 128 × 1 × 64 = 8 KB / bank
  BSCP: Tensor_N × ReduceGroupSize × ReduceWidthByte = 128 × 1 × 64 = 8 KB / bank
  CSCP: Tensor_M × Tensor_N × ResultWidthByte = 128 × 128 × 4 = 64 KB / bank
```

**映射规则：**
- **tr0, tr1** → ASCP 双缓冲：两个 bank 交替使用，一个用于当前计算，另一个用于后台加载
- **tr2, tr3** → BSCP 双缓冲：同上
- **acc0, acc1** → CSCP 双缓冲：累加结果驻留在 CSCP 中，整个 K 维度遍历后才写回
- **acc2, acc3** → 预留给扩展用途（如额外的累加缓冲或 Scale Factor 存储）

#### 4.2.2 双缓冲与流水线重叠

CUTE 的双缓冲机制通过 tr/acc 寄存器的交替使用来表达：

```
双缓冲循环 (Ping-Pong):
  Iteration 0: tr0 (ASCP[0]), tr2 (BSCP[0]), acc0 (CSCP[0]) → Compute
               tr1 (ASCP[1]), tr3 (BSCP[1]) ← 后台 Load (与 Compute 重叠)

  Iteration 1: tr1 (ASCP[1]), tr3 (BSCP[1]), acc1 (CSCP[1]) → Compute
               tr0 (ASCP[0]), tr2 (BSCP[0]) ← 后台 Load

  Iteration 2: 循环回 Iteration 0
```

软件通过交替指定 tr0/tr1 和 tr2/tr3 即可自然实现双缓冲，无需显式管理 bank 切换。

#### 4.2.3 AME 参数与 CUTE 参数的对应关系

以 CUTE_8Tops_128SCP 配置为例：

```scala
// CUTE 编译时参数
Tensor_M = 128, Tensor_N = 128, Tensor_K = 64
ReduceWidthByte = 64, ResultWidthByte = 4
Matrix_M = 4, Matrix_N = 4

// AME 参数 (通过 CSR 暴露给软件)
ELEN   = ResultWidth = 32                          // 最大元素宽度 (FP32)
TRLEN  = ReduceWidth = 512                         // 每行位宽 (匹配硬件 reduce 宽度)
ROWNUM = Tensor_M = 128                            // 行数 = A 矩阵行数
TLEN   = ROWNUM × TRLEN = 128 × 512 = 65536 bits  // 每个 tr 总位宽 = 8 KB
ARLEN  = Tensor_N × ResultWidth = 128 × 32 = 4096 // 每个 acc 每行位宽
ALEN   = ROWNUM × ARLEN = 128 × 4096 = 524288 bits // 每个 acc 总位宽 = 64 KB
```

**tr 寄存器 (Tile Register) 的逻辑视图：**
- 每个 tr 寄存器组织为 ROWNUM (128) 行，每行 TRLEN (512 bits = 64 bytes)
- 对于 A 矩阵 (tr0/tr1)：每行存储 Tensor_K / (ReduceWidth / ELEN) 个 reduce vector
- 对于 B 矩阵 (tr2/tr3)：每行存储 Tensor_K / (ReduceWidth / ELEN) 个 reduce vector

**acc 寄存器 (Accumulator) 的逻辑视图：**
- 每个 acc 寄存器组织为 ROWNUM (128) 行，每行 ARLEN (4096 bits = 512 bytes)
- 每行存储 Tensor_N (128) 个 FP32 累加元素
- 总容量 = ALEN = 64 KB，与 CSCP 物理大小一致

### 4.3 指令编码

AME 指令采用 RISC-V 标准编码格式。矩阵运算指令使用 R-type 格式，rs1/rs2/rd 字段分别编码输入 Tile Register (tr) 和 Accumulator (acc) 的 ID。

#### 4.3.1 指令格式

```
矩阵运算指令 (R-type, AME 兼容):
┌───────┬──────────┬──────────┬───────┬──────────┬───────┐
│ 31-25 │   24-20  │   19-15  │ 14-12 │   11-7   │  6-0  │
│funct7 │   rs2    │   rs1    │funct3 │    rd    │opcode │
└───────┴──────────┴──────────┴───────┴──────────┴───────┘
  OP      tr_src2    tr_src1    OP      acc_dst    MATMUL
          (B 矩阵)   (A 矩阵)            (C/D 累加器)

CUTE 扩展指令 (R-type, custom):
┌───────┬──────────┬──────────┬───────┬──────────┬───────┐
│ 31-25 │   24-20  │   19-15  │ 14-12 │   11-7   │  6-0  │
│funct7 │   rs2    │   rs1    │funct3 │    rd    │opcode │
└───────┴──────────┴──────────┴───────┴──────────┴───────┘
  CUTE     TCM/      imm/     CUTE     TCM/      AME_EXT
  ext      Scale     cfg               acc
```

**字段说明：**
- `rd [4:0]`：目标 acc 寄存器 ID (acc0=00000, acc1=00001, acc2=00010, acc3=00011)
- `rs1 [4:0]`：源 tr 寄存器 ID (tr0=00000, tr1=00001, tr2=00010, tr3=00011)
- `rs2 [4:0]`：源 tr 寄存器 ID (tr0=00000, tr1=00001, tr2=00010, tr3=00011)
- `funct3`：操作码子字段，区分 madd/msub/mul 等
- `funct7`：扩展操作码，CUTE 特有操作使用非零值

#### 4.3.2 指令集

| 类别 | 助记符 | 操作 | 编码字段 | 对应 CUTE 微操作 |
|------|--------|------|---------|-----------------|
| **矩阵运算** | `mmadd` | acc += tr × tr | rd=acc, rs1=tr_A, rs2=tr_B, funct3=000 | Load A/B/C → Compute → Store C |
| | `mmsub` | acc -= tr × tr | rd=acc, rs1=tr_A, rs2=tr_B, funct3=001 | Load A/B/C → Neg Compute → Store C |
| | `mmul` | acc = tr × tr (C=0) | rd=acc, rs1=tr_A, rs2=tr_B, funct3=010 | Clear C → Load A/B → Compute → Store C |
| | `mmadd.u` | 无符号 madd | funct3=011 | 同 mmadd，输入视为无符号 |
| **数据搬运** | `mmload.tr` | Memory → tr | rs1=tr, rs2=base_reg | AML/BML Load 到 ASCP/BSCP |
| | `mmload.acc` | Memory → acc | rd=acc, rs2=base_reg | CML Load 到 CSCP |
| | `mmstore.acc` | acc → Memory | rd=acc, rs2=base_reg | CML Store |
| | `tcmput` | acc → TCM | rd=acc, funct7=0000001 | CSCP → TCM Controller |
| | `tcmget` | TCM → tr | rs1=tr, funct7=0000010 | TCM Controller → ASCP/BSCP |
| **配置** | `csrrw` | 设置 CSR | 标准 CSR 指令 | 写 xmcscr / mtilem 等 |
| | `scaleload` | 加载 scale factor | funct7=0000100 | ASL/BSL Load |
| **同步** | `fence.m` | 矩阵操作同步 | 标准 fence | 等待 ComputeGo |
| **CUTE 特有** | `cute.exop` | 启动 AfterOps | funct7=0001000 | AfterOps 配置与启动 |
| | `cute.vstart` | 启动 Vector 流水 | funct7=0001001 | VectorStreamInterface |

#### 4.3.3 核心指令编码示例

```
AMEMADD (acc += tr_A × tr_B):
  // acc1 += tr0 × tr2  (D[CSCP[1]] += A[ASCP[0]] × B[BSCP[0]])
  funct7 = 0000000          // 标准 madd
  rs2    = 00010             // tr2 (B 矩阵)
  rs1    = 00000             // tr0 (A 矩阵)
  funct3 = 000               // matmul add
  rd     = 00001             // acc1 (C/D 累加器)
  opcode = 0111011           // 0x3B (AME matmul opcode, custom-0)

AMEMSUB (acc -= tr_A × tr_B):
  // acc0 -= tr1 × tr3
  funct7 = 0000000
  rs2    = 00011             // tr3
  rs1    = 00001             // tr1
  funct3 = 001               // matmul sub
  rd     = 00000             // acc0
  opcode = 0111011

AMEMMUL (acc = tr_A × tr_B, clear C):
  // acc0 = tr0 × tr2
  funct7 = 0000000
  rs2    = 00010             // tr2
  rs1    = 00000             // tr0
  funct3 = 010               // matmul (zero C)
  rd     = 00000             // acc0
  opcode = 0111011

MMLOAD.TR (Memory → tr):
  // 从内存加载到 tr0 (ASCP[0])
  funct7 = 0000001           // load
  rs2    = x1                // base address register
  rs1    = 00000             // tr0
  funct3 = 000               // load tile
  rd     = 00000             // unused
  opcode = 0111011

MMSTORE.ACC (acc → Memory):
  // 将 acc0 (CSCP[0]) 存回内存
  funct7 = 0000010           // store
  rs2    = x2                // base address register
  rs1    = 00000             // unused
  funct3 = 000               // store tile
  rd     = 00000             // acc0
  opcode = 0111011

TCMPUT (acc → TCM):
  // 将 acc0 结果放入 TCM 供 RVV 使用
  funct7 = 0000001           // CUTE 扩展: tcmput
  rs2    = 00000             // TCM target offset
  rs1    = 00000             // unused
  funct3 = 011               // tcmput
  rd     = 00000             // acc0 (source)
  opcode = 1110111           // 0x77 (custom-3, AME_EXT)

TCMGET (TCM → tr):
  // 从 TCM 加载数据到 tr0 (ASCP[0])
  funct7 = 0000010           // CUTE 扩展: tcmget
  rs2    = 00000             // unused
  rs1    = 00000             // TCM source offset
  funct3 = 100               // tcmget
  rd     = 00000             // tr0 (destination)
  opcode = 1110111           // 0x77 (AME_EXT)
```

### 4.4 指令语义与 CUTE 微指令映射

#### 4.4.1 AMEMADD 指令流程

`amemadd acc1, tr0, tr2` (acc1 += tr0 × tr2) 的执行过程：

```
Step 1: AME Decoder 解析指令
  - rd=00001 → acc1 → CSCP[1]
  - rs1=00000 → tr0 → ASCP[0]
  - rs2=00010 → tr2 → BSCP[0]
  - funct3=000 → matmul add

Step 2: 配置 TaskController
  - A source = ASCP[0], B source = BSCP[0], C/D = CSCP[1]
  - 数据类型 = 当前 xmcscr 配置
  - 如果 A/B 数据不在 ASCP/BSCP 中，发起 Load

Step 3: 数据加载 (如果需要)
  - tr0 内存地址 → AML Load 到 ASCP[0]
  - tr2 内存地址 → BML Load 到 BSCP[0]
  - acc1 初始值 → CML Load 到 CSCP[1] (仅 K=0 第一轮)

Step 4: 等待 Load 完成

Step 5: 启动 Compute
  - TaskController → ADataController, BDataController, CDataController
  - MTE 开始矩阵乘法: D = A × B + C

Step 6: 等待 Compute 完成 (fence.m)

Step 7: 结果驻留在 CSCP[1] (acc1)，可供后续 AMEMADD 或 MMSTORE 使用
```

#### 4.4.2 双缓冲示例：连续矩阵乘法

```asm
# 假设要计算 D = A × B，其中 A 是 256×128, B 是 128×256
# 分块为两个 128×128 矩阵乘法

# 第一轮: 使用 tr0/tr2/acc0 (bank 0)
mmload.tr  tr0, (x0)        # 加载 A[0:128, :] 到 ASCP[0]
mmload.tr  tr2, (x1)        # 加载 B[:, 0:128] 到 BSCP[0]
ammadd     acc0, tr0, tr2   # acc0 += tr0 × tr2

# 第二轮: 使用 tr1/tr3/acc1 (bank 1)，与第一轮的 Store 重叠
mmload.tr  tr1, (x2)        # 加载 A[128:256, :] 到 ASCP[1]  ← 后台加载
mmload.tr  tr3, (x3)        # 加载 B[:, 128:256] 到 BSCP[1]  ← 后台加载
mmstore.acc acc0, (x4)      # 存储 D[0:128, 0:128]            ← 后台存储
ammadd     acc1, tr1, tr3   # acc1 += tr1 × tr3               ← 计算不等待

fence.m                       # 等待所有操作完成
mmstore.acc acc1, (x5)      # 存储 D[128:256, 128:256]
```

#### 4.4.3 TCM 数据交换流程

```
# RVV 计算 element-wise 操作后，通过 TCM 传给 CUTE
vadd.vv    v0, v1, v2            # RVV 向量加法
# 将向量结果写入 TCM (通过 CUTE 扩展路径)
tcmput     acc0, tcm_offset_0    # acc0 (CSCP[0]) → TCM region

# CUTE 直接从 TCM 读取，无需经过内存
tcmget     tr0, tcm_offset_0     # TCM → tr0 (ASCP[0], 1~2 cycles!)
ammadd     acc1, tr0, tr2        # 矩阵乘法
mmstore.acc acc1, result_addr    # 结果写回内存
```

### 4.5 配置寄存器 (CSR)

#### 4.5.1 CSR 地址映射

AME 遵循提案文档的 CSR 地址空间，同时新增 CUTE 特有的扩展 CSR：

| CSR 地址 | 名称 | 位宽 | 访问权限 | 说明 |
|----------|------|------|---------|------|
| **0x802** | `xmcscr` | 64 | R/W | 矩阵控制与状态寄存器 (AME 提案) |
| **0x803** | `mtilem` | 64 | R/W | Tile M 维度 = Tensor_M |
| **0x804** | `mtilen` | 64 | R/W | Tile N 维度 = Tensor_N |
| **0x805** | `mtilek` | 64 | R/W | Tile K 维度 = Tensor_K |
| **0x806** | `mdatatype` | 64 | R/W | 数据类型配置 (CUTE 扩展) |
| **0x807** | `mscalecfg` | 64 | R/W | Scale factor 配置 (CUTE 扩展) |
| **0x808** | `mtcmcfg` | 64 | R/W | TCM 映射配置 (CUTE 扩展) |
| **0x809** | `mcuteext` | 64 | R/W | CUTE 扩展控制 |
| **0xCC0** | `xmisr` | 64 | R | 实现信息与特性支持 (AME 提案) |
| **0xCC1** | `xtlenb` | 64 | R | TLEN 字节数 = TLEN/8 (AME 提案) |
| **0xCC2** | `xtrlenb` | 64 | R | TRLEN 字节数 = TRLEN/8 (AME 提案) |
| **0xCC3** | `xalenb` | 64 | R | ALEN 字节数 = ALEN/8 (AME 提案) |

#### 4.5.2 xmcscr — 矩阵控制与状态寄存器 (AME 提案 0x802)

```
xmcscr (0x802):
┌─────────────────────────────────────────────────────────────────┐
│ Bit 63    - xmsaten: Saturation enable (CUTE 扩展)              │
│ Bit 62:61 - xmfrm: Float rounding mode (CUTE 扩展)             │
│ Bit 60:59 - xmxrm: Fixed-point rounding mode                   │
│ Bit 58    - xmsat: Saturation occurred flag                     │
│ Bit 57:52 - xmfflags: Float exception flags (CUTE 扩展)        │
│ Bit 51:48 - CUTE operation mode                                 │
│            0000 = Normal matmul                                 │
│            0001 = Block-scaled matmul (MXFP8/MXFP4)             │
│            0010 = Symmetric quantized matmul                    │
│ Bit 47:40 - Data type encoding                                  │
│            高 4 位: Output type (FP32/FP16/BF16/INT32)          │
│            低 4 位: Input type (INT8/FP8/FP16/BF16/FP32/FP4)   │
│ Bit 39:32 - Reserved                                           │
│ Bit 31:0  - 指令状态 (busy, load_done, compute_done 等)        │
└─────────────────────────────────────────────────────────────────┘
```

#### 4.5.3 mtilem / mtilen / mtilek — Tile 维度配置

```
mtilem (0x803):  // 编译时固定，运行时只读
┌──────────────────────────────────────────────────────────────┐
│ Bit 63:16 - Reserved                                         │
│ Bit 15:0  - M 维度 = Tensor_M (例: 128)                     │
└──────────────────────────────────────────────────────────────┘

mtilen (0x804):
┌──────────────────────────────────────────────────────────────┐
│ Bit 63:16 - Reserved                                         │
│ Bit 15:0  - N 维度 = Tensor_N (例: 128)                     │
└──────────────────────────────────────────────────────────────┘

mtilek (0x805):
┌──────────────────────────────────────────────────────────────┐
│ Bit 63:16 - Reserved                                         │
│ Bit 15:0  - K 维度 = Tensor_K (例: 64)                      │
└──────────────────────────────────────────────────────────────┘
```

#### 4.5.4 xmisr — 实现信息与特性支持 (AME 提案 0xCC0)

```
xmisr (0xCC0):
┌─────────────────────────────────────────────────────────────────┐
│ Bit 63:48 - 实现版本号 (例: 0x0001 = v0.1)                    │
│ Bit 47:32 - NTR: Number of Tile Registers (4 = tr0-3)         │
│ Bit 31:16 - NACC: Number of Accumulators (4 = acc0-3)         │
│ Bit 15:0  - 特性支持位图                                       │
│   Bit 0  - mmi4i32   (INT4×INT4→INT32 matmul, optional)        │
│   Bit 1  - mmi8i32   (INT8×INT8→INT32 matmul, compulsory)     │
│   Bit 2  - mmf16f16  (FP16×FP16→FP16 matmul, compulsory)      │
│   Bit 3  - mmf32f32  (FP32×FP32→FP32 matmul, optional)        │
│   Bit 4  - mmf8f16   (FP8×FP8→FP16 matmul, compulsory)        │
│   Bit 5  - mmf8bf16  (FP8×FP8→BF16 matmul, compulsory)        │
│   Bit 6  - mmf16f32  (FP16×FP16→FP32 matmul, compulsory)      │
│   Bit 7  - mmbf16f32 (BF16×BF16→FP32 matmul, compulsory)      │
│   Bit 8  - mmf8f32   (FP8×FP8→FP32 matmul, compulsory)        │
│   Bit 9  - mmf32f64  (FP32×FP32→FP64 matmul, optional)        │
│   Bit 10 - mmscale   (Block-scaled matmul, CUTE 扩展)          │
│   Bit 11 - mmtcm     (TCM data exchange, CUTE 扩展)            │
└─────────────────────────────────────────────────────────────────┘
```

#### 4.5.5 xtlenb / xtrlenb / xalenb — 寄存器大小查询 (AME 提案)

```
xtlenb (0xCC1):  // 每个 tr 的字节数
┌──────────────────────────────────────────────────────────────┐
│ 值 = TLEN / 8 = 8192 (例: CUTE_8Tops_128SCP)               │
└──────────────────────────────────────────────────────────────┘

xtrlenb (0xCC2): // 每个 tr 每行的字节数
┌──────────────────────────────────────────────────────────────┐
│ 值 = TRLEN / 8 = 64 (例: CUTE_8Tops_128SCP)                │
└──────────────────────────────────────────────────────────────┘

xalenb (0xCC3):  // 每个 acc 的字节数
┌──────────────────────────────────────────────────────────────┐
│ 值 = ALEN / 8 = 65536 (例: CUTE_8Tops_128SCP)              │
└──────────────────────────────────────────────────────────────┘
```

#### 4.5.6 mdatatype — 数据类型配置 (CUTE 扩展 0x806)

```
mdatatype (0x806):
┌──────────────────────────────────────────────────────┐
│ Bit 63:16 - Reserved                                 │
│ Bit 15:12 - Output Type (累加类型)                    │
│   0000 = INT32  |  0001 = FP16  |  0010 = BF16      │
│   0011 = FP32  |  0100 = FP64                        │
│ Bit 11:8  - Input B Type                             │
│   0000 = INT8   |  0001 = UINT8 |  0010 = FP16      │
│   0011 = BF16  |  0100 = TF32  |  0101 = FP8E4M3   │
│   0110 = FP8E5M2 | 0111 = MXFP8 |  1000 = MXFP4    │
│   1001 = NVFP4  |  1010 = FP4                        │
│ Bit 7:4   - Input A Type (同上编码)                   │
│ Bit 3:0   - Operation Mode                           │
│   0000 = Normal matmul                               │
│   0001 = Block-scaled matmul                         │
│   0010 = Symmetric quantized matmul                  │
│   0011 = Transposed matmul (B^T)                     │
└──────────────────────────────────────────────────────┘
```

#### 4.5.7 mtcmcfg — TCM 映射配置 (CUTE 扩展 0x808)

```
mtcmcfg (0x808):
┌──────────────────────────────────────────────────────┐
│ Bit 63    - TCM Enable                               │
│ Bit 62:56 - TCM region ID                            │
│ Bit 55:48 - Active TCM tile count                    │
│ Bit 47:32 - TCM element stride (bytes)               │
│ Bit 31:16 - TCM row stride (bytes)                   │
│ Bit 15:0  - TCM base address (within TCM region)     │
└──────────────────────────────────────────────────────┘
```

### 4.6 与现有 YGJK 指令的关系

| 维度 | YGJK | AME |
|------|------|-----|
| 指令来源 | 自定义 RoCC 指令 | AME 提案编码 + CUTE 扩展 |
| 编程模型 | 指令流 + 微指令配置 | tr/acc 寄存器 + CSR 配置 |
| 寄存器抽象 | 直接操作 SCP 地址 | tr0-3 (输入) + acc0-3 (累加器) |
| 底层执行 | TaskController + MTE | 相同的 TaskController + MTE |
| 软件支持 | 自定义汇编/C wrapper | 可复用 RISC-V matrix toolchain |
| 迁移策略 | 保留，不废弃 | AME 指令最终翻译为 YGJK 微指令 |

**迁移路径**：AME 指令由 CPU 译码后，通过 RoCC 接口传递给 CUTE 的 AMEDecoder，翻译为 tr→SCP 地址映射，最终生成与 YGJK 指令相同的微操作序列。

```
软件层:   AME asm / C intrinsics  (使用 tr0-3, acc0-3)
            ↓
译码层:   CPU Pipeline (AME Decoder)
          - tr id → ASCP/BSCP bank 选择
          - acc id → CSCP bank 选择
            ↓
RoCC 层:  RoCC Interface → TaskController
          - 与 YGJK 微指令格式完全一致
            ↓
执行层:   Load → Compute → Store (硬件不变)
```

**关键映射关系：**

| AME 指令 | YGJK 微指令 | tr/acc → SCP 映射 |
|----------|------------|-------------------|
| `ammadd acc0, tr0, tr2` | YGJK Load(A)+Load(B)+Compute+Store(C) | tr0→ASCP[0], tr2→BSCP[0], acc0→CSCP[0] |
| `ammadd acc1, tr1, tr3` | YGJK Load(A)+Load(B)+Compute+Store(C) | tr1→ASCP[1], tr3→BSCP[1], acc1→CSCP[1] |
| `mmload.tr tr0, (addr)` | YGJK AML Load | tr0→ASCP[0] |
| `mmstore.acc acc0, (addr)` | YGJK CML Store | acc0→CSCP[0] |

---

## 5. 系统集成方案

### 5.1 Chipyard 配置

```scala
class CUTE4TopsSCP128L2TCMConfig extends Config(
  new cute.WithCuteCoustomParams(CoustomCuteParam = CuteParams.CUTE_4Tops_128SCP_L2TCM) ++
  new cute.WithCUTE(Seq(0)) ++
  new cute.WithPrivateL2 ++                         // 新增：Tile 内私有 L2
  new freechips.rocketchip.subsystem.WithNBitMemoryBus(512) ++
  new freechips.rocketchip.subsystem.WithCacheHash ++
  new freechips.rocketchip.subsystem.WithNBanks(4) ++
  new freechips.rocketchip.subsystem.WithInclusiveCache(capacityKB=512, outerLatencyCycles=40) ++
  new chipyard.config.WithSystemBusWidth(512) ++
  new saturn.shuttle.WithShuttleVectorUnit(vLen = 512, dLen = 512, VectorParams.CUTErefParams, mLen = Option(512)) ++
  new shuttle.common.WithShuttleTileBeatBytes(64) ++
  new shuttle.common.WithNShuttleCores(1) ++
  new freechips.rocketchip.subsystem.WithoutTLMonitors ++
  new chipyard.config.AbstractConfig)
```

### 5.2 顶层模块变化

```
CUTETop (新增接口):
  - l2_io: PrivateL2IO        // L2 Cache 控制接口
  - tcm_io: TCMControllerIO    // TCM 访问接口
  - tma_io: TMAIO             // TMA 描述符提交与状态查询
  - rvv_tcm_io: RVVTCMIO       // RVV ↔ TCM 接口 (连接到 Vector Unit)

模块新增:
  - PrivateL2: PrivateL2Cache module
  - TCMCtrl: TCMController module
  - TMA: TensorMemoryAccelerator module
  - AMEDecoder: AME 指令译码模块 (可选，也可在 CPU pipeline 中实现)
```

### 5.3 CUTETop 修改后架构

```scala
class CUTEV2TopWithL2TCM()(implicit p: Parameters) extends CuteModule {
    val io = IO(new CUTETopIO)

    // === 现有模块 (不变) ===
    val ASpad = Seq.tabulate(2)(i => Module(new AScratchpad(i)))
    val ADC = Module(new ADataController)
    val AML = Module(new AMemoryLoader)
    // ... B, C, Scale 同 ...

    val TaskCtrl = Module(new TaskController)
    val MTE = Module(new MatrixTE)

    // === 新增模块 ===
    val PrivateL2 = Module(new PrivateL2Cache)
    val TCMCtrl = Module(new TCMController)
    val TMA = Module(new TensorMemoryAccelerator)

    // === TCM Banks 直连 (不经过 L2 Controller) ===
    // CUTE ↔ TCM 数据交换 (Port A, 直连, 1 cycle)
    TCMCtrl.io.cute_write <> TaskCtrl.io.tcm_write_req
    TCMCtrl.io.cute_read <> TaskCtrl.io.tcm_read_req
    TaskCtrl.io.tcm_read_data <> TCMCtrl.io.cute_read_data

    // RVV ↔ TCM 数据交换 (Port B, 直连, 1 cycle)
    TCMCtrl.io.rvv_write <> io.rvv_tcm_io.write
    TCMCtrl.io.rvv_read <> io.rvv_tcm_io.read

    // === TMA ↔ TCM (Port D, TMA 后台搬运) ===
    TMA.io.tcm_write <> TCMCtrl.io.tma_write
    TMA.io.tcm_read <> TCMCtrl.io.tma_read
    TMA.io.tcm_read_data <> TCMCtrl.io.tma_read_data

    // === TMA 描述符接口 (CPU 通过 RoCC 提交) ===
    TMA.io.descriptor <> TaskCtrl.io.tma_descriptor
    TMA.io.status <> TaskCtrl.io.tma_status
    TMA.io.completion_irq <> io.tma_irq

    // === Cache Banks 访问 (经过 L2 Controller) ===
    AML.io.PrivateL2IO <> PrivateL2.io.cute_port
    AML.io.LocalMMUIO <> MMU.io.ALocalMMUIO

    // RVV 聚合路径 (Port C, 跨全部 Bank)
    io.rvv_tcm_io.aggregate <> TCMCtrl.io.aggregate_port
    PrivateL2.io.rvv_aggregate <> io.rvv_tcm_io.aggregate_cache

    // === TileLink 端口 (两个独立 Client) ===
    PrivateL2.io.tilelink <> io.mmu2llc              // L2 Cache ↔ LLC
    TMA.io.tilelink <> io.tma_tilelink                // TMA ↔ LLC (独立端口)
}
```

---

## 6. 性能分析

### 6.1 延迟对比

| 操作 | 现有 (v2) | 新设计 (L2 hit) | 新设计 (TCM 直连) | 新设计 (TMA 后台) | 加速比 |
|------|-----------|----------------|-------------|------------------|--------|
| ASCP 加载 (K>0 复用) | 40~100 cycles (DRAM) | 5~15 cycles (L2) | N/A | TCM 已预取, 1 cycle 读 | 4~100x |
| RVV→CUTE 数据传递 | ~200 cycles (Store+Load) | ~10 cycles (L2) | 1 cycle (TCM 直连) | N/A | 10~200x |
| CUTE→RVV 数据传递 | ~200 cycles (Store+Load) | ~10 cycles (L2) | 1 cycle (TCM 直连) | N/A | 10~200x |
| K 维跨轮复用 | 每轮 DRAM load | L2 hit | N/A | TCM 预取完成, 即用 | 3~100x |
| CPU 预处理结果传递 | Store to DRAM + Reload | L2 hit | N/A | N/A | 3~10x |
| **TMA 后台搬运 (8KB)** | N/A | N/A | N/A | **后台完成, 0 cycle 等待** | — |

### 6.2 带宽对比

| 指标 | 现有 (v2) | 新设计 | 说明 |
|------|-----------|--------|------|
| CUTE 峰值内存带宽需求 | 2 × outsideDataWidth | 0.3~0.5 × outsideDataWidth | L2 命中 + TCM 预取减少外部带宽 |
| TCM 直连带宽 | N/A | TCMBanks × 512 bits/cycle | CUTE↔RVV 专用低延迟路径 (例: 4×512=2048 bit/cycle) |
| RVV 聚合带宽 | N/A | L2NBanks × 512 bits/cycle | 跨全部 Bank 聚合 (例: 8×512=4096 bit/cycle) |
| Cache Banks 带宽 | N/A | CacheNBanks × 512 bits/cycle | CPU/RVV/CUTE 正常缓存访问 |
| **TMA 搬运带宽** | **N/A** | **512 bits/cycle (独立 TileLink)** | **TMA 独立 TileLink 端口, 不与 L2 Cache 竞争** |

### 6.3 面积估算

| 组件 | 面积估算 (relative) | 说明 |
|------|---------------------|------|
| L2 Tag Store (仅 Cache Banks) | ~1.0x CSCP | 仅覆盖 Cache Banks, TCM Banks 无 Tag |
| TCM Banks SRAM | ~0.5x total SCP | 独立 SRAM 实例, 无额外控制逻辑 |
| Cache Banks SRAM | ~2.0x total SCP | 标准 set-associative cache data array |
| TCM Controller | ~0.1x total SCP | 多端口仲裁 + 直连 Mux |
| TMA (Tensor Memory Accelerator) | ~0.15x total SCP | 描述符队列 + 数据 FIFO + TileLink Client + 控制状态机 |
| AME Decoder | ~0.05x TaskCtrl | 指令译码逻辑 |
| **总计** | **~1.5~2x 现有 CUTE 面积** | |

---

## 7. 实现计划

### Phase 1: 基础架构 (Private L2 + TCM + TMA)

| 步骤 | 内容 | 依赖 |
|------|------|------|
| 1.1 | `CuteL2TCMParams` 参数定义与 `CuteParams` 集成（含 Bank 分区 + TMA 参数） | 无 |
| 1.2 | `PrivateL2Cache` 模块实现 (仅管理 Cache Banks, TileLink Client) | 1.1 |
| 1.3 | `TCMController` 模块实现 (直连 TCM Banks, 多端口仲裁, 聚合通路, Port D 给 TMA) | 1.1 |
| 1.4 | `TensorMemoryAccelerator` (TMA) 模块实现：描述符队列, TileLink Client, 数据 FIFO, 状态机 | 1.1 |
| 1.5 | `AMemoryLoader` / `BMemoryLoader` 修改：优先 Cache Banks，miss 回退 TileLink | 1.2 |
| 1.6 | `CUTETop` 集成 L2 + TCM + TMA 模块，TMA 独立 TileLink 端口连接 LLC | 1.2, 1.3, 1.4 |
| 1.7 | Chipyard `WithPrivateL2` Config Mixin | 1.6 |
| 1.8 | RTL 仿真验证：L2 hit/miss, TCM 直连, TMA 后台搬运行为正确 | 1.7 |

### Phase 2: AME 指令集

| 步骤 | 内容 | 依赖 |
|------|------|------|
| 2.1 | AME CSR 定义 (`mcfgcsr`, `mdatatype`, `mtcmcfg` 等) | 无 |
| 2.2 | `AMEDecoder` 实现：tile register → SCP 地址翻译 | 2.1 |
| 2.3 | `TaskController` 修改：接收 AME 指令，生成微操作 | 2.2 |
| 2.4 | `tcmput` / `tcmget` 指令实现：TCM ↔ SCP 数据搬运 (CUTE/RVV 直连) | Phase 1 |
| 2.4b | `tma.submit` 指令实现：通过 RoCC 提交 TMA 搬运描述符 | Phase 1 |
| 2.5 | `amemadd` / `amestore` 等核心指令实现 | 2.3 |
| 2.6 | AME 汇编宏 / C intrinsic 头文件 | 2.5 |
| 2.7 | 端到端测试：矩阵乘法 kernel 用 AME 指令编写 | 2.5, 2.6 |

### Phase 3: 性能优化

| 步骤 | 内容 | 依赖 |
|------|------|------|
| 3.1 | TMA 多描述符流水线：多条搬运描述符连续提交、流水执行 | Phase 1 |
| 3.2 | TMA 与 Compute 双缓冲：TMA 预取下一 tile 数据的同时 CUTE 计算当前 tile | Phase 1 |
| 3.3 | RVV ↔ TCM 低延迟路径优化 | Phase 1 |
| 3.4 | TMA 智能 prefetch：根据 TaskController 的 YGJK/AME 指令序列自动生成 TMA 描述符 | Phase 2 |
| 3.5 | Benchmark 对比 (v2 vs v4) | Phase 1, 2 |

---

## 8. 风险与开放问题

### 8.1 技术风险

| 风险 | 严重度 | 缓解措施 |
|------|--------|---------|
| L2 Cache Banks 多端口并发冲突 | 中 | Bank 交织 + 优先级仲裁 |
| ~~TCM 与 Cache bank 竞争~~ | ~~已解决~~ | TCM Banks 与 Cache Banks 物理独立，天然无冲突 |
| TileLink 带宽瓶颈 (L2 miss 大量时) | 低 | TMA 独立 TileLink 端口，不与 L2 Cache 端口竞争 |
| 面积增加过大 | 中 | TCM Bank 数可配置，支持关闭 (TCMBanks=0)，TMA 可独立关闭 (TMAEnable=false) |
| TCM 容量不足 | 中 | 可通过增大 BankSizeKB 或 TCMBanks 调整 |
| TMA 描述符队列溢出 | 低 | 软件可通过 CSR 查询队列深度，队列满时 stall CPU 提交 |
| TMA TileLink 端口与 LLC 的 source ID 竞争 | 低 | TMA 有独立的 TMASourceMaxNum 参数 |

### 8.2 开放问题

1. **RVV ↔ TCM 路径**：RVV 的 Vector Unit 需要新增专用 TCM 端口还是复用 Vector Load/Store？
2. **AME 指令在 CPU pipeline 中的译码位置**：是在 CPU frontend 还是 RoCC 端？
3. **TMA 搬运与 CUTE 计算的同步机制**：TMA 完成标志是查询 CSR 还是中断？软件如何保证 TCM 数据就绪后 CUTE 才开始读取？
4. **TMA 自动预取**：TMA 能否根据 TaskController 的 YGJK/AME 指令序列自动生成搬运描述符，实现零软件开销的预取？
5. **多 CUTE Tile 场景**：多个 CUTE 实例如何共享/竞争 Private L2 和 TMA？(本阶段不处理)
6. **Bank 分配比例的灵活性**：当前采用静态分配 (编译时固定 TCMBanks)，是否需要运行时可配？

---

## 附录 A: 术语表

| 术语 | 全称 | 说明 |
|------|------|------|
| SCP | Scratchpad | CUTE 内部暂存存储 |
| ASCP | A Scratchpad | A 矩阵输入暂存 |
| BSCP | B Scratchpad | B 矩阵输入暂存 |
| CSCP | C Scratchpad | C 矩阵/累加值暂存 |
| TCM | Tightly Coupled Memory | 紧耦合存储器，由独立 TCM Banks 组成，直连 CUTE |
| TCM Banks | TCM 专用 Bank | Bank 0 ~ N_tcm-1，物理独立 SRAM，无 Tag，直连 CUTE/RVV |
| Cache Banks | 缓存 Bank | Bank N_tcm ~ N_total-1，组成 Set-associative Cache |
| MTE | Matrix Tensor Engine | 矩阵张量引擎 |
| AME | Accelerator Matrix Extension | 加速器矩阵扩展指令集 |
| tr0-3 | Tile Register | AME 输入矩阵寄存器，映射到 ASCP/BSCP |
| acc0-3 | Accumulator Register | AME 累加器寄存器，映射到 CSCP |
| TLEN | Tile Register 总位宽 | 每个 tr 的总位数 (TLEN = ROWNUM × TRLEN) |
| TRLEN | Tile Register 行位宽 | 每个 tr 每行的位数 |
| ROWNUM | Tile Register 行数 | ROWNUM = TLEN / TRLEN |
| ALEN | Accumulator 总位宽 | 每个 acc 的总位数 (ALEN = ROWNUM × ARLEN) |
| ARLEN | Accumulator 行位宽 | 每个 acc 每行的位数 (ARLEN = ROWNUM × ELEN) |
| ELEN | Element Length | 最大元素位宽 |
| AML/BML/CML | A/B/C Memory Loader | A/B/C 存储加载器 |
| ADC/BDC/CDC | A/B/C Data Controller | A/B/C 数据控制器 |
| RVV | RISC-V Vector Extension | RISC-V 向量扩展 |
| ROCC | Rocket Custom Coprocessor | RISC-V 自定义协处理器接口 |
| LLC | Last Level Cache | 末级缓存 |
| TMA | Tensor Memory Accelerator | 张量存储加速器，后台搬运引擎 |
| TMADescriptor | TMA 描述符 | 软件下发给 TMA 的搬运描述指令 (256-bit) |
| PE | Processing Element | 处理单元 |

## 附录 B: 参考资料

- RISC-V Matrix Extension v1.0 Specification
- CUTE Architecture Overview (`doc/design-doc/docs/overview/architecture-overview.md`)
- CUTE Parameters (`src/main/scala/CUTEParameters.scala`)
- CUTE Top Module (`src/main/scala/CUTETOP.scala`)
- Chipyard Configuration (`chipyard/generators/chipyard/src/main/scala/config/CuteConfig.scala`)
- AME Proposal (`docs/riscv_matrix_extension_proposal.pdf`)
