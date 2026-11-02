# OpenCUTE：从自然语言愿望到 SoC

OpenCUTE 的核心愿望是 **AI 原生的 RTL SoC 开发**：人用自然语言描述要实现的计算
系统，AI 把愿望逐层具体化，形成能够被构建和验证工具消费的输入，并用执行证据回答
这个愿望实现到了哪里。

我们的工作是把这条路径连接起来：

```text
愿望与约束 → 可完成的子目标 → 接口和行为约定
           → 配置、软件、RTL 与验证输入 → 构建、运行与证据
           → 回答上层目标，确定下一次增量
```

## 为什么这样组织仓库

复杂 SoC 的开发包含大量相互依赖的选择。把这些选择分到有明确输入、输出和完成条件
的小任务中，AI 就能在有限范围内作出判断，并得到及时的检查反馈。局部实现不断演进，
子项目对外仍维持清楚的功能抽象。

这依赖 **Only One Truth**：每项事实有明确的定义位置，其他地方引用、生成或检查它。
配置、接口、实现和验收结果保持可追踪的对应关系，增量才能成为下一步的可靠基础。

## 各组件帮助实现什么

| 组件 | 承担的小愿望 | 主要交付 |
|---|---|---|
| OpenCUTE | 按配置组织 SoC 生成与集成 | 系统配置、RTL、构建产物 |
| cute-sdk | 将计算意图表达为可运行和可比较的任务 | 软件库、程序、输入、输出描述与参考结果 |
| cute-trace | 让执行事实可观察、可理解 | 事件定义、生成 API 和实际运行记录 |
| cute-fpe | 为浮点计算提供有明确含义的部件 | 数值部件、接口和参考实现 |
| verify | 判断执行是否满足约定 | 数据、顺序与完整性的验证结论 |

cute-trace 当前位于 `trace/` 与 `tools/trace/`，系统 verify 位于 `tools/verify/`。
各组件如何交接，以及哪些承诺已有证据，见主文档。

## 阅读主线

1. [愿望与目的](doc/docs/vision.md)：为什么需要从自然语言到结构化工程输入的路径。
2. [逐层分解](doc/docs/decomposition.md)：怎样把大愿望变成能合作的小愿望。
3. [组件承诺](doc/docs/modules.md)：每个子项目接受什么、交付什么。
4. [Config-first 对象与依赖](doc/docs/config-architecture.md)：配置怎样形成产物、保持一致并支持增量开发。
5. [配置 SoC](doc/docs/practice-config.md) 与 [验证 BERT 阶段](doc/docs/practice.md)：把愿望落实到已有流程。

当前已经具备配置生成和 RTL 系统验证的基础，并有 S1 及 BERT/LLaMA 阶段的验收记录。
自然语言任务转换、统一跨组件契约和完整物理实现流程仍有工作需要补齐，详见
[当前进展与证据](doc/docs/status.md)。

## 工程入口

[目录与职责](doc/docs/repository.md) · [构建](doc/docs/build-system.md) ·
[配置生成](doc/docs/configuration.md) · [运行](doc/docs/running.md) ·
[Trace](trace/docs/index.md) · [SDK](doc/sdk-doc/docs/index.md) ·
[硬件设计](doc/design-doc/docs/index.md)

在仓库根目录运行 `python3 tools/docs/preview_docs.py`，可预览主指南与子项目文档。
环境准备、端口转发和文档维护见 [文档入口](doc/README.md)。
