package cute.util

import cute._
import org.chipsalliance.cde.config.{Config, Parameters, Field}
import java.io._
import scala.util.{Try, Success, Failure}

object HeaderGenerator {

  // 从 CUTEParameters.scala 的 ElementDataType 提取
  // 对应 CUTEParameters.scala 第 1520-1532 行
  val dataTypeEnum = Map(
    "CUTEDataTypeI8I8I32" -> (0, 8, 8, 32, "Int8 * Int8 -> Int32"),
    "CUTEDataTypeF16F16F32" -> (1, 16, 16, 32, "FP16 * FP16 -> FP32"),
    "CUTEDataTypeBF16BF16F32" -> (2, 16, 16, 32, "BF16 * BF16 -> FP32"),
    "CUTEDataTypeTF32TF32F32" -> (3, 32, 32, 32, "TF32 * TF32 -> FP32"),
    "CUTEDataTypeI8U8I32" -> (4, 8, 8, 32, "Int8 * UInt8 -> Int32"),
    "CUTEDataTypeU8I8I32" -> (5, 8, 8, 32, "UInt8 * Int8 -> Int32"),
    "CUTEDataTypeU8U8I32" -> (6, 8, 8, 32, "UInt8 * UInt8 -> Int32"),
    "CUTEDataTypeMxfp8e4m3F32" -> (7, 8, 8, 32, "MXFP8 E4M3 -> FP32"),
    "CUTEDataTypeMxfp8e5m2F32" -> (8, 8, 8, 32, "MXFP8 E5M2 -> FP32"),
    "CUTEDataTypenvfp4F32" -> (9, 4, 4, 32, "NVFP4 -> FP32"),
    "CUTEDataTypemxfp4F32" -> (10, 4, 4, 32, "MXFP4 -> FP32"),
    "CUTEDataTypefp8e4m3F32" -> (11, 8, 8, 32, "FP8 E4M3 -> FP32"),
    "CUTEDataTypefp8e5m2F32" -> (12, 8, 8, 32, "FP8 E5M2 -> FP32")
  )

  /**
   * 从 Config 类名称中真正提取 CuteParams
   * 使用与 chipyard 相同的方法来加载配置
   */
  def extractParamsFromConfig(configClassName: String): Try[CuteParams] = Try {
    println(s"Loading Config class: $configClassName")

    // 使用 chipyard 的方法加载 Config
    val config = loadConfig(Seq(configClassName))

    println(s" Config loaded successfully")

    // Config 本身就是一个 Parameters 对象，可以直接使用
    // 从 Config 中提取 CuteParams
    val cuteParams = config(CuteParamsKey)

    println(s" CuteParams extracted:")
    println(s"  Tensor_M: ${cuteParams.Tensor_M}")
    println(s"  Tensor_N: ${cuteParams.Tensor_N}")
    println(s"  Tensor_K: ${cuteParams.Tensor_K}")
    println(s"  Matrix_M: ${cuteParams.Matrix_M}")
    println(s"  Matrix_N: ${cuteParams.Matrix_N}")
    println(s"  ReduceWidthByte: ${cuteParams.ReduceWidthByte}")
    println(s"  OutsideDataWidth: ${cuteParams.outsideDataWidth}")
    println(s"  VectorWidth: ${cuteParams.VectorWidth}")
    println(s"  MMU: vpn=${cuteParams.MMUParams.vpnBits}, ppn=${cuteParams.MMUParams.ppnBits}")

    cuteParams
  }

  /**
   * 加载 Config 类，模仿 chipyard.stage.HasChipyardStageUtils.getConfig
   */
  private def loadConfig(fullConfigClassNames: Seq[String]): Config = {
    new Config(fullConfigClassNames.foldRight(Parameters.empty) { case (currentName, config) =>
      val currentConfig = try {
        Class.forName(currentName).newInstance.asInstanceOf[Config]
      } catch {
        case e: java.lang.ClassNotFoundException =>
          throw new Exception(
            s"""Unable to find part "$currentName" from "$fullConfigClassNames"
               |Did you misspell it or specify the wrong package path?
               |Try using the full package name, e.g., chipyard.CUTE4TopsSCP128Config""".stripMargin,
            e
          )
      }
      currentConfig ++ config
    })
  }

  def generateDataTypeHeader(params: CuteParams, outputDir: String): Unit = {
    val writer = new PrintWriter(new File(s"$outputDir/datatype.h.generated"))

    writer.println(s"/**")
    writer.println(s" * Auto-generated from CUTEParameters.scala")
    writer.println(s" * DO NOT EDIT MANUALLY")
    writer.println(s" * Generated at: ${new java.util.Date()}")
    writer.println(s" */")
    writer.println()
    writer.println("#ifndef CUTE_DATATYPE_H")
    writer.println("#define CUTE_DATATYPE_H")
    writer.println()

    // 生成数据类型枚举（按ID排序）
    writer.println("// Element Type Definitions")
    dataTypeEnum.toList.sortBy(_._2._1).foreach { case (name, (id, aBits, bBits, dBits, desc)) =>
      writer.println(s"#define $name $id  // $desc")
    }
    writer.println()
    writer.println(s"#define CUTE_MAX_ELEMENT_TYPE ${dataTypeEnum.size - 1}")
    writer.println()

    // 生成位宽查询宏
    writer.println("// Data Type Bit Width Queries")
    writer.println("#define CUTE_GET_ADATA_BITWIDTH(elem_type) \\")
    dataTypeEnum.toList.sortBy(_._2._1).foreach { case (name, (id, aBits, _, _, _)) =>
      writer.println(s"    ((elem_type) == $id ? $aBits : \\")
    }
    // 添加足够的闭合括号（数量等于数据类型数量）
    val numClosures = dataTypeEnum.size
    writer.println("    32" + ")" * numClosures)
    writer.println()

    // 生成数据类型名称查询宏
    writer.println("// Data Type Name Strings")
    writer.println("#define CUTE_DATATYPE_NAME(elem_type) \\")
    dataTypeEnum.toList.sortBy(_._2._1).foreach { case (name, (id, _, _, _, _)) =>
      val cName = name.replace("CUTEDataType", "").replace("F32", "FP32")
      writer.println(s"    ((elem_type) == $id ? \"$cName\" : \\")
    }
    writer.println("    \"Unknown\"" + ")" * numClosures)
    writer.println()

    // 生成步长计算宏
    writer.println("// Stride Calculation Macros")
    writer.println(s"#define CUTE_CALC_M_STRIDE(elem_type, k) \\")
    writer.println(s"    ((k) * CUTE_GET_ADATA_BITWIDTH(elem_type) / 8)")
    writer.println()
    writer.println(s"#define CUTE_CALC_N_STRIDE(elem_type, k) \\")
    writer.println(s"    ((k) * CUTE_GET_ADATA_BITWIDTH(elem_type) / 8)")
    writer.println()
    writer.println(s"#define CUTE_CALC_K_STRIDE_A(elem_type) \\")
    writer.println(s"    (CUTE_GET_ADATA_BITWIDTH(elem_type) / 8)")
    writer.println()
    writer.println(s"#define CUTE_CALC_K_STRIDE_B(elem_type) \\")
    writer.println(s"    (CUTE_GET_ADATA_BITWIDTH(elem_type) / 8)")
    writer.println()

    writer.println("#endif // CUTE_DATATYPE_H")
    writer.close()
    println(s"✓ Generated: $outputDir/datatype.h.generated")
  }

  def generateValidationHeader(params: CuteParams, outputDir: String): Unit = {
    val writer = new PrintWriter(new File(s"$outputDir/validation.h.generated"))

    writer.println(s"/**")
    writer.println(s" * Auto-generated from CUTEParameters.scala")
    writer.println(s" * DO NOT EDIT MANUALLY")
    writer.println(s" * Generated at: ${new java.util.Date()}")
    writer.println(s" */")
    writer.println()
    writer.println("#ifndef CUTE_VALIDATION_H")
    writer.println("#define CUTE_VALIDATION_H")
    writer.println()
    writer.println("#include <stdint.h>")
    writer.println("#include <stdbool.h>")
    writer.println("#include \"datatype.h.generated\"")
    writer.println()

    // 从 CuteParams 生成常量定义
    writer.println("// Hardware Parameters (from CuteParams)")
    writer.println(s"#define CUTE_OUTSIDE_DATA_WIDTH ${params.outsideDataWidth}")
    writer.println(s"#define CUTE_MEMORY_DATA_WIDTH ${params.MemoryDataWidth}")
    writer.println(s"#define CUTE_VECTOR_WIDTH ${params.VectorWidth}")
    writer.println(s"#define CUTE_MMU_ADDR_WIDTH ${params.MMUAddrWidth}")
    writer.println()

    writer.println("// Tensor Dimensions")
    writer.println(s"#define CUTE_TENSOR_M ${params.Tensor_M}")
    writer.println(s"#define CUTE_TENSOR_N ${params.Tensor_N}")
    writer.println(s"#define CUTE_TENSOR_K ${params.Tensor_K}")
    writer.println()

    writer.println("// Matrix Dimensions (for TE execution)")
    writer.println(s"#define CUTE_MATRIX_M ${params.Matrix_M}")
    writer.println(s"#define CUTE_MATRIX_N ${params.Matrix_N}")
    writer.println()

    writer.println("// Buffer Depths")
    writer.println(s"#define CUTE_RESULT_FIFO_DEPTH ${params.ResultFIFODepth}")
    writer.println(s"#define CUTE_VEC_TASK_INST_BUFFER_DEPTH ${params.VecTaskInstBufferDepth}")
    writer.println(s"#define CUTE_VEC_TASK_INST_BUFFER_SIZE ${params.VecTaskInstBufferSize}")
    writer.println(s"#define CUTE_VEC_TASK_DATA_BUFFER_DEPTH ${params.VecTaskDataBufferDepth}")
    writer.println()

    writer.println("// Cache Configuration")
    writer.println(s"#define CUTE_LLC_SOURCE_MAX_NUM ${params.LLCSourceMaxNum}")
    writer.println(s"#define CUTE_MEMORY_SOURCE_MAX_NUM ${params.MemorysourceMaxNum}")
    writer.println()

    writer.println("// Convolution Parameters")
    writer.println(s"#define CUTE_CONVOLUTION_DIM_MAX ${params.ConvolutionApplicationConfigDataWidth}")
    writer.println(s"#define CUTE_CONVOLUTION_INPUT_MAX ${params.Convolution_Input_Height_Weight_Dim_Max}")
    writer.println(s"#define CUTE_KERNEL_SIZE_MAX ${params.KernelSizeMax}")
    writer.println(s"#define CUTE_STRIDE_SIZE_MAX ${params.StrideSizeMax}")
    writer.println(s"#define CUTE_APPLICATION_MAX_TENSOR_SIZE ${params.ApplicationMaxTensorSize}")
    writer.println()

    // Scratchpad 相关参数（从参数计算）
    writer.println("// Scratchpad Configuration (derived from CuteParams)")
    writer.println(s"#define CUTE_REDUCE_GROUP_SIZE ${params.Tensor_K / params.ReduceWidthByte}")
    writer.println(s"#define CUTE_REDUCE_WIDTH ${params.ReduceWidthByte * 8}")
    writer.println(s"#define CUTE_RESULT_WIDTH ${params.ResultWidthByte * 8}")
    writer.println()

    // MMU 相关参数
    writer.println("// MMU Configuration (from CuteMMUParams)")
    writer.println(s"#define CUTE_MMU_VPN_BITS ${params.MMUParams.vpnBits}")
    writer.println(s"#define CUTE_MMU_PPN_BITS ${params.MMUParams.ppnBits}")
    writer.println(s"#define CUTE_MMU_PGIDX_BITS ${params.MMUParams.pgIdxBits}")
    writer.println(s"#define CUTE_MMU_VADDR_BITS ${params.MMUParams.vaddrBits}")
    writer.println(s"#define CUTE_MMU_PADDR_BITS ${params.MMUParams.paddrBits}")
    writer.println(s"#define CUTE_MMU_CORE_PADDR_BITS ${params.MMUParams.corePAddrBits}")
    writer.println()

    // FPE 相关参数
    writer.println("// FPE Configuration (from CuteFPEParams)")
    writer.println(s"#define CUTE_FPE_MIN_GROUP_SIZE ${params.FPEparams.MinGroupSize}")
    writer.println(s"#define CUTE_FPE_MIN_DATA_TYPE_WIDTH ${params.FPEparams.MinDataTypeWidth}")
    writer.println(s"#define CUTE_FPE_SCALE_WIDTH ${params.FPEparams.ScaleWidth}")
    writer.println(s"#define CUTE_FPE_COMP_TREE_LAYERS ${params.FPEparams.cmptreelayers}")
    writer.println(s"#define CUTE_FPE_FP8_COMP_TREE_LAYERS ${params.FPEparams.fp8cmptreelayers}")
    writer.println()

    writer.println("#endif // CUTE_VALIDATION_H")
    writer.close()
    println(s" Generated: $outputDir/validation.h.generated")
  }

  /**
   * 生成instruction.h.generated（指令集定义）
   */
  def generateInstHeader(params: CuteParams, outputDir: String): Unit = {
    val writer = new PrintWriter(new File(s"$outputDir/instruction.h.generated"))

    writer.println(s"/**")
    writer.println(s" * Auto-generated from CuteInstConfigs")
    writer.println(s" * DO NOT EDIT MANUALLY")
    writer.println(s" * Generated at: ${new java.util.Date()}")
    writer.println(s" */")
    writer.println()
    writer.println("#ifndef CUTE_INSTRUCTION_H")
    writer.println("#define CUTE_INSTRUCTION_H")
    writer.println()
    writer.println("#include <stdint.h>")
    writer.println()

    // 生成funct常量定义
    generateFunctDefines(writer, params)
    writer.println()

    // 生成字段定义
    generateFieldDefines(writer, params)
    writer.println()

    // 生成提取宏
    generateExtractionMacros(writer, params)
    writer.println()

    // 生成组装宏
    generateAssemblyMacros(writer, params)
    writer.println()

    // 生成指令文档
    generateInstDocumentation(writer, params)
    writer.println()

    writer.println("#endif // CUTE_INSTRUCTION_H")
    writer.close()
    println(s"✓ Generated: $outputDir/instruction.h.generated")
  }

  /**
   * 生成funct常量定义
   */
  private def generateFunctDefines(writer: PrintWriter, params: CuteParams): Unit = {
    writer.println("// ========================================")
    writer.println("// Instruction Function Codes")
    writer.println("// ========================================")
    params.allInstConfigs.foreach { inst =>
      val macroName = s"CUTE_INST_FUNCT_${inst.name}"
      writer.println(s"#define ${macroName.padTo(45, ' ')} ${inst.funct}  // ${inst.description}")
    }
    writer.println()
  }

  /**
   * 生成字段定义
   */
  private def generateFieldDefines(writer: PrintWriter, params: CuteParams): Unit = {
    writer.println("// ========================================")
    writer.println("// Instruction Field Definitions")
    writer.println("// ========================================")
    writer.println()

    params.allInstConfigs.foreach { inst =>
      writer.println(s"// Instruction: ${inst.name} (funct = ${inst.funct})")
      writer.println(s"// ${inst.description}")

      inst.cfgData1Fields match {
        case Some(fields) =>
          writer.println("// cfgData1 fields:")
          fields.foreach { field =>
            val macroName = s"CUTE_INST_${inst.name}_CFGDATA1_${field.name}"
            val hiStr = s"${macroName}_HI".padTo(60, ' ')
            val loStr = s"${macroName}_LO".padTo(60, ' ')
            val widthStr = s"${macroName}_WIDTH".padTo(60, ' ')

            writer.println(s"#define ${hiStr} ${field.bitHigh}")
            writer.println(s"#define ${loStr} ${field.bitLow}  // ${field.description}")

            // 生成MAX_VALUE宏（如果有约束）
            field.maxValue match {
              case Some(maxVal) =>
                val maxStr = s"${macroName}_MAX_VALUE".padTo(60, ' ')
                writer.println(s"#define ${maxStr} ${maxVal}UL  // 软件填值不应超过此值")
              case None => // 无约束（如地址字段）
            }

            writer.println(s"#define ${widthStr} ${field.width}")
          }
        case None => // 不使用cfgData1
      }

      inst.cfgData2Fields match {
        case Some(fields) =>
          writer.println("// cfgData2 fields:")
          fields.foreach { field =>
            val macroName = s"CUTE_INST_${inst.name}_CFGDATA2_${field.name}"
            val hiStr = s"${macroName}_HI".padTo(60, ' ')
            val loStr = s"${macroName}_LO".padTo(60, ' ')
            val widthStr = s"${macroName}_WIDTH".padTo(60, ' ')

            writer.println(s"#define ${hiStr} ${field.bitHigh}")
            writer.println(s"#define ${loStr} ${field.bitLow}  // ${field.description}")

            // 生成MAX_VALUE宏（如果有约束）
            field.maxValue match {
              case Some(maxVal) =>
                val maxStr = s"${macroName}_MAX_VALUE".padTo(60, ' ')
                writer.println(s"#define ${maxStr} ${maxVal}UL  // 软件填值不应超过此值")
              case None => // 无约束（如地址字段）
            }

            writer.println(s"#define ${widthStr} ${field.width}")
          }
        case None => // 不使用cfgData2
      }

      writer.println()
    }
  }

  /**
   * 生成字段提取宏
   */
  private def generateExtractionMacros(writer: PrintWriter, params: CuteParams): Unit = {
    writer.println("// ========================================")
    writer.println("// Field Extraction Macros")
    writer.println("// ========================================")
    writer.println()

    params.allInstConfigs.foreach { inst =>
      // cfgData1提取宏
      inst.cfgData1Fields match {
        case Some(fields) =>
          writer.println(s"// Extract fields for ${inst.name} (cfgData1)")
          fields.foreach { field =>
            val macroName = s"CUTE_GET_${inst.name}_CFGDATA1_${field.name}"
            val mask = (BigInt(1) << field.width) - 1
            val maskHex = f"0x${mask}%X"
            writer.println(s"#define ${macroName}(cfgdata1) (((cfgdata1) >> ${field.bitLow}) & ${maskHex}UL)")
          }
          writer.println()
        case None =>
      }

      // cfgData2提取宏
      inst.cfgData2Fields match {
        case Some(fields) =>
          writer.println(s"// Extract fields for ${inst.name} (cfgData2)")
          fields.foreach { field =>
            val macroName = s"CUTE_GET_${inst.name}_CFGDATA2_${field.name}"
            val mask = (BigInt(1) << field.width) - 1
            val maskHex = f"0x${mask}%X"
            writer.println(s"#define ${macroName}(cfgdata2) (((cfgdata2) >> ${field.bitLow}) & ${maskHex}UL)")
          }
          writer.println()
        case None =>
      }
    }
  }

  /**
   * 生成字段组装宏
   */
  private def generateAssemblyMacros(writer: PrintWriter, params: CuteParams): Unit = {
    writer.println("// ========================================")
    writer.println("// Field Assembly Macros")
    writer.println("// ========================================")
    writer.println()

    params.allInstConfigs.foreach { inst =>
      // cfgData1组装宏
      inst.cfgData1Fields match {
        case Some(fields) =>
          val macroName = s"CUTE_ASSEMBLY_${inst.name}_CFGDATA1"
          val paramsList = fields.map(f => f.name.toLowerCase).mkString(", ")
          writer.println(s"// Assemble cfgData1 for ${inst.name}")
          writer.println(s"#define ${macroName}(${paramsList}) \\")
          fields.reverse.zipWithIndex.foreach { case (field, idx) =>
            val mask = (BigInt(1) << field.width) - 1
            val maskHex = f"0x${mask}%X"
            val isLast = idx == fields.length - 1
            val line = if (isLast) "" else " | \\"
            writer.println(s"  ((((uint64_t)(${field.name.toLowerCase})) & ${maskHex}UL) << ${field.bitLow})${line}")
          }
          writer.println()
        case None =>
      }

      // cfgData2组装宏
      inst.cfgData2Fields match {
        case Some(fields) =>
          val macroName = s"CUTE_ASSEMBLY_${inst.name}_CFGDATA2"
          val paramsList = fields.map(f => f.name.toLowerCase).mkString(", ")
          writer.println(s"// Assemble cfgData2 for ${inst.name}")
          writer.println(s"#define ${macroName}(${paramsList}) \\")
          fields.reverse.zipWithIndex.foreach { case (field, idx) =>
            val mask = (BigInt(1) << field.width) - 1
            val maskHex = f"0x${mask}%X"
            val isLast = idx == fields.length - 1
            val line = if (isLast) "" else " | \\"
            writer.println(s"  ((((uint64_t)(${field.name.toLowerCase})) & ${maskHex}UL) << ${field.bitLow})${line}")
          }
          writer.println()
        case None =>
      }
    }
  }

  /**
   * 生成指令文档（注释格式）
   */
  private def generateInstDocumentation(writer: PrintWriter, params: CuteParams): Unit = {
    writer.println("/*")
    writer.println(" * ========================================")
    writer.println(" * Instruction Set Documentation")
    writer.println(" * ========================================")
    writer.println(" */")
    writer.println()

    params.allInstConfigs.foreach { inst =>
      writer.println(s"/*")
      writer.println(s" * Instruction: ${inst.name}")
      writer.println(s" * Funct: ${inst.funct}")
      writer.println(s" * Description: ${inst.description}")
      writer.println(s" *")

      inst.cfgData1Fields match {
        case Some(fields) =>
          writer.println(s" * cfgData1:")
          fields.foreach { field =>
            writer.println(s" *   [${field.bitHigh}:${field.bitLow}] ${field.name} - ${field.description}")
          }
        case None =>
          writer.println(s" * cfgData1: Not used")
      }

      inst.cfgData2Fields match {
        case Some(fields) =>
          writer.println(s" * cfgData2:")
          fields.foreach { field =>
            writer.println(s" *   [${field.bitHigh}:${field.bitLow}] ${field.name} - ${field.description}")
          }
        case None =>
          writer.println(s" * cfgData2: Not used")
      }

      writer.println(s" */")
      writer.println()
    }
  }

  def main(args: Array[String]): Unit = {
    if (args.length < 2) {
      println("""
╔═══════════════════════════════════════════════════════════════╗
║           CUTE Header Generation Script                        ║
║     Extract REAL parameters from Config classes                ║
╚═══════════════════════════════════════════════════════════════╝

USAGE:
    runMain cute.util.HeaderGenerator <OUTPUT_DIR> <CONFIG_NAME>

ARGUMENTS:
    OUTPUT_DIR     Output directory for generated headers
    CONFIG_NAME    Full Config class name (e.g., chipyard.CUTE4TopsSCP128Config)

EXAMPLES:
    # Generate from a Config class
    sbt "runMain cute.util.HeaderGenerator /root/opencute/CUTE/cutetest/include chipyard.CUTE4TopsSCP128Config"

    # Generate with custom output directory
    sbt "runMain cute.util.HeaderGenerator /tmp/headers chipyard.CUTE2TopsSCP64Config"

This tool will:
  1. Load the Config class using reflection
  2. Extract the complete Parameters from the Config
  3. Retrieve CuteParams from the Parameters
  4. Generate C header files with REAL values from the Config

""")
      sys.exit(1)
    }

    val outputDir = args(0)
    val configName = args(1)

    println("╔═══════════════════════════════════════════════════════════════╗")
    println("║           CUTE Header Generation                               ║")
    println("║       Extracting REAL parameters from Config                  ║")
    println("╚═══════════════════════════════════════════════════════════════╝")
    println()
    println(s"Output directory: $outputDir")
    println(s"Config class: $configName")
    println()

    // 确保输出目录存在
    new File(outputDir).mkdirs()

    // 从 Config 类中提取参数
    val paramsTry = extractParamsFromConfig(configName)

    paramsTry match {
      case Success(params) =>
        println()
        println("─────────────────────────────────────────────────────────────")
        println("Generating headers...")
        println("─────────────────────────────────────────────────────────────")
        println()

        generateDataTypeHeader(params, outputDir)
        generateValidationHeader(params, outputDir)
        generateInstHeader(params, outputDir)

        println()
        println("╔═══════════════════════════════════════════════════════════════╗")
        println("║    Headers generated successfully!                            ║")
        println("║   Parameters extracted from actual Config class               ║")
        println("╚═══════════════════════════════════════════════════════════════╝")

      case Failure(exception) =>
        println()
        println("╔═══════════════════════════════════════════════════════════════╗")
        println("║    Error extracting parameters from Config                    ║")
        println("╚═══════════════════════════════════════════════════════════════╝")
        println()
        println(s"Error: ${exception.getMessage}")
        println()
        println("Common issues:")
        println("  1. Config class name is incorrect")
        println("  2. Config class is not in the classpath")
        println("  3. Missing dependencies")
        println()
        println("Please ensure:")
        println("  - Using full package name (e.g., chipyard.CUTE4TopsSCP128Config)")
        println("  - Running from chipyard directory with proper environment")
        println()
        exception.printStackTrace()
        sys.exit(1)
    }
  }
}
