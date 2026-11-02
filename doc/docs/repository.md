# 仓库与文档职责

第一次找模块，可以先看 [核心模块的折叠目录树](modules.md#directories)。本页把
[目标分解](decomposition.md) 和 [核心子模块](modules.md) 映射到维护职责和检查入口。
阅读一个路径前，先确定本次要维护哪项事实或接口；路径帮助定位实现，职责帮助限定
修改范围。关于事实的归属和派生关系，见 [Only One Truth](config-architecture.md#single-truth)。

| 目录 | 职责 | 修改后的主要检查 |
|---|---|---|
| `src/main/scala` | CUTE 控制、数据通路、MMU 和 RoCC 接口 | Scala 生成一致性、RTL 构建、目标用例 |
| `configs` | 加速器/SoC/HWConfig、ISA、schema、内存 profile | `cute-check-config.py` 和 codegen |
| `CPU`、`Vector` | CPU 与向量实现的独立子模块 | 对应子模块 diff；SoC 集成验证 |
| `cute-fpe` | 混合精度 PE 与数值参考 | 格式、舍入、累加规则和对应测试 |
| `chipyard` | SoC 组合、仿真 harness、构建基础设施 | 配置展开、Scala/JAR/RTL/C++ 构建 |
| `cute-sdk` | ISA 产物、runtime/tensor/primitive/fusion/layer、case 与 golden | 双平台编译、软件和系统回归 |
| `cute-sdk/cuteqemu` | RISC-V / CUTE ISA 模拟器 | system 模式、指令语义与独立数值参考校准 |
| `cutetest` | 历史 workload 与实验来源 | 迁移保留来源和计算语义，不把旧二进制当新结果 |
| `trace` | catalog、Scala emit、Python 解码和 C++ 事件定义 | codegen 检查、协议完整性 |
| `tools/runner` | 配置、生成、构建、运行入口 | CLI、产物身份、超时和结果 |
| `tools/verify` | host C++ ack 重建与严格比较 | 正负用例、在线/离线一致 |
| `doc` | 文档入口、主指南、SDK 和硬件站点 | strict 构建、导航和源码引用 |

## 子模块与工作区

`git submodule status` 前缀 `-` 表示尚未初始化，不代表上游漏文件。
为需要的 profile 初始化依赖，记录父仓库 gitlink 和子模块实际 HEAD。
改动前查看顶层和相关子模块 `git status --short`；保留已有未提交文件。

系统验证构建的 fingerprint 包含初始化硬件依赖的实际文件内容，支持未提交
代码的可追溯实验。记录仍需与实际生成二进制一起保存，不能只写一个 master 名称。

## 文档维护边界

主指南解释愿望如何分解、组件如何合作以及增量如何验收；`trace/docs` 解释事件与
完整性；sdk-doc 解释软件 API 和 case；design-doc 解释硬件。命令与字段放在相应
“工程组件”中，主线通过链接使用它们。根 README 提供阅读入口。
新增 CLI 参数、事件、任务协议时同时更新对应接口文档与状态页。

QEMU 的支持范围、启动和 checkpoint 接口见 [ISA 模拟器](qemu.md)。
