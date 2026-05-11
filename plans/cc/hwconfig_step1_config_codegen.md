# Step 1: Config Codegen 工具链 — 详细实施方案

## 目标

写 `tools/runner/cute-gen-config.py`，从 Config YAML 生成头文件和 JSON。
Config YAML 是唯一真相源，不再从 Chipyard Scala Config class 反射提取参数。

```bash
python3 tools/runner/cute-gen-config.py \
  --chipyard-config cute4tops_scp128 \
  --output build/chipyard_configs/cute4tops_scp128/generated/
```

## 当前状态

### 产物现状

旧流程（废弃）：`sbt "runMain cute.util.HeaderGenerator ..."` → 从 Scala 反射生成头文件。

当前 `cutetest/include/` 下有三个 `.h.generated`：
- `instruction.h.generated` — 指令 funct 编码、字段定义、提取/组装宏、wrapper 函数
- `datatype.h.generated` — 元素类型枚举、位宽查询、名称字符串
- `validation.h.generated` — 硬件参数宏（Tensor_M/N/K、数据宽度、buffer 深度等）

### 数据源现状

| 输入 | 路径 | 内容 |
|------|------|------|
| ChipyardConfig | `configs/chipyard_configs/cute4tops_scp128.yaml` | SoC 结构、CUTE params、capability |
| ISA version | `configs/cute_isa_versions/cute_isa_v1.yaml` | 指令编码、funct、字段布局 |
| FPE version | `configs/cute_fpe_versions/cute_fpe_v1.yaml` | datatype 列表 |
| Vector version | `configs/vector_versions/saturn_rvv.yaml` 或 `none.yaml` | 向量扩展配置 |
| 参数目录 | `configs/schemas/chipyard_config_params.json` | 参数定义、校验依据 |

### 工具现状

- `tools/runner/cute-check-config.py` — 已有，做 YAML schema 校验和跨文件引用检查
- `tools/runner/cute-gen-config.py` — **待实现**

## 产物清单

| 输入 YAML | 产物文件 | 说明 |
|-----------|---------|------|
| `cute_isa_versions/<isa>.yaml` | `instruction.h` | 指令 funct 编码、字段定义、提取/组装宏、wrapper 函数 |
| `cute_isa_versions/<isa>.yaml` | `isa.json` | 结构化 ISA 定义（供其他工具消费） |
| `cute_fpe_versions/<fpe>.yaml` | `cute_fpe.h` | datatype 枚举、位宽查询宏、名称字符串 |
| `chipyard_configs/<config>.yaml` + `chipyard_config_params.json` | `cute_config.h` | SoC 参数宏（Tensor_M/N/K、bus width、TCM alias base 等） |
| 所有输入 | `config_fingerprint.txt` | 输入 YAML 的 sha256（漂移检查用） |

## 工具接口设计

```
tools/runner/cute-gen-config.py
  --chipyard-config <id_or_path>   # ChipyardConfig id 或路径
  --output <dir>                    # 输出目录（默认从 YAML 的 generated_headers.output_dir 读取）
  --root <dir>                      # CUTE 根目录（默认自动检测）
  --force                           # 即使 fingerprint 匹配也重新生成
  --verbose                         # 详细日志
```

核心流程：

```
1. 解析 --chipyard-config → 加载 chipyard_config YAML
2. 从 chipyard_config 解析出：
   - fpe version id → 加载 cute_fpe_versions/<id>.yaml
   - isa version id → 加载 cute_isa_versions/<id>.yaml
   - vector version id → 加载 vector_versions/<id>.yaml
   - params_symbol → 从 chipyard_config_params.json 查找具体参数值
3. 计算所有输入的 sha256 → config_fingerprint.txt
4. 如果 fingerprint 未变且 --force 未设置 → 跳过
5. 依次生成四个产物
6. 写 fingerprint 文件
```

## 四个产物的详细生成逻辑

### 1. `instruction.h` — 从 ISA YAML 生成

**输入**: `cute_isa_versions/cute_isa_v1.yaml`

**当前产物参考**: `cutetest/include/instruction.h.generated`（590 行）

需要生成的段落：

#### (a) 文件头 + include guard
```c
/**
 * Auto-generated from cute_isa_v1.yaml
 * DO NOT EDIT MANUALLY
 * Generated at: <timestamp>
 */
#ifndef CUTE_INSTRUCTION_H
#define CUTE_INSTRUCTION_H
#include <stdint.h>
#include "ygjk.h"
```

#### (b) 指令 funct 编码宏
遍历所有 groups 下所有 instructions，生成 `#define CUTE_INST_FUNCT_<NAME> <rocc_funct>`：

```c
// YGK/RoCC Interface Instructions (funct 1-8)
// CUTE Internal Instructions (funct + <offset>)

#define CUTE_INST_FUNCT_QUERY_ACCELERATOR_BUSY  1
#define CUTE_INST_FUNCT_SEND_MACRO_INST         64
...
```

从 YAML 中提取逻辑：
- 遍历 `groups` 下每个 group
- 每个 instruction 取 `rocc_funct` 值
- macro name = `CUTE_INST_FUNCT_` + instruction `name` 大写

#### (c) 指令字段定义宏
对每个有字段的 instruction（如 CONFIG_TENSOR_A、CONFIG_TENSOR_DIM、CONFIG_CONV_PARAMS），生成 `_HI`、`_LO`、`_WIDTH`、`_MAX_VALUE` 宏。

**关键问题**: 当前 `instruction.h.generated` 中的字段定义（如 `Application_M_HI 19`）来自 HeaderGenerator 对 Scala Config 的反射。但 ISA YAML 中**没有定义字段布局**（字段在 `cfgData1`/`cfgData2` 中的 bit 位置）。

**方案**: 字段布局信息目前只在 Scala 源码中。有两种处理方式：

- **方案 A（推荐）**: 在 ISA YAML 的 instruction 中增加 `fields` 定义，把字段布局也描述进 YAML。这样 codegen 就能完全从 YAML 生成字段宏。
- **方案 B**: 字段布局暂时不在 Phase 1 处理。`instruction.h` 只生成 funct 编码和 wrapper 函数骨架，字段宏后续再补。

**方案 A 的 YAML 扩展示例**:
```yaml
- name: CONFIG_TENSOR_DIM
  funct: 5
  rocc_funct: 69
  description: 配置张量维度(M,N,K)
  fields:
    cfgData1:
      - name: Application_M
        hi: 19
        lo: 0
        max_value: 65535
      - name: Application_N
        hi: 39
        lo: 20
        max_value: 65535
      - name: Application_K
        hi: 59
        lo: 40
        max_value: 65535
    cfgData2:
      - name: kernel_stride
        hi: 63
        lo: 0
```

#### (d) 字段提取宏
```c
#define CUTE_GET_CONFIG_TENSOR_DIM_CFGDATA1_Application_M(cfgdata1) (((cfgdata1) >> 0) & 0xFFFFFUL)
```

从 fields 生成：mask = `(1 << (hi - lo + 1)) - 1`，shift = lo。

#### (e) 字段组装宏
```c
#define CUTE_ASSEMBLY_CONFIG_TENSOR_DIM_CFGDATA1(application_m, application_n, application_k) ( \
  ((((uint64_t)(application_k)) & 0xFFFFFUL) << 40) | \
  ((((uint64_t)(application_n)) & 0xFFFFFUL) << 20) | \
  ((((uint64_t)(application_m)) & 0xFFFFFUL) << 0))
```

从 fields 逆序生成。

#### (f) Wrapper 函数
对每个 instruction 生成一个 C 函数：
- 无参数指令（QUERY 类）：直接调 `YGJK_INS_RRR`
- 有参数指令（CONFIG 类）：先组装 cfgData1/cfgData2，再调 `YGJK_INS_RRR`

```c
uint64_t CUTE_CONFIG_TENSOR_DIM(uint64_t application_m, uint64_t application_n, uint64_t application_k, uint64_t kernel_stride)
{
    uint64_t cfgData1 = CUTE_ASSEMBLY_CONFIG_TENSOR_DIM_CFGDATA1(application_m, application_n, application_k);
    uint64_t res1=0;
    YGJK_INS_RRR(res1, cfgData1, kernel_stride, CUTE_INST_FUNCT_CONFIG_TENSOR_DIM);
    return res1;
}
```

#### (g) 指令文档注释块
每个 instruction 生成一段注释，包含 type、funct、description、return、field 布局。

### 2. `isa.json` — 结构化 ISA

**输入**: 同 `cute_isa_v1.yaml`

**产物**: 一个 JSON 文件，包含：

```json
{
  "version": "cute_isa_v1",
  "rocc_opcode": "0x0B",
  "groups": {
    "ygjk": {
      "rocc_funct_offset": 0,
      "instructions": [
        {
          "name": "QUERY_ACCELERATOR_BUSY",
          "funct": 1,
          "rocc_funct": 1,
          "description": "...",
          "has_cfgData1": false,
          "has_cfgData2": false
        },
        ...
      ]
    },
    "cute": {
      "rocc_funct_offset": 64,
      "instructions": [
        {
          "name": "CONFIG_TENSOR_DIM",
          "funct": 5,
          "rocc_funct": 69,
          "description": "...",
          "has_cfgData1": true,
          "has_cfgData2": true,
          "fields": {
            "cfgData1": [
              {"name": "Application_M", "hi": 19, "lo": 0, "width": 20, "max_value": 65535}
            ]
          }
        }
      ]
    }
  }
}
```

用途：其他工具（如 trace 解码器、测试生成器）可以用结构化 JSON 而非解析 C 头文件。

### 3. `cute_fpe.h` — Datatype 宏

**输入**: `cute_fpe_versions/cute_fpe_v1.yaml`

**当前产物参考**: `cutetest/include/datatype.h.generated`

生成逻辑：

```c
#ifndef CUTE_DATATYPE_H
#define CUTE_DATATYPE_H

// Element Type Definitions — 从 YAML datatypes 列表按序编号
#define CUTEDataTypeI8I8I32   0
#define CUTEDataTypeF16F16F32 1
...

#define CUTE_MAX_ELEMENT_TYPE <N-1>

// Data Type Bit Width Queries — 每种类型的输入位宽
#define CUTE_GET_ADATA_BITWIDTH(elem_type) \
    ((elem_type) == 0 ? 8 : \
     (elem_type) == 1 ? 16 : \
     ...)

// Data Type Name Strings
#define CUTE_DATATYPE_NAME(elem_type) \
    ((elem_type) == 0 ? "I8I8I32" : \
     ...)

// Stride Calculation Macros — 不变
#define CUTE_CALC_M_STRIDE(elem_type, k) ...
#define CUTE_CALC_N_STRIDE(elem_type, k) ...
#define CUTE_CALC_K_STRIDE_A(elem_type) ...
#define CUTE_CALC_K_STRIDE_B(elem_type) ...

#endif
```

**关键问题**: 位宽信息不在 FPE YAML 中。当前 YAML 只有 datatype 名称列表，没有每种类型的 A/B/C 位宽。

**方案**: 在 FPE YAML 中扩展 datatype 为结构化定义：

```yaml
datatypes:
  - name: i8i8i32
    a_bits: 8
    b_bits: 8
    c_bits: 32
  - name: fp16fp16fp32
    a_bits: 16
    b_bits: 16
    c_bits: 32
  ...
```

或者保持简单列表，位宽从命名规则推导（`i8i8i32` → A=8, B=8, C=32）。后者更轻量但不够通用。

### 4. `cute_config.h` — SoC 参数宏

**输入**:
- `chipyard_configs/cute4tops_scp128.yaml` — SoC 结构参数
- `configs/schemas/chipyard_config_params.json` — 参数定义和默认值

**当前产物参考**: `cutetest/include/validation.h.generated`

**新产物范围**（比旧 `validation.h` 更全面）:

```c
#ifndef CUTE_CONFIG_H
#define CUTE_CONFIG_H

#include <stdint.h>
#include <stdbool.h>

// ChipyardConfig: cute4tops_scp128
// params_symbol: CuteParams.CUTE_4Tops_128SCP

// === Core ===
#define CUTE_SOC_CORE_KIND        shuttle       // soc.core.kind
#define CUTE_SOC_CORE_COUNT       1             // soc.core.count

// === Bus ===
#define CUTE_SOC_SYSTEM_BUS_BITS  512           // soc.bus.system_bits
#define CUTE_SOC_MEMORY_BUS_BITS  512           // soc.bus.memory_bits

// === Cache ===
#define CUTE_SOC_L2_CACHE_KB      512           // soc.cache.inclusive_kb
#define CUTE_SOC_L2_BANKS         4             // soc.cache.banks

// === CUTE Accelerator ===
// 从 chipyard_config_params.json 的 cute_params.composed 解析
#define CUTE_TENSOR_M             128
#define CUTE_TENSOR_N             128
#define CUTE_TENSOR_K             64
#define CUTE_MATRIX_M             4
#define CUTE_MATRIX_N             4
#define CUTE_REDUCE_WIDTH_BYTE    64

// === TCM (if shuttle + vector) ===
// 从 chipyard_config_params.json 的 vector.tcm 读取
#define CUTE_TCM_BASE             0x70000000
#define CUTE_TCM_SIZE             0x200000      // 2 MiB
#define CUTE_TCM_BANKS            2
// Software alias baseaddr for this config (1 tile):
#define CUTE_TCM_SOFTWARE_ALIAS_BASE  0x70200000

// === Vector ===
// vector version: none

#endif
```

**参数解析逻辑**:
1. `soc.*` 字段直接从 chipyard_config YAML 读取
2. `cute.params_symbol` → 从 `chipyard_config_params.json` 的 `cute_params.composed` 查找对应的 Tensor_M/N/K、Matrix_M/N、ReduceWidthByte 等
3. 如果 `soc.core.kind == shuttle` 且 `soc.vector.version != none`，则从 `chipyard_config_params.json` 的 `vector.tcm` 读取 TCM 参数，并计算 `software_alias_base`

## 实施步骤

### Step 1.0: 扩展 ISA YAML 字段定义

在 `cute_isa_v1.yaml` 中为每个有字段的 instruction 增加 `fields` 段。

当前需要扩展的 instructions：
- CONFIG_TENSOR_A: cfgData1 = BaseVaddr[63:0], cfgData2 = Stride[63:0]
- CONFIG_TENSOR_B: 同上
- CONFIG_TENSOR_C: 同上
- CONFIG_TENSOR_D: 同上
- CONFIG_TENSOR_DIM: cfgData1 = M[19:0] N[39:20] K[59:40], cfgData2 = kernel_stride[63:0]
- CONFIG_CONV_PARAMS: cfgData1 = element_type[7:0] bias_type[15:8] transpose_result[23:16] conv_stride[31:24] conv_oh_max[47:32] conv_ow_max[63:48], cfgData2 = kernel_size[7:0] conv_oh_per_add[25:16] conv_ow_per_add[35:26] conv_oh_index[45:36] conv_ow_index[55:46]
- CONFIG_SCALE_A: cfgData1 = BaseVaddr[63:0]
- CONFIG_SCALE_B: cfgData1 = BaseVaddr[63:0]

其余 instructions（QUERY 类、SEND、CLEAR、RESERVED）无字段。

### Step 1.1: 扩展 FPE YAML 位宽信息

在 `cute_fpe_v1.yaml` 中把 datatypes 从简单字符串列表改为结构化列表，包含 a_bits/b_bits/c_bits。

或者：codegen 中从命名规则推导位宽（更简单，但 MXFP4 等非标准命名需要特殊处理）。

**建议**: 先用命名规则推导，如果不够用再改 YAML。

### Step 1.2: 实现 `cute-gen-config.py`

脚本结构：

```python
# tools/runner/cute-gen-config.py

class ConfigGenerator:
    def __init__(self, root: Path, verbose: bool):
        self.root = root
        self.verbose = verbose
        # 复用 cute-check-config.py 的 YAML 加载逻辑

    def load_chipyard_config(self, config_id: str) -> dict
    def load_isa_version(self, isa_id: str) -> dict
    def load_fpe_version(self, fpe_id: str) -> dict
    def load_vector_version(self, vector_id: str) -> dict
    def load_params_catalog(self) -> dict  # chipyard_config_params.json

    def resolve_cute_params(self, chipyard_config: dict) -> dict
        # 从 params_symbol 查 chipyard_config_params.json 的 composed 表
        # 再查 tops_presets + scp_presets 得到具体数值

    def compute_fingerprint(self, inputs: dict[str, str]) -> str
        # sha256 of all input YAML contents

    def generate_instruction_h(self, isa: dict) -> str
    def generate_isa_json(self, isa: dict) -> str
    def generate_cute_fpe_h(self, fpe: dict) -> str
    def generate_cute_config_h(self, chipyard: dict, params: dict) -> str

    def run(self, config_id: str, output_dir: Path, force: bool)
```

**复用**: 从 `cute-check-config.py` 提取 `find_cute_root()`、YAML 加载、路径解析等公共逻辑。可以考虑把公共部分提取为 `tools/runner/cute_config_common.py`。

### Step 1.3: 验证

对现有的 `cute4tops_scp128` 配置运行 codegen，将输出与 `cutetest/include/` 下的现有 `.h.generated` 对比：

```bash
python3 tools/runner/cute-gen-config.py \
  --chipyard-config cute4tops_scp128 \
  --output build/chipyard_configs/cute4tops_scp128/generated/ \
  --verbose

# 对比
diff build/chipyard_configs/cute4tops_scp128/generated/instruction.h \
     cutetest/include/instruction.h.generated
```

由于新 codegen 从 YAML 生成而非从 Scala 反射，产物格式会有差异（时间戳、注释风格等），但功能等价的宏值必须一致。

## 依赖关系

```text
Step 1.0 (扩展 ISA YAML) ──┐
Step 1.1 (扩展 FPE YAML) ──┤
                            ├── Step 1.2 (实现 codegen) ── Step 1.3 (验证)
Step 1.0 (params.json 已有)┘
```

Step 1.0 和 1.1 可以并行。1.2 依赖两者。1.3 依赖 1.2。

## 与后续 Step 的衔接

- **Step 1.5** (`cute-update-chipyard-configs.py`): 会复用 `cute_config_common.py` 的加载逻辑
- **Step 2** (`cute-build.py`): `--step config` 会调用 `cute-gen-config.py`
- **Step 4** (漂移检查): 使用 `config_fingerprint.txt` 比对

## 风险和决策点

1. **ISA YAML 字段扩展的工作量**: 当前 12 条指令中约 8 条有字段，需要手动从现有 `.h.generated` 反推字段布局写入 YAML。这是最繁重的手动步骤。

2. **FPE 位宽**: 从命名推导可行但不够优雅。如果后续增加自定义命名类型，需要改 YAML schema。

3. **codegen 产物与旧产物的兼容性**: cutetest 目前通过 symlink 引用 `.h.generated`。新产物命名去掉 `.generated` 后缀，cutelib 未来直接用新路径，cutetest 的旧路径不需要迁移。
