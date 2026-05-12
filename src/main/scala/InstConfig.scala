// Auto-generated from configs/cute_isa_versions/cute_isa_v1.yaml
// DO NOT EDIT MANUALLY.
// Generated at: Tue May 12 20:28:51 2026

package cute

import chisel3._
import chisel3.util._
import org.chipsalliance.cde.config._

case class InstField(
  name: String,
  bitHigh: Int,
  bitLow: Int,
  maxValue: Option[Long],
  description: String
) {
  def width: Int = bitHigh - bitLow + 1
  def mask: Long = ((1L << width) - 1) << bitLow

  def requiredWidth: Int = maxValue match {
    case Some(v) => log2Ceil(v + 1)
    case None => width
  }

  require(width >= requiredWidth || maxValue.isEmpty,
    s"InstField $name: width=$width < requiredWidth=$requiredWidth " +
    s"(maxValue=$maxValue, bits [$bitHigh:$bitLow])")
}

object InstField {
  def apply(name: String, bitHigh: Int, bitLow: Int, maxValue: Long, description: String): InstField =
    new InstField(name, bitHigh, bitLow, Some(maxValue), description)

  def apply(name: String, bitHigh: Int, bitLow: Int, description: String): InstField =
    new InstField(name, bitHigh, bitLow, None, description)
}

sealed abstract class CuteInstConfig {
  def funct: Int
  def name: String
  def cfgData1Fields: Option[Seq[InstField]]
  def cfgData2Fields: Option[Seq[InstField]]
  def description: String
  def isYGJKInst: Boolean
  def returnDescription: String

  def usesCfgData1: Boolean = cfgData1Fields.isDefined
  def usesCfgData2: Boolean = cfgData2Fields.isDefined

  def field(fieldName: String): InstField = {
    val allFields = cfgData1Fields.toSeq.flatten ++ cfgData2Fields.toSeq.flatten
    allFields.find(_.name == fieldName).getOrElse(
      throw new NoSuchElementException(
        s"Field '$fieldName' not found in ${this.name}. " +
        s"Available fields: ${allFields.map(_.name).mkString(", ")}"))
  }
}

object YGJKInstConfigs {

  case object QueryAcceleratorBusy extends CuteInstConfig {
    def funct = 1
    def name = "QUERY_ACCELERATOR_BUSY"
    def cfgData1Fields = None
    def cfgData2Fields = None
    def description = "查询加速器是否正在运行"
    def isYGJKInst = true
    def returnDescription = "返回加速器是否忙碌 (1=忙碌, 0=空闲)"
  }

  case object QueryRuntime extends CuteInstConfig {
    def funct = 2
    def name = "QUERY_RUNTIME"
    def cfgData1Fields = None
    def cfgData2Fields = None
    def description = "查询加速器运行时间（时钟周期数）"
    def isYGJKInst = true
    def returnDescription = "返回加速器运行时间（时钟周期数）"
  }

  case object QueryMemReadCount extends CuteInstConfig {
    def funct = 3
    def name = "QUERY_MEM_READ_COUNT"
    def cfgData1Fields = None
    def cfgData2Fields = None
    def description = "查询加速器对外访存读次数"
    def isYGJKInst = true
    def returnDescription = "返回对外访存读次数"
  }

  case object QueryMemWriteCount extends CuteInstConfig {
    def funct = 4
    def name = "QUERY_MEM_WRITE_COUNT"
    def cfgData1Fields = None
    def cfgData2Fields = None
    def description = "查询加速器对外访存写次数"
    def isYGJKInst = true
    def returnDescription = "返回对外访存写次数"
  }

  case object QueryComputeTime extends CuteInstConfig {
    def funct = 5
    def name = "QUERY_COMPUTE_TIME"
    def cfgData1Fields = None
    def cfgData2Fields = None
    def description = "查询加速器计算时间"
    def isYGJKInst = true
    def returnDescription = "返回计算时间（时钟周期数）"
  }

  case object QueryMacroInstFinish extends CuteInstConfig {
    def funct = 6
    def name = "QUERY_MACRO_INST_FINISH"
    def cfgData1Fields = None
    def cfgData2Fields = None
    def description = "查询 CUTE 宏指令的完成情况"
    def isYGJKInst = true
    def returnDescription = "返回宏指令队列中的完成情况 (0010 = id为1的指令已完成)"
  }

  case object QueryMacroInstFIFOFull extends CuteInstConfig {
    def funct = 7
    def name = "QUERY_MACRO_INST_FIFO_FULL"
    def cfgData1Fields = None
    def cfgData2Fields = None
    def description = "查询 CUTE 宏指令队列是否已满"
    def isYGJKInst = true
    def returnDescription = "返回FIFO是否已满 (1=满, 0=未满)"
  }

  case object QueryMacroInstFIFOInfo extends CuteInstConfig {
    def funct = 8
    def name = "QUERY_MACRO_INST_FIFO_INFO"
    def cfgData1Fields = None
    def cfgData2Fields = None
    def description = "查询 CUTE 宏指令队列目前有多少指令"
    def isYGJKInst = true
    def returnDescription = "返回FIFO中当前指令状态 (0010 = id为1的位置已有指令)"
  }

  val allInsts: Seq[CuteInstConfig] = Seq(
    QueryAcceleratorBusy,
    QueryRuntime,
    QueryMemReadCount,
    QueryMemWriteCount,
    QueryComputeTime,
    QueryMacroInstFinish,
    QueryMacroInstFIFOFull,
    QueryMacroInstFIFOInfo
  ).sortBy(_.funct)

  def getInstByFunct(funct: Int): Option[CuteInstConfig] =
    allInsts.find(_.funct == funct)
}

object CuteInstConfigs {

  case object SendMacroInst extends CuteInstConfig {
    def funct = 0
    def name = "SEND_MACRO_INST"
    def cfgData1Fields = None
    def cfgData2Fields = None
    def description = "发送已配置的宏指令到指令FIFO"
    def isYGJKInst = false
    def returnDescription = "返回指令在FIFO中的编号"
  }

  case object ConfigTensorA extends CuteInstConfig {
    def funct = 1
    def name = "CONFIG_TENSOR_A"
    def cfgData1Fields = Some(Seq(InstField("ApplicationTensor_A_BaseVaddr", 63, 0, "A张量的基地址")))
    def cfgData2Fields = Some(Seq(InstField("ApplicationTensor_A_Stride", 63, 0, "A张量的步长")))
    def description = "配置A张量的基地址和步长"
    def isYGJKInst = false
    def returnDescription = "未使用"
  }

  case object ConfigTensorB extends CuteInstConfig {
    def funct = 2
    def name = "CONFIG_TENSOR_B"
    def cfgData1Fields = Some(Seq(InstField("ApplicationTensor_B_BaseVaddr", 63, 0, "B张量的基地址")))
    def cfgData2Fields = Some(Seq(InstField("ApplicationTensor_B_Stride", 63, 0, "B张量的步长")))
    def description = "配置B张量的基地址和步长"
    def isYGJKInst = false
    def returnDescription = "未使用"
  }

  case object ConfigTensorC extends CuteInstConfig {
    def funct = 3
    def name = "CONFIG_TENSOR_C"
    def cfgData1Fields = Some(Seq(InstField("ApplicationTensor_C_BaseVaddr", 63, 0, "C张量的基地址")))
    def cfgData2Fields = Some(Seq(InstField("ApplicationTensor_C_Stride", 63, 0, "C张量的步长")))
    def description = "配置C张量的基地址和步长"
    def isYGJKInst = false
    def returnDescription = "未使用"
  }

  case object ConfigTensorD extends CuteInstConfig {
    def funct = 4
    def name = "CONFIG_TENSOR_D"
    def cfgData1Fields = Some(Seq(InstField("ApplicationTensor_D_BaseVaddr", 63, 0, "D张量的基地址")))
    def cfgData2Fields = Some(Seq(InstField("ApplicationTensor_D_Stride", 63, 0, "D张量的步长")))
    def description = "配置D张量的基地址和步长"
    def isYGJKInst = false
    def returnDescription = "未使用"
  }

  case object ConfigTensorDim extends CuteInstConfig {
    def funct = 5
    def name = "CONFIG_TENSOR_DIM"
    def cfgData1Fields = Some(Seq(
      InstField("Application_M", 19, 0, 65535, "张量M维度 (max=65536)"),
      InstField("Application_N", 39, 20, 65535, "张量N维度 (max=65536)"),
      InstField("Application_K", 59, 40, 65535, "张量K维度 (max=65536)")
    ))
    def cfgData2Fields = Some(Seq(InstField("kernel_stride", 63, 0, "卷积核步长（矩阵乘时为0），64位地址无约束")))
    def description = "配置张量维度(M,N,K)，对于卷积则是(ohow,oc,ic)"
    def isYGJKInst = false
    def returnDescription = "未使用"
  }

  case object ConfigConvParams extends CuteInstConfig {
    def funct = 6
    def name = "CONFIG_CONV_PARAMS"
    def cfgData1Fields = Some(Seq(
      InstField("element_type", 7, 0, 15, "元素数据类型"),
      InstField("bias_type", 15, 8, 3, "C张量（bias）加载模式"),
      InstField("transpose_result", 23, 16, 1, "是否转置结果 (Bool, max=1)"),
      InstField("conv_stride", 31, 24, 3, "卷积步长 (max=4)"),
      InstField("conv_oh_max", 47, 32, 16383, "卷积输出高度最大值 (max=16384)"),
      InstField("conv_ow_max", 63, 48, 16383, "卷积输出宽度最大值 (max=16384)")
    ))
    def cfgData2Fields = Some(Seq(
      InstField("kernel_size", 7, 0, 15, "卷积核大小 (max=16)"),
      InstField("conv_oh_per_add", 25, 16, 1023, "卷积输出高度每次增加量 (max=1024)"),
      InstField("conv_ow_per_add", 35, 26, 1023, "卷积输出宽度每次增加量 (max=1024)"),
      InstField("conv_oh_index", 45, 36, 1023, "卷积输出的高起始值"),
      InstField("conv_ow_index", 55, 46, 1023, "卷积输出的宽起始值")
    ))
    def description = "配置卷积相关参数（element_type, bias_type, kernel_size等）"
    def isYGJKInst = false
    def returnDescription = "未使用"
  }

  case object ConfigScaleA extends CuteInstConfig {
    def funct = 7
    def name = "CONFIG_SCALE_A"
    def cfgData1Fields = Some(Seq(InstField("ApplicationScale_A_BaseVaddr", 63, 0, "A Scale的基地址")))
    def cfgData2Fields = None
    def description = "配置A Scale（量化参数）的基地址"
    def isYGJKInst = false
    def returnDescription = "未使用"
  }

  case object ConfigScaleB extends CuteInstConfig {
    def funct = 8
    def name = "CONFIG_SCALE_B"
    def cfgData1Fields = Some(Seq(InstField("ApplicationScale_B_BaseVaddr", 63, 0, "B Scale的基地址")))
    def cfgData2Fields = None
    def description = "配置B Scale（量化参数）的基地址"
    def isYGJKInst = false
    def returnDescription = "未使用"
  }

  case object ClearInst extends CuteInstConfig {
    def funct = 16
    def name = "CLEAR_INST"
    def cfgData1Fields = None
    def cfgData2Fields = None
    def description = "清除队尾的宏指令"
    def isYGJKInst = false
    def returnDescription = "未使用"
  }

  case object QueryInst extends CuteInstConfig {
    def funct = 17
    def name = "QUERY_INST"
    def cfgData1Fields = None
    def cfgData2Fields = None
    def description = "查询当前完成宏指令的尾编号位置"
    def isYGJKInst = false
    def returnDescription = "返回已完成宏指令的尾编号位置"
  }

  case object ReservedInst extends CuteInstConfig {
    def funct = 18
    def name = "RESERVED"
    def cfgData1Fields = None
    def cfgData2Fields = None
    def description = "保留指令（空操作）"
    def isYGJKInst = false
    def returnDescription = "未使用"
  }

  val allInsts: Seq[CuteInstConfig] = Seq(
    SendMacroInst,
    ConfigTensorA,
    ConfigTensorB,
    ConfigTensorC,
    ConfigTensorD,
    ConfigTensorDim,
    ConfigConvParams,
    ConfigScaleA,
    ConfigScaleB,
    ClearInst,
    QueryInst,
    ReservedInst
  ).sortBy(_.funct)

  def getInstByFunct(funct: Int): Option[CuteInstConfig] =
    allInsts.find(_.funct == funct)
}

case object ElementDataType extends Field[UInt] {
  val DataTypeBitWidth = 4
  val DataTypeUndef = 0.U(DataTypeBitWidth.W)
  val DataTypeWidth32 = 4.U(DataTypeBitWidth.W)
  val DataTypeWidth16 = 2.U(DataTypeBitWidth.W)
  val DataTypeWidth8 = 1.U(DataTypeBitWidth.W)
  val DataTypeI8I8I32 = 0.U(DataTypeBitWidth.W)
  val DataTypeF16F16F32 = 1.U(DataTypeBitWidth.W)
  val DataTypeBF16BF16F32 = 2.U(DataTypeBitWidth.W)
  val DataTypeTF32TF32F32 = 3.U(DataTypeBitWidth.W)
  val DataTypeI8U8I32 = 4.U(DataTypeBitWidth.W)
  val DataTypeU8I8I32 = 5.U(DataTypeBitWidth.W)
  val DataTypeU8U8I32 = 6.U(DataTypeBitWidth.W)
  val DataTypeMxfp8e4m3F32 = 7.U(DataTypeBitWidth.W)
  val DataTypeMxfp8e5m2F32 = 8.U(DataTypeBitWidth.W)
  val DataTypenvfp4F32 = 9.U(DataTypeBitWidth.W)
  val DataTypemxfp4F32 = 10.U(DataTypeBitWidth.W)
  val DataTypefp8e4m3F32 = 11.U(DataTypeBitWidth.W)
  val DataTypefp8e5m2F32 = 12.U(DataTypeBitWidth.W)
}

case object CMemoryLoaderTaskType extends Field[UInt] {
  val TypeBitWidth = 4
  val TaskTypeUndef = 0.U(TypeBitWidth.W)
  val TaskTypeTensorZeroLoad = 1.U(TypeBitWidth.W)
  val TaskTypeTensorRepeatRowLoad = 2.U(TypeBitWidth.W)
  val TaskTypeTensorLoad = 3.U(TypeBitWidth.W)
}
