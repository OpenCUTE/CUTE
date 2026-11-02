# 构建系统

以下命令均从 CUTE 根目录执行，可直接复制；所有路径相对于这个目录。
系统构建和文档构建要求产物位于源码树之外，因此统一使用同级的 `../opencute-out/`。
脚本会创建所需的输出目录，并在清单中记录解析后的绝对路径，便于后续核对。
先确认子模块、工具版本和选择的 HWConfig。已有开发环境激活其 `chipyard/env.sh`
或本机工具环境；工具找不到时先核对环境和 PATH。

| 内容 | 本文约定的相对路径 |
|---|---|
| 系统构建 | `../opencute-out/system/` |
| quick 模型构建 | `../opencute-out/models/quick/` |
| 每次运行结果 | `../opencute-out/runs/` 下带时间的独立目录 |
| 文档环境、生成站点 | `../opencute-out/docs-env/`、`../opencute-out/docs-site/` |

全新 checkout 可使用 `scripts/setup-env.sh` 初始化。它执行顶层
`git submodule update --init`，再调用 Chipyard 的 `build-setup.sh` 下载和构建依赖。
这会修改依赖工作区，不是每次打开终端时的环境激活命令；已有未提交开发内容时，
先记录各仓库状态，按缺少的依赖处理。当前本机验收不包含该脚本的全新机器安装验收。

## 三条构建路径

| 路径 | 用途 | 入口 |
|---|---|---|
| Config-first SoC | 选择 HWConfig 生成 C/Scala 配置和模拟器 | `tools/runner/cute-build.py` |
| SDK CMake | 编译裸机 case、primitive/fusion/layer | `cute-sdk/CMakeLists.txt` |
| 系统级验证 | 同源双 ELF、QEMU、RTL、C++ verifier 与清单 | `tools/runner/cute-system-build.py` |

硬件构建链为：YAML/Scala Config → SBT 项目与 assembly JAR → Chisel elaboration
→ FIRRTL/firtool → SystemVerilog → Verilator C++ → host simulator。
SDK 构建链为：ISA/平台头 → RISC-V C 编译和链接 → 裸机 ELF。
QEMU 与 C++ verifier 是宿主机程序，不能用 RISC-V 编译器构建。

模型的两个 ELF 目标分别编译、链接。当前 Spike 与 Verilator profile 都使用 HTIF，
ISA/ABI 选项相同，因此允许两份 ELF 内容相同；runner 仍独立解析符号。未来启动、
链接或平台 I/O 不同时可通过两个目标扩展，不依赖尚未定义的统一平台 CSR。

## 工具与环境

已验收系统 profile 使用 RV64、VLEN=512、`-march=rv64gcv_zvl512b_zvfh`、
`-mabi=lp64d` 和 HTIF 裸机启动。编译、链接必须一致；仅编译阶段设置 ABI 会被
默认 RV32 工具链影响。工具集还包括 JDK/SBT、firtool、Verilator、C/C++17、CMake、
Python/PyYAML/jsonschema，以及 QEMU 的 Python、Meson、Ninja、GLib/pkg-config。

平台参数是 profile 的组成部分，不能把一个目录中的编译器或 simulator 存在
当作环境配置正确。部署环境应固定工具版本和下载来源；当前源码构建验收不等于
所有新机器或 Docker 从零安装已经验收。

下面的 `$(command -v riscv-none-elf-gcc)` 从已激活环境的 `PATH` 自动取得编译器
路径，无需填写安装目录。可以先执行 `command -v riscv-none-elf-gcc` 检查；没有
输出时，需要先安装或激活上述工具环境。相对路径示例不代替工具依赖的安装。

## Config-first 示例

```sh
python3 tools/runner/cute-check-config.py --scan
python3 tools/runner/cute-build.py --hwconfig cute4tops_shuttle512_d512_v512_m512_sysbus512_membus1_core_dramsim48 --step genfiles
python3 tools/runner/cute-build.py --hwconfig cute4tops_shuttle512_d512_v512_m512_sysbus512_membus1_core_dramsim48 --step simulator
```

生成头和常规模拟器存放在 `build/chipyard_configs/<chipyard_config_id>/`。
HWConfig 选择 DRAMSim2 配置和运行策略；ChipyardConfig 选择硬件组合。
两种不同内存速度的 HWConfig 可以复用同一个硬件配置，参见 [配置关系](configuration.md)。

## 系统验证构建

```sh
python3 tools/runner/cute-system-build.py \
  --hwconfig cute4tops_shuttle512_d512_v512_m512_sysbus512_membus1_core_dramsim48 \
  --out ../opencute-out/system \
  --cc "$(command -v riscv-none-elf-gcc)" --jobs 16
```

脚本验证 trace/Scala/SDK codegen，先 elaboration 并核对 DTS，再生成带身份的
SDK 目标包与确定输入，构建软件、QEMU、verifier 和 simulator。ELF 布局、QEMU
能力与边界探针属于构建检查。当前验证后端支持单 hart；更多硬件配置需满足所选
软件需求和后端约束。平台、链接与依赖的关系见 [配置链路](config-contracts.md)。
首次构建会创建输出目录；同一 checkout 后续构建可复用它。每次运行的结果目录独立保存，
见 [运行程序与结果](running.md)。本地 QEMU 依赖前缀可以用重复的
`--qemu-configure-arg=...` 传入。先看 `--help` 确认当前参数。

## 产物与缓存 {#artifacts}

系统构建输出包含 `build-manifest.json`、`build-commands.json`、`target/`、`logs/`、fixture
和各工具产物。RTL 目录按硬件源码内容、子模块、profile、工具身份派生；修改
trace 或 Scala 后不能复用旧 simulator 作为新接口验收。

Chipyard assembly 会检查新路径 JAR 非空，并避免 SBT 输出缓存将旧路径当成新产物。
历史 `cute-test.py` 的文件存在检查与系统 runner 的完整指纹检查不同；使用旧入口
时必须自行确认产物新鲜度。系统 runner 要求 build manifest 与当前源码、ELF、
QEMU、simulator、verifier 一致，并在每次 run 中保存清单副本。

## 排错顺序

1. 环境/依赖错误：检查工具是否来自同一声明环境，GLib 的编译/链接/运行库是否一致。
2. 生成物漂移：运行 [配置生成检查](configuration.md)，不要手改生成文件掩盖错误。
3. Scala/RTL 错误：先看第一处报错，检查子模块 gitlink、类路径和配置名称。
4. 模拟器运行错误：保存构建日志与二进制哈希，再按 [结果诊断](running.md) 定位。

## 模型阶段构建 {#model-builds}

`cute-model-build.py` 在已有 S1 构建上生成模型 fixtures 并构建双 ELF。复用前检查
硬件、QEMU 源码及二进制哈希；SDK 和 host verifier 重新构建。不会仅根据旧 simulator
文件名判断可复用。需要 Python NumPy（模型输入/reference）和原构建使用的工具环境。

```sh
python3 tools/runner/cute-model-build.py \
  --base-build-manifest ../opencute-out/system/build-manifest.json \
  --out ../opencute-out/models/quick --profile quick \
  --cc "$(command -v riscv-none-elf-gcc)" --jobs 16
python3 tools/runner/cute-model-run.py \
  --build-manifest ../opencute-out/models/quick/build-manifest.json \
  --out "../opencute-out/runs/models-quick-$(date +%Y%m%d-%H%M%S)" --jobs 4
```

可选 profile 为 `quick`、`bert-small`、`bert-base`、`llama-1b`；后面三项使用原实验
形状。每个 profile 使用独立构建目录。`--cases bert_1 llama_2` 可选阶段；不存在于
该 profile 的阶段会报错。模型阶段详情见 SDK 的“BERT 与 LLaMA 迁移”。

`--jobs` 在构建入口表示并行编译任务数，在模型运行入口表示同时运行的 case 数。
它不会把单个 simulator 改成多线程版本。运行超时、周期预算和大日志回放预算见
[模型运行参数](running.md#model-runs)。
