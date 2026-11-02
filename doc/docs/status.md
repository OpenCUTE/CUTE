# 当前进展与验收边界

## 距离 AI 原生开发还需要什么

下面按 [整体愿望](vision.md) 说明目前的基础和后续工作方向。它们不预设具体实现方案；
每一项还要按 [增量任务边界](config-architecture.md#task-brief) 继续拆分。

| 希望建立的能力 | 当前基础 | 还需补齐的关系 |
|---|---|---|
| 将自然语言变成明确的开发任务 | 本文档提供目标分解、组件承诺和任务说明约定 | 可检查的任务表示及自动执行入口 |
| 按配置组织 SoC 生成 | YAML/schema、引用与生成检查、Chisel/Chipyard 构建 | 通用配置与系统验收 profile 的统一衔接 |
| 在增量中保持 Only One Truth | 部分定义集中、生成物检查、源码与产物身份核对 | 平台事实的统一派生、跨组件契约和变更影响检查 |
| 让子项目可独立实现、共同验证 | SDK、trace、FPE 与系统 verify 的现有接口 | 更多数据类型、调度与平台的契约及组合证据 |
| 将结果沿目标关系反馈 | 已有构建/运行报告、阶段验收和失败诊断 | 从工程结果回到开发目标的统一关联与状态维护 |
| 将设计推进到物理实现 | 当前闭环主要覆盖 RTL 构建与仿真 | 综合、时序、面积、功耗及物理验证输入与证据的接入 |

## 已有实践证据

2026-10-29 的配置层已新增 ISAProfile、MemoryMap 引用和 DTS/SDK 资源匹配。
TCM 的 owner、容量及客户端窗口由实际 DTS 核对，精确向量参数与已实现契约也已导出。
system/model 流程已接入依赖归并、生成平台与链接配置、QEMU 适配和 ELF/身份检查，
详见 [配置契约](config-contracts.md)。新流程的实测证据单独记录，不改写下述历史验收。

截至 2026-10-28，已完成 S1 系统级验证基线，以及 BERT B1–B6、LLaMA L1–L4
的 28 项阶段验收。两者均基于本机工作树，包含尚未提交的实现；不能只检出
`master` 或顶层 HEAD 就认定获得了相同版本。报告需绑定源码内容、二进制、配置和输入。

S1 指同源双 ELF、QEMU 数值校准、RTL 访存重建和逐任务比较的首个系统闭环；
其中 P0 是平台启动、TCM、事务 trace 与同步检查，T1 是 128³ INT8 GEMM 基线。
B/L 编号的计算含义见
[模型阶段表](/sdk/testing/workload-migration/)。下面先列 S1 证据，再列模型验收。

| 内容 | 已有证据 | 未覆盖部分 |
|---|---|---|
| 同源双裸机 ELF | 非零 128³ INT8，RVV→CUTE→RVV | 任意平台和编译器组合 |
| QEMU INT8 | bias/stride/transpose、FIFO ID 回绕、严格非法输入检查 | CUTE 浮点、异步延迟模型 |
| RTL 系统比较 | 5120 请求/响应，3 任务，163840 字节 | 多核和全部调度变体 |
| TCM | RVV 64 字节写与消费，两任务 | 所有 TCM/SGTCM 配置 |
| 验证器 | 27 项行为测试、7 种真实日志破坏测试 | 完整总线一致性验证 |
| 故障早停 | 缺少 wait、错误向量输出，在线/离线一致 | 所有异常组合 |
| 旧 SDK | 原 66 目标加新 7 目标编译；3 项代表回归 | 全 66 目标的运行、旧 suite 的完整 LLaMA 长测 |

BERT B1–B6、LLaMA L1–L4 已完成本轮阶段迁移与验收，结果见下表。L5 的 CUTE FP16 attention 和完整 LLaMA block 仍等待浮点模型。

ResNet50/卷积迁移 X2 永久搁置；online_softmax X1 和低精度实验 X3 留待后续。
这不要求删除硬件已有卷积能力。完整 Docker 配方、多核和完整 profiling
不是 S1 的完成条件，也不能从 S1 推断已经可用。

## 文档中的“支持”

区分接口声明、源码实现、单元测试、系统执行、全部负载验收。历史文档中的
7/7 或 13/13 示例只描述当时用例，不能作为新源码的结果。严格系统 checker
与旧 memverify 的容差路径具有不同保证，应在报告中写明入口和比较方式。

## 2026-10-28 模型阶段验收 {#model-acceptance}

“通过阶段”按 profile × case 计数，共 10 + 6 + 6 + 4 + 2 = 28 项；
每项包含多个软件任务和输出区域。表中的任务数与输出字节数均为该组通过运行的合计。
延迟组使用快速形状，仅覆盖 L2、L4，不能理解为所有原始形状都做过延迟测试。

| Profile | 通过阶段 | 软件任务数 | 比较输出字节 |
|---|---:|---:|---:|
| 快速 B1–B6 / L1–L4 | 10 | 44 | 1,270,784 |
| BERT small 原始形状 | 6 | 17 | 3,276,800 |
| BERT base 原始形状 | 6 | 17 | 6,782,976 |
| LLaMA-1B 原始形状 | 4 | 27 | 39,323,648 |
| L2 / L4 延迟 ack / marker | 2 | 19 | 672,000 |

共 28 项主验收通过，在线/离线结论一致。另有 27 项 verifier 行为测试、6 项校准/依赖检查、7 项真实日志破坏检查和 4 项回放恢复正负检查通过。

L4 原始日志使用独立回放入口完成最终离线核对；已增加可配置回放超时，原运行报告和新回放报告均保留。验收汇总逐项指向实际 report，并核对 ELF、QEMU、simulator、verifier 与最终产物一致。

原始 L2/L4 长测采用同一 elaborated RTL 的 8 线程 Verilator；两个代表用例与单线程的全部 CT 事件按同周期排序后完全一致。32 线程对照结果正确但更慢，未选用于长测。

本轮是确定的非零阶段负载验证，使用 DDR 和串行 tile 调度；不包含训练权重精度评估、完整模型推理、旧 TCM/double-buffer 性能迁移或 CUTE 浮点矩阵模型。

## 验收证据与复核 {#evidence}

本服务器的模型验收包位于
`/home/admin-yjp/workspace/cute-model-migration-20261028/`，入口是包内
`README.zh.md`。它是本机实验产物目录，不随 Git 仓库或文档网站分发。

| 包内路径 | 复核内容 |
|---|---|
| `evidence/acceptance.json` | 28 项通过记录、实际 `report_path`、报告哈希及产物匹配结果 |
| `build-manifest.json`、`profiles/*/build-manifest.json` | 快速及原始形状的源码、工具、输入和产物身份 |
| `threaded-llama-build-manifest.json` | 原始 L2/L4 使用的 8 线程 simulator 身份 |
| `replays/accepted-llama-4/report.json`、`provenance.json` | 原始 L4 的最终离线回放及输入哈希 |
| `evidence/threaded-equivalence.json` | B3、快速 L4 的单线程/8 线程 CT 事件对照 |
| `evidence/review-snapshot/` | 验收时各仓库的未提交代码快照 |

`runs/` 中同时保留开发失败、早停和被替代的运行。验收对象以
`acceptance.json` 明列的报告为准，目录名称中含 `accepted` 不代表其中所有记录都通过。
原始 L4 的旧运行报告保留了离线分析超时；最终结论指向独立回放报告，不能删除旧记录
或将它改写为成功。恢复步骤见 [大日志回放](running.md#replay)。

S1 的独立验收记录位于本服务器的
`/home/admin-yjp/workspace/cute-system-validation-20261027/README.zh.md`。
在其他机器复核时需另行取得对应验收包，或按 [构建](build-system.md) 和
[运行](running.md) 生成新报告。文档构建和链接检查仅验证文档，不能代替硬件回归。
