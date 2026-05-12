# CUTE 软件测试框架 — Big Plan (2026-05 更新)

> 本文档是 `bigplan.md` 的更新版，反映 Phase 0.5 / 0.6 的实际进展，重新校准 Phase 1+ 的路线图。
> 原始 `bigplan.md` 的核心抽象（HWConfig / Test / Trace）不变，这里只更新进度和优先级。

---

## 核心抽象（不变）

```text
HWConfig -> 定义测试运行在哪个具体硬件/SoC/仿真环境上
Test     -> 定义要测试什么、支持哪些 HWConfig、代码是什么、golden 是什么
Trace    -> 定义如何观察一次运行，并用功能模型/性能模型解释它
```

```text
RunArtifact = run(Test.code, HWConfig)
ObservedTrace = Trace.filter(RunArtifact.raw_trace)
FunctionalPass = Trace.func(ObservedTrace, HWConfig, Test) == Test.golden(level)
PerformanceProfile = Trace.perf(ObservedTrace, HWConfig, Test)
```

详细抽象定义见原始 `bigplan.md`。

---

## Phase 0 进度

Phase 0 拆为 0.5 和 0.6 两个子阶段。

### Phase 0.5: Verilator Trace 与 Top-Down Status — 已完成

产物：

```text
trace/cutetrace/src/main/scala/trace/
├── CUTETraceContext.scala     # cycle + params 隐式上下文
├── CUTETraceParams.scala      # enable/mode/category 开关
├── CUTETracePrintf.scala      # compact/human 双模式 emit
└── generated/
    ├── CUTETrace.scala        # 生成：CUTETrace.TaskControllerTrace.macroInstInsert(...)
    └── CUTETraceIds.scala     # 生成：Category/Module/Task/Event id 常量
```

关键设计：

- compact 格式 `CT,1,<cycle>,<task_id>,<event_id>,<fields...>`
- human 格式 `CTH c=<cycle> task=X event=Y field=value ...`
- `CUTETraceParams.enabledCategories` 控制按 category 过滤
- Verilator printf 直接输出，无需额外 trace 基础设施

### Phase 0.6: CUTETrace Catalog 代码生成 — 大部分完成

#### 已完成

| Task | 内容 | 状态 |
|------|------|------|
| 1 | JSON Schema + catalog seed (`cute_trace.json`) | 已完成 |
| 2 | `catalog.py` loader + validator | 已完成 |
| 3 | `gen_cute_trace.py` codegen（Scala ids / API / Python catalog） | 已完成 |
| 4 | Scala runtime（Context / Params / Printf） | 已完成 |
| 5 | TaskController + AML/BML/CML/MTE 插入 trace | 已完成 |
| 6 | 解码器 / 渲染器 / JSONL | 已完成 |
| codegen 增强 | sint 用 `%d` 输出保留符号、EVENTS_BY_ID 补 method+render | 已完成 |
| sdk 文档 | parser/decoder/render/decode-cli 四份说明 | 已完成 |

Phase 0.6 Task 6 产物：

```text
trace/python/cutetrace/
├── __init__.py
├── parser.py                    # 从 Verilator 日志提取 CT 行
├── decoder.py                   # 用 catalog 解码为 typed DecodedEvent
├── render.py                    # text / jsonl 渲染
└── generated/
    └── cute_trace_catalog.py    # 生成的 catalog 索引

tools/trace/
├── gen_cute_trace.py            # catalog -> Scala/Python codegen
├── check_cute_trace.py          # catalog + filter 校验
└── decode_cute_trace.py         # 解码 CLI: parse -> decode -> render
```

验证：真实 Verilator 日志（186 条 CT 行）端到端 parse→decode→render 全部通过。

#### 待完成

| Task | 内容 | 说明 |
|------|------|------|
| 8 | 构建入口 | `tools/trace/README.md`，串联 gen / check / decode 三条命令 |

#### 推迟到 Phase 1

| Task | 内容 | 说明 |
|------|------|------|
| 7 | 过滤器检查器 | filter 的真正价值在 Phase 1 Runner，Phase 0.6 decode 已能工作，推迟到 Phase 1 补 |

---

## Phase 0.6 完成后 -> Phase 1 的衔接

Phase 0.6 完成时，CUTETrace 的 catalog-driven 工程闭环已经跑通：

```text
cute_trace.json
  -> gen_cute_trace.py -> Scala typed API + Python catalog
  -> CUTE 模块调用 CUTETrace.Task.method(...)
  -> Verilator 输出 CT compact 日志
  -> decode_cute_trace.py -> text / jsonl
  -> check_cute_trace.py --filters -> 校验 filter
```

Phase 1 不再需要重新设计 trace 基础设施。Phase 1 可以直接使用：

- `decode_cute_trace.py --mode jsonl` 生成 `events.jsonl`
- Runner 调用 `parse_file` + `Decoder` 做 inline 解析
- filter YAML 选择需要的 event 子集

### Phase 1: BaseTest -> runtime lib 最小闭环

目标：用 base test 跑通 HWConfig + Test + Trace 的最小端到端。

前置条件（Phase 0.6 需提供）：
- trace parser/decoder/render 可用
- filter 检查器可用
- Level1_Inst trace 能输出 inst/task 生命周期

任务：

| 序号 | 内容 | 说明 |
|------|------|------|
| 1.1 | 选择最小 base test（如 hello world / basic RoCC） | 复用已有 `hello.c` |
| 1.2 | Runner 脚本 `tools/runner/cute-run.py` | 编译 + 运行 + 收集日志 |
| 1.3 | Trace.func F0_event 检查器 | 验证 inst/task 事件顺序 |
| 1.4 | Run artifact 目录结构 | `build/cute-runs/<run-id>/` 保存完整快照 |
| 1.5 | `cute_runtime` lib 最小 API | init / send_macro_inst / query_busy / wait_done |

验收：
- BaseTest 编译、运行、生成 trace
- F0_event 检查器能判断 pass/fail
- artifact 完整保存 HWConfig + Test + Trace

---

## Phase 2: TensorTest -> tensor op lib

目标：在 runtime lib 上包装 Tensor Config，形成 tensor op lib。

前置条件：Phase 1 的 runtime lib 稳定。

任务：

| 序号 | 内容 | 说明 |
|------|------|------|
| 2.1 | tensor descriptor / config wrapper | `cute_tensor.h` |
| 2.2 | matmul tensor test | 复用现有 `cute_Matmul` 系列 |
| 2.3 | catalog 扩展 `cute_loadstore` 事件 | D_STORE_DATA 等 |
| 2.4 | Trace.func F1_store / F2_tensor_op | 从 trace 重建 D tensor |
| 2.5 | golden 生成 + 比对 | Python 参考实现 |

验收：
- TensorTest pass
- tensor op lib 可复用
- trace 能重建 D tensor 并与 golden 比较

---

## Phase 3+: 保持原 bigplan 路线

Phase 3 (LayerTest) / Phase 4 (FuseLayerTest) / Phase 5 (SOCOptTest) / Phase 6 (ModelTest) 的目标和任务不变，参见原始 `bigplan.md` 第 7 章。

关键依赖链：

```text
Phase 0.6 (Trace 基础设施)
  -> Phase 1 (BaseTest + runtime + F0_event)
    -> Phase 2 (TensorTest + tensor op lib + F1/F2)
      -> Phase 3 (LayerTest + layer op lib + F3)
        -> Phase 4 (FuseLayerTest + fuse op lib + F4)
          -> Phase 5 (SOCOptTest + opt op lib + perf)
            -> Phase 6 (ModelTest + 端到端)
```

---

## 当前文件布局（已落地）

```text
CUTE/
├── trace/                                # CUTETrace 核心
│   ├── catalogs/
│   │   └── cute_trace.json              # 唯一真相源
│   ├── cutetrace/src/main/scala/trace/  # Scala trace runtime
│   │   ├── CUTETraceContext.scala
│   │   ├── CUTETraceParams.scala
│   │   ├── CUTETracePrintf.scala
│   │   └── generated/                   # codegen 产物
│   │       ├── CUTETrace.scala
│   │       └── CUTETraceIds.scala
│   ├── python/cutetrace/                # Python trace 工具
│   │   ├── catalog.py                   # catalog loader + validator
│   │   ├── parser.py                    # CT 行解析器
│   │   ├── decoder.py                   # event 解码器
│   │   ├── render.py                    # text/jsonl 渲染器
│   │   └── generated/
│   │       └── cute_trace_catalog.py
│   └── generated/
│       └── cute_trace_catalog.normalized.json
│
├── tools/trace/                          # Trace 工具链
│   ├── gen_cute_trace.py                # codegen 入口
│   ├── check_cute_trace.py              # catalog + filter 检查
│   └── decode_cute_trace.py             # 解码 CLI
│
├── configs/
│   ├── schemas/                          # JSON Schema
│   │   └── cute_trace_catalog.schema.json
│   └── trace_filters/                    # 待 Task 7 创建
│
├── doc/sdk-doc/                          # SDK 文档
│   ├── cute-trace-catalog.md
│   ├── cute-trace-checker.md
│   ├── cute-trace-usage.md
│   ├── cute-trace-parser.md
│   ├── cute-trace-decoder.md
│   ├── cute-trace-render.md
│   └── cute-trace-decode-cli.md
│
├── chipyard/                             # Chipyard 子仓库
├── cute-sdk/                             # 目标板软件栈（待建设）
├── plans/                                # 设计文档
└── build/                                # 构建产物 + artifact（待建设）
```

---

## 近期优先级

```text
现在 ──────────────────────────────────────────────────────────> 未来

[Phase 0.6 收尾]    [Phase 1]              [Phase 2]
Task 7: filter      BaseTest 闭环          TensorTest + D tensor
Task 8: README      Runner 脚本            catalog 扩展
                    F0_event 检查器         golden 生成
                    runtime lib 最小 API
```

### 本周（Phase 0.6 收尾）

1. 完成 Task 7：定义 filter YAML schema，写 5 个 filter，扩展 `check_cute_trace.py`
2. 完成 Task 8：`tools/trace/README.md`，串联 gen / check / decode

### 下一周（Phase 1 启动）

3. 写 `tools/runner/cute-run.py` 最小版
4. 用现有 `hello.c` 跑通 Runner
5. 写 F0_event 检查器（基于 decoded events 验证事件顺序）
6. 定义 `build/cute-runs/<run-id>/` artifact 结构
