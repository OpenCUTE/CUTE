# 工程组件

这里集中维护配置、构建、运行、验证及各子项目的工程说明。根据要完成的任务选择入口，
再沿组件接口追踪实现和验收。系统的目标与协作原则见
[OpenCUTE](../index.md)，第一次运行示例从 [上手 demo](../demo/index.md) 开始。

## 配置、构建与运行

| 要完成的任务 | 入口 |
|---|---|
| 找到源码、配置与维护责任 | [仓库与文档位置](../repository.md) |
| 把系统目标落实到配置对象 | [配置 SoC 实践](../practice-config.md) |
| 检查配置并生成代码 | [配置与代码生成](../configuration.md) |
| 核对硬件能力、软件需求和后端支持 | [Config 与 SDK 需求匹配](../config-contracts.md) |
| 构建 simulator、SDK 和验证工具 | [构建系统](../build-system.md) |
| 执行用例、读取报告和离线回放 | [运行与结果](../running.md) |

## 子项目与验证

| 组件 | 文档入口与职责 |
|---|---|
| cute-sdk | [SDK 文档](/sdk/)：软件栈、数值核、case 与模型阶段 |
| cute-trace | [Trace 文档](/trace/)：事件定义、事务协议与日志诊断 |
| 硬件设计 | [设计文档](/design/)：计算、存储、控制、CPU 集成、指令与数据类型 |
| QEMU | [ISA 模拟器](../qemu.md)：执行 SDK 程序、支持范围与 checkpoint 输出接口 |
| verify | [系统级验证](../system-verification.md)：事务重建、输出比较与完成条件 |

## 进展与维护

[当前进展与验收边界](../status.md) 说明已经验证哪些目标、形状和执行路径。
[文档维护与预览](../documentation.md) 说明导航、源文件、实时预览和定稿检查。
