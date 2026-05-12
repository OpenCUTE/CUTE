# Step 1: Config Codegen 工具链 — 详细实施方案

## 目标

写 `tools/runner/cute-gen-config.py`，从 Config YAML 生成头文件和 JSON。
Config YAML 是唯一真相源，不再从 Chipyard Scala Config class 反射提取参数。

```bash
python3 tools/runner/cute-gen-config.py \
  --chipyard-config cute4tops_scp128 \
  --output build/chipyard_configs/cute4tops_scp128/generated/
```

## 数据源（已完成）

所有输入 YAML 已就绪，无需额外扩展：

| 输入 | 路径 | 内容 |
|------|------|------|
| ChipyardConfig | `configs/chipyard_configs/cute4tops_scp128.yaml` | SoC 结构、CUTE 配置引用、capability |
| CuteConfig 预设 | `configs/cute_configs/CUTE_4Tops_128SCP.yaml` | tensor/matrix 形状、访存带宽、MMU、FPE、张量任务常量 |
| ISA version | `configs/cute_isa_versions/cute_isa_v1.yaml` | 指令编码、funct、字段布局、枚举（ElementDataType + CMemoryLoaderTaskType） |
| Vector version | `configs/vector_versions/saturn_rvv.yaml` 或 `none.yaml` | 向量扩展配置 |

已废弃的输入（不再需要）：
- ~~`cute_fpe_versions/`~~ — datatype 信息现在从 ISA YAML 的 `enums.ElementDataType` 获取
- ~~`chipyard_config_params.json` 的 `cute_params`~~ — 现在从 `cute_configs/` 独立 YAML 获取

## 数据流

```text
cute_configs/<preset>.yaml  ──→ cute_config.h（参数宏）
                               → CuteConfig.scala（Chipyard Config class）

cute_isa_versions/<isa>.yaml ──→ instruction.h（funct 编码 + 字段宏 + wrapper 函数）
                               → isa.json（结构化 ISA）
                               → cute_fpe.h（datatype 枚举 + 位宽查询宏，从 enums.ElementDataType 生成）

chipyard_configs/<id>.yaml   ──→ 串联 cute_config + isa + soc 参数
                               → config_fingerprint.txt（输入 sha256）
```

## 产物清单

| 输入 YAML | 产物文件 | 说明 |
|-----------|---------|------|
| `cute_isa_versions/<isa>.yaml` | `instruction.h` | 指令 funct 编码、字段定义、提取/组装宏、枚举宏、wrapper 函数 |
| `cute_isa_versions/<isa>.yaml` | `isa.json` | 结构化 ISA 定义（供其他工具消费） |
| `cute_isa_versions/<isa>.yaml` 的 `enums.ElementDataType` | `cute_fpe.h` | datatype 枚举、A/B 位宽查询宏、名称字符串 |
| `cute_configs/<preset>.yaml` + `chipyard_configs/<config>.yaml` | `cute_config.h` | SoC 参数宏（Tensor_M/N/K、bus width、MMU、FPE、TCM alias base 等） |
| 所有输入 | `config_fingerprint.txt` | 输入 YAML 的 sha256（漂移检查用） |

## 工具接口设计

```
tools/runner/cute-gen-config.py
  --chipyard-config <id_or_path>   # ChipyardConfig id 或路径
  --output <dir>                    # 输出目录（默认 build/chipyard_configs/<id>/generated/）
  --root <dir>                      # CUTE 根目录（默认自动检测）
  --force                           # 即使 fingerprint 匹配也重新生成
  --verbose                         # 详细日志
```

核心流程：

```
1. 解析 --chipyard-config → 加载 chipyard_config YAML
2. 从 chipyard_config 解析出：
   - cute.config → 加载 cute_configs/<id>.yaml（CUTE 加速器参数）
   - cute.isa.version → 加载 cute_isa_versions/<id>.yaml（指令集 + 枚举 + datatype 位宽）
   - soc.vector.version → 加载 vector_versions/<id>.yaml
3. 计算所有输入的 sha256 → config_fingerprint.txt
4. 如果 fingerprint 未变且 --force 未设置 → 跳过
5. 依次生成五个产物
6. 写 fingerprint 文件
```

## 五个产物的详细生成逻辑

### 1. `instruction.h` — 从 ISA YAML 生成

**输入**: `cute_isa_versions/cute_isa_v1.yaml` 的 `groups` 和 `enums`

需要生成的段落：

#### (a) 文件头 + include guard
```c
#ifndef CUTE_INSTRUCTION_H
#define CUTE_INSTRUCTION_H
#include <stdint.h>
#include "ygjk.h"
```

#### (b) 指令 funct 编码宏
遍历所有 groups 下所有 instructions，生成 `#define CUTE_INST_FUNCT_<NAME> <rocc_funct>`。

#### (c) 枚举宏
遍历 `enums` 下每个枚举类型，为每个 value 生成 `#define CUTE_<ENUM_NAME>_<VALUE_NAME> <value>`：
```c
// ElementDataType
#define CUTE_ELEMENT_DATA_TYPE_I8I8I32 0
#define CUTE_ELEMENT_DATA_TYPE_F16F16F32 1
...
// CMemoryLoaderTaskType
#define CUTE_CMEMORY_LOADER_TASK_TYPE_TENSOR_ZERO_LOAD 1
#define CUTE_CMEMORY_LOADER_TASK_TYPE_TENSOR_LOAD 3
```

#### (d) 指令字段定义宏
对每个有 `fields` 的 instruction，生成 `_HI`、`_LO`、`_WIDTH`、`_MAX_VALUE` 宏。字段有 `enum_ref` 的在注释中标注枚举来源。

#### (e) 字段提取宏
```c
#define CUTE_GET_CONFIG_TENSOR_DIM_CFGDATA1_Application_M(cfgdata1) (((cfgdata1) >> 0) & 0xFFFFFUL)
```

#### (f) 字段组装宏
从 fields 逆序生成 OR 组合。

#### (g) Wrapper 函数
对每个 instruction 生成 C 函数，调用 `YGJK_INS_RRR`。

#### (h) 指令文档注释块

### 2. `isa.json` — 结构化 ISA

**输入**: `cute_isa_v1.yaml`

直接序列化为 JSON，包含 groups、enums（含 a_bits/b_bits/c_bits）、rocc opcode。

### 3. `cute_fpe.h` — Datatype 宏

**输入**: `cute_isa_v1.yaml` 的 `enums.ElementDataType`

从枚举的 `value` + `a_bits`/`b_bits`/`c_bits` 生成：

```c
#ifndef CUTE_DATATYPE_H
#define CUTE_DATATYPE_H

// Element Type Definitions
#define CUTEDataTypeI8I8I32   0
#define CUTEDataTypeF16F16F32 1
...
#define CUTE_MAX_ELEMENT_TYPE 12

// Data Type A Bit Width Queries
#define CUTE_GET_ADATA_BITWIDTH(elem_type) \
    ((elem_type) == 0 ? 8 : \
     (elem_type) == 1 ? 16 : \
     ...)

// Data Type B Bit Width Queries
#define CUTE_GET_BDATA_BITWIDTH(elem_type) ...

// Data Type Name Strings
#define CUTE_DATATYPE_NAME(elem_type) ...

// Stride Calculation Macros
#define CUTE_CALC_M_STRIDE(elem_type, k) ((k) * CUTE_GET_ADATA_BITWIDTH(elem_type) / 8)
...

#endif
```

不再需要单独的 FPE YAML — 所有 datatype 信息从 ISA YAML 的 `enums.ElementDataType` 获取。

### 4. `cute_config.h` — SoC 参数宏

**输入**:
- `cute_configs/CUTE_4Tops_128SCP.yaml` — CUTE 加速器全部硬件参数
- `chipyard_configs/cute4tops_scp128.yaml` — SoC 结构参数

```c
#ifndef CUTE_CONFIG_H
#define CUTE_CONFIG_H

#include <stdint.h>
#include <stdbool.h>

// ChipyardConfig: cute4tops_scp128
// CuteConfig: CUTE_4Tops_128SCP

// === CUTE Accelerator (from cute_config) ===
#define CUTE_TENSOR_M             128
#define CUTE_TENSOR_N             128
#define CUTE_TENSOR_K             64
#define CUTE_MATRIX_M             4
#define CUTE_MATRIX_N             4
#define CUTE_REDUCE_WIDTH_BYTE    64
#define CUTE_REDUCE_WIDTH         512    // reduce_width_byte * 8
#define CUTE_RESULT_WIDTH_BYTE    4
#define CUTE_RESULT_WIDTH         32     // result_width_byte * 8
#define CUTE_RESULT_FIFO_DEPTH    8
#define CUTE_OUTSIDE_DATA_WIDTH   512
#define CUTE_MMU_ADDR_WIDTH       39
#define CUTE_LLC_SOURCE_MAX_NUM   64

// === Tensor Task (from cute_config.tensor_task) ===
#define CUTE_APPLICATION_MAX_TENSOR_SIZE 65535
#define CUTE_CONV_INPUT_MAX      16383
#define CUTE_CONV_KERNEL_SIZE_MAX 15
#define CUTE_CONV_STRIDE_SIZE_MAX 3

// === MMU (from cute_config.mmu) ===
#define CUTE_MMU_VPN_BITS         12
#define CUTE_MMU_PPN_BITS         12
#define CUTE_MMU_PGIDX_BITS       12
#define CUTE_MMU_VADDR_BITS       39
#define CUTE_MMU_PADDR_BITS       39
#define CUTE_MMU_CORE_PADDR_BITS  64

// === FPE (from cute_config.fpe) ===
#define CUTE_FPE_MIN_GROUP_SIZE   16
#define CUTE_FPE_MIN_DATA_TYPE_WIDTH 4
#define CUTE_FPE_COMP_TREE_LAYERS 4
#define CUTE_FPE_FP8_COMP_TREE_LAYERS 4

// === SoC (from chipyard_config.soc) ===
#define CUTE_SOC_CORE_KIND        shuttle
#define CUTE_SOC_CORE_COUNT       1
#define CUTE_SOC_SYSTEM_BUS_BITS  512
#define CUTE_SOC_MEMORY_BUS_BITS  512
#define CUTE_SOC_L2_CACHE_KB      512
#define CUTE_SOC_L2_BANKS         4

// === TCM (if shuttle + vector, computed) ===
// (only when vector version != none)

// === WIP params (not generated, reserved for future use) ===
// vector_width, memory_data_width, vec_task_*, enable_perf_counter, memory_source_max_num

#endif
```

**参数解析逻辑**:
1. `cute_configs/<preset>.yaml` → CUTE 加速器参数（tensor/matrix/reduce/tensor_task/mmu/fpe）
2. `chipyard_configs/<config>.yaml` 的 `soc.*` → SoC 结构参数
3. 如果 `soc.core.kind == shuttle` 且 `soc.vector.version != none`，从 `chipyard_config_params.json` 的 `vector.tcm` 读取 TCM 参数，并计算 `software_alias_base`
4. `wip` 段的参数 codegen 暂不生成对应的宏

### 5. `config_fingerprint.txt`

所有输入 YAML 的 sha256。

## 实施步骤

### Step 1.0: 扩展 ISA YAML（已完成）

- 指令字段布局 `fields`（hi/lo/max_value/enum_ref）
- 枚举定义 `enums`（ElementDataType 含 a_bits/b_bits/c_bits、CMemoryLoaderTaskType）

### Step 1.1: CuteConfig 预设文件（已完成）

- `configs/cute_configs/` 下 16 个预设 YAML，包含完整硬件参数
- WIP 参数（vector_width、memory_data_width、vec_task_*、enable_perf_counter、memory_source_max_num）统一收到 `wip` 对象下

### Step 1.2: 实现 `cute-gen-config.py`

```python
# tools/runner/cute-gen-config.py

class ConfigGenerator:
    def __init__(self, root: Path, verbose: bool):
        self.root = root
        self.verbose = verbose

    def load_chipyard_config(self, config_id: str) -> dict
    def load_cute_config(self, preset_id: str) -> dict
    def load_isa_version(self, isa_id: str) -> dict
    def load_vector_version(self, vector_id: str) -> dict

    def compute_fingerprint(self, inputs: dict[str, str]) -> str

    def generate_instruction_h(self, isa: dict) -> str
    def generate_isa_json(self, isa: dict) -> str
    def generate_cute_fpe_h(self, isa: dict) -> str  # 从 isa.enums.ElementDataType
    def generate_cute_config_h(self, chipyard: dict, cute_config: dict) -> str

    def run(self, config_id: str, output_dir: Path, force: bool)
```

公共逻辑（`find_cute_root()`、YAML 加载、路径解析）提取为 `tools/runner/cute_config_common.py`。

### Step 1.3: 验证

```bash
python3 tools/runner/cute-gen-config.py \
  --chipyard-config cute4tops_scp128 \
  --output build/chipyard_configs/cute4tops_scp128/generated/ \
  --verbose
```

## 依赖关系

```text
Step 1.0 (ISA YAML 字段+枚举)  ──已完成
Step 1.1 (CuteConfig 预设)      ──已完成
Step 1.2 (实现 codegen)          ──待实现
Step 1.3 (验证)                  ──待实现
```

## 与后续 Step 的衔接

- **Step 1.5** (`cute-update-chipyard-configs.py`): 从 `cute_configs/<preset>.yaml` + `chipyard_configs/<id>.yaml` 生成 `CuteConfig.scala`
- **Step 2** (`cute-build.py`): `--step config` 会调用 `cute-gen-config.py`
- **Step 4** (漂移检查): 使用 `config_fingerprint.txt` 比对
