# Task 6: 解码器 / 渲染器 / JSONL — 详细实施计划

## 背景

Verilator 仿真输出两种 trace 行：

- **Compact**: `CT,<version>,<cycle_hex>,<task_id_hex>,<event_id_hex>,<field1_hex>,<field2_hex>,...\n`
- **Human**: `CTH c=<cycle_dec> task=<TaskName> event=<method> <field>=<value> ...\n`

Task 6 要写三个 Python 文件，把 compact 行解码成结构化 event，然后渲染为可读文本或 JSONL。

依赖：
- `cutetrace.catalog.TraceCatalog` — 已有
- `cutetrace.generated.cute_trace_catalog` — 已有
- catalog JSON — 已有

产物：

```text
trace/python/cutetrace/parser.py   — 从 Verilator 日志逐行解析 compact trace
trace/python/cutetrace/decoder.py  — 用 catalog 将原始字段解码为 typed event dict
trace/python/cutetrace/render.py   — 将 decoded event 渲染为可读文本或 JSONL
```

---

## 紧凑行格式规范

格式由 [gen_cute_trace.py](../../tools/trace/gen_cute_trace.py:285) 中的 codegen 逻辑定义：

```python
compact_format = "CT,1" + ",%x" * (3 + len(fields)) + "\n"
```

生成的 compact 行：

```text
CT,1,<cycle_hex>,<task_id_hex>,<event_id_hex>,<field_value>,<field_value>,...,<fieldN_value>\n
```

| 位置 | 含义 | 示例 |
|------|------|------|
| `[0]` | 固定前缀 `"CT"` | `CT` |
| `[1]` | 固定版本 `"1"` | `1` |
| `[2]` | cycle 计数 (hex) | `a3f` |
| `[3]` | task id (hex) | `1` |
| `[4]` | event id (hex) | `3` |
| `[5..]` | event fields，按 catalog 定义顺序 | `2`, `0`, `-3`, `1` |

字段值的 wire 格式由 field type 决定：

| field type | compact printf 格式 | wire 示例 | 解码方式 |
|------------|---------------------|-----------|----------|
| `uint` | `%x` | `a3f` | `int(s, 16)` |
| `sint` | `%d` | `-3` | `int(s)` |
| `bool` | `%x`（经过 `.asUInt`） | `1` | `int(s, 16)` |

sint 字段用 `%d` 直接输出 SInt，符号信息保留在 wire 上，无需位宽、无需符号扩展。
bool 字段先经 `.asUInt` 转为 UInt 再以 `%x` 输出。

> **对 codegen 的改动**：`_scala_compact_value` 和 compact format 拼接逻辑需要根据 field type 区分：sint 不做 `.asUInt`，用 `%d`；uint/bool 保持现有 `%x`。

---

## Step 1: `parser.py` — 紧凑行解析器

### 输入

Verilator 仿真输出的完整日志（多行文本），其中混杂 CT 行、CTH 行、以及其他 Verilator printf。

### 输出

每个 CT 行解析为一个 `RawTraceLine` dataclass：

```python
@dataclass(frozen=True)
class RawTraceLine:
    version: int
    cycle: int
    task_id: int
    event_id: int
    fields: tuple[str, ...]   # 原始字符串，由 decoder 根据 field type 解析
    raw_text: str             # 原始行文本，用于错误报告
```

### 核心逻辑

1. **`parse_line(line: str) -> RawTraceLine | None`**
   - strip 行尾 `\n`
   - 如果不以 `CT,` 开头，返回 `None`（不是 compact 行）
   - 以 `,` split
   - 校验 `parts[0] == "CT"`
   - 解析 `version = int(parts[1])`
   - 如果 `version != 1`，抛 `ParseError`（当前只支持 v1）
   - 解析 `cycle = int(parts[2], 16)`
   - 解析 `task_id = int(parts[3], 16)`
   - 解析 `event_id = int(parts[4], 16)`
   - 剩余 `parts[5:]` 保持字符串形式存入 `fields` tuple
   - 返回 `RawTraceLine`

2. **`parse_lines(lines: Iterable[str]) -> Iterator[RawTraceLine]`**
   - 对每行调用 `parse_line`
   - 返回 `None` 的跳过（非 CT 行静默忽略）
   - 解析失败的行：yield `ParseError` 异常，不中断流

3. **`parse_file(path: str | Path) -> Iterator[RawTraceLine]`**
   - 打开文件，逐行调用 `parse_lines`

### 错误处理

```python
class TraceParseError(Exception):
    line_text: str
    line_number: int
```

- hex 解析失败
- 字段数量不足（< 5 个部分）
- 版本号不为 1

### 测试要点

- 正常 CT 行 → 正确 `RawTraceLine`
- 混合日志中 CTH 行 / 空行 / 其他 printf → 返回 `None`，不报错
- 字段数量与 catalog event 不匹配 → 在 decoder 层报错，parser 不校验
- sint 字段的负数值（如 `-3`）作为字符串保留，由 decoder 解析

---

## Step 2: `decoder.py` — 事件解码器

### 输入

- `RawTraceLine`（来自 parser）
- `TraceCatalog`（来自 `cutetrace.catalog`）

### 输出

每个 `RawTraceLine` 解码为 `DecodedEvent` dataclass：

```python
@dataclass(frozen=True)
class DecodedEvent:
    cycle: int
    event_name: str          # e.g. "TaskControllerTrace.macroInstInsert"
    task_name: str           # e.g. "TaskControllerTrace"
    category_name: str       # e.g. "cute_inst"
    method: str              # e.g. "macroInstInsert"
    fields: dict[str, Any]   # {"macro_id": 5, "opcode": 18}
    raw: RawTraceLine        # 保留原始数据，用于溯源
```

### 核心逻辑

1. **`Decoder` 类**

   ```python
   class Decoder:
       def __init__(self, catalog: TraceCatalog): ...
       def decode(self, raw: RawTraceLine) -> DecodedEvent: ...
       def decode_lines(self, raw_lines: Iterable[RawTraceLine]) -> Iterator[DecodedEvent]: ...
   ```

2. **`decode(raw) -> DecodedEvent`**
   - 用 `raw.event_id` 从 catalog 查 `event_by_id`
   - 如果 event_id 不存在，抛 `DecodeError(f"unknown event_id={raw.event_id}")`
   - 取 event 的 `fields` 列表
   - 校验 `len(raw.fields) == len(event.fields)`
     - 不等则抛 `DecodeError`，列出期望数量和实际数量
   - 遍历 `zip(event.fields, raw.fields)`，将每个字符串值按 field `type` 解析：
     - `uint`：`int(s, 16)`（wire 是 hex）
     - `sint`：`int(s)`（wire 是 signed decimal，自带符号）
     - `bool`：`int(s, 16)`，然后 `0→False, nonzero→True`
   - 构建 `fields: dict[str, Any]`
   - 同时查 task 和 category 的 name
   - 返回 `DecodedEvent`

3. **字段值转换规则**

   wire 格式按 field type 区分：uint/bool 用 `%x`，sint 用 `%d`。解码时 parser 层不区分，统一以字符串传给 decoder；decoder 根据 catalog field type 选择解析方式。

   | field type | wire 格式 | 解码方式 | 存储类型 |
   |------------|-----------|----------|----------|
   | `uint` | `%x` hex | `int(s, 16)` | `int` |
   | `sint` | `%d` signed decimal | `int(s)` | `int`（可为负） |
   | `bool` | `%x` hex (`.asUInt`) | `int(s, 16)`，`0→False` | `bool` |

### 错误处理

```python
class TraceDecodeError(Exception):
    raw: RawTraceLine
```

- `event_id` 在 catalog 中不存在
- field 数量不匹配
- `task_id` 在 catalog 中不存在

### 测试要点

- 正常解码 → 所有字段类型正确
- event_id 不存在 → `TraceDecodeError`
- field 数量不匹配 → `TraceDecodeError` 带详细信息

---

## Step 3: `render.py` — 渲染器

### 输入

- `DecodedEvent`（来自 decoder）
- 渲染模式：`text` / `jsonl`

### 输出

渲染后的字符串。

### 核心逻辑

1. **`render_text(event: DecodedEvent) -> str`**

   用 catalog event 的 `render` 模板格式化字段值。

   示例 catalog render 模板：
   ```python
   "macro_id={macro_id} opcode=0x{opcode:x}"
   ```

   需要自定义 Formatter 处理：
   - `bool` 类型字段：`True` → `"true"`, `False` → `"false"`
   - `hex` 格式的 uint：按模板中的 `{opcode:x}` 格式化
   - `dec` 格式：直接 `str(value)`
   - `bin` 格式：`bin(value)` 或按模板中的格式说明符

   输出行格式：
   ```text
   [<cycle>] <task_name>.<method> <rendered_fields>
   ```

   示例：
   ```text
   [2623] TaskControllerTrace.macroInstInsert macro_id=5 opcode=0x12
   ```

2. **`render_jsonl(event: DecodedEvent) -> str`**

   将 event 序列化为单行 JSON。

   ```python
   {
     "cycle": 2623,
     "task": "TaskControllerTrace",
     "category": "cute_inst",
     "event": "macroInstInsert",
     "fields": {"macro_id": 5, "opcode": 18}
   }
   ```

   使用 `json.dumps(event_dict, separators=(",", ":"))` 保证紧凑单行。

3. **`render_event(event: DecodedEvent, mode: str = "text") -> str`**

   根据 mode 分发到 `render_text` 或 `render_jsonl`。

4. **`render_stream(events: Iterable[DecodedEvent], mode: str = "text", out: IO[str] | None = None) -> None`**

   流式渲染，每写一行就 flush（如果 out 是 stdout）。默认 out=sys.stdout。

### 测试要点

- text 渲染输出与 catalog render 模板一致
- jsonl 每行是合法 JSON
- bool 字段在 text 中显示为 `true`/`false`，在 jsonl 中为 `true`/`false`（JSON native）
- hex 字段在 text 中按模板格式化，在 jsonl 中为十进制 int

---

## Step 4: CLI 入口 `tools/trace/decode_cute_trace.py`

> 这个不在 Task 6 原始产物列表中，但对验收至关重要。如果用户觉得没必要，可以跳过。

### 用法

```bash
python3 tools/trace/decode_cute_trace.py \
  --log <verilator_log_file> \
  --catalog trace/catalogs/cute_trace.json \
  --mode text|jsonl \
  [-o <output_file>]
```

- `--mode text`（默认）：输出可读文本
- `--mode jsonl`：输出 JSONL
- 不指定 `-o` 时写 stdout

### 逻辑

1. 加载 catalog
2. 逐行 parse log → `RawTraceLine`
3. decode → `DecodedEvent`
4. render → 输出
5. 结束时打印统计：`TRACE_DECODE_OK events=<N> errors=<M>`

---

## Step 5: 集成测试

用手工构造的 compact 行验证端到端：

```text
CT,1,0,1,1,5,12
CT,1,1,1,2,5,12
CT,1,2,2,6,3
```

（当前 catalog 只有 uint 字段，全部是 hex。未来加入 sint 字段后，对应的 compact 值会是十进制如 `-3`。）

期望解码结果：

| cycle | event | fields |
|-------|-------|--------|
| 0 | TaskControllerTrace.macroInstInsert | macro_id=5, opcode=18 |
| 1 | TaskControllerTrace.macroInstDecodeStart | macro_id=5, opcode=18 |
| 2 | AMLLoad.taskStart | task_count=3 |

验证：
- parser → decoder → render_text 输出正确
- parser → decoder → render_jsonl 每行可 `json.loads`
- catalog 缺失或 event_id 不存在时报明确错误

---

## 文件依赖关系

```text
catalog.py  ──────────────────┐
parser.py   ─── RawTraceLine ─┤
                              ├→ decoder.py ── DecodedEvent ──→ render.py
generated/cute_trace_catalog ─┘                                    │
                                                                    ↓
                                                          tools/trace/decode_cute_trace.py
```

---

## 实施顺序

| 序号 | 内容 | 产出文件 |
|------|------|----------|
| 1 | 写 parser.py | `trace/python/cutetrace/parser.py` |
| 2 | 写 decoder.py | `trace/python/cutetrace/decoder.py` |
| 3 | 写 render.py | `trace/python/cutetrace/render.py` |
| 4 | 写 CLI 入口 | `tools/trace/decode_cute_trace.py` |
| 5 | 端到端验证 | 手工构造 compact 日志跑通 |

每一步写完立即用手工数据验证，不依赖 Verilator 真实仿真输出。
