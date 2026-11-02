# 事务、任务和完整性协议

## 外层格式

```text
CT,1,<cycle_hex>,<catalog_task_id_hex>,<event_id_hex>,<fields...>
```

`catalog_task_id` 是事件所属静态类别，不是软件任务号或 TL source。
字段顺序按 catalog；uint/bool 打印十六进制，sint 的格式依各事件声明。
系统事件当前使用无符号字段，payload 按总线位序打印，host 按小端字节解释。

## 系统事件

| 事件 | 关键字段 | 产生条件 |
|---|---|---|
| `SystemMemory.request` | hart/engine/port/event_seq/source、opcode/address/lg_size/width_bytes/mask/data | 实际 `A.fire` |
| `SystemMemory.response` | 同一端口事件序列/source、opcode/size/data/denied/corrupt | 实际 `D.fire` |
| `SystemMemory.progress` | hart/engine/port、next_seq/outstanding | 每 256 周期的完整周期水位 |
| `SystemCheckpoint.mark` | hart/seq/key | TRACE_MARK `cmd.fire` |
| `SystemCheckpoint.returned` | hart/seq/key | 加速器向 CPU 返回通路的 `resp.fire` |

engine 0 是 CUTE，port 0；engine 1 是 RVV，普通 read/write 为 port 0/1，
启用的 SG 为 port 2+。在同一 client 边界配对 source；不要跨 width widget
和 source 重映射边界混用。source 可复用，未结束前再次占用必须报错。

同端口 request/response 共用 event_seq；同周期请求的序号先于响应。progress
记录包含本周期握手后的 next_seq/outstanding。仅靠请求/响应配对不能发现
整对事件同时丢失，因此 watermark 是必需的完整性证据。

## ID 与一条写事务

当前 catalog 的十进制 ID 为 request=18、response=19、mark=20、returned=21、
progress=22；在 compact 行中分别打印为 `12/13/14/15/16`（十六进制）。

写请求先记录 `(hart, engine, port, source)`、地址、mask 和 payload；该身份的
成功 D ack 到达后才应用字节掩码。后来的 source 复用属于新事务。比如一个
FP32 scale 的四字节写入也会以完整 64-byte beat 加 mask 观察，不能把其他
60 字节一起覆盖或当成新输出写入。

## Host 解释

请求入 pending，响应按 hart/engine/port/source 找回；成功写响应才提交 mask
指定字节。错误响应 FAIL，无请求/重复响应或序号缺口 INVALID。读响应核对已有
actual 内存；unknown 不等于零，golden 不能用来补写 actual。

首版选定的接口发完整单 beat；其他形状被明确拒绝。多个时钟或复位域必须先
建立映射；目前使用单时钟 profile。日志按完整周期分组，printf 行先后不等于
协议序列。同周期无法证明的同字节依赖保守拒绝。

软件每核维护 checkpoint seq/key，case 描述该任务的全部输出及版本。MARK
前必须已经等待相关 CUTE/RVV 活动，buffer 复用发生在 marker 确认后。未声明
新版本时，任务完成后的额外 store 会失败。首版使用本核排空的 checkpoint。

## 收尾

`cute_checkpoint_finish()` 用短 CSR 计时等待，让所有必选端口水位覆盖最后一次
marker 返回。host 在模拟器退出后追加 `SV_RUN_END,<exit_code>`；只有成功 footer、
全部必选 marker/返回、无 outstanding、最终序号水位和全部输出比较同时满足
才可 PASS。单纯 EOF 或 Verilog `$finish` 文本不足以替代这些条件。

目录中的 trace filter 可以用于分析，但过滤了必需请求/响应的日志不能再用于
完整系统验证。新旧 catalog 的同名事件字段变化时，保留构建/run 清单的 catalog
哈希，不能将旧日志强行按新字段解析。
