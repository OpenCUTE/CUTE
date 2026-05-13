# CUTE WIP README 中文版

CUTE 是一个 CPU-centric and Ultra-utilized Tensor Engine 项目。这个 WIP
README 是面向开发者的仓库级入口，用来快速理解目录结构、config-first
工作流、仿真执行、trace 工具链，以及 CUTE SDK 的整体方向。

英文版见：`readme_wip.md`。

当前公开设计文档见：
[CUTE Design Doc](https://opencute.github.io/CUTE-Design-Doc/)。

## 仓库结构概览

下面列出仓库中最关键的目录：

```text
.
├── src
│   └── main/scala         # design files
│       ├── CUTETOP.scala  # top module
├── configs                # CUTE、Chipyard、可运行目标的声明式配置
│   ├── cute_configs       # CUTE 加速器参数预设
│   ├── chipyard_configs   # SoC + CUTE 组合配置
│   ├── hwconfigs          # 可运行目标配置
│   ├── cute_isa_versions  # CUTE/YGJK ISA 和 datatype 定义
│   ├── vector_versions    # 向量扩展能力配置
│   └── schemas            # JSON schema 和参数字典
├── trace                  # CUTE trace catalog、生成 API、解码数据
│   ├── catalogs           # trace catalog 真相源
│   ├── cutetrace          # Scala trace runtime 和生成 API
│   └── python             # Python parser、decoder、render 库
├── cute-sdk               # CUTE 软件开发与验证 SDK
│   ├── cuteisa            # 生成出的 ISA artifacts
│   ├── cuteqemu           # 功能级模拟器方向
│   ├── nvwa               # golden 生成方向
│   ├── memverify          # 内存比对方向
│   └── cutelib            # 分层 CUTE 软件库
├── cute-fpe               # mixed-precision PE project
│   ├── fpe                # mixed-precision PE 的 RTL 实现
│   └── ccode              # float golden C 代码
├── cutetest               # 不同 workload 的 C 测试实现
│   ├── base_test          # 基础 conv/gemm 测试和软件 helper
│   ├── dramsim_config     # 不同 DRAM 带宽的 DRAMSim 配置
│   ├── gemm_test          # 不同 GEMM 测试
│   ├── resnet50_test      # ResNet50 conv-vector fuse kernel 测试
│   └── transformer_test   # BERT/LLaMA gemm-vector fuse kernel 测试
├── tools                  # host 端 Python 工具链
│   ├── runner             # config 检查、生成、build、run 工具
│   └── trace              # trace 检查、生成、解码 CLI 工具
├── scripts                # 敏捷开发脚本
├── chipyard               # Chisel SoC 敏捷开发框架
├── CPU                    # 已完成集成的 CPU 列表
│   ├── boom               # out-of-order superscalar core (BOOM)
│   ├── rocket             # in-order 1-issue core (Rocket)
│   └── shuttle            # in-order superscalar core (Shuttle)
└── doc                    # 设计文档和 SDK 文档
```

## 后续阅读入口

根 README 保持短一些。各个活跃系统有自己的文档：

- Config manifests：`configs/README.md`
  说明 CuteConfig、ChipyardConfig、HWConfig、ISA、vector、memory
  和 schema 检查。
- Runner tools：`tools/README.md`
  说明 `cute-check-config.py`、`cute-build.py`、`cute-run.py`
  以及 Scala config 生成器。
- Trace system：`trace/README.md`
  说明 trace catalog、Scala/Python 生成 API，以及 compact trace
  解码流程。
- Trace format：`trace/format_spec.md`
  说明 compact trace 行格式和字段编码。
- CUTE SDK：`cute-sdk/readme.md`
  说明 cuteisa、cuteqemu、nvwa、memverify 和 cutelib。
- 深度 Chipyard/config 开发：
  `doc/sdk-doc/chipyard-config-development.zh.md`
  说明 YAML、Scala Config、Chipyard、simulator 和 run flow 的关系。

## 准备环境

执行后续步骤之前，先完成环境初始化：

```bash
./scripts/setup-env.sh
```

该脚本会更新 submodule，并准备 Chipyard 环境。如果后续命令报缺少
Chipyard 工具或环境变量，先重新执行这个步骤，并检查 `chipyard/env.sh`。

## Config-First 工作流

当前方向是：**Config YAML 是真相源**。

整体关系如下：

```text
configs/
  ├── cute_configs/*.yaml
  ├── chipyard_configs/*.yaml
  ├── hwconfigs/*.yaml
  ├── cute_isa_versions/*.yaml
  └── vector_versions/*.yaml
        │
        ├─ Scala config 生成和检查
        ├─ C header / ISA JSON 生成
        ├─ Verilator simulator 构建
        └─ simulator run + trace decode
```

检查所有 config 输入：

```bash
python3 tools/runner/cute-check-config.py --scan
python3 tools/runner/cute-check-config.py --hwconfig --all
python3 tools/runner/cute-check-config.py --chipyard-config --all
```

为单个可运行目标生成 C header 和 ISA JSON：

```bash
python3 tools/runner/cute-build.py \
  --hwconfig cute4tops_scp128_dramsim48 \
  --step genfiles
```

为所有 HWConfig 生成文件：

```bash
python3 tools/runner/cute-build.py \
  --all \
  --step genfiles
```

`--all` 会扫描 `configs/hwconfigs/*.yaml`，并按 `chipyard_config`
去重，因为生成文件和 simulator 都按 Chipyard config id 存放。

## Scala 与 Chipyard Config 生成

CUTE 有两条面向 Scala 的 config 路径：

```text
configs/cute_configs/*.yaml
  └─→ src/main/scala/HardwareConfig.scala

configs/cute_isa_versions/*.yaml
  └─→ src/main/scala/InstConfig.scala

configs/chipyard_configs/*.yaml
  └─→ chipyard/generators/chipyard/src/main/scala/config/CuteConfig.scala
```

检查生成出的 Scala 文件是否和 YAML 真相源一致：

```bash
python3 tools/runner/cute-gen-scala-config.py --check
```

更新 `HardwareConfig.scala` 和 `InstConfig.scala`：

```bash
python3 tools/runner/cute-gen-scala-config.py --update
```

检查或更新 Chipyard `CuteConfig.scala`：

```bash
python3 tools/runner/cute-update-chipyard-configs.py \
  --output chipyard/generators/chipyard/src/main/scala/config/CuteConfig.scala \
  --check
```

如果要理解这些文件如何关联，以及如何增加新目标，阅读
`doc/sdk-doc/chipyard-config-development.zh.md`。

## 构建 Simulator

从 HWConfig 构建 Verilator simulator：

```bash
python3 tools/runner/cute-build.py \
  --hwconfig cute4tops_scp128_dramsim48 \
  --step simulator
```

也可以一条命令完成生成文件和 simulator 构建：

```bash
python3 tools/runner/cute-build.py \
  --hwconfig cute4tops_scp128_dramsim48 \
  --step all
```

Simulator 产物归档在：

```text
build/chipyard_configs/<chipyard_config_id>/simulator-verilator
```

Simulator 构建完成后，工具会输出匹配到的 Chipyard Scala config class，
以及绝对路径形式的 `CuteConfig.scala:<line>`，方便 VS Code 等编辑器
直接跳转。

## 构建 CUTE Tests

使用现有测试脚本构建 bare-metal RISC-V 二进制：

```bash
./scripts/setup-get-rvv-toolchain.sh
./scripts/build_cute_test.sh
```

当前 `cutetest/` 下包含 base tests、GEMM tests、ResNet50 kernels
和 Transformer kernels。

## 通过仿真运行程序

使用 HWConfig 运行一个编译好的测试二进制：

```bash
python3 tools/runner/cute-run.py \
  --hwconfig cute4tops_scp128_dramsim48 \
  --test /root/opencute/CUTE/cutetest/base_test/cute_Matmul_mnk_128_128_128_zeroinit.riscv
```

使用 `--quiet` 可以隐藏 runner 自己的状态行，例如 `[CMD]`，但仍然保留
simulator stdout：

```bash
python3 tools/runner/cute-run.py \
  --quiet \
  --hwconfig cute4tops_scp128_dramsim48 \
  --test /root/opencute/CUTE/cutetest/base_test/cute_Matmul_mnk_128_128_128_zeroinit.riscv
```

默认输出目录：

```text
build/chipyard_runs/<hwconfig>/<test>/
├── hwconfig.yaml
├── run.log     # simulator stdout
└── run.out     # simulator stderr
```

## Trace 工作流

CUTETrace 是 catalog-driven 的。Catalog 是 Scala trace emit API、
Python decoder 数据和稳定生成 metadata 的真相源。

```bash
# 1. 检查 trace catalog 和 filters
python3 tools/trace/check_cute_trace.py

# 2. 重新生成 Scala/Python trace artifacts
python3 tools/trace/gen_cute_trace.py \
  --catalog trace/catalogs/cute_trace.json \
  --scala-out trace/cutetrace/src/main/scala/trace/generated \
  --python-out trace/python/cutetrace/generated \
  --build-out trace/generated

# 3. 解码 simulator log
python3 tools/trace/decode_cute_trace.py \
  --log build/chipyard_runs/<hwconfig>/<test>/run.log \
  --mode jsonl \
  -o out.jsonl
```

先阅读 `trace/README.md`，再根据需要阅读 `doc/sdk-doc/cute-trace-*.md`
下的 catalog、parser、decoder、render 和 CLI 文档。

## CUTE SDK 工作流

`cute-sdk/` 是面向 CUTE 程序开发和验证的软件栈方向。

```text
configs/cute_isa_versions/*.yaml
  └─→ cute-sdk/cuteisa/<isa_version>/
        ├── instruction.h
        └── isa.json

cutelib development
  ├── cuteqemu functional simulation
  ├── Verilator simulation + trace decode
  └── FPGA demo readback
        └─→ memverify bit-level comparison against golden data
```

主要概念见 `cute-sdk/readme.md`：

- `cuteisa`：共享 ISA artifacts。
- `cuteqemu`：功能级模拟器方向。
- `nvwa`：golden 生成方向。
- `memverify`：内存比对方向。
- `cutelib`：runtime/tensor/layer/fusion/model 分层库。

## 旧脚本流程

一些脚本仍然适合直接走 Chipyard 风格流程：

```bash
./scripts/build-verilog.sh CUTE2TopsSCP64Config
./scripts/build-simulator.sh CUTE2TopsSCP64Config
./scripts/run-simulator-test.sh \
  CUTE2TopsSCP64Config \
  /root/opencute/CUTE/cutetest/base_test/cute_Matmul_mnk_128_128_128_zeroinit.riscv
```

新流程建议优先使用 HWConfig-driven runner tools。这样 YAML manifests、
生成文件、simulator 产物、run logs 和 trace decode 输入之间的关系会更清楚。
