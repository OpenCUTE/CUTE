# 运行程序与结果

普通裸机仿真使用 `cute-run.py --hwconfig ... --test program.riscv`；现有 SDK suite
使用 `cute-test.py --suite cute-sdk/tests/<suite>.yaml`。这些入口保留既有
case/golden 工作流。系统级验证使用 `cute-system.py`，同时执行 QEMU 和 RTL 并
检查事务完整性，两种 PASS 不代表相同验证覆盖。

## 系统级运行

先按 [构建系统](build-system.md) 生成 schema_version=2 的 build manifest。
以下命令均从 CUTE 根目录执行；时间后缀为每次运行保留独立结果，无需手改目录：

```sh
RUN_DIR="../opencute-out/runs/system-$(date +%Y%m%d-%H%M%S)"
python3 tools/runner/cute-system.py \
  --build-manifest ../opencute-out/system/build-manifest.json \
  --out "$RUN_DIR" --case-name system_int8_128
```

工具、ELF、fixture、带指纹的 simulator 目录和 DRAM 配置均由清单选取，
无需手动查找或拼接路径。保留当前终端中的 `RUN_DIR`，后面的 trace 解码和离线回放
可以直接使用。TCM 测试使用 `--case-name system_tcm`。

需要检查延迟场景时，可以另跑一组：

```sh
python3 tools/runner/cute-system.py \
  --build-manifest ../opencute-out/system/build-manifest.json \
  --case-name system_int8_128 \
  --out "../opencute-out/runs/system-delay-$(date +%Y%m%d-%H%M%S)" \
  --ack-delay 3 --marker-delay 17 --mode online --poll-seconds 1
```

输出目录必须新建，不覆盖旧结果。开发时可缩短轮询间隔；它决定发现错误的延迟，
不替代硬件同步。`--rtl-elf` 等显式产物参数保留用于有记录的故障注入。
`--ack-delay 3 --marker-delay 17` 用于测试返回延迟，默认均为零。

## 分阶段观察 {#stages}

上手实验可以使用 `--stop-after golden` 在 QEMU 输出全部经过独立 reference 校准后
结束，或者用 `--mode offline --stop-after trace` 在 RTL 正常结束、trace 保存后结束。
这两个入口只写 `stage-report.json`，分别为 `GOLDEN_READY`、`TRACE_READY`，并标记
`correctness_verified: false`；不会把中间产物写成 `report.json` 的 PASS。

trace 停止点要求 offline 模式，确保本步没有启动在线 checker。随后可用
`cute-system-replay.py` 独立验证该日志。省略 `--stop-after` 时默认完整验证，在线模式
还会核对独立离线报告。每次使用新输出目录，不在旧目录中续写；完整步骤和验收图见
[上手 demo](demo/index.md)。

## 模型阶段运行 {#model-runs}

模型构建完成后，`cute-model-run.py` 从 manifest 读取工具、ELF 和 fixture 路径：

```sh
python3 tools/runner/cute-model-run.py \
  --build-manifest ../opencute-out/models/quick/build-manifest.json \
  --out "../opencute-out/runs/models-selected-$(date +%Y%m%d-%H%M%S)" \
  --cases bert_1 llama_2 --jobs 2
```

省略 `--cases` 会运行该 profile 的全部阶段。各 case 保存独立运行包，根目录的
`summary.json` 汇总退出状态和报告。以下默认值适用于 `cute-model-run.py`：

| 参数 | 默认值 | 控制范围 |
|---|---:|---|
| `--jobs` | 4 | 同时运行的 case 数；每个 case 使用 manifest 中的 simulator |
| `--poll-seconds` | 1 | 在线检查间隔，单位为秒 |
| `--timeout` | 3600 | 单 case 的 QEMU、RTL 执行各自的墙钟时间上限，单位为秒 |
| `--max-cycles` | 100000000 | 单 case 的 RTL 仿真周期上限 |
| `--replay-timeout` | 600 | 单 case 的离线回放时间上限，单位为秒 |

直接调用 `cute-system.py` 的默认轮询间隔为 60 秒、执行超时为 600 秒；周期上限从
HWConfig 派生的平台读取，也可用 `--max-cycles` 覆盖。原始形状长测需根据运行规模
设置预算，超时不能归类为数值通过。
完整使用的命令和产物身份应随报告保存。

## 结果目录 {#results}

| 文件 | 含义 |
|---|---|
| `build-manifest.json`、`run-manifest.json` | 构建身份副本、两 ELF、profile、源码和工具/产物哈希 |
| `target/`、`requirement-check.json`、`elf-checks.json` | 生成的平台包、依赖匹配与实际 ELF 布局检查 |
| `task-manifest.json` | 任务顺序、版本、全部输出及两个 ELF 的地址 |
| `golden/` | QEMU 在对应 checkpoint 导出的输出 |
| `trace.log` | RTL 结构化事件及 host 退出 footer |
| `online-report.json`、`offline-report.json` | 同一 C++ 引擎对同一流的结论 |
| `report.json`、`rtl-result.json` | 最终结论、早停/超时/退出与运行时间 |
| `*-command.json`、`*.log` | 可重放调用和诊断 |

PASS 表示当前 case 声明的输出和协议要求都满足。FAIL 表示数据、访问或完成
顺序错误；INVALID 表示日志/描述缺失、损坏或不支持；TIMEOUT/ERROR 表示运行
未完成。失败均返回非零。不要把某个 checker 没有报错而模拟器未正常结束当作 PASS。

## 定位第一处错误

先看 `report.json`，找到任务、region、offset 和 expected/actual；再查对应
请求/ack 和 marker。确认两个 ELF 的逻辑输出描述一致、初态已知、golden 来自
当前输入与模型。缺日志/unknown 字节不能补零；错误 actual 不能用 golden 修补。

首错停止只终止本次仿真的进程组。完整 trace 可离线重放；保留缺陷用例和原始
日志，不为了 PASS 修改 golden。数值模式在用例中明确，严格位级比较失败不自动
回退到容差。

## 大日志离线回放 {#replay}

`cute-system.py` 的 `--replay-timeout` 单独控制离线分析超时，默认 600 秒。
它不改变 RTL 运行超时、同步或比较规则。早期 runner 曾固定使用 60 秒分析预算；
当前版本已将其改为可配置参数。原始模型日志应按实际规模设置预算。

RTL 已正常完成且运行包完整时，可以独立回放，无需重跑 QEMU 或 RTL。
在同一终端接着执行，`RUN_DIR` 指向上面保存的系统运行结果：

```sh
python3 tools/runner/cute-system-replay.py \
  --run "$RUN_DIR" \
  --verifier ../opencute-out/system/build/verify/cute-system-verify \
  --out "../opencute-out/replays/system-$(date +%Y%m%d-%H%M%S)" --timeout 600
```

新回放目录保留 trace、初态/golden、verifier 的哈希与报告，不覆盖原报告。
检查器仍要求成功 footer、全部任务和最终 watermark；在线运行还必须与原
在线报告完全一致。源 run 未正常退出、verifier 不匹配或回放时输入变化均报错。
该入口用于完整运行的复核/分析超时恢复；失败 trace 的协议诊断可直接使用
`tools/verify` 的 C++ CLI。
