# 系统级验证

系统验证承担组合层的愿望：各个部件协作后，计算、数据交接和完成条件仍满足约定。
它为父目标提供限定范围内的证据，具体协作关系见 [组件承诺](modules.md#verify)，
从自然语言目标进入这条流程的例子见 [BERT 阶段实践](practice.md)。

闭环为：同源裸机程序 → QEMU ISA 模拟执行 / RTL 执行 → 成功写 ack 重建实际内存
→ 软件任务完成标记 → 比较该任务全部输出。L2/LLC 视为可信，不验证其内部状态；
软件避免同字节未完成的读写/写写冲突。允许不同 buffer 并行与只读共享。

QEMU 按指令语义执行程序，验证时不与 RTL 逐周期、逐分包比较。当前 CUTE INT8
指令实现采用确定性完成，FIFO
占用和 CLEAR 语义仍保留。独立整数/数值参考校准 QEMU；任务的中间结果是同一
软件任务版本，而不是日志结尾的最新内存。

## 同步与任务完成 {#completion}

CUTE 用指定 task finish 查询，按 FIFO issue 顺序 wait/CLEAR。旧 accelerator
busy 查询存在提前报空风险，不作为完成依据。当前 Shuttle/Saturn 的 fence
等待本核向量后端及普通/SG 访存队列，首版采用保守排空。

`cute_checkpoint()` 在前置 fence 后发 `TRACE_MARK(seq,key)`，显式消费其返回
值，再执行后置 fence。每核上下文维护 seq，参数通过 RoCC 寄存器传给 Chisel
printf，QEMU 执行同一指令导出输出。marker 不经过模拟 UART，也不要求 CPU
用普通 load 读回全部输出。

`SystemCheckpoint.returned` 位于加速器的返回握手处，可能早于 CPU 的最终
寄存器写回；SDK 的数据依赖继续等待实际结果。marker 本身不代替任务等待。

## 内存、版本和完整性

请求缓存地址/data/mask，通过 hart/engine/port/source 对应响应，成功 ack 才
更新 actual。读响应用于检查实际读值；初态来自 fixture/ELF。每任务全部输出
均有有效范围、类型/布局和新写入证据；多个输出全部检查。

端口 event_seq 检测丢记录，周期水位核对计数/outstanding。结束前
`cute_checkpoint_finish()` 留出水位周期；host footer 证明进程正常结束。
两者共同防止删掉一整对 A/D 或截断尾部仍 PASS，详见 [trace 协议](trace/protocol.md)。

## 用例边界

已验收 S1 是单核 INT8、普通向量访存、TCM smoke 和延迟/故障用例；其上已完成
BERT B1–B6、LLaMA L1–L4 的阶段验收，详见 [状态页](status.md#model-acceptance)。
每个 checkpoint 当前排空本核相关活动。并发 double-buffer 的局部等待、额外
临时工作区、标量数据写入、新模型和更多核数需新增描述和验收。

CPU/RVV 后处理可包含浮点，CUTE INT8 不代表整程序无浮点。新 CUTE 浮点模型按
后续 FPE 版本对齐；RVV 归约与近似函数的数值规则需要单独说明。
