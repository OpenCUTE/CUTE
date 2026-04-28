# CUTE 软件测试框架完全重构 Big Plan

> 目标：把 CUTE 的软件测试、trace 系统级正确性验证、trace top-down 性能分析、CONFIG 驱动流程重新规划成一套结构化工程系统。  
> 本计划面向后续细化讨论：先定义总体架构、边界、数据模型、迁移路线和验收标准，再逐块落地。

---

## 0. 核心判断

当前 CUTE 已经具备几个重要基础：

- `src/main/scala/util/HeaderGenerator.scala` 已经能从 Chipyard Config 反射提取真实 `CuteParams`，生成 `datatype.h.generated`、`validation.h.generated`、`instruction.h.generated`。
- `cutetest/` 已经沉淀大量 GEMM、datatype、ResNet50、BERT、LLaMA 测试程序和 benchmark 数据。
- `scripts/build-test.sh`、`scripts/generate-headers.sh`、`scripts/run-simulator-test.sh` 已经形成最小可用的编译与仿真入口。
- `verify/` 目前为空，适合作为新验证框架的承载目录。
- 现有测试更多是文件级、脚本级、人工结果级组织，缺少一个结构化的“测试任务描述”和“运行结果协议”。

因此这次重构的关键不是单纯多写脚本，而是建立一个稳定的中间层：

```text
CONFIG + SOFTWARE + Inputs + TracePolicy
  -> Run Job
  -> Run Artifact + TRACE
  -> Verify/Profile/Regression Report
```

以后无论是跑一个 matmul correctness、扫一组硬件 CONFIG、做 LLaMA layer 性能归因，还是比较 nofuse/notcm/fuse，都应该由同一套 job schema 驱动。

### 0.1 三大核心对象：CONFIG / SOFTWARE / TRACE

整个重构可以先抽象成三个一等对象：

```text
CONFIG   -> 固化一个具体 CUTE 硬件实体
SOFTWARE -> 面向这个实体生成/选择可运行的软件语义
TRACE    -> 把一次运行变成可验证、可分析的事实记录
```

这三个对象分别回答不同问题：

| 对象 | 核心职责 | 回答的问题 |
|---|---|---|
| `CONFIG` | 决定硬件实体。把可参数化的 CUTE 固定成一个具体实现，包括 tensor tile、数据宽度、指令字段、buffer、MMU、FPE、scale layout、支持能力边界 | 这台 CUTE 到底长什么样，能跑什么 |
| `SOFTWARE` | 决定软件语义。依据 `CONFIG` 生成/选择 tensor runtime、算子实现、NN layer 测试、向量融合算子、golden 策略、合法性检查 | 针对这台 CUTE，应该怎么发指令、怎么布局 tensor、哪些 case 合法、golden 长什么样 |
| `TRACE` | 决定事实记录。把 `SOFTWARE` 在某个 `CONFIG` 上的一次实际执行记录下来，供 verify 和 profile 使用 | 实际发生了什么，输出是什么，时间花在哪里，瓶颈在哪里 |

因此真正的运行单元不是单独的 C 文件，也不是单独的硬件配置，而是：

```text
Run = CONFIG + SOFTWARE + Inputs + TracePolicy
```

在这个基础上派生出：

```text
Verify     = Run Artifact + GoldenPolicy + TRACE
Profile    = Run Artifact + PerfModel + TRACE
Regression = Many Runs + BaselinePolicy
```

这个模型也解释了为什么需要更好的 config 机制：`CONFIG` 不只影响硬件生成，它还决定 `SOFTWARE` 能否生成、测试是否合法、golden 如何计算、trace 如何解释。  
同样，`TRACE` 也不只是 debug log；它是 `SOFTWARE on CONFIG` 的可复盘证据，是 verify 和 profile 的共同事实层。

### 0.2 本 Plan 的阅读地图

后续章节可以按“三大对象如何逐步成熟、如何相互联合”来理解：

| 章节 | 主要推进对象 | 建立的联合关系 | 最终服务的目标 |
|---|---|---|---|
| `2. Config 机制重构` | `CONFIG` | `CONFIG -> generated headers -> SOFTWARE capability boundary` | 固化硬件实体，并让软件知道这台硬件能跑什么 |
| `7. Test Line` | `SOFTWARE` | `SOFTWARE depends on CONFIG` | 依据硬件配置生成 tensor runtime、算子、NN layer、融合算子测试 |
| `4. Trace Layer` | `TRACE` | `TRACE records SOFTWARE on CONFIG` | 把一次执行变成 verify/profile 都能复用的事实层 |
| `3. Runner & Artifact` | 三者的组合器 | `CONFIG + SOFTWARE + TRACE policy -> Run Artifact` | 让每次实验可复现、可归档、可比较 |
| `5. Verify Line` | `SOFTWARE + TRACE` | `GoldenPolicy(SOFTWARE, CONFIG) + Actual(TRACE)` | 判断输出是否正确，并定位 mismatch |
| `6. Perf Line` | `TRACE + CONFIG` | `PerfModel(CONFIG) + Timeline(TRACE)` | 判断性能瓶颈、利用率、带宽、stall 来源 |
| `8. 目录与模块建议` | 三者的物理落点 | 把抽象映射到目录边界 | 降低工程混乱度，知道文件该放哪里 |
| `9. 分阶段实施路线` | 三者的成熟路线 | 从 schema 到最小闭环，再到 suite/regression | 分阶段达成完整测试框架 |

也可以把目标分成三层：

```text
第一层：对象自洽
  CONFIG 自洽：硬件参数、指令、layout、capability 有唯一来源
  SOFTWARE 自洽：runtime、算子、测试、golden 都能依据 CONFIG 生成或选择
  TRACE 自洽：事件格式、parser、index、artifact 都稳定

第二层：对象联合
  CONFIG + SOFTWARE：知道哪些测试可生成、可编译、可运行
  SOFTWARE + TRACE：知道实际输出能否与 golden 对齐
  CONFIG + TRACE：知道性能事件如何解释、瓶颈如何归因

第三层：系统闭环
  CONFIG + SOFTWARE + TRACE
    -> reproducible Run Artifact
    -> correctness Verify
    -> top-down Profile
    -> regression Suite
```

---

## 1. 总体架构

本章把三大对象放进一个工程流水线里：`CONFIG` 和 `SOFTWARE` 在 runner 中被组合成一次 run，run 产生 `TRACE` 和 artifact，随后 verify/profile/regression 复用同一个 artifact。

### 1.1 四层工程模型

```text
┌─────────────────────────────────────────────────────────────────┐
│ Layer A: Config & Manifest                                      │
│ - CONFIG: Chipyard/Chisel Config + generated headers             │
│ - SOFTWARE manifest: test case / suite / sweep / golden policy   │
│ - TracePolicy: trace level / event set / perf policy             │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│ Layer B: Runner & Artifact                                      │
│ - 组合 CONFIG + SOFTWARE + Inputs + TracePolicy                  │
│ - 编译: generated headers、C test binary、simulator               │
│ - 运行: Verilator + DRAMSim + workload                           │
│ - Artifact: config/software/trace/build/run snapshots            │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│ Layer C: Trace & Event Model                                    │
│ - TRACE: cycle/module/event/task/tile/addr/data                  │
│ - Parser: raw log -> structured trace                            │
│ - Index: task timeline、memory transaction、store tensor          │
│ - Export: jsonl/csv/html summary                                 │
└──────────────────────────────┬──────────────────────────────────┘
                               │
┌──────────────────────────────▼──────────────────────────────────┐
│ Layer D: Verify & Perf                                          │
│ - Verify: SOFTWARE golden + TRACE actual                         │
│ - Perf: CONFIG perf model + TRACE timeline                       │
│ - Regression: many Run Artifacts + baseline policy               │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 三条主线

1. **Test Line**
   - 负责“生成什么测试、编译什么 binary、跑在哪个硬件 CONFIG 上”。
   - 产物是可复现的 run artifact，而不是散落的 `.riscv` 和 `.log`。

2. **Verify Line**
   - 负责“跑出来的行为是否正确”。
   - 以 trace 为主要输入，从 store 事件或 memory writeback 事件中重建输出 tensor。
   - golden 可以来自 CPU reference、已有 `.h` 数据、Python/numpy、或测试自带 checker。

3. **Perf Line**
   - 负责“为什么快/慢，瓶颈在哪里”。
   - 以 trace 和性能计数器为输入，做 top-down 分析。
   - 输出结构化指标和可读报告，而不是只看 `rdcycle` 或日志片段。

---

## 2. Config 机制重构

本章主要推进 `CONFIG` 抽象：把“可参数化 CUTE”固定成一个可命名、可生成 header、可校验 capability 的具体硬件实体。它的阶段性目标是让 `SOFTWARE` 不再猜硬件参数，而是从 `CONFIG` 派生自己的合法边界。

### 2.1 两类 Config 必须分清

这里建议明确区分：

| 类型 | 说明 | 现状 | 重构目标 |
|---|---|---|---|
| Hardware Config | Chipyard/Chisel 的硬件配置，如 `chipyard.CUTE2TopsSCP64Config` | 已存在 | 继续作为硬件参数唯一真相源 |
| Test Config | 测试任务、输入规模、数据类型、golden、trace、perf policy | 目前分散在 C 文件名、Makefile、脚本里 | 新增 YAML/TOML manifest |

不要把所有东西都塞进 Chisel Config。硬件结构参数属于 Hardware Config；测试矩阵、模型层、DRAM 带宽、是否采 trace、比较容差属于 Test Config。

### 2.2 Hardware Config 规划

保留现有生成链路：

```text
Chipyard Config class
  -> HeaderGenerator.extractParamsFromConfig
  -> cutetest/include/*.generated
```

需要增强生成产物：

- `datatype.h.generated`
  - 保留数据类型 ID、位宽、名称。
  - 增加 A/B/C/D element byte width 查询，避免测试端手算 stride。

- `validation.h.generated`
  - 保留 `CUTE_TENSOR_M/N/K`、`CUTE_MATRIX_M/N`、MMU、FPE、buffer 等。
  - 增加 config fingerprint，例如 `CUTE_CONFIG_FINGERPRINT`，用于 run artifact 检查“binary 是否和当前 header/config 匹配”。

- `instruction.h.generated`
  - 作为上层 C API 的唯一 funct 来源。
  - 手写 helper 只保留底层 inline asm 和少量兼容 wrapper，不再维护 funct 号。

- 新增 `cute_config.h.generated`
  - `CUTE_HW_CONFIG_NAME`
  - `CUTE_HW_CONFIG_SHORT_NAME`
  - `CUTE_HEADER_GENERATED_AT`
  - `CUTE_HEADER_GENERATOR_VERSION`
  - `CUTE_PARAM_*` 摘要

- 新增 `cute_layout.h.generated`
  - tile 相关派生常量。
  - 标准 stride/layout helper。
  - tensor 对齐、block size、scale layout 的查询宏。

### 2.3 Test Manifest 规划

建议在 `configs/` 或 `cutetest/configs/` 下建立声明式配置：

```text
configs/
├── hardware/
│   ├── cute2tops_scp64.yaml
│   ├── cute4tops_scp128.yaml
│   └── cute4tops_shuttle512.yaml
├── tests/
│   ├── matmul_i8_basic.yaml
│   ├── datatype_mxfp8_sweep.yaml
│   ├── resnet50_conv_layers.yaml
│   └── llama3_1b_layers.yaml
├── suites/
│   ├── smoke.yaml
│   ├── nightly.yaml
│   ├── correctness_full.yaml
│   └── perf_sweep.yaml
└── schemas/
    ├── hardware.schema.json
    ├── test.schema.json
    └── suite.schema.json
```

一个测试 config 的建议结构：

```yaml
version: 1
name: matmul_i8_128
kind: op_test
tags: [smoke, correctness, matmul, int8]

hardware:
  chipyard_config: chipyard.CUTE2TopsSCP64Config
  generated_headers: cutetest/include
  simulator: auto
  dramsim:
    enabled: true
    preset: dramsim2_ini_32GB_per_s

build:
  source: cutetest/templates/matmul.c.j2
  output: build/cutetests/matmul_i8_128/matmul_i8_128.riscv
  cflags: [-O3]
  headers:
    generated: true
    data: auto

op:
  type: matmul
  dtype: CUTEDataTypeI8I8I32
  M: 128
  N: 128
  K: 128
  bias: zero
  transpose: false
  layout:
    A: row_major
    B: row_major
    D: row_major

golden:
  source: cpu_reference
  compare:
    mode: exact
    max_mismatch: 0

trace:
  enabled: true
  level: store
  events: [TASK_BEGIN, TASK_END, D_STORE]

perf:
  enabled: true
  metrics: [total_cycles, tops, compute_util, bandwidth, stall_breakdown]
  thresholds:
    max_cycles: null
```

### 2.4 Suite Manifest 规划

suite 不应该复制测试细节，只负责组合、参数 sweep、并发和报告：

```yaml
version: 1
name: perf_sweep_gemm_k
description: Sweep GEMM K dimension under multiple DRAM bandwidth presets.

matrix:
  hardware.chipyard_config:
    - chipyard.CUTE2TopsSCP64Config
    - chipyard.CUTE4TopsSCP128Config
  hardware.dramsim.preset:
    - dramsim2_ini_16GB_per_s
    - dramsim2_ini_32GB_per_s
    - dramsim2_ini_64GB_per_s
  op.K:
    - 512
    - 1024
    - 2048
    - 4096

base_test: configs/tests/matmul_i8_template.yaml
report:
  compare_by: [hardware.chipyard_config, hardware.dramsim.preset, op.K]
  output: reports/perf_sweep_gemm_k
```

### 2.5 Config 校验原则

每次 run 前必须校验：

- `chipyard_config` 是否能被 `HeaderGenerator` 加载。
- manifest 中的 `M/N/K/dtype/layout` 是否能被当前 `validation.h.generated` 支持。
- binary 编译时使用的 header fingerprint 是否等于 run 时硬件 config fingerprint。
- trace event level 是否被当前 RTL trace 开关支持。
- golden compare mode 是否适配 dtype，比如整数 exact，浮点 tolerance。

---

## 3. Runner 与 Artifact 系统

本章推进三大对象的第一次联合：把 `CONFIG + SOFTWARE + Inputs + TracePolicy` 编排成一次可复现 run，并把该 run 的所有证据保存成 artifact。Runner 不应该吞掉对象边界；它只负责把对象组合、执行、归档。

### 3.1 统一 CLI

建议新增 Python CLI，先放在 `tools/cutecli/` 或 `scripts/cute.py`，成熟后再包成命令：

```text
cute config generate --hw chipyard.CUTE2TopsSCP64Config
cute test build configs/tests/matmul_i8_128.yaml
cute test run configs/tests/matmul_i8_128.yaml
cute suite run configs/suites/smoke.yaml
cute verify artifacts/<run-id>
cute perf artifacts/<run-id>
cute report open artifacts/<run-id>
```

第一阶段可以只实现：

```text
scripts/cute-run.py --config configs/tests/matmul_i8_128.yaml
scripts/cute-verify.py --artifact build/cute-runs/<run-id>
scripts/cute-perf.py --artifact build/cute-runs/<run-id>
```

### 3.2 Run Artifact 目录规范

每次运行生成独立目录，避免覆盖日志：

```text
build/cute-runs/
└── 20260428-153012-matmul_i8_128-cute2tops_scp64/
    ├── manifest.resolved.yaml
    ├── hw_config.snapshot.json
    ├── headers/
    │   ├── datatype.h.generated
    │   ├── validation.h.generated
    │   └── instruction.h.generated
    ├── build/
    │   ├── test.c
    │   ├── test.riscv
    │   └── test.dump
    ├── run/
    │   ├── simulator.cmd.txt
    │   ├── uart.log
    │   ├── debug.out
    │   └── raw.log
    ├── trace/
    │   ├── cute.trace.jsonl
    │   ├── cute.trace.raw
    │   └── cute.trace.index.json
    ├── verify/
    │   ├── golden.npy
    │   ├── actual.npy
    │   ├── mismatch.csv
    │   └── verify.json
    ├── perf/
    │   ├── perf.json
    │   ├── topdown.md
    │   └── timeline.csv
    └── report.md
```

### 3.3 Runner 状态机

每个 test job 按如下状态推进：

```text
RESOLVE_CONFIG
  -> GENERATE_HEADERS
  -> BUILD_TEST
  -> BUILD_OR_SELECT_SIMULATOR
  -> RUN_SIMULATOR
  -> EXTRACT_TRACE
  -> VERIFY
  -> PERF_ANALYZE
  -> REPORT
```

任何阶段失败都要输出机器可读状态：

```json
{
  "status": "failed",
  "stage": "VERIFY",
  "reason": "mismatch",
  "summary": {
    "mismatch": 12,
    "first_mismatch": {"row": 0, "col": 7, "actual": 16, "expected": 15}
  }
}
```

### 3.4 与现有脚本兼容

短期不要删除现有脚本，而是让新 CLI 调用它们：

- `scripts/generate-headers.sh`
- `scripts/build-test.sh` 中的 Makefile 逻辑可以逐步拆分。
- `scripts/run-simulator-test.sh`
- `scripts/build-simulator.sh`
- `scripts/build-verilog.sh`

中期再把硬编码批量 build 改成 manifest 驱动。

---

## 4. Trace Layer 规划

本章主要推进 `TRACE` 抽象：定义“事实记录”的格式、事件、parser、index 与导出方式。它的目标不是多打印日志，而是让 `SOFTWARE on CONFIG` 的实际行为能被 verify 和 profile 共同复用。

### 4.1 Trace 设计原则

trace 要服务两个目标：

1. **Correctness reconstruction**
   - 能从 trace 中复原关键输出数据或至少定位输出写回。
   - 能把每个 D store 映射回 task/tile/tensor 坐标。

2. **Performance attribution**
   - 能把总周期拆到 task、stage、module、tile、stall 原因。
   - 能关联 memory request/response、compute start/end、store start/end。

因此 trace 不能只是字符串 printf。建议使用“人可读 + 机器可解析”的 key-value 格式。

### 4.2 推荐 Trace 格式

原始 RTL printf：

```text
[CUTE_TRACE cycle=12345 module=CML inst=0 event=D_STORE task=7 tile_m=1 tile_n=2 addr=0x80004000 bytes=64 data=0x...]
```

解析后 JSONL：

```json
{"cycle":12345,"module":"CML","inst":0,"event":"D_STORE","task":7,"tile_m":1,"tile_n":2,"addr":"0x80004000","bytes":64,"data":"0x..."}
```

### 4.3 Event Taxonomy

建议先定义最小但足够有用的事件集合：

| 层级 | Event | 说明 |
|---|---|---|
| Task | `TASK_BEGIN` | 宏任务开始，记录 M/N/K/dtype/bias/layout |
| Task | `TASK_END` | 宏任务结束，记录总周期和状态 |
| Inst | `INST_DECODE` | RoCC/CUTE 指令被解析 |
| Inst | `INST_ISSUE` | 指令进入内部队列或 microtask |
| Inst | `INST_DONE` | 指令完成 |
| Tile | `TILE_BEGIN` | tile 级计算开始 |
| Tile | `TILE_END` | tile 级计算结束 |
| Load | `A_LOAD_BEGIN` / `A_LOAD_END` | A tensor load |
| Load | `B_LOAD_BEGIN` / `B_LOAD_END` | B tensor load |
| Load | `C_LOAD_BEGIN` / `C_LOAD_END` | C/bias load |
| Compute | `COMPUTE_BEGIN` / `COMPUTE_END` | TE/PE 计算阶段 |
| Store | `D_STORE_BEGIN` / `D_STORE_DATA` / `D_STORE_END` | 输出写回 |
| Memory | `MEM_REQ` / `MEM_RSP` | MMU/TileLink/DRAM 事务 |
| Stall | `STALL_BEGIN` / `STALL_END` | 显式 stall 原因 |
| Counter | `COUNTER_SNAPSHOT` | 计数器快照 |

### 4.4 必须带的公共字段

所有事件必须尽量带：

- `cycle`
- `module`
- `event`
- `task_id`
- `config_id` 或 `run_id`
- `core_id`，如果多核/多 RoCC
- `cute_id`，如果多个 CUTE 实例

与 tensor 相关的事件带：

- `tensor`: A/B/C/D/scaleA/scaleB
- `tile_m/tile_n/tile_k`
- `global_m/global_n/global_k`，如果能算出全局坐标
- `addr`
- `bytes`
- `dtype`
- `layout`

与性能相关的事件带：

- `stage`
- `reason`
- `queue_depth`
- `valid/ready`
- `req_id/source/sink`

### 4.5 RTL 插桩位置

第一阶段建议只插关键路径，避免一下子污染所有模块：

| 模块 | 第一阶段事件 |
|---|---|
| `CUTE2YGJK` / top wrapper | `TASK_BEGIN`、`TASK_END`、query counter |
| `TaskController` | `INST_DECODE`、`INST_ISSUE`、`INST_DONE` |
| `MatrixTE` | `TILE_BEGIN`、`COMPUTE_BEGIN`、`COMPUTE_END`、`TILE_END` |
| `AMemoryLoader` / `BMemoryLoader` / `CMemoryLoader` | load/store begin/end、`D_STORE_DATA` |
| `LocalMMU` | `MEM_REQ`、`MEM_RSP` |

插桩需要受参数控制：

- `TraceDisable`: 默认关闭。
- `TraceLevelBasic`: task/inst/counter。
- `TraceLevelPerf`: task/stage/tile/memory。
- `TraceLevelVerify`: 包含 D store 数据。
- `TraceLevelDebug`: 更细 valid/ready 和内部状态。

### 4.6 Trace Parser

新增：

```text
trace/
├── format_spec.md
├── python/
│   ├── cute_trace.py
│   ├── cute_trace_index.py
│   ├── cute_trace_extract.py
│   └── cute_trace_legacy.py
└── scripts/
    ├── trace-filter.py
    ├── trace-to-jsonl.py
    └── trace-stats.py
```

parser 要支持：

- 新格式 `[CUTE_TRACE ...]`。
- 旧格式 printf 的兼容提取，例如 `CML_Store_trace.out`、`vpu_Store_trace.out`。
- 大日志流式解析，避免一次性读入超大 log。
- 输出 JSONL 和索引。

---

## 5. Verify Line 规划

本章推进 `SOFTWARE + TRACE` 的联合：`SOFTWARE` 给出语义和 golden policy，`TRACE` 给出实际执行结果，verify 负责把两者对齐并判断 correctness。`CONFIG` 在这里提供 dtype、layout、tile、stride、capability 等解释上下文。

### 5.1 Verify 的职责

verify 不负责“怎么编译/怎么跑”，只负责：

- 读 manifest 和 artifact。
- 生成或加载 golden。
- 从 trace/log/memory dump 中提取 actual。
- 做数值比较。
- 输出结构化结果。

### 5.2 Verify 目录结构

```text
verify/
├── README.md
├── python/
│   ├── cute_verify_config.py
│   ├── cute_golden.py
│   ├── cute_compare.py
│   ├── cute_reconstruct.py
│   ├── cute_report.py
│   └── ops/
│       ├── matmul.py
│       ├── conv.py
│       ├── blockscale.py
│       └── transformer.py
├── scripts/
│   ├── cute-verify.py
│   └── cute-golden.py
└── tests/
    ├── test_compare.py
    ├── test_reconstruct_d_store.py
    └── golden_samples/
```

### 5.3 Golden 来源

按优先级支持：

1. **Python/numpy reference**
   - 适合 matmul、conv、简单 dtype。
   - 快速迭代，最适合新框架。

2. **已有 C header 数据**
   - 兼容现有 `matmul_value_*.h`、`conv_*.h`。
   - 需要 parser 或模板约定，把 expected D 读出来。

3. **C CPU reference**
   - 对复杂 fused op 更贴近当前测试代码。
   - 可以编译 native host 程序生成 golden。

4. **外部模型 golden**
   - BERT/LLaMA/ResNet 的已有 Python checker 或 golden 目录。

### 5.4 Actual 重建

第一阶段用 `D_STORE_DATA` trace 重建 D：

```text
D_STORE_DATA:
  task_id
  addr
  bytes
  data
  tile_m/tile_n
  row/col optional
```

reconstruct 负责：

- 根据 manifest 中 D tensor base/stride/layout，把 addr 映射到 row/col。
- 根据 dtype 解码 bytes。
- 处理 partial store、padding、transpose。
- 输出 `actual.npy` 和可读 csv。

### 5.5 Compare 策略

| dtype | 默认比较 |
|---|---|
| int8/int32 output | exact |
| fp16/bf16/fp32 output | abs/rel tolerance |
| fp8/mxfp/nvfp4 path | reference decode 后 tolerance |
| transformer end-to-end | top-k / layer output / max error 多指标 |

compare 输出：

```json
{
  "passed": false,
  "total": 16384,
  "mismatch": 3,
  "max_abs_err": 2,
  "max_rel_err": 0.0,
  "first_mismatch": {
    "index": [0, 17],
    "actual": 42,
    "expected": 40
  }
}
```

### 5.6 Verify 分层

建议建立 4 个 verify 层级：

| 层级 | 名称 | 目标 |
|---|---|---|
| V0 | smoke verify | 能启动、能完成、无明显 fatal |
| V1 | output verify | D tensor 与 golden 比对 |
| V2 | protocol verify | trace 事件顺序、task 生命周期、memory req/rsp 匹配 |
| V3 | invariant verify | 模块级不变量：无越界、无非法 dtype、无重复完成、无漏 store |

第一阶段先做 V0/V1，后续逐步扩展 V2/V3。

---

## 6. Perf Line 规划：Trace Top-Down 性能分析

本章推进 `CONFIG + TRACE` 的联合：`TRACE` 提供 timeline 和事件事实，`CONFIG` 提供硬件结构、理论峰值、tile 规模和带宽解释上下文，perf analyzer 负责把事实转成 top-down 性能归因。

### 6.1 Top-Down 总思路

性能分析必须从“总时间去哪了”开始，而不是直接盯某个模块。

推荐四级 top-down：

```text
Level 0: Run summary
  total_cycles, total_ops, TOPS, bandwidth, pass/fail

Level 1: Task breakdown
  每个 macro task/layer/operator 的周期、占比、效率

Level 2: Stage breakdown
  config / load_A / load_B / load_C / compute / store_D / wait / stall

Level 3: Bottleneck attribution
  memory-bound / compute-bound / store-bound / front-end-bound / sync-bound

Level 4: Module and event detail
  MMU latency, queue occupancy, loader imbalance, PE utilization, DRAM bw
```

### 6.2 Perf 指标

最小指标集：

- `total_cycles`
- `effective_ops`
- `effective_tops`
- `compute_cycles`
- `load_cycles`
- `store_cycles`
- `stall_cycles`
- `compute_utilization`
- `dram_read_bytes`
- `dram_write_bytes`
- `dram_bandwidth`
- `tile_count`
- `avg_tile_cycles`
- `p50/p95 tile_cycles`

进阶指标：

- A/B/C loader overlap ratio。
- TE busy ratio。
- PE array utilization。
- MMU avg/max latency。
- request queue occupancy。
- D store drain latency。
- DRAM bandwidth saturation。
- fuse vs nofuse overhead。
- TCM vs notcm memory pressure。

### 6.3 Stage 归因规则

perf analyzer 不能只依赖事件名，需要一套清晰规则：

- `TASK_BEGIN -> TASK_END` 是总 task window。
- `COMPUTE_BEGIN -> COMPUTE_END` 是 compute busy。
- `A/B/C_LOAD_BEGIN -> *_END` 是 load window。
- `D_STORE_BEGIN -> D_STORE_END` 是 store window。
- 多个 window 重叠时：
  - 报告 both raw duration 和 critical path duration。
  - raw duration 用于模块繁忙度。
  - critical path 用于总周期归因。
- 没有显式 stage event 时，使用 counter snapshot 或 legacy printf fallback。

### 6.4 Perf 报告格式

每次 run 生成：

- `perf/perf.json`: 机器可读。
- `perf/topdown.md`: 人可读。
- `perf/timeline.csv`: 可画图。
- `perf/timeline.html`: 后续可选。

`topdown.md` 示例结构：

```text
# Perf Report: matmul_i8_128

## Summary
- total_cycles: 123456
- effective_tops: 1.83
- compute_util: 72.4%
- bottleneck: memory_load_B

## Task Breakdown
...

## Stage Breakdown
...

## Bottleneck Evidence
...

## Suggestions
...
```

### 6.5 性能回归

suite 支持 perf threshold：

```yaml
perf:
  thresholds:
    total_cycles:
      max_regression_pct: 5
      baseline: baselines/matmul_i8_128.cute2tops.json
    compute_util:
      min: 0.65
```

如果性能变差：

- correctness 仍可 PASS。
- perf status 标记为 `REGRESSED`。
- report 中列出哪个指标越界。

---

## 7. Test Line 规划：CONFIG 驱动的软件测试流程

本章主要推进 `SOFTWARE` 抽象：把 C 测试从散落文件升级为可由 `CONFIG` 驱动的 runtime、算子、NN layer、融合算子与 golden 生成体系。它的目标是让“能生成什么软件、能跑什么测试、golden 应该是什么”都受 `CONFIG` 约束。

### 7.1 测试生成方式

现有大量 `.c` 文件可以保留，但新测试建议走模板化：

```text
cutetest/
├── include/
│   ├── cute_runtime.h
│   ├── cute_tensor.h
│   ├── cute_ops.h
│   ├── cute_perf.h
│   └── *.generated
├── templates/
│   ├── matmul.c.j2
│   ├── conv.c.j2
│   ├── datatype.c.j2
│   └── model_layer.c.j2
├── generated/
│   └── <test-name>/test.c
├── legacy/
│   └── optional wrappers to existing tests
└── configs/
```

第一阶段不强行迁移所有旧测试，只挑 3 个代表：

- GEMM matmul correctness。
- datatype mxfp/fp8 correctness。
- LLaMA/ResNet 单层性能。

### 7.2 C Runtime API

新增轻量 C runtime，封装 generated instruction：

```c
typedef struct {
    void *data;
    uint64_t rows;
    uint64_t cols;
    uint64_t stride_bytes;
    uint64_t dtype;
    uint64_t layout;
} cute_tensor_t;

typedef struct {
    cute_tensor_t A;
    cute_tensor_t B;
    cute_tensor_t C;
    cute_tensor_t D;
    uint64_t M;
    uint64_t N;
    uint64_t K;
    uint64_t bias_mode;
    uint64_t transpose;
} cute_matmul_desc_t;

int cute_matmul_submit(const cute_matmul_desc_t *desc);
int cute_wait_done(uint64_t timeout_cycles);
void cute_perf_snapshot(cute_perf_t *perf);
```

原则：

- 上层测试不再直接拼 funct。
- 上层测试尽量不手算 cfgData bitfield。
- 所有 bitfield assembly 来自 `instruction.h.generated`。
- runtime 只做软件描述到 CUTE 指令序列的稳定映射。

### 7.3 Build 流程

新 build 流程：

```text
resolve manifest
  -> generate headers for hardware config
  -> render test.c from template or use existing source
  -> compile test.riscv
  -> dump symbols/metadata
  -> copy all inputs into artifact
```

### 7.4 Run 流程

新 run 流程：

```text
select simulator by hardware config
  -> if missing, build simulator
  -> run with DRAMSim preset and max-cycles
  -> capture stdout/stderr/UART/debug log
  -> extract trace
  -> generate artifact status
```

### 7.5 Legacy 测试迁移

迁移不要一口吃掉所有文件，按价值排序：

1. **Smoke**
   - 一个最小 matmul。
   - 一个 dtype。
   - 一个 transformer/resnet layer。

2. **GEMM Sweep**
   - 把 `gemm_test` 中 K sweep 收敛为 manifest matrix。
   - 保留已有 `.c`，先由 manifest 指向 source。

3. **Datatype Sweep**
   - 统一 fp8/mxfp/nvfp4 的 golden 和 compare。

4. **Model Layer**
   - BERT/LLaMA/ResNet 的 notcm/nofuse/fuse 变体转成 tags 和 manifest matrix。

5. **旧脚本清理**
   - 当新 runner 覆盖 smoke/nightly/perf 后，旧脚本降级为兼容入口。

---

## 8. 目录与模块建议

这一节的核心不是“必须马上创建所有目录”，而是先建立边界感：哪些目录是**源输入**，哪些是**生成输入**，哪些是**运行产物**，哪些是**分析工具**。建议用下面的组织方式学习和推演。

从三大对象看，本章是在给抽象找物理落点：`configs/` 承载 `CONFIG` 与 `SOFTWARE manifest`，`cutetest/` 承载 `SOFTWARE` 的 C runtime 和测试源码，`trace/` 承载 `TRACE`，`verify/` 与 `perf/` 承载对象联合后的分析逻辑，`build/cute-runs/` 承载三者组合产生的事实快照。

### 8.1 总体目标结构

推荐目标结构如下，展开到可以指导实现的层级：

```text
CUTE/
├── configs/
│   ├── hardware/                       # 硬件配置别名与元信息，不替代 Chipyard Config
│   │   ├── cute2tops_scp64.yaml
│   │   ├── cute4tops_scp128.yaml
│   │   └── cute4tops_shuttle512.yaml
│   ├── tests/                          # 单个 test/job 的声明式描述
│   │   ├── smoke/
│   │   │   ├── matmul_i8_128.yaml
│   │   │   ├── datatype_mxfp8_smoke.yaml
│   │   │   └── llama_layer_smoke.yaml
│   │   ├── gemm/
│   │   │   ├── matmul_i8_template.yaml
│   │   │   ├── matmul_k_sweep.yaml
│   │   │   └── matmul_multi_config.yaml
│   │   ├── datatype/
│   │   │   ├── fp8e4m3.yaml
│   │   │   ├── mxfp8e4m3.yaml
│   │   │   ├── nvfp4.yaml
│   │   │   └── mxfp4.yaml
│   │   ├── model/
│   │   │   ├── resnet50_conv_layers.yaml
│   │   │   ├── bert_layers.yaml
│   │   │   └── llama3_1b_layers.yaml
│   │   └── legacy/                      # 指向现有 .c/.riscv 的兼容 manifest
│   │       ├── existing_gemm_cases.yaml
│   │       └── existing_transformer_cases.yaml
│   ├── suites/                         # 多个 test 的组合、矩阵展开、回归集
│   │   ├── smoke.yaml
│   │   ├── correctness_full.yaml
│   │   ├── perf_sweep.yaml
│   │   ├── nightly.yaml
│   │   └── ci_fast.yaml
│   └── schemas/                        # manifest schema 与例子
│       ├── hardware.schema.json
│       ├── test.schema.json
│       ├── suite.schema.json
│       └── examples/
│           ├── minimal_matmul.yaml
│           └── perf_sweep.yaml
├── cutetest/
│   ├── include/                        # C 端公共 runtime 与 generated headers
│   │   ├── cute.h
│   │   ├── cute_runtime.h
│   │   ├── cute_tensor.h
│   │   ├── cute_ops.h
│   │   ├── cute_perf.h
│   │   ├── ygjk.h
│   │   ├── marcohelper.h
│   │   ├── datatype.h.generated
│   │   ├── validation.h.generated
│   │   ├── instruction.h.generated
│   │   ├── cute_config.h.generated
│   │   └── cute_layout.h.generated
│   ├── runtime/                        # 若 runtime 变复杂，可从 include 拆出实现
│   │   ├── cute_runtime.c
│   │   ├── cute_ops_matmul.c
│   │   ├── cute_ops_conv.c
│   │   ├── cute_perf.c
│   │   └── Makefile
│   ├── templates/                      # 新测试优先从模板生成
│   │   ├── common/
│   │   │   ├── test_main.c.j2
│   │   │   ├── data_section.h.j2
│   │   │   └── perf_print.c.j2
│   │   ├── matmul.c.j2
│   │   ├── conv.c.j2
│   │   ├── datatype.c.j2
│   │   └── model_layer.c.j2
│   ├── generated/                      # manifest 渲染出来的 C 测试源码，可清理重建
│   │   └── <test-name>/
│   │       ├── test.c
│   │       ├── data.h
│   │       ├── Makefile
│   │       └── README.generated.md
│   ├── data/                           # 可复用测试数据，不放 run artifact
│   │   ├── gemm/
│   │   ├── conv/
│   │   ├── datatype/
│   │   └── model/
│   ├── legacy/                         # 旧测试的薄包装和迁移记录
│   │   ├── README.md
│   │   ├── wrappers/
│   │   └── migration_map.yaml
│   ├── gemm_test/                      # 现有目录保留，逐步被 manifest 纳管
│   ├── datatype_mm_test/
│   ├── resnet50_test/
│   └── transformer_test/
├── trace/
│   ├── format_spec.md                  # trace event 与字段规范
│   ├── events.md                       # event taxonomy，人读版
│   ├── examples/
│   │   ├── cute.trace.raw
│   │   ├── cute.trace.jsonl
│   │   └── legacy_cml_store.out
│   ├── python/
│   │   ├── cute_trace.py               # parser 与 TraceEvent dataclass
│   │   ├── cute_trace_index.py         # task/tile/memory 索引
│   │   ├── cute_trace_extract.py       # 从 raw log 提取 trace
│   │   ├── cute_trace_legacy.py        # 兼容旧 printf / CML_Store_trace
│   │   ├── cute_trace_schema.py        # 字段校验
│   │   └── cute_trace_viz.py           # timeline 可视化，后续可选
│   ├── scripts/
│   │   ├── trace-to-jsonl.py
│   │   ├── trace-filter.py
│   │   ├── trace-stats.py
│   │   └── trace-timeline.py
│   └── tests/
│       ├── test_parser.py
│       ├── test_legacy_parser.py
│       └── samples/
├── verify/
│   ├── README.md
│   ├── python/
│   │   ├── cute_verify_config.py       # 读取 manifest 中的 golden/compare 配置
│   │   ├── cute_golden.py              # golden 统一入口
│   │   ├── cute_reconstruct.py         # trace -> actual tensor
│   │   ├── cute_compare.py             # exact/tolerance/top-k 等比较
│   │   ├── cute_report.py              # verify.json / mismatch.csv / markdown
│   │   └── ops/
│   │       ├── matmul.py
│   │       ├── conv.py
│   │       ├── blockscale.py
│   │       ├── datatype.py
│   │       ├── resnet50.py
│   │       ├── bert.py
│   │       └── llama.py
│   ├── scripts/
│   │   ├── cute-verify.py
│   │   ├── cute-golden.py
│   │   └── cute-reconstruct.py
│   └── tests/
│       ├── test_compare_exact.py
│       ├── test_compare_tolerance.py
│       ├── test_reconstruct_d_store.py
│       └── golden_samples/
├── perf/
│   ├── README.md
│   ├── metrics.md                      # 指标定义，避免报告口径漂移
│   ├── python/
│   │   ├── cute_perf_analyzer.py       # top-down 主入口
│   │   ├── cute_stage_model.py         # stage overlap/critical path 规则
│   │   ├── cute_metrics.py             # TOPS/bw/util/stall 等计算
│   │   ├── cute_bottleneck.py          # bottleneck 归因
│   │   ├── cute_perf_report.py         # perf.json/topdown.md
│   │   └── cute_baseline.py            # regression baseline
│   ├── scripts/
│   │   ├── cute-perf.py
│   │   ├── cute-perf-compare.py
│   │   └── cute-perf-baseline.py
│   ├── baselines/
│   │   ├── gemm/
│   │   ├── datatype/
│   │   └── model/
│   └── tests/
│       ├── test_stage_model.py
│       ├── test_metrics.py
│       └── samples/
├── tools/
│   └── cutecli/                        # 统一 CLI，编排 config/build/run/verify/perf
│       ├── pyproject.toml
│       ├── README.md
│       ├── cutecli/
│       │   ├── __init__.py
│       │   ├── main.py                 # argparse/click/typer 入口
│       │   ├── config.py               # manifest load/resolve/validate
│       │   ├── suite.py                # suite matrix expansion
│       │   ├── artifact.py             # run-id 与 artifact 目录
│       │   ├── headergen.py            # 调用 HeaderGenerator/generate-headers.sh
│       │   ├── build.py                # render template + compile C test
│       │   ├── simulator.py            # simulator discovery/build/select
│       │   ├── run.py                  # verilator run command
│       │   ├── trace.py                # 调 trace parser
│       │   ├── verify.py               # 调 verify line
│       │   ├── perf.py                 # 调 perf line
│       │   ├── report.py               # 汇总 report.md
│       │   └── util/
│       │       ├── paths.py
│       │       ├── subprocess.py
│       │       └── logging.py
│       └── tests/
├── build/
│   ├── cutetests/                      # 编译中间产物，可删除重建
│   │   └── <test-name>/
│   │       ├── test.c
│   │       ├── test.riscv
│   │       ├── test.dump
│   │       └── compile.log
│   ├── cute-runs/                      # 每次运行的不可变 artifact
│   │   └── <timestamp>-<test>-<hw>/
│   │       ├── manifest.resolved.yaml
│   │       ├── hw_config.snapshot.json
│   │       ├── headers/
│   │       ├── build/
│   │       ├── run/
│   │       ├── trace/
│   │       ├── verify/
│   │       ├── perf/
│   │       ├── status.json
│   │       └── report.md
│   └── cute-reports/                   # suite 级聚合报告
│       └── <suite-run-id>/
│           ├── suite.resolved.yaml
│           ├── summary.csv
│           ├── summary.json
│           └── report.md
└── plans/
    ├── bigplan.gpt.md
    ├── phase0_manifest_schema.md
    ├── phase1_min_loop.md
    └── decisions/
        ├── 0001-manifest-format.md
        ├── 0002-trace-format.md
        └── 0003-artifact-layout.md
```

### 8.2 源文件、生成文件、运行产物的边界

建议强制区分三类文件：

| 类型 | 目录 | 是否提交 | 说明 |
|---|---|---|---|
| 人维护源输入 | `configs/`、`cutetest/templates/`、`verify/python/`、`perf/python/`、`trace/python/` | 是 | 这是框架本体 |
| 可重建生成输入 | `cutetest/generated/`、`cutetest/include/*.generated` | 视情况 | 小规模可提交，频繁变化时只提交样例 |
| 运行产物 | `build/cutetests/`、`build/cute-runs/`、`build/cute-reports/` | 否 | 必须可由 manifest 复现 |

这个边界很重要：如果一个文件是“实验结果”，它应该进入 `build/cute-runs/<run-id>/`；如果一个文件是“实验定义”，它应该进入 `configs/`。

### 8.3 configs 的组织原则

`configs/` 只描述“要跑什么”，不放大数据、不放 Python 逻辑、不放编译产物。

- `hardware/` 只是给 Chipyard Config 起别名、记录 simulator policy、默认 DRAMSim preset、默认 trace capability。
- `tests/` 描述单个 job，可被 suite 引用。
- `suites/` 描述多个 job 的组合和 matrix sweep。
- `schemas/` 保证 manifest 可校验，避免字段名随手发散。

### 8.4 cutetest 的组织原则

`cutetest/` 是 C 侧测试和 runtime 的地盘。

- `include/` 放 C API、generated header、底层 inline asm。
- `runtime/` 放复杂的 C 实现；如果 API 都是 header-only，可暂时不建。
- `templates/` 放新增测试的模板。
- `generated/` 放由 manifest 渲染出的源码，尽量可删除重建。
- 旧的 `gemm_test/`、`datatype_mm_test/`、`resnet50_test/`、`transformer_test/` 先保留，不要急着搬空。

### 8.5 trace / verify / perf 的组织原则

三者建议拆开，而不是全塞进一个 `scripts/`：

- `trace/` 只负责“日志如何变成结构化事件”。
- `verify/` 只负责“actual 是否等于 golden”。
- `perf/` 只负责“性能指标和瓶颈归因”。

这样后续 FPGA trace、Verilator trace、旧 printf trace 都可以先统一进入 `trace/`，然后 verify/perf 复用同一份 `cute.trace.jsonl`。

### 8.6 tools/cutecli 的组织原则

`tools/cutecli` 是编排层，不应该包含过多业务算法。

- build/run/artifact/suite 这类流程控制放在 `cutecli/`。
- trace parsing 放 `trace/python/`。
- golden/compare 放 `verify/python/`。
- metrics/topdown 放 `perf/python/`。

这样 CLI 只是把各层串起来，以后即使换 CLI 框架，也不会影响核心分析逻辑。

### 8.7 build artifact 的组织原则

`build/cute-runs/<run-id>/` 应该是一次实验的完整快照。理想情况下，把这个目录打包给别人，对方不需要猜测你当时用了哪个 manifest、哪个 header、哪个 binary、哪个日志。

一个 run artifact 至少包含：

- resolved manifest。
- generated header snapshot。
- test source/binary/dump。
- simulator command。
- raw log 和解析后的 trace。
- verify.json。
- perf.json。
- report.md。

suite artifact 则只做聚合，不复制每个 run 的大文件，只保存子 run 的路径和 summary。

---

## 9. 分阶段实施路线

本章按“三大对象的成熟度”和“对象联合的闭环程度”组织阶段：先让对象可描述，再让对象可组合，再让 trace 结构化，最后形成 suite/regression。

### Phase 0: 梳理与冻结接口

目标：先把三大对象如何被描述定死，不急着全量迁移。Phase 0 的核心是对象自洽：`CONFIG` 有 schema 和 header 规划，`SOFTWARE` 有 manifest schema，`TRACE` 有 format spec。

任务：

- 写 `configs/schemas/test.schema.json` 初版。
- 写 3 个代表性 manifest：
  - `matmul_i8_128.yaml`
  - `datatype_mxfp8_smoke.yaml`
  - `llama_layer_smoke.yaml`
- 写 `trace/format_spec.md` 初版。
- 给 `HeaderGenerator` 增加 `cute_config.h.generated` 规划，但可先不实现。
- 定义 artifact 目录规范。

验收：

- 人读 manifest 能清楚知道跑什么、怎么跑、怎么 verify、怎么 perf。
- manifest 能被 Python loader 解析和校验。

### Phase 1: 最小闭环

目标：让三大对象第一次形成最小闭环：一个 manifest 能把 `CONFIG + SOFTWARE + TracePolicy` 跑成 artifact，并完成 trace 提取、verify 和 report。

任务：

- 新增 `scripts/cute-run.py` 或 `tools/cutecli` 最小 CLI。
- 调用现有 `generate-headers.sh` 生成 headers。
- 用现有 Makefile 或简单编译模板生成一个 `.riscv`。
- 调用现有 `run-simulator-test.sh` 跑仿真。
- 从 log 中提取已有 store trace 或新增最少量 `D_STORE_DATA`。
- Python 生成 golden，重建 actual，比对输出 `verify.json`。
- 生成 `report.md`。

验收：

- `matmul_i8_128.yaml` 一条命令得到 PASS/FAIL。
- artifact 中包含 manifest snapshot、headers、binary、raw log、verify report。

### Phase 2: Trace 结构化

目标：让 `TRACE` 从兼容旧日志过渡到 RTL 结构化事件，使 verify/perf 不再依赖人工 grep。

任务：

- 在 top/task/cml/mmu/matrixTE 插入第一批 `[CUTE_TRACE ...]`。
- 增加 Chisel/Config 参数控制 trace level。
- Parser 支持 JSONL 输出。
- Perf analyzer 基于 structured trace 做 task/stage summary。

验收：

- 同一个 run 可以生成 `cute.trace.jsonl`。
- trace 中能看到 TASK、INST、COMPUTE、D_STORE、MEM 基本事件。
- verify 不再依赖人工 grep。

### Phase 3: Config-driven Test Suite

目标：扩大 `CONFIG + SOFTWARE` 的组合能力，用 suite 替代硬编码批量脚本，让多硬件配置、多 DRAM preset、多 workload 维度都能声明式展开。

任务：

- 建立 `configs/suites/smoke.yaml`、`nightly.yaml`、`perf_sweep.yaml`。
- 支持 manifest matrix expansion。
- 支持多 DRAMSim preset sweep。
- 支持多 hardware config sweep。
- 迁移 `gemm_test/multi_cute_config_test` 和 `diff_core_cute_config_test` 的核心能力。

验收：

- `smoke` suite 能在合理时间内跑完。
- perf sweep 自动生成 CSV/Markdown 汇总。
- 旧脚本中的关键实验能由 suite 表达。

### Phase 4: Perf Top-Down 完整化

目标：强化 `CONFIG + TRACE` 的 profile 联合能力，让性能报告能定位瓶颈，不只是列周期。

任务：

- 完善 stage overlap 和 critical path 归因。
- 增加 memory bandwidth、loader imbalance、compute utilization。
- 增加 fuse/nofuse/notcm 对比报告。
- 增加 baseline 和 regression 检测。

验收：

- 对 GEMM K sweep 能自动判断 memory-bound 或 compute-bound。
- 对 LLaMA/ResNet 层能指出主要耗时 stage。
- perf regression 能单独标红，不影响 correctness PASS。

### Phase 5: 全量迁移与清理

目标：让 `CONFIG + SOFTWARE + TRACE` 成为默认测试流程，旧测试通过 manifest 或 legacy wrapper 纳入统一体系。

任务：

- 逐步把 `cutetest` 中重复 `.c` 迁移到模板 + manifest。
- 手写 helper 降级为兼容层。
- 旧 compare 脚本收敛到 verify ops。
- CI/nightly 使用 suite。
- 文档更新到 `doc/design-doc/docs/software/`。

验收：

- 新增测试只需要写 manifest 或少量模板。
- 硬件 Config 改动后，header、test、verify、perf 自动一致。
- 旧测试仍可通过 legacy wrapper 运行。

---

## 10. 关键风险与处理

本章也按三大对象理解风险：有些风险来自单个对象不自洽，比如 `TRACE` 太大；有些风险来自对象联合失败，比如 `CONFIG` 和 `SOFTWARE` 不一致，或者 `SOFTWARE` golden 无法解释 `TRACE` actual。

### 10.1 Trace 数据过大

风险对象：`TRACE`。`D_STORE_DATA` 和 memory event 会让 log 巨大。

处理：

- Trace level 分级。
- Verify trace 只开 store data。
- Perf trace 可不开 data payload，只记录 bytes/addr/cycle。
- 支持按 task/layer/tile filter。
- 大文件用 streaming parser。

### 10.2 Hardware Config 与 Test Config 不一致

风险对象：`CONFIG + SOFTWARE`。用 A config 生成 header，用 B config 跑 simulator，导致 software 认为自己在适配一台硬件，实际却跑在另一台硬件上。

处理：

- generated header 加 fingerprint。
- artifact 保存 header snapshot。
- runner 在 run 前校验 chipyard config 名和 fingerprint。
- C binary 启动时打印 `CUTE_HW_CONFIG_NAME` 和 fingerprint。

### 10.3 旧测试太多，迁移成本大

风险对象：`SOFTWARE`。全量迁移会拖垮节奏，也会让 runtime、模板、legacy wrapper 同时变动，难以判断问题来自哪里。

处理：

- 先 legacy wrapper。
- 只迁移高价值代表。
- manifest 允许 `build.source` 指向已有 `.c`。
- 模板化只用于新增测试。

### 10.4 Golden 对复杂 fused op 不稳定

风险对象：`SOFTWARE + TRACE`。Transformer fused op 的 golden 与实际软件路径不完全一致，会让 verify 无法判断是软件语义不清、trace 重建错误，还是硬件真的错。

处理：

- 分层 golden：op-level exact、layer-level tolerance、end-to-end semantic。
- 保留已有 checker 作为 external golden。
- 对 fused op 先验证关键中间 tensor，再扩展全输出。

### 10.5 RTL 插桩影响性能或时序

风险对象：`CONFIG + TRACE`。printf 太多拖慢仿真，也可能污染综合路径；trace capability 必须成为 config-controlled feature，而不是无条件散落在 RTL 中。

处理：

- trace 只用于仿真 config。
- Chisel 参数控制生成/不生成 trace printf。
- 默认关闭。
- FPGA trace 另走轻量 buffer/event counter，不直接复用海量 printf。

---

## 11. 第一批建议落地文件

第一批文件按“三大对象 + 对象联合”组织，尽量少而闭环：

```text
# CONFIG / SOFTWARE manifest
configs/tests/matmul_i8_128.yaml
configs/suites/smoke.yaml
configs/schemas/test.schema.json

# TRACE object
trace/format_spec.md
trace/python/cute_trace.py

# SOFTWARE + TRACE -> Verify
verify/python/cute_golden.py
verify/python/cute_compare.py
verify/python/cute_reconstruct.py

# Object composition / orchestration
scripts/cute-run.py
scripts/cute-verify.py
scripts/cute-perf.py
```

`TRACE` 第一批 RTL 插桩位置：

```text
src/main/scala/CUTE2YGJK.scala
src/main/scala/TaskController.scala
src/main/scala/MatrixTE.scala
src/main/scala/CMemoryLoader.scala
src/main/scala/LocalMMU.scala
```

`CONFIG -> SOFTWARE capability` 第一批 HeaderGenerator 增强：

```text
src/main/scala/util/HeaderGenerator.scala
  -> cute_config.h.generated
  -> config fingerprint
  -> more dtype byte-width helpers
```

---

## 12. 成功标准

短期成功：

- `CONFIG`：一条命令能按指定 Chipyard Config 生成 headers 和 config fingerprint。
- `SOFTWARE`：一个 manifest 能生成或选择合法 C 测试，并编译出 `.riscv`。
- `TRACE`：一次运行能产生可解析 trace 或兼容旧日志的 structured trace。
- `SOFTWARE + TRACE`：能自动从 trace 重建输出并 PASS/FAIL。
- `CONFIG + TRACE`：能自动产出基础 perf summary。

中期成功：

- `CONFIG + SOFTWARE`：smoke/nightly/perf sweep 都由 suite 驱动，支持多硬件配置和 workload matrix。
- `CONFIG + SOFTWARE + TRACE`：GEMM/datatype/model layer 三类测试进入统一 artifact/report。
- `TRACE`：trace parser 成为 verify/perf 的共同事实入口。
- `SOFTWARE + TRACE` 与 `CONFIG + TRACE`：verify/perf analyzer 可复用同一份 run artifact。

长期成功：

- `CONFIG` 成熟：新增硬件 Config 不需要手改 C 测试常量。
- `SOFTWARE` 成熟：新增软件测试主要写 manifest 或模板，而不是复制 C 文件。
- `TRACE` 成熟：trace 能覆盖 verify/profile 所需事实，且支持分级控制。
- `SOFTWARE + TRACE` 成熟：正确性验证能定位到 task/tile/store/mismatch，而不是靠人眼看日志。
- `CONFIG + TRACE` 成熟：性能分析能解释瓶颈来源，而不是只记录最终周期。
- `CONFIG + SOFTWARE + TRACE` 闭环成熟：回归测试能同时管理 correctness、performance、baseline 和 artifact。

---

## 13. 下一步细化建议

建议按下面顺序继续讨论和细化：

1. **先定 CONFIG + SOFTWARE manifest schema**
   - `hardware/build/op/golden/trace/perf` 字段是否够用。
   - 是否使用 YAML，还是 TOML/JSON。
   - 哪些字段属于硬件实体，哪些字段属于软件 workload，哪些字段只是 run policy。

2. **再定 TRACE event schema**
   - 第一批事件名字和字段。
   - 哪些事件必须在 RTL 里加，哪些可以从现有日志推导。
   - 哪些字段服务 verify，哪些字段服务 profile。

3. **然后做三对象最小闭环**
   - 选一个最小 matmul 测试作为样板。
   - 实现 `CONFIG + SOFTWARE + TracePolicy -> artifact -> verify/perf` 的最小版本。

4. **最后迁移 SOFTWARE legacy**
   - 不急着重写所有 `.c`。
   - 先让旧测试能被 manifest 纳管，再逐步模板化。
