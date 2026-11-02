# QEMU ISA 模拟器

QEMU 在 OpenCUTE 中承担 **ISA 模拟器**的职责：按照所支持的 RISC-V 与 CUTE 扩展
指令语义执行 SDK 编译出的程序，维护程序可见的寄存器与内存状态。SDK 可以据此运行
和检查程序；在系统验证中，还会把各任务的输出导出为 golden。

独立 reference 则按计算规则求出预期结果，用于校准 QEMU 的输出。ISA 模拟执行和
独立数值参考分别提供检查依据，具体职责见 [CUTE-SDK](modules.md#sdk)。

代码在 `cute-sdk/cuteqemu` 子模块。构建目标是 `riscv64-softmmu`，system runner
使用 Spike 裸机机型与 HTIF 启动。SDK 为 QEMU 与 Verilator 分别生成 ELF，runner
独立解析符号地址；共享 C 源码和数值选项不要求两者 ELF 地址相同。

## 已实现接口

- CPU 选项 `x-cute=true` 开启自定义指令，默认关闭。
- `x-cute-checkpoints` 指定任务输出清单；runner 从 ELF 和 case 生成清单并自动传入
  路径，无需手填。TRACE_MARK 匹配 hart、seq、key 后导出该任务全部区域。
- `spike,cute-tcm=true` 启用单 hart 私有 TCM；`cute-tcm-base`、`cute-tcm-size` 由
  SDK 目标适配器从 DTS 派生。当前基线窗口为 `0x70200000`、2 MiB，不能混用
  内部译码基址 `0x70000000`。关闭 TCM 时不启用该映射。
- INT8 × INT8 → INT32 使用二进制补码累加；支持 zero、行 bias、matrix bias、
  stride 与 transpose 等已建模参数。完整编码由 ISA YAML 与生成头文件定义。

CUTE 指令语义主要实现在 `target/riscv/cute_helper.c`，译码接入 RISC-V decoder/translator。
任务配置、发送、查询与清除保留可见 FIFO 状态。当前 CUTE 数值计算在发送时同步完成，
没有模拟 RTL 的实际执行延迟和总线并发。验证流程使用 QEMU 输出作为 golden，
另从 RTL trace 检查数据可见性、ack 和访问冲突。

## 数值与诊断

每个新阶段先校准 QEMU 对独立 reference 的输出，再比较 RTL 与 QEMU 全输出字节。
BERT 整数规则要求精确；LLaMA 的 CPU/RVV FP32 与 FP16 后处理可针对数学 reference
声明容差，RTL/QEMU 仍逐字节一致。该范围没有包含 CUTE 浮点矩阵模型。

不支持的配置或非法任务状态应报非法指令，不能静默用零输出代替。查问题时保留
QEMU 日志、两个 ELF、checkpoint manifest 与输入文件哈希；不要从失败的 RTL
日志反向生成 golden。构建入口还会运行 `tests/system/qemu_contract.c` 的 ISA 契约检查。

近似激活影响后续整数舍入时，模型 case 可声明逐阶段 reference 依赖：只读取
已校准的前驱任务或已哈希输入，独立重新计算本任务输出。当前 L4 使用此方式，
整数阶段不放宽比较；派生 reference 留在运行包中供审查。
