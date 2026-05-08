# Phase 0.6 Level 2/3: Store Trace → 重建内存 → Golden 比对

## 核心思路

```
C Golden 程序 (同一份输入 A/B/C)
  → 软件计算 D = A*B+C，输出 golden memory image
  → 格式: (vaddr, data) 序列

CUTE Verilator 仿真 (同一份输入 A/B/C)
  → CMLStore.storeData / VectorStore.storeData trace event
  → 每笔 store 带 vaddr + data
  → Python decoder 解码 store trace，重建 actual memory image

自动化比对
  → 两个 memory image 做 diff
  → 输出: PASS 或 (FAIL: addr=0x... golden=0x... actual=0x...)
```

只关注 **store 输出端**，不 trace load 输入端。重建内存只需要写操作的地址和数据。

## Golden 约束

Golden 程序员保证：**输出数据（D tensor 区域）在程序结束前不会被 CUTE / Vector 再次修改。** 验证只针对输出区域，不验证中间 scratchpad 状态。

## 多场景验证策略

| 场景 | 方法 | 说明 |
|---|---|---|
| **Verilator** | Store trace → Python 重建内存 → 与 golden image 全量 diff | 仿真结束后 host 侧处理，不动仿真内 CPU |
| **FPGA** | XDMA 读回 D tensor → host 侧与 golden image 全量 diff | host x86 做比较，逐地址定位错误 |

Verilator 不依赖仿真内 CPU，Python 直接从 log 重建。FPGA 通过 XDMA 读回全量数据做比较。两边都是全量比对，精确定位到地址级别。

## 当前硬件状态

- **CMLStore**: CMemoryLoader 通过 LocalMMU 写回 D tensor，`WriteRequest.fire` 时 `RequestVirtualAddr` + `RequestData` 
- **VectorStore / AfterOps**: 当前代码大部分被注释掉，暂未实现
- `outsideDataWidth` = 512 bit (64 byte) 或 256 bit (32 byte)

Level 2 先只做 CMLStore，Level 3 扩展到 VectorStore。

---

## Step 1: Catalog 新增 storeData 事件

文件：`trace/catalogs/cute_trace.json`

在 `cute_loadstore` category 下新增事件：

### 1.1 CMLStore.storeData

```json
{
  "name": "CMLStore.storeData",
  "method": "storeData",
  "id": 16,
  "task": "CMLStore",
  "category": "cute_loadstore",
  "description": "CML 向外部存储写回一笔 D tensor 数据。",
  "fields": [
    { "name": "task_count", "type": "uint", "fmt": "dec" },
    { "name": "vaddr", "type": "uint", "fmt": "hex" },
    { "name": "data", "type": "uint", "fmt": "hex" }
  ],
  "render": "task_count={task_count} vaddr=0x{vaddr:x} data=0x{data:x}"
}
```

### 1.2 预留 VectorStore.storeData

```json
{
  "name": "VectorStore.storeData",
  "method": "storeData",
  "id": 17,
  "task": "VectorStore",
  "category": "vector_loadstore",
  "description": "Vector 单元向外部存储写回一笔数据。（预留）",
  "fields": [
    { "name": "task_count", "type": "uint", "fmt": "dec" },
    { "name": "vaddr", "type": "uint", "fmt": "hex" },
    { "name": "data", "type": "uint", "fmt": "hex" }
  ],
  "render": "task_count={task_count} vaddr=0x{vaddr:x} data=0x{data:x}"
}
```

### 1.3 重新生成 Scala API

```bash
python3 tools/trace/gen_cute_trace.py \
  --catalog trace/catalogs/cute_trace.json \
  --scala-out trace/cutetrace/src/main/scala/trace/generated \
  --python-out trace/python/cutetrace/generated \
  --build-out trace/generated
```

---

## Step 2: CMemoryLoader 插入 CMLStore.storeData trace

文件：`src/main/scala/CMemoryLoader.scala`

### 2.1 插入点

**位置**: ~L839, `when(WriteRequest.fire && io.LocalMMUIO.ConherentRequsetSourceID.valid)` 内部第一行。

```scala
CUTETrace.CMLStore.storeData(
  cond = true.B,
  task_count = storeTaskCount - 1.U,
  vaddr = WriteRequest.bits.RequestVirtualAddr,
  data = WriteRequest.bits.RequestData
)
```

`CMLStore.storeData` 的 `categoryId = cute_loadstore`，当前 `enabledCategories` 只包含 `cute_task`。需要在 CML 的 traceCtx 中加入 `cute_loadstore`：

```scala
enabledCategories = Set(
  CUTETraceIds.Category.cute_task,
  CUTETraceIds.Category.cute_loadstore
)
```

### 2.2 性能考量

每笔 store 都会触发一次 printf。对于大 tensor，store 次数 = `Tensor_M * Tensor_N * D_DataType / outsideDataWidthByte`。以 (64, 64, 4byte) 为例：`64 * 64 * 4 / 64 = 256` 次 printf。Verilator 仿真可接受。

---

## Step 3: Golden 来源与分层验证

### 3.1 分层验证架构

```
NVWA (Python, 可信参考)
  → 对同一份输入 (A, B, C, M, N, K, ...) 执行矩阵乘/卷积
  → 输出 golden memory image (addr → data)
  → 唯一真相源

C 应用程序 (跑在 CPU 上，通过 rocc 指令驱动 CUTE)
  → 初始化 A/B/C tensor，配置 CUTE 参数，触发计算
  → 这是实际跑在 CPU + CUTE 硬件上的真实 workload
  → 需要先用 CUTEQEMU 验证其正确性

CUTEQEMU (CUTE 软件仿真器)
  → 跑同一份 C 应用程序，用软件模拟 CUTE 硬件行为
  → 验证 C 应用程序本身的正确性（数据排布、参数传递、指令序列）
  → 如果 CUTEQEMU 结果 != NVWA golden → C 应用程序有 bug
  → 如果 CUTEQEMU 结果 == NVWA golden → C 应用程序可信

CUTE 硬件 (Verilator / FPGA)
  → 跑同一份 C 应用程序
  → store trace 重建 / XDMA 读回 → 和 NVWA golden 比对
  → 有 CUTEQEMU 兜底，不对就是硬件 bug
```

**Mismatch 归因**：

| NVWA golden vs CUTE 硬件 | NVWA golden vs CUTEQEMU | 结论 |
|---|---|---|
| 不一致 | 一致 | CUTE 硬件 bug |
| 不一致 | 不一致 | C 应用程序有 bug（数据排布、参数、指令序列错误） |

### 3.2 Golden 数据来源：NVWA

NVWA (Python 张量计算库) 作为 golden 唯一真相源：

1. NVWA 对同一份输入 (A, B, C, M, N, K, ...) 执行矩阵乘/卷积
2. NVWA 输出 D tensor 的 golden memory image（addr → data 映射）
3. 格式与 store trace 重建的 memory image 一致，可直接 diff

### 3.3 C 应用程序

实际跑在 CPU + CUTE 硬件上的 workload 程序：
- 初始化 A/B/C tensor 数据到 memory
- 通过 CUTE 的 rocc 指令配置参数（ConfigTensorA/B/C/D, ConfigTensorDim, SendMacroInst 等）
- 触发 CUTE 执行矩阵乘/卷积
- 等待完成

这个 C 程序就是最终用户写的应用程序，同时被 CUTEQEMU 和真实硬件执行。

### 3.4 CUTEQEMU

CUTE 硬件的软件仿真器，核心功能：
- 模拟 CPU + CUTE 的 rocc 指令接口
- 用软件实现 CUTE 的分块、计算、地址生成逻辑
- 跑同一份 C 应用程序
- 输出结果和 NVWA golden 比对

CUTEQEMU 的价值：**隔离 C 应用程序的错误和 CUTE 硬件的错误**。如果 CUTEQEMU 跑通过了但硬件不通过，确认是硬件 bug，不需要怀疑 C 代码或 golden。

---

## Step 4: Python 内存重建工具

### 4.1 设计

文件：`trace/python/cutetrace/rebuilder.py`

```python
class MemoryRebuilder:
    """从 store trace event 重建内存 image"""

    def __init__(self, data_width_bytes: int = 64):
        self.data_width_bytes = data_width_bytes
        self.writes: Dict[int, bytes] = {}  # addr → data

    def apply_store(self, vaddr: int, data: int):
        """写入一笔 store"""
        self.writes[vaddr] = data.to_bytes(self.data_width_bytes, 'little')

    def to_image(self) -> List[Tuple[int, bytes]]:
        """输出排序后的 (addr, data) 序列"""
        return sorted(self.writes.items())

    def diff(self, golden: Dict[int, bytes]) -> List[str]:
        """和 golden image 做 diff"""
        errors = []
        for addr in sorted(set(self.writes) | set(golden)):
            actual = self.writes.get(addr)
            expected = golden.get(addr)
            if actual != expected:
                errors.append(
                    f"addr=0x{addr:016x} golden={expected.hex() if expected else 'MISSING'} "
                    f"actual={actual.hex() if actual else 'MISSING'}"
                )
        return errors
```

### 4.2 解码器集成

在 decoder 输出 decoded event 后，rebuilder 过滤 `CMLStore.storeData` 事件：

```python
rebuilder = MemoryRebuilder()
for event in decoder.decode(parser.parse(log_lines)):
    if event.event == "CMLStore.storeData":
        rebuilder.apply_store(
            vaddr=event.fields["vaddr"],
            data=event.fields["data"]
        )
```

### 4.3 Golden image 解析

```python
def load_golden_image(path: str) -> Dict[int, bytes]:
    """解析 C golden 程序输出的 memory image"""
    golden = {}
    with open(path) as f:
        for line in f:
            if line.startswith("ADDR"):
                addr = int(line[4:20], 16)
                data = bytes.fromhex(line[21:].strip())
                golden[addr] = data
    return golden
```

---

## Step 5: 自动化比对 Pipeline

### 5.1 端到端流程

```bash
# 1. 运行 C golden 程序
./golden_matmul --M 64 --N 64 --K 64 \
  --addr_a 0x80000000 --addr_b 0x80100000 \
  --addr_c 0x80200000 --addr_d 0x80300000 \
  --stride_a 256 --stride_b 256 --stride_c 256 --stride_d 256 \
  -o golden_image.txt

# 2. 运行 Verilator 仿真（同一份输入参数）
make verilator-run CONFIG=CuteMatmul64Config

# 3. 解码 store trace 并重建内存 + 比对
python3 -m cutetrace.verify \
  --catalog trace/catalogs/cute_trace.json \
  --log sim_output.log \
  --golden golden_image.txt \
  --store-events CMLStore.storeData

# 输出:
# STORE_COUNT: 256
# GOLDEN_COUNT: 256
# DIFF_RESULT: PASS
# 或
# DIFF_RESULT: FAIL
# MISMATCH_COUNT: 3
# addr=0x0000000080300040 golden=... actual=...
```

### 5.2 verify 命令的内部逻辑

```text
1. 解析 golden_image.txt → golden: Dict[addr, data]
2. 解析 Verilator log，过滤 CT,... 行
3. 用 catalog 解码，找出 CMLStore.storeData 事件
4. 每笔 storeData → rebuilder.apply_store(vaddr, data)
5. rebuilder.diff(golden) → errors
6. 输出结果
```

---

## Step 6: Level 3 扩展（Vector Store）

Level 3 和 Level 2 用完全相同的 pipeline，只是多一个 store source：

```python
# Level 3: 同时收集 CMLStore 和 VectorStore 的 store
for event in decoder.decode(parser.parse(log_lines)):
    if event.event in ("CMLStore.storeData", "VectorStore.storeData"):
        rebuilder.apply_store(
            vaddr=event.fields["vaddr"],
            data=event.fields["data"]
        )
```

VectorStore 的 trace 插入点和 CMLStore 同理，在 vector 单元的 WriteRequest.fire 处插入。

---

## 执行顺序

```
Step 1: 修改 catalog JSON，新增 CMLStore.storeData (id=16) 和 VectorStore.storeData (id=17)
Step 1b: 重新生成 Scala API

Step 2: CMemoryLoader 插入 CMLStore.storeData trace，扩展 enabledCategories

Step 3: 编写 C golden 程序
  3.1 支持 matmul D = A*B+C
  3.2 输出 golden memory image 格式
  3.3 编译为 RISC-V ELF（或先用 x86 验证流程）

Step 4: Python 内存重建工具
  4.1 rebuilder.py: apply_store / to_image / diff
  4.2 golden image 解析器
  4.3 集成到 decoder pipeline

Step 5: 端到端自动化验证脚本
  5.1 verify 命令行工具
  5.2 用最小 workload 跑通

Step 6: Level 3 扩展
  6.1 VectorStore.storeData trace 插入
  6.2 verify 命令支持多 store source
  6.3 Conv 扩展到 C golden
```

Step 3/4 可并行。Step 2 独立于 Step 3/4。

## 数据宽度处理

| 参数 | 默认值 | 说明 |
|---|---|---|
| `outsideDataWidth` | 512 bit | LocalMMU 单笔访存宽度 |
| `outsideDataWidthByte` | 64 byte | 同上，字节数 |
| `ResultWidth` | 32 bit | D tensor 单元素宽度 |
| 每笔 store 包含元素数 | 512/32 = 16 | `outsideDataWidth / ResultWidth` |

compact printf 中 `data` 字段用 `%x` 打印 512 bit UInt，输出最长 128 hex chars。decoder 按 catalog 中 field 的位置解析 hex 串即可。

## 浮点处理

浮点 golden 由用户提供专用的浮点参考模型生成，确保和 CUTE 硬件的浮点行为精确对齐。rebuilder 的 diff 直接做逐 bit 比较，不需要 ULP 容差逻辑。
