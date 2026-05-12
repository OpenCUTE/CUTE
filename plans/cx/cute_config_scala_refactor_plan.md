# CUTE Config README 与 Scala 参数拆分重构计划

## 背景

`configs/README.md` 目前仍按较早的 `ChipyardConfig -> CuteParams.CUTE_xxx` 方式描述配置流。实际设计已经推进到：

- `configs/cute_configs/*.yaml` 可以声明一个 CUTE 硬件参数预设，例如 `CUTE_4Tops_128SCP`。
- `configs/chipyard_configs/*.yaml` 通过 `cute.config` 引用 `cute_configs/<id>.yaml`，再绑定 SoC、ISA、vector 等信息。
- `tools/runner/cute-gen-config.py` 已经能从 YAML 生成 C 侧 `instruction.h`、`isa.json`、`cute_fpe.h`、`cute_config.h`。
- Scala 侧仍主要依赖 `src/main/scala/CUTEParameters.scala` 里的手写 `object CuteParams`、`object CuteInstConfigs`、`object YGJKInstConfigs`、`ElementDataType` 等定义。

核心问题是：YAML 已经能描述 CUTE config，但 `CUTEParameters.scala` 仍同时承担了“配置真相源”和“硬件实现/派生参数”两种职责，容易和 YAML 漂移。

## 目标

把 CUTE 的参数层拆成三类：

1. YAML 声明事实：用户可编辑的配置真相源。
2. Scala 生成事实：从 YAML 生成的 Scala 常量、预设、指令枚举。
3. Scala 派生/实现：Chisel 模块真正需要的派生参数、Bundle、IO、helper logic。

最终形成：

```text
configs/
  cute_configs/*.yaml          # CUTE 硬件参数预设
  cute_isa_versions/*.yaml     # 指令、funct、字段、enum/datatype
  chipyard_configs/*.yaml      # SoC + CUTE 预设引用

src/main/scala/
  HardwareConfig.scala         # 生成或半生成：CuteParams 预设 + YAML 映射
  InstConfig.scala             # 生成或半生成：指令配置 + ElementDataType + CMemoryLoaderTaskType
  CUTEParameters.scala         # 手写：CuteParams case class、require、派生值、Bundle/IO/硬件实现参数
```

## 现状观察

### `CUTEParameters.scala` 当前混在一起的内容

```text
object CuteParams / Cutev3Params
  静态预设：CUTE_4Tops_128SCP 等，应该由 cute_configs YAML 生成或校验。

case class CuteParams / CuteMMUParams / CuteFPEParams / CuteDebugParams
  参数数据结构和默认值，建议继续手写保留。

case class CuteParams 中的 def ...
trait CUTEImplParameters
  硬件派生参数和 Chisel 侧访问入口，建议继续手写保留。

InstField / CuteInstConfig / CuteInstConfigs / YGJKInstConfigs
ElementDataType / CMemoryLoaderTaskType
  指令和 enum 静态事实，应该从 cute_isa_versions YAML 生成。

CuteModule / CuteBundle / MacroInst / LoadMicroInst / ...
  硬件 Bundle/IO/实现类型，继续保留在手写 Scala。
```

### `cute_fpe_versions` 的状态

`configs/README.md` 仍描述 `cute_fpe_versions/`。但当前工具链 `cute-gen-config.py` 已把 datatype 信息放在 `cute_isa_versions/<id>.yaml` 的 `enums.ElementDataType` 下，并由此生成 `cute_fpe.h`。当前 repo 中没有实际的 `configs/cute_fpe_versions/` 目录。

这里需要定一个口径：

- 路线 A：保留独立 `cute_fpe_versions/`，ISA YAML 只引用 FPE version，datatype enum 从 FPE version 生成。
- 路线 B：废弃独立 `cute_fpe_versions/`，datatype 能力归属 ISA version，README 移除该目录。

建议先采用路线 B，因为现有 codegen 已按这个方向实现，改动最小。若后续 FPE datatype 要独立演进，再把它从 ISA YAML 中拆出去。

## 推荐架构

### 1. `HardwareConfig.scala`

职责：承接 `cute_configs/*.yaml` 到 Scala 的静态预设映射。

建议内容：

```scala
package cute

object HardwareConfig {
  def CUTE_4Tops_128SCP: CuteParams = CuteParams(
    Tensor_M = 128,
    Tensor_N = 128,
    Tensor_K = 64,
    Matrix_M = 4,
    Matrix_N = 4,
    ReduceWidthByte = 64,
    outsideDataWidth = 512,
    ResultWidthByte = 4,
    MMUAddrWidth = 39,
    LLCSourceMaxNum = 64,
    ResultFIFODepth = 8,
    MMUParams = CuteMMUParams(...),
    FPEparams = CuteFPEParams(...),
    EnablePerfCounter = false
  )

  val byId: Map[String, CuteParams] = Map(
    "CUTE_4Tops_128SCP" -> CUTE_4Tops_128SCP
  )
}
```

兼容层可以暂时保留：

```scala
object CuteParams {
  def baseParams = CuteParams()
  def CUTE_4Tops_128SCP = HardwareConfig.CUTE_4Tops_128SCP
}
```

这样 Chipyard 里已有 `CuteParams.CUTE_4Tops_128SCP` 不会立刻炸掉，但新增配置的真相源变成 YAML。

### 2. `InstConfig.scala`

职责：承接 `cute_isa_versions/*.yaml` 到 Scala 的静态指令/enum 映射。

建议内容：

```scala
package cute

case class InstField(...)
sealed abstract class CuteInstConfig { ... }

object YGJKInstConfigs {
  case object QueryAcceleratorBusy extends CuteInstConfig { ... }
  val allInsts = Seq(...)
}

object CuteInstConfigs {
  case object SendMacroInst extends CuteInstConfig { ... }
  val allInsts = Seq(...)
}

case object ElementDataType extends Field[UInt] {
  val DataTypeBitWidth = 4
  val DataTypeI8I8I32 = 0.U(DataTypeBitWidth.W)
  ...
}

case object CMemoryLoaderTaskType extends Field[UInt] {
  val TypeBitWidth = 4
  val TaskTypeTensorZeroLoad = 1.U(TypeBitWidth.W)
  ...
}
```

短期可以先手动搬迁，确保行为不变。中期应由 `cute_isa_versions/cute_isa_v1.yaml` 生成，避免 C 头文件和 Scala 指令定义双源漂移。

### 3. `CUTEParameters.scala`

职责收缩为：

- `CuteParamsKey`
- `CuteDebugParams`、`CuteMMUParams`、`CuteFPEParams`、`Cutev3extParams`
- `case class CuteParams` 及其 `require`、派生 `def`
- `trait CUTEImplParameters`
- `CuteModule` / `CuteBundle`
- 各类 Bundle、IO、task type 中和硬件实现强绑定的结构

不再手写：

- 所有 `CUTE_4Tops_128SCP` 这类预设
- `CuteInstConfigs` / `YGJKInstConfigs`
- `ElementDataType` / `CMemoryLoaderTaskType` 这类来自 ISA manifest 的 enum

## Codegen 方案

在现有 `tools/runner/cute-gen-config.py` 基础上增加 Scala 产物，或新增独立工具：

```bash
python3 tools/runner/cute-gen-scala-config.py \
  --root /root/opencute/CUTE \
  --output-dir src/main/scala \
  --force
```

生成产物：

```text
src/main/scala/HardwareConfig.scala
src/main/scala/InstConfig.scala
src/main/scala/GeneratedConfigFingerprint.scala  # 可选
```

输入：

```text
configs/cute_configs/*.yaml
configs/cute_isa_versions/*.yaml
configs/chipyard_configs/*.yaml      # 可选，用于生成 Chipyard Config class 时再读
```

生成规则：

| YAML 字段 | Scala 字段 |
|-----------|------------|
| `tensor.M/N/K` | `Tensor_M/N/K` |
| `matrix.M/N` | `Matrix_M/N` |
| `reduce_width_byte` | `ReduceWidthByte` |
| `outside_data_width` | `outsideDataWidth` |
| `result_width_byte` | `ResultWidthByte` |
| `mmu_addr_width` | `MMUAddrWidth` |
| `llc_source_max_num` | `LLCSourceMaxNum` |
| `wip.memory_source_max_num` | `MemorysourceMaxNum` |
| `wip.vector_width` | `VectorWidth` |
| `wip.enable_perf_counter` | `EnablePerfCounter` |
| `mmu.*` | `CuteMMUParams(...)` |
| `fpe.*` | `CuteFPEParams(...)` |
| `tensor_task.*` | `ApplicationMaxTensorSize` / conv max fields |

### 命名约定

- `cute_configs/<id>.yaml` 的 `id` 必须生成同名 Scala def。
- 文件名必须等于 `id + ".yaml"`。
- 生成代码顶部写入 `DO NOT EDIT MANUALLY`。
- 生成器排序固定，保证 git diff 稳定。

## README 更新计划

`configs/README.md` 应更新为新层级：

```text
HWConfig
  -> ChipyardConfig
       -> CuteConfig                 # 新增，引用 configs/cute_configs/<id>.yaml
       -> CUTEISAVersion             # 指令 + datatype enum
       -> VectorVersion
  -> MemoryConfig
  -> SimulatorPolicy
```

README 需要替换的重点：

- 把旧 `cute.params_symbol: CuteParams.CUTE_xxx` 改成 `cute.config: CUTE_xxx`。
- 增加 `cute_configs/` 目录说明。
- 根据最终口径决定是否保留 `cute_fpe_versions/`；若按推荐路线 B，则写明 datatype 信息已迁入 `cute_isa_versions/*.yaml` 的 `enums.ElementDataType`。
- 把构建流程改成 `Config YAML -> codegen -> C headers + Scala config`，不再说从 Chipyard Scala 反射提取头文件是主流程。
- 增加 “Scala 参数拆分” 小节，说明 `HardwareConfig.scala`、`InstConfig.scala`、`CUTEParameters.scala` 的职责。

## 分阶段实施

### Phase 0: 文档先对齐

只更新 `configs/README.md`，不改 Scala 行为。

验收：

- README 能准确描述 `cute_configs/`。
- README 不再引用 `params_symbol` 作为新流程主路径。
- README 明确 `CUTEParameters.scala` 后续会拆分。

### Phase 1: 手动拆文件，保持行为不变

新增：

```text
src/main/scala/HardwareConfig.scala
src/main/scala/InstConfig.scala
```

迁移：

- 把 `object CuteParams` 中所有 `CUTE_xxx` 预设搬到 `HardwareConfig`。
- `object CuteParams` 保留兼容转发。
- 把 `InstField`、`CuteInstConfig`、`CuteInstConfigs`、`YGJKInstConfigs`、`ElementDataType`、`CMemoryLoaderTaskType` 搬到 `InstConfig.scala`。
- `CUTEParameters.scala` 删除对应定义，只保留引用。

验收：

```bash
cd /root/opencute/CUTE/chipyard
make build
```

或者至少跑当前项目的 Scala 编译目标。

### Phase 2: 生成 `HardwareConfig.scala`

扩展 codegen，从所有 `configs/cute_configs/*.yaml` 生成 `HardwareConfig.scala`。

`object CuteParams` 仍可保留为手写兼容层：

```scala
object CuteParams {
  def baseParams = CuteParams()
  def CUTE_4Tops_128SCP = HardwareConfig.CUTE_4Tops_128SCP
}
```

验收：

- YAML 改一个参数，重新生成后 Scala 预设同步变化。
- `HardwareConfig.byId("CUTE_4Tops_128SCP")` 和 `CuteParams.CUTE_4Tops_128SCP` 值一致。
- C 侧 `cute_config.h` 与 Scala 侧 `HardwareConfig.scala` 来自同一 YAML。

### Phase 3: 生成 `InstConfig.scala`

扩展 codegen，从 `configs/cute_isa_versions/<id>.yaml` 生成：

- `InstField`
- `CuteInstConfig`
- `YGJKInstConfigs`
- `CuteInstConfigs`
- `ElementDataType`
- `CMemoryLoaderTaskType`

注意：如果未来存在多个 ISA version，Scala 侧需要决定是：

- 只生成当前默认 ISA，例如 `cute_isa_v1`。
- 或生成 `InstConfig_cute_isa_v1.scala` 等多版本文件，再由 Chipyard config 选择。

短期建议只支持一个当前默认 ISA，降低变更面。

验收：

- `instruction.h` 和 `InstConfig.scala` 的 funct、field、enum 值来自同一 YAML。
- `CUTE2YGJK.scala` 中所有 `YGJKInstConfigs.Query...` 引用不变。
- `TaskController.scala` 中 `CMemoryLoaderTaskType.TaskType...` 引用不变。

### Phase 4: 漂移检查

新增检查工具：

```bash
python3 tools/runner/cute-check-scala-config.py
```

检查：

- `cute_configs/*.yaml` 和生成的 `HardwareConfig.scala` fingerprint 一致。
- `cute_isa_versions/*.yaml` 和生成的 `InstConfig.scala` fingerprint 一致。
- 可选：用 Scala 小程序打印 `HardwareConfig.byId` 的关键参数，与 YAML 逐项比对。

验收：

- CI 中如果 YAML 改了但 Scala 未重新生成，直接失败。

### Phase 5: Chipyard Config class 生成

在 Scala 参数拆分稳定后，再推进：

```text
chipyard_configs/*.yaml -> chipyard/generators/chipyard/src/main/scala/config/CuteConfig.scala
```

这一步和 `HardwareConfig.scala` 是相邻但不同的目标：

- `HardwareConfig.scala` 给 CUTE generator 模块使用。
- Chipyard `CuteConfig.scala` 给 SoC 顶层组合使用。

不要把这两步混在同一个初始 PR 里，否则风险会扩大。

## 风险与处理

### 风险 1: 生成 Scala 需要 Chisel import

`ElementDataType`、`CMemoryLoaderTaskType` 使用 `UInt` 和 `.U/.W`，生成文件需要：

```scala
import chisel3._
import org.chipsalliance.cde.config._
```

处理：`InstConfig.scala` 模板固定写入这些 import。

### 风险 2: `CuteParams` 既是 object 又是 case class companion

当前 `case class CuteParams` 和 `object CuteParams` 同名，这是 Scala 合法 companion。若迁移不小心删除 `object CuteParams`，Chipyard 现有引用会断。

处理：第一阶段必须保留 `object CuteParams` 作为兼容 facade，只把实现转发到 `HardwareConfig`。

### 风险 3: `cute_fpe_versions` 口径未定

如果 README 继续写 `cute_fpe_versions/`，但工具实际从 ISA YAML 生成 FPE，会继续造成认知漂移。

处理：先在 README 里明确“当前 datatype 信息由 ISA YAML 承担”。如果要恢复独立 FPE version，应单开计划迁移。

### 风险 4: 多 ISA version 的 Scala 选择

硬件编译通常只会用一个 ISA version。若一次生成多个 `ElementDataType` object，会命名冲突。

处理：短期固定生成默认 ISA version；后续如需多版本，可生成带 version suffix 的 object，并由 `CuteParams` 增加 `isaVersion` 字段选择。

## 推荐落地顺序

1. 先改 `configs/README.md`，把 YAML 设计和当前 codegen 状态讲清楚。
2. 手动拆出 `HardwareConfig.scala` 和 `InstConfig.scala`，保证编译完全等价。
3. 给 `cute-gen-config.py` 或新脚本加 `--scala` 产物，先生成 `HardwareConfig.scala`。
4. 再生成 `InstConfig.scala`。
5. 加 drift/fingerprint 检查，防止 YAML 和 Scala 产物不同步。

## 第一版建议提交范围

第一版可以只做：

- 更新 `configs/README.md`。
- 新增此设计文档。
- 不动 Scala。

第二版再做：

- 新增 `HardwareConfig.scala`、`InstConfig.scala`。
- 从 `CUTEParameters.scala` 搬迁静态定义，但保留兼容转发。

第三版再做：

- codegen 生成 Scala。
- 加 drift 检查。

