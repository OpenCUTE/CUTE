# Config 从声明到实际运行

HWConfig 是构建目标的入口。配置先生成硬件，随后使用同次 elaboration 的 DTS/内存
导出核对目标，并生成 SDK 目标包。软件编译、链接、QEMU 和 RTL runner 消费同一包，
运行报告绑定该包及实际产物的身份。

## 输入对象各自负责什么

完整的 [配置引用图](config-architecture.md#dependencies) 和
[配置到执行的数据流图](config-architecture.md#flow) 位于“实现方式”章节。
HWConfig 引用硬件组合、内存模型和 ExecutionProfile；ChipyardConfig 再引用部件参数、
编码、向量实现、ISAProfile 与 MemoryMap。本页说明这些接口怎样参与实际构建和运行。

内置目标都显式引用 ISAProfile、MemoryMap 和 execution_profile。引用配置与 schema
进入构建身份；重复 YAML 键、重复 TCM 定义、无效引用和矛盾约束会报错。
配置声明不会自动实现指令：实际硬件必须导出相应能力，软件需求也必须通过检查。

## MemoryMap 保留私有归属

MemoryMap v2 已覆盖 RAM、ROM、静态保留区、设备 MMIO 和普通 TCM。已支持的硬件
绑定驱动布局生成，固定窗口作为预期约束核对；同次 DTS 和物理 manager 导出提供实际
地址与权限。字段、SDK 设备需求和限制见 [MemoryMap 地址空间](memory-map.md)。

`configs/memory_maps/shuttle_private_tcm_2m.yaml` 中的 `tcm` 对象如下；
`owner_tiles` 是可选字段：

```yaml
tcm:
  scope: tile-private
  internal_base: "0x70000000"
  size_bytes: 2097152
  banks: 2
  owner_tiles: [0]
```

省略 owner_tiles 时应用到全部 Shuttle tile；指定时生成 `WithTCMForTiles`，只有
被选中的 tile 拥有 TCM。`tcm: null` 显式关闭 TCM，与是否有 RVV 无关。旧的
`soc.vector.tcm` 仅作为兼容输入；不能与 memory_map 同时定义。

DTS 导出内部存储实体、所属 CPU 和每个客户端的窗口。SDK 按
`(hart, client, address) → (region-id, offset)` 解释地址。多个 alias 共用容量，
不同 tile 的同值地址可以指向不同私有实体。窗口地址从实际接口取得，配置中不再
维护一份手算的软件 alias。

主存来自 DTS；DTB 读取器处理地址 cell 宽度、总线 ranges 和固定保留区，分配时扣除
保留空间。没有 ranges 与空 ranges 分别表示无父映射、同址映射。动态保留区必须先
确定具体分配，不能把尚未确定的位置当作空闲 RAM。

## 硬件事实如何进入 SDK

Shuttle 导出精确 VLEN/ELEN；CUTE/Saturn 实现导出自身的编码、版本化契约、trace
端口、beat 宽度、周期水位和客户端可见范围。DTS 的 `zvl512b` 仍表示下限，不被
错误地解释成精确 VLEN。

当前实施的 CUTE 契约包括 `int8_matmul_wrap32_v1` 和 `checkpoint_v1`，Saturn
提供 `saturn_quiescent_checkpoint_v1`。它们对应实际实现与测试，不能从 datatype
枚举中推断额外浮点矩阵能力。ISAProfile 的目标级契约要求与 SDK 的执行 hart 要求
分别核对；一个 hart 的能力不会被另一个 hart 的能力补齐。

## 软件需求与依赖归并

具体程序通过 requires 文件声明需求，并引用库和运行时的需求。例如：

```yaml
version: 1
id: system_int8
hart: 0
depends_on: [../../targets/requirements/int8_runtime.yaml]
```

`depends_on` 相对当前文件解析，支持传递依赖，拒绝循环。扩展需求取并集，XLEN、
精确 VLEN 和 hart 选择必须兼容，版本上下界取交集。依赖中的 buffer 名称被限定在
所属需求文件的身份内，不会因两个库都叫 scratch 而意外共享。选定实现的依赖参与
归并；替代算法应分别声明并选择具体实现。

标准 ISA 名称支持显式版本，解析已知标准扩展的蕴含关系。硬件只声明未版本化名称时，
不会假定它满足任意版本约束。软件需要而硬件没有导出的事实返回 INCOMPLETE。

显式 buffer 按实体偏移作不重叠分配，支持多个客户端的共同可见范围和对齐约束。
该资源匹配与最终 ELF 布局检查分别执行：前者处理声明的工作区，后者处理实际代码、
数据、堆和栈。

## 正式构建入口

从 CUTE 根目录激活 [工具环境](build-system.md)，执行。输出路径相对于仓库根目录，
编译器由 `PATH` 自动查找：

```sh
python3 tools/runner/cute-system-build.py \
  --hwconfig cute4tops_shuttle512_d512_v512_m512_sysbus512_membus1_core_dramsim48 \
  --out ../opencute-out/system \
  --cc "$(command -v riscv-none-elf-gcc)" --jobs 16
```

顺序为：配置/codegen 检查 → 硬件 elaboration → DTS/需求核对 → SDK 目标包 → 软件、
QEMU、verifier 构建 → ELF/QEMU 契约检查 → RTL simulator。输出目录位于源码树之外。
首次安装 QEMU 依赖时仍可通过 `--qemu-configure-arg` 指定本机依赖路径。

目标包 `target/` 包含：

| 文件 | 消费者和含义 |
|---|---|
| hardware.dts、hardware.memmap.json、facts.json | 同次硬件导出与标准化事实 |
| requires.json | 已归并的软件需求及依赖文件身份 |
| platform.json | 由事实和执行策略生成的平台视图 |
| memory-map.json、target_memory.h | 已核对的地址区域及 SDK 地址常量 |
| target.cmake | SDK 编译/链接 ISA、ABI、ISA 头目录、TCM 开关和收尾等待周期 |
| target.ld | 从当前工具链 HTIF 脚本派生的地址布局、堆栈预算和越界断言 |
| bundle.json | 输入来源及各生成文件哈希 |

这些文件在构建和运行目录中的位置，以及下次怎样复用，见
[关键产物目录](config-architecture.md#artifacts)。

手写的 `cute-sdk/tests/system/platform.json` 已移除。fixture 生成器要求显式传入
目标包的 platform.json。系统与模型构建都向 CMake 传递目标包；独立的旧 SDK CMake
用法保留兼容默认参数，但不具有这条链路的目标身份保证。

链接后核对 ELF 的 ISA 属性、浮点 ABI、入口、加载段、堆栈符号和容量预算。这里的
ISA 属性与静态布局检查不能代替执行测试，也不证明程序动态栈深度永远不会溢出。
`stack_bytes` 是每 hart 请求的最小栈空间，工具链会加入 TLS 并按启动协议取整；
检查报告记录实际符号范围。资源匹配的候选 buffer 绑定也需要软件按接口使用，不能
把容量匹配理解为对任意 C 指针操作的证明。

## QEMU 服务于 SDK

SDK 的 `targets/backends/` 维护后端能力，适配器据实际目标生成 CPU、内存和 TCM
参数，并用 QMP 检查参数能否生效。当前 Spike/CUTE 后端支持单 hart；TCM 地址和容量
可配置，RAM 基址、大小和 CLINT 基址跟随目标。构建时运行指令契约和平台边界探针。

execution_profile 中有两种覆盖要求：

- `workload`：满足已选软件需求，报告明确列出未建模的其他硬件设备。
- `full-target`：目标存在未建模设备时拒绝通过，不能把工作负载正确性当作全机等价。

当前 CUTE 浮点矩阵、多 hart 私有内存执行以及部分 Chipyard MMIO 设备仍超出该
QEMU 后端能力。配置系统会报告不支持，不会静默改成共享 TCM 或容差比较。

## 运行与身份核对

新构建完成后可以直接从清单选择产物：

```sh
RUN_DIR="../opencute-out/runs/system-$(date +%Y%m%d-%H%M%S)"
python3 tools/runner/cute-system.py \
  --build-manifest ../opencute-out/system/build-manifest.json \
  --out "$RUN_DIR" --case-name system_int8_128
```

TCM case 使用 `--case-name system_tcm`。工具、ELF、fixture、case 和 DRAM 配置由
清单选择；显式参数仍可用于有记录的故障注入。模型构建复用已验证的硬件/QEMU，
为模型需求生成自己的 target 包，入口见 [模型构建](build-system.md#model-builds)。

runner 在执行前核对构建清单、目标包、源版本、依赖、case、fixture 和 ELF。
模型与系统输出均复制目标包和报告。新流程使用 schema_version=2 的构建清单；
旧清单需要重建，历史日志仍可使用绑定的旧 verifier 离线复核。

## 独立检查与增量扩展

`cute-check-config.py --hwconfig ... --dts ... --memmap ... --requires ...` 保留为独立
诊断入口。MATCH 表示声明条件满足；MISMATCH 表示明确矛盾；INCOMPLETE 表示缺少
必要事实或有界搜索尚未找到分配。只有 MATCH 才进入正式构建，运行成功另外记录。

增加能力时，在负责该事实的配置或实现中修改，更新实际导出、需求与后端支持，再运行
相应正负测试。新增一个枚举或配置名称不能替代实现和验收。性能/功耗等指标仍需要
对应后端提供证据，不由本流程的功能检查推导。
