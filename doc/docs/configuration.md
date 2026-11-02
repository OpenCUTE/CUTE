# 配置与代码生成

配置层把系统组合中的选择变成工具可以检查和消费的输入。它承接上层已经确定的目标
和接口约定；怎样从愿望作出这些选择，见 [配置实践](practice-config.md)。本文提供
字段来源、生成关系和操作入口。先读 [Config-first 对象与依赖图](config-architecture.md)，
理解 HWConfig、硬件组合、能力要求、内存与执行策略分别负责什么，再使用本页的命令。

YAML 是声明参数的来源，硬件状态机和数学实现仍在代码中，不能只增加 manifest 就
宣称实现某条指令。普通 TCM 布局由 MemoryMap 定义，客户端地址从 DTS 获取。
配置与 SDK requires 的实际匹配及运行接口见 [Config 到运行](config-contracts.md)。

| 输入 | 输出/消费方 | 命令 |
|---|---|---|
| `configs/cute_configs/*.yaml` | `src/main/scala/HardwareConfig.scala` | `cute-gen-scala-config.py` |
| `configs/cute_isa_versions/*.yaml` | `src/main/scala/InstConfig.scala` | 同上 |
| ISA YAML | SDK `instruction.h/isa.json/cute_fpe.h/isa_summary.md` | `cute-gen-cuteisa.py` |
| `configs/chipyard_configs/*.yaml` | Chipyard `CuteConfig.scala` | `cute-update-chipyard-configs.py` |
| HWConfig 引用链 | `generated/` 下 SDK 头和 fingerprint | `cute-build.py --step genfiles` |
| `trace/catalogs/cute_trace.json` | Scala/Python/C++ 事件 API | `tools/trace/gen_cute_trace.py` |

```sh
python3 tools/runner/cute-check-config.py --hwconfig --all
python3 tools/runner/cute-check-config.py --cute-isa-version --all
python3 tools/runner/cute-gen-scala-config.py --check
python3 tools/runner/cute-gen-scala-config.py --update
python3 tools/runner/cute-gen-cuteisa.py --isa-version cute_isa_v1
python3 tools/trace/gen_cute_trace.py --check
```

`--update` 和生成命令会写源树；先检查工作区。生成文件应由对应来源重建，避免
YAML、Scala 常量、SDK 编码各自漂移。修改编码同时修改 QEMU decoder/语义和 RTL
处理路径；codegen 一致不证明执行语义一致。

当前系统验证平台描述生成在构建目录的 `target/platform.json`，包含精确 VLEN、
TCM client 地址、必选端口和 trace 水位周期，输入来自同次硬件导出及执行策略。
原手写 SDK 平台文件已移除。当前单核 RVV TCM client 地址为 `0x70200000`；
`0x70000000` 是该 profile 的内部译码基址，不能直接替换，也不能理解为全局访问窗口。

## 核私有 TCM 的 DTS 导出 {#local-memory-dts}

Shuttle 的普通 TCM 现在通过 Chipyard 原有资源绑定过程进入 DTS。每个
`local-memory-<tile-id>-tcm` 节点记录所属 CPU、容量、bank 数和内部译码基址；
子节点分别描述标量访存、取指、RVV 和 RoCC 路径的 TileLink 可见窗口。
窗口来自已协商的硬件接口，既不硬编码为单核地址，也不将内部译码地址当作全局地址。

这些节点使用 OpenCUTE 自定义 binding，且没有到全局地址域的 `ranges` 映射。
全局 `memmap.json` 仍只描述系统视图；SDK 的 MemoryMap 消费者需要显式读取本地
节点，将 `(hart, client, address)` 解析成 `(region-id, offset)`。多个 alias 不增加
物理容量，不同 tile 的私有实体也不能因地址相同而合并。

当前单核 2 MiB profile 的内部基址为 `0x70000000`，已协商窗口为 `0x70200000`。
导出的是 manager/PMA 可见信息，不能据此推断所有软件访问、缓存交接或多核行为都已
验证。SGTCM、专用 tensor bypass 和仅由运行时重写产生的额外 alias 尚未纳入该导出。

格式说明位于 `CPU/shuttle/doc/local-memory-dts.md`，生成回归位于
`CPU/shuttle/tests/local-memory-dts/`。当前可用 `cute-check-config.py --dts ... --requires ...`
检查配置与软件资源条件；system/model builder 与 runner 已消费生成目标包，详见
[完整配置链路](config-contracts.md)。

## 新增一个配置

复制最接近的 Cute/Chipyard/HWConfig，给各层唯一 ID；只在对应层改参数。
运行 schema/引用检查、生成器检查和 RTL elaboration，最后为该 profile 运行
有明确非零输入的测试。manifest 的 capability 是声明，必须在状态页注明实际
验证到的 dtype、shape、核数和内存路径。
