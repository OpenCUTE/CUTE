# MemoryMap：从地址空间配置到软件使用

MemoryMap v2 统一描述系统 RAM、ROM、设备 MMIO、保留区，以及核私有 TCM。
构建器把支持的布局参数交给真实硬件生成，并用同次 DTS、物理 manager 导出核对
地址、容量、类型、状态和权限。SDK 消费核对后的地址表，不另维护一份手填地址。

## 配置里有哪些对象

入口仍是 ChipyardConfig 的 `memory_map` 引用。内置 `shuttle_private_tcm_2m` 和
`no_tcm` 已使用 v2；`no_tcm` 关闭的是 TCM，仍明确描述全局地址空间。

| 字段 | 含义 |
|---|---|
| `version: 2`、`id` | 配置版本与身份，ID 对应文件名 |
| `coverage` | `complete` 要求声明全部导出的全局地址区域，包括 disabled 区域；`subset` 只核对所列区域 |
| `regions` | 全局 RAM、ROM、MMIO 的区域清单 |
| `reserved` | 位于可用 RAM 内的固定保留区；不增加物理存储容量 |
| `tcm` | 原有 tile-private 布局；`null` 明确关闭 |

旧 v1 TCM 配置仍可读取，但不提供完整地址空间的预期核对。v1 不能混入 v2 的新字段。

以下是一个 RAM 区域条目的示意，完整可运行配置见
`configs/memory_maps/shuttle_memorymap_demo.yaml`：

```yaml
id: dram
kind: ram
node: /memory
base: "0x90000000"
size_bytes: 268435456
status: okay
permissions: [read, write, execute, cacheable, atomic]
implementation: external_ram
```

`node` 选择 DTS 节点路径，可以省略最后的 `@地址`。同类节点有多个时，继续按基址与
状态区分；无法唯一对应时拒绝通过。`compatible` 可以进一步约束设备类型。
`permissions` 核对实际 manager 的访问属性；只在 DTS 看到 `reg`，不能证明读写权限。

区域 ID 不重复，地址和长度不得溢出，全局区域不得重叠。ROM 不允许写权限。
disabled 区域参与布局核对，但不作为程序可分配的 RAM。

## 哪些布局由配置生成

`implementation` 表示怎样把选择传给已有硬件。它修改相应部件的参数，不根据一个
MMIO 地址凭空生成未知外设。

| implementation | 实际生成行为 |
|---|---|
| `external_ram` | 设置外部 RAM 基址、容量，并更新裸机默认启动地址 |
| `boot_rom` | 设置已有 BootROM 的基址、容量，保持复位入口相对偏移 |
| `uart` | 设置已有单个 UART 的基址，寄存器窗口固定为 4 KiB |
| `clint` | 设置 CLINT 基址，窗口固定为 64 KiB |
| `plic` | 设置 PLIC 基址，当前窗口固定为 64 MiB |
| `prci_clock`、`prci_reset` | 成对设置时钟/复位控制窗口，复位窗口为时钟窗口加 `0x10000` |
| `fixed` | 保持部件实现提供的布局，并严格核对配置中的预期值 |

CLINT 布局与启动过程一起配置：`clint` 绑定要求同时选择 `boot_rom` 绑定，启动 ROM
从生成的地址表取得 CLINT 和启动地址寄存器位置。RTL runner 按目标地址写入程序
启动位置并唤醒 hart，避免仿真装载器使用旧的固定地址。

例如 debug、错误响应窗口、启动地址寄存器和缓存控制窗口，可以用 `fixed` 纳入完整
清单。新设备只要已由硬件导出，也可以这样声明并核对；要让配置主动改变其实现参数，
还需增加对应的硬件绑定。不同部件真实支持的窗口大小与对齐要求在生成前检查。

## 保留区怎样贯穿硬件与 SDK

```yaml
reserved:
  - id: firmware
    base: "0x90000000"
    size_bytes: 65536
    no_map: true
```

保留区必须位于一个 enabled RAM 区域内，按页对齐，彼此不重叠。Chipyard 生成
标准 `/reserved-memory` 节点；这段空间继续属于 RAM，不会在全局 memmap 中再生成
一个重叠的内存设备。结构和 `no-map` 含义遵循
[Devicetree reserved-memory 约定](https://devicetree-specification.readthedocs.io/en/latest/chapter3-devicenodes.html#reserved-memory-node)。

SDK 的显式工作区分配扣除保留区。当前 HTIF 链接布局选择剩余空间中最大的连续区间，
代码、数据、堆和栈都要放进这个区间，链接断言与 ELF 检查共同防止越界。启动地址也
跟随该布局。总空闲空间足够但没有足够大的连续区间时，当前链接方式仍可能失败。

保留区表达软件分配和映射约定，不等于新增硬件访问保护。任意 C 指针写入仍需程序
和执行检查约束。动态保留区需要先确定地址，本流程使用静态分配。

## 产物与软件接口

生成的 `target/` 新增两份文件：

| 产物 | 下游用途 |
|---|---|
| `memory-map.json` | 按稳定区域 ID 保存核对后的 RAM/ROM/MMIO、保留区和私有 TCM 视图 |
| `target_memory.h` | 全局区域的 `CUTE_MEM_<ID>_BASE/BYTES/ENABLED` 宏，以及保留区地址宏 |

SDK CMake 自动把该头文件目录加入 include 路径。程序可以包含 `target_memory.h`，
使用例如 `CUTE_MEM_UART_BASE` 的常量。文件存在不意味着对应设备被 QEMU 模拟；
设备访问要同时声明软件需求。

requires 可以按区域 ID 声明 MMIO 或 ROM 需求：

```yaml
devices:
  - id: clint
    kind: mmio
    permissions: [read, write]
    min_bytes: 65536
    compatible: ["riscv,clint0"]
```

依赖文件中的同一设备需求合并权限、容量和 compatible 约束，设备类型冲突会报错。
硬件匹配后，SDK 后端继续检查能否执行该访问。MMIO、ROM 只提供地址与访问契约，
不会被放进普通 RAM 工作区分配器。

## QEMU 消费与支持边界

当前 Spike/CUTE ISA 模拟器支持一块 enabled RAM，基址和容量跟随目标；CLINT 基址
也可配置。普通 TCM 保留单 hart、一个所选窗口的限制。多个 enabled RAM 区域可以
被 MemoryMap 描述和核对，但当前后端会明确拒绝运行这种目标。

后端按设备类型、实际基址和窗口长度确认覆盖，不能只看到 compatible 相同就认为
支持。UART、PLIC、硬件 BootROM 等仍列入未建模设备。`workload` 模式要求满足本次
软件声明的需求；程序要求访问未建模设备时拒绝构建。`full-target` 要求整个目标被
覆盖，因此当前完整 Chipyard 平台仍不能宣称全机等价。

完整地址空间配置与任意外设仿真是不同层的能力；新外设的 ISA 模拟器行为需要在后端
单独实现。QEMU 的内部启动 ROM 也不等同于目标硬件 BootROM。

## 一个包含地址迁移和保留区的目标

`cute4tops_shuttle512_memorymap_demo_dramsim48` 引用演示布局：

- RAM：`0x90000000` 起的 256 MiB。
- BootROM：`0x20000`；UART：`0x10030000`；CLINT：`0x3000000`。
- PLIC：`0x18000000`；时钟/复位控制：`0x120000` / `0x130000`。
- RAM 首部、中间、尾部各保留 64 KiB；2 MiB 私有 TCM 保持原有归属。

从仓库根目录激活工具环境后，可以单独构建：

```sh
python3 tools/runner/cute-system-build.py \
  --hwconfig cute4tops_shuttle512_memorymap_demo_dramsim48 \
  --out ../opencute-out/memorymap-demo \
  --cc "$(command -v riscv-none-elf-gcc)" --jobs 16
```

完整构建会验证配置与硬件导出、程序布局和 QEMU 平台探针。然后按
[运行说明](running.md) 使用这个目标的构建清单执行系统 case，并保留本次报告。

启动 ROM 模板源文件位于 `chipyard/generators/chipyard/src/main/resources/opencute/bootrom/`。
修改其汇编后，从仓库根目录重新生成 RV32/RV64 模板：

```sh
python3 tools/runner/cute-gen-bootrom.py --cc "$(command -v riscv-none-elf-gcc)"
```

system 构建会以 `--check` 验证生成物一致。实例地址填入模板的数据表，DTS 随该实例
生成并附加。
