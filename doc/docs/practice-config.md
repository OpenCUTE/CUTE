# 实践：把系统愿望落实为 SoC 配置

从一个示例愿望出发：“我想让 CPU、RVV 和 CUTE 配合执行模型阶段，先在仿真中建立
正确性基线，之后再研究内存性能。”这一句话还不足以生成 SoC。我们需要把它转成
已有部件能够承担的功能，以及可以明确选择的配置。

## 1. 找到这次必须确定的系统选择

| 子目标 | 需要作出的决定 | 本例的选择 |
|---|---|---|
| CPU 能提交并等待计算任务 | CPU 类型、核数、启动方式 | 复用已有单核 Shuttle 系统路径 |
| 向量与矩阵计算能交接数据 | RVV 参数、互联和内存路径 | 采用已验收的 Saturn 512-bit profile |
| 指令的含义对软件与硬件一致 | ISA、数据类型和运算范围 | 先使用 `cute_isa_v1` 中已验证的 INT8 路径 |
| 可以运行并收集结果 | 仿真后端、内存配置、运行预算 | 使用 Verilator 与现有 DRAMSim2 配置 |
| 后续能判断结果正确 | 输出、完成条件、可观察的事件 | 接入已有系统验证流程 |

这些选择服务于“先得到可信基线”的目的，不包含对面积、功耗或吞吐最优的承诺。
如果目标换成多核吞吐或新浮点格式，选择空间和前置任务也会变化。

## 2. 把选择放到正确的配置层

OpenCUTE 现有配置按不同责任分层，完整关系见
[Config-first 对象与依赖图](config-architecture.md#dependencies)。HWConfig 选择本次
构建与运行目标，ChipyardConfig 组合硬件，ISAProfile 与 MemoryMap 明确能力和布局，
ExecutionProfile 规定软件运行及后端策略。部件参数和编码继续由各自对象维护。

本例可以复用
`cute4tops_shuttle512_d512_v512_m512_sysbus512_membus1_core_dramsim48`。
它引用的 ChipyardConfig 选中单核 Shuttle、Saturn、CUTE 参数和 ISA，HWConfig
再绑定 48 GB/s 命名的内存预设与 Verilator。具体字段见 [配置参考](configuration.md)。

这个目标现在还引用标准 ISAProfile 和完整地址空间的 MemoryMap；配置参数与导出的
客户端窗口分别维护，新增的实际检查步骤见 [Config 与 SDK 需求匹配](config-contracts.md)。

分层的意义是限制每次变化。研究另一组内存参数时，优先改变运行层的内存选择；
调整矩阵部件参数时，进入 CuteConfig 并检查系统及软件约束；修改指令编码时，则需要
协调软件、硬件和模型消费者。只在实际拥有这项事实的层修改它。

## 3. 让配置成为构建工具可以消费的输入

在 CUTE 根目录、已激活的 [工具环境](build-system.md) 中执行：

```sh
python3 tools/runner/cute-check-config.py \
  --hwconfig cute4tops_shuttle512_d512_v512_m512_sysbus512_membus1_core_dramsim48
python3 tools/runner/cute-build.py \
  --hwconfig cute4tops_shuttle512_d512_v512_m512_sysbus512_membus1_core_dramsim48 \
  --step genfiles
python3 tools/runner/cute-build.py \
  --hwconfig cute4tops_shuttle512_d512_v512_m512_sysbus512_membus1_core_dramsim48 \
  --step simulator
```

检查器先核对配置结构和引用，生成器产生相应配置产物，硬件工具继续生成 RTL 和
simulator。实际构建链和输出位置见 [构建系统](build-system.md)。
如果已有组合无法满足新愿望，应先明确缺少哪个部件或接口，再新增配置与对应实现。
在 capability 中加一项名称，不会同时生成实现和测试。

## 4. 把系统产物交给下一层愿望

到这里得到的是一套可构建、可运行的系统产物。父目标还要求“计算结果可信”，因此
下一步需要软件输入、参考结果、trace 和 verify 的协作。

当前通用 `cute-build.py` 生成硬件产物，`cute-system-build.py --hwconfig ...` 还生成
目标包、双 ELF、QEMU、verifier、simulator 和 manifest。
通用 simulator 不能仅凭配置名称相同就直接充当这份验收清单中的产物。

继续阅读 [BERT 阶段实践](practice.md)，看同一个系统目标如何交接到计算、观测与
验证。当前配置到 SDK/QEMU 的衔接已经自动执行，新增能力仍需扩展相应契约、实现
与验收，不能只增加配置名称。
