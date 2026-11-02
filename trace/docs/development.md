# 新增事件与诊断

1. 修改 catalog，分配唯一 event ID，明确字段单位和握手含义；保持已使用 ID 稳定。
2. 扩展 schema 中确实需要的 category；运行 catalog/schema 检查。
3. 生成 Scala/Python/C++ 产物，检查 diff，禁止只手改生成 API。
4. 在实际有效握手处调用 typed API；valid 等待期间不要重复打印。
5. 重建 simulator 和 verifier，记录 catalog/源版本/hash，运行正负用例。

系统 trace 用 `+cute_sys_trace=1` 开启，不依赖打开所有调试 printf。
`+cute_store_ack_delay=N`、`+cute_marker_response_delay=N` 是验证同步的背压注入，
默认 0；它们延迟真实握手，不能仅改日志 timestamp。

## Parser 与验证器的边界

Python parser/decoder 适合格式解析、JSONL 输出和事件筛选；C++ checker 管理
pending、内存有效位、冲突、checkpoint 和终态。旧 Python memverify 可以继续
分析历史 storeData，但不能将其结果等同于 ack 完整性验收。

常见诊断：

| 现象 | 检查 |
|---|---|
| source 重复/孤立 ack | 核/port 是否遗漏、是否取错观测边界、事件是否丢失 |
| watermark next_seq 不匹配 | 是否过滤或截断了请求/响应；不能静默跳过坏行 |
| 时钟回退 | 是否混用了 reset epoch、不同模块周期或旧日志 |
| output unknown/没有新写入 | 初态、输出范围、任务版本、写 mask 和漏 ack |
| marker 时 pending 非空 | 软件是否漏 wait/fence，或指令完成语义不充分 |
| 数据错但输出“接近” | 检查明确的比较模式；bit_exact 不自动容差 |

运行 `tools/verify/test_system_verify.py --verifier PATH -v` 检查合成行为；
`tools/verify/test_recorded_trace.py` 对真实通过日志删除 ack/整对请求响应/水位/footer，
注入坏数据和错误响应，确保都被拒绝。负例也应保存命令、来源和预期结论。
