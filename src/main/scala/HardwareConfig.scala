// Auto-generated from configs/cute_configs/*.yaml
// DO NOT EDIT MANUALLY.
// Generated at: Tue May 12 17:44:40 2026

package cute

object HardwareConfig {
  def baseParams: CuteParams = CuteParams()

  // 0.5Tops + 64x64x64 tile。最小配置，用于面积验证。
  def CUTE_05Tops_64SCP: CuteParams = CuteParams(
      outsideDataWidth = 512,
      MemoryDataWidth = 64,
      VectorWidth = 256,
      ConvolutionDIM_Max = 65535,
      Convolution_Input_Height_Weight_Dim_Max = 16383,
      KernelSizeMax = 15,
      StrideSizeMax = 3,
      ApplicationMaxTensorSize = 65535,
      MMUAddrWidth = 39,
      LLCSourceMaxNum = 64,
      MemorysourceMaxNum = 64,
      Tensor_M = 64,
      Tensor_N = 64,
      Tensor_K = 64,
      Matrix_M = 2,
      Matrix_N = 2,
      ReduceWidthByte = 32,
      ResultWidthByte = 4,
      ResultFIFODepth = 8,
      VecTaskInstBufferDepth = 32,
      VecTaskInstBufferSize = 8,
      VecTaskDataBufferDepth = 4,
      MMUParams = CuteMMUParams(
        vpnBits = 12,
        ppnBits = 12,
        pgIdxBits = 12,
        vaddrBits = 39,
        paddrBits = 39,
        corePAddrBits = 64
      ),
      FPEparams = CuteFPEParams(
        MinGroupSize = 16,
        MinDataTypeWidth = 4,
        ScaleElementWidth = 8,
        cmptreelayers = 4,
        fp8cmptreelayers = 4
      ),
      EnablePerfCounter = false
    )

  // 16Tops + 256x256x64 tile
  def CUTE_16Tops_256SCP: CuteParams = CuteParams(
      outsideDataWidth = 512,
      MemoryDataWidth = 64,
      VectorWidth = 256,
      ConvolutionDIM_Max = 65535,
      Convolution_Input_Height_Weight_Dim_Max = 16383,
      KernelSizeMax = 15,
      StrideSizeMax = 3,
      ApplicationMaxTensorSize = 65535,
      MMUAddrWidth = 39,
      LLCSourceMaxNum = 64,
      MemorysourceMaxNum = 64,
      Tensor_M = 256,
      Tensor_N = 256,
      Tensor_K = 64,
      Matrix_M = 8,
      Matrix_N = 8,
      ReduceWidthByte = 64,
      ResultWidthByte = 4,
      ResultFIFODepth = 8,
      VecTaskInstBufferDepth = 32,
      VecTaskInstBufferSize = 8,
      VecTaskDataBufferDepth = 4,
      MMUParams = CuteMMUParams(
        vpnBits = 12,
        ppnBits = 12,
        pgIdxBits = 12,
        vaddrBits = 39,
        paddrBits = 39,
        corePAddrBits = 64
      ),
      FPEparams = CuteFPEParams(
        MinGroupSize = 16,
        MinDataTypeWidth = 4,
        ScaleElementWidth = 8,
        cmptreelayers = 4,
        fp8cmptreelayers = 4
      ),
      EnablePerfCounter = false
    )

  // 16Tops + 512x512x64 tile
  def CUTE_16Tops_512SCP: CuteParams = CuteParams(
      outsideDataWidth = 512,
      MemoryDataWidth = 64,
      VectorWidth = 256,
      ConvolutionDIM_Max = 65535,
      Convolution_Input_Height_Weight_Dim_Max = 16383,
      KernelSizeMax = 15,
      StrideSizeMax = 3,
      ApplicationMaxTensorSize = 65535,
      MMUAddrWidth = 39,
      LLCSourceMaxNum = 64,
      MemorysourceMaxNum = 64,
      Tensor_M = 512,
      Tensor_N = 512,
      Tensor_K = 64,
      Matrix_M = 8,
      Matrix_N = 8,
      ReduceWidthByte = 64,
      ResultWidthByte = 4,
      ResultFIFODepth = 8,
      VecTaskInstBufferDepth = 32,
      VecTaskInstBufferSize = 8,
      VecTaskDataBufferDepth = 4,
      MMUParams = CuteMMUParams(
        vpnBits = 12,
        ppnBits = 12,
        pgIdxBits = 12,
        vaddrBits = 39,
        paddrBits = 39,
        corePAddrBits = 64
      ),
      FPEparams = CuteFPEParams(
        MinGroupSize = 16,
        MinDataTypeWidth = 4,
        ScaleElementWidth = 8,
        cmptreelayers = 4,
        fp8cmptreelayers = 4
      ),
      EnablePerfCounter = false
    )

  // 1Tops + 128x128x64 tile
  def CUTE_1Tops_128SCP: CuteParams = CuteParams(
      outsideDataWidth = 512,
      MemoryDataWidth = 64,
      VectorWidth = 256,
      ConvolutionDIM_Max = 65535,
      Convolution_Input_Height_Weight_Dim_Max = 16383,
      KernelSizeMax = 15,
      StrideSizeMax = 3,
      ApplicationMaxTensorSize = 65535,
      MMUAddrWidth = 39,
      LLCSourceMaxNum = 64,
      MemorysourceMaxNum = 64,
      Tensor_M = 128,
      Tensor_N = 128,
      Tensor_K = 64,
      Matrix_M = 2,
      Matrix_N = 2,
      ReduceWidthByte = 64,
      ResultWidthByte = 4,
      ResultFIFODepth = 8,
      VecTaskInstBufferDepth = 32,
      VecTaskInstBufferSize = 8,
      VecTaskDataBufferDepth = 4,
      MMUParams = CuteMMUParams(
        vpnBits = 12,
        ppnBits = 12,
        pgIdxBits = 12,
        vaddrBits = 39,
        paddrBits = 39,
        corePAddrBits = 64
      ),
      FPEparams = CuteFPEParams(
        MinGroupSize = 16,
        MinDataTypeWidth = 4,
        ScaleElementWidth = 8,
        cmptreelayers = 4,
        fp8cmptreelayers = 4
      ),
      EnablePerfCounter = false
    )

  // 1Tops + 64x64x64 tile
  def CUTE_1Tops_64SCP: CuteParams = CuteParams(
      outsideDataWidth = 512,
      MemoryDataWidth = 64,
      VectorWidth = 256,
      ConvolutionDIM_Max = 65535,
      Convolution_Input_Height_Weight_Dim_Max = 16383,
      KernelSizeMax = 15,
      StrideSizeMax = 3,
      ApplicationMaxTensorSize = 65535,
      MMUAddrWidth = 39,
      LLCSourceMaxNum = 64,
      MemorysourceMaxNum = 64,
      Tensor_M = 64,
      Tensor_N = 64,
      Tensor_K = 64,
      Matrix_M = 2,
      Matrix_N = 2,
      ReduceWidthByte = 64,
      ResultWidthByte = 4,
      ResultFIFODepth = 8,
      VecTaskInstBufferDepth = 32,
      VecTaskInstBufferSize = 8,
      VecTaskDataBufferDepth = 4,
      MMUParams = CuteMMUParams(
        vpnBits = 12,
        ppnBits = 12,
        pgIdxBits = 12,
        vaddrBits = 39,
        paddrBits = 39,
        corePAddrBits = 64
      ),
      FPEparams = CuteFPEParams(
        MinGroupSize = 16,
        MinDataTypeWidth = 4,
        ScaleElementWidth = 8,
        cmptreelayers = 4,
        fp8cmptreelayers = 4
      ),
      EnablePerfCounter = false
    )

  // 2Tops + 128x128x64 tile
  def CUTE_2Tops_128SCP: CuteParams = CuteParams(
      outsideDataWidth = 512,
      MemoryDataWidth = 64,
      VectorWidth = 256,
      ConvolutionDIM_Max = 65535,
      Convolution_Input_Height_Weight_Dim_Max = 16383,
      KernelSizeMax = 15,
      StrideSizeMax = 3,
      ApplicationMaxTensorSize = 65535,
      MMUAddrWidth = 39,
      LLCSourceMaxNum = 64,
      MemorysourceMaxNum = 64,
      Tensor_M = 128,
      Tensor_N = 128,
      Tensor_K = 64,
      Matrix_M = 4,
      Matrix_N = 4,
      ReduceWidthByte = 32,
      ResultWidthByte = 4,
      ResultFIFODepth = 8,
      VecTaskInstBufferDepth = 32,
      VecTaskInstBufferSize = 8,
      VecTaskDataBufferDepth = 4,
      MMUParams = CuteMMUParams(
        vpnBits = 12,
        ppnBits = 12,
        pgIdxBits = 12,
        vaddrBits = 39,
        paddrBits = 39,
        corePAddrBits = 64
      ),
      FPEparams = CuteFPEParams(
        MinGroupSize = 16,
        MinDataTypeWidth = 4,
        ScaleElementWidth = 8,
        cmptreelayers = 4,
        fp8cmptreelayers = 4
      ),
      EnablePerfCounter = false
    )

  // 2Tops + 256x256x64 tile
  def CUTE_2Tops_256SCP: CuteParams = CuteParams(
      outsideDataWidth = 512,
      MemoryDataWidth = 64,
      VectorWidth = 256,
      ConvolutionDIM_Max = 65535,
      Convolution_Input_Height_Weight_Dim_Max = 16383,
      KernelSizeMax = 15,
      StrideSizeMax = 3,
      ApplicationMaxTensorSize = 65535,
      MMUAddrWidth = 39,
      LLCSourceMaxNum = 64,
      MemorysourceMaxNum = 64,
      Tensor_M = 256,
      Tensor_N = 256,
      Tensor_K = 64,
      Matrix_M = 4,
      Matrix_N = 4,
      ReduceWidthByte = 32,
      ResultWidthByte = 4,
      ResultFIFODepth = 8,
      VecTaskInstBufferDepth = 32,
      VecTaskInstBufferSize = 8,
      VecTaskDataBufferDepth = 4,
      MMUParams = CuteMMUParams(
        vpnBits = 12,
        ppnBits = 12,
        pgIdxBits = 12,
        vaddrBits = 39,
        paddrBits = 39,
        corePAddrBits = 64
      ),
      FPEparams = CuteFPEParams(
        MinGroupSize = 16,
        MinDataTypeWidth = 4,
        ScaleElementWidth = 8,
        cmptreelayers = 4,
        fp8cmptreelayers = 4
      ),
      EnablePerfCounter = false
    )

  // 2Tops + 64x64x64 tile
  def CUTE_2Tops_64SCP: CuteParams = CuteParams(
      outsideDataWidth = 512,
      MemoryDataWidth = 64,
      VectorWidth = 256,
      ConvolutionDIM_Max = 65535,
      Convolution_Input_Height_Weight_Dim_Max = 16383,
      KernelSizeMax = 15,
      StrideSizeMax = 3,
      ApplicationMaxTensorSize = 65535,
      MMUAddrWidth = 39,
      LLCSourceMaxNum = 64,
      MemorysourceMaxNum = 64,
      Tensor_M = 64,
      Tensor_N = 64,
      Tensor_K = 64,
      Matrix_M = 4,
      Matrix_N = 4,
      ReduceWidthByte = 32,
      ResultWidthByte = 4,
      ResultFIFODepth = 8,
      VecTaskInstBufferDepth = 32,
      VecTaskInstBufferSize = 8,
      VecTaskDataBufferDepth = 4,
      MMUParams = CuteMMUParams(
        vpnBits = 12,
        ppnBits = 12,
        pgIdxBits = 12,
        vaddrBits = 39,
        paddrBits = 39,
        corePAddrBits = 64
      ),
      FPEparams = CuteFPEParams(
        MinGroupSize = 16,
        MinDataTypeWidth = 4,
        ScaleElementWidth = 8,
        cmptreelayers = 4,
        fp8cmptreelayers = 4
      ),
      EnablePerfCounter = false
    )

  // 32Tops + 512x512x64 tile。最大算力配置
  def CUTE_32Tops_512SCP: CuteParams = CuteParams(
      outsideDataWidth = 512,
      MemoryDataWidth = 64,
      VectorWidth = 256,
      ConvolutionDIM_Max = 65535,
      Convolution_Input_Height_Weight_Dim_Max = 16383,
      KernelSizeMax = 15,
      StrideSizeMax = 3,
      ApplicationMaxTensorSize = 65535,
      MMUAddrWidth = 39,
      LLCSourceMaxNum = 64,
      MemorysourceMaxNum = 64,
      Tensor_M = 512,
      Tensor_N = 512,
      Tensor_K = 64,
      Matrix_M = 16,
      Matrix_N = 16,
      ReduceWidthByte = 32,
      ResultWidthByte = 4,
      ResultFIFODepth = 8,
      VecTaskInstBufferDepth = 32,
      VecTaskInstBufferSize = 8,
      VecTaskDataBufferDepth = 4,
      MMUParams = CuteMMUParams(
        vpnBits = 12,
        ppnBits = 12,
        pgIdxBits = 12,
        vaddrBits = 39,
        paddrBits = 39,
        corePAddrBits = 64
      ),
      FPEparams = CuteFPEParams(
        MinGroupSize = 16,
        MinDataTypeWidth = 4,
        ScaleElementWidth = 8,
        cmptreelayers = 4,
        fp8cmptreelayers = 4
      ),
      EnablePerfCounter = false
    )

  // 4Tops + 128x128x64 tile
  def CUTE_4Tops_128SCP: CuteParams = CuteParams(
      outsideDataWidth = 512,
      MemoryDataWidth = 64,
      VectorWidth = 256,
      ConvolutionDIM_Max = 65535,
      Convolution_Input_Height_Weight_Dim_Max = 16383,
      KernelSizeMax = 15,
      StrideSizeMax = 3,
      ApplicationMaxTensorSize = 65535,
      MMUAddrWidth = 39,
      LLCSourceMaxNum = 64,
      MemorysourceMaxNum = 64,
      Tensor_M = 128,
      Tensor_N = 128,
      Tensor_K = 64,
      Matrix_M = 4,
      Matrix_N = 4,
      ReduceWidthByte = 64,
      ResultWidthByte = 4,
      ResultFIFODepth = 8,
      VecTaskInstBufferDepth = 32,
      VecTaskInstBufferSize = 8,
      VecTaskDataBufferDepth = 4,
      MMUParams = CuteMMUParams(
        vpnBits = 12,
        ppnBits = 12,
        pgIdxBits = 12,
        vaddrBits = 39,
        paddrBits = 39,
        corePAddrBits = 64
      ),
      FPEparams = CuteFPEParams(
        MinGroupSize = 16,
        MinDataTypeWidth = 4,
        ScaleElementWidth = 8,
        cmptreelayers = 4,
        fp8cmptreelayers = 4
      ),
      EnablePerfCounter = false
    )

  // 4Tops + 256x256x64 tile
  def CUTE_4Tops_256SCP: CuteParams = CuteParams(
      outsideDataWidth = 512,
      MemoryDataWidth = 64,
      VectorWidth = 256,
      ConvolutionDIM_Max = 65535,
      Convolution_Input_Height_Weight_Dim_Max = 16383,
      KernelSizeMax = 15,
      StrideSizeMax = 3,
      ApplicationMaxTensorSize = 65535,
      MMUAddrWidth = 39,
      LLCSourceMaxNum = 64,
      MemorysourceMaxNum = 64,
      Tensor_M = 256,
      Tensor_N = 256,
      Tensor_K = 64,
      Matrix_M = 4,
      Matrix_N = 4,
      ReduceWidthByte = 64,
      ResultWidthByte = 4,
      ResultFIFODepth = 8,
      VecTaskInstBufferDepth = 32,
      VecTaskInstBufferSize = 8,
      VecTaskDataBufferDepth = 4,
      MMUParams = CuteMMUParams(
        vpnBits = 12,
        ppnBits = 12,
        pgIdxBits = 12,
        vaddrBits = 39,
        paddrBits = 39,
        corePAddrBits = 64
      ),
      FPEparams = CuteFPEParams(
        MinGroupSize = 16,
        MinDataTypeWidth = 4,
        ScaleElementWidth = 8,
        cmptreelayers = 4,
        fp8cmptreelayers = 4
      ),
      EnablePerfCounter = false
    )

  // 4Tops + 512x512x64 tile
  def CUTE_4Tops_512SCP: CuteParams = CuteParams(
      outsideDataWidth = 512,
      MemoryDataWidth = 64,
      VectorWidth = 256,
      ConvolutionDIM_Max = 65535,
      Convolution_Input_Height_Weight_Dim_Max = 16383,
      KernelSizeMax = 15,
      StrideSizeMax = 3,
      ApplicationMaxTensorSize = 65535,
      MMUAddrWidth = 39,
      LLCSourceMaxNum = 64,
      MemorysourceMaxNum = 64,
      Tensor_M = 512,
      Tensor_N = 512,
      Tensor_K = 64,
      Matrix_M = 4,
      Matrix_N = 4,
      ReduceWidthByte = 64,
      ResultWidthByte = 4,
      ResultFIFODepth = 8,
      VecTaskInstBufferDepth = 32,
      VecTaskInstBufferSize = 8,
      VecTaskDataBufferDepth = 4,
      MMUParams = CuteMMUParams(
        vpnBits = 12,
        ppnBits = 12,
        pgIdxBits = 12,
        vaddrBits = 39,
        paddrBits = 39,
        corePAddrBits = 64
      ),
      FPEparams = CuteFPEParams(
        MinGroupSize = 16,
        MinDataTypeWidth = 4,
        ScaleElementWidth = 8,
        cmptreelayers = 4,
        fp8cmptreelayers = 4
      ),
      EnablePerfCounter = false
    )

  // 4Tops + 64x64x64 tile
  def CUTE_4Tops_64SCP: CuteParams = CuteParams(
      outsideDataWidth = 512,
      MemoryDataWidth = 64,
      VectorWidth = 256,
      ConvolutionDIM_Max = 65535,
      Convolution_Input_Height_Weight_Dim_Max = 16383,
      KernelSizeMax = 15,
      StrideSizeMax = 3,
      ApplicationMaxTensorSize = 65535,
      MMUAddrWidth = 39,
      LLCSourceMaxNum = 64,
      MemorysourceMaxNum = 64,
      Tensor_M = 64,
      Tensor_N = 64,
      Tensor_K = 64,
      Matrix_M = 4,
      Matrix_N = 4,
      ReduceWidthByte = 64,
      ResultWidthByte = 4,
      ResultFIFODepth = 8,
      VecTaskInstBufferDepth = 32,
      VecTaskInstBufferSize = 8,
      VecTaskDataBufferDepth = 4,
      MMUParams = CuteMMUParams(
        vpnBits = 12,
        ppnBits = 12,
        pgIdxBits = 12,
        vaddrBits = 39,
        paddrBits = 39,
        corePAddrBits = 64
      ),
      FPEparams = CuteFPEParams(
        MinGroupSize = 16,
        MinDataTypeWidth = 4,
        ScaleElementWidth = 8,
        cmptreelayers = 4,
        fp8cmptreelayers = 4
      ),
      EnablePerfCounter = false
    )

  // 8Tops + 128x128x64 tile
  def CUTE_8Tops_128SCP: CuteParams = CuteParams(
      outsideDataWidth = 512,
      MemoryDataWidth = 64,
      VectorWidth = 256,
      ConvolutionDIM_Max = 65535,
      Convolution_Input_Height_Weight_Dim_Max = 16383,
      KernelSizeMax = 15,
      StrideSizeMax = 3,
      ApplicationMaxTensorSize = 65535,
      MMUAddrWidth = 39,
      LLCSourceMaxNum = 64,
      MemorysourceMaxNum = 64,
      Tensor_M = 128,
      Tensor_N = 128,
      Tensor_K = 64,
      Matrix_M = 8,
      Matrix_N = 8,
      ReduceWidthByte = 32,
      ResultWidthByte = 4,
      ResultFIFODepth = 8,
      VecTaskInstBufferDepth = 32,
      VecTaskInstBufferSize = 8,
      VecTaskDataBufferDepth = 4,
      MMUParams = CuteMMUParams(
        vpnBits = 12,
        ppnBits = 12,
        pgIdxBits = 12,
        vaddrBits = 39,
        paddrBits = 39,
        corePAddrBits = 64
      ),
      FPEparams = CuteFPEParams(
        MinGroupSize = 16,
        MinDataTypeWidth = 4,
        ScaleElementWidth = 8,
        cmptreelayers = 4,
        fp8cmptreelayers = 4
      ),
      EnablePerfCounter = false
    )

  // 8Tops + 256x256x64 tile
  def CUTE_8Tops_256SCP: CuteParams = CuteParams(
      outsideDataWidth = 512,
      MemoryDataWidth = 64,
      VectorWidth = 256,
      ConvolutionDIM_Max = 65535,
      Convolution_Input_Height_Weight_Dim_Max = 16383,
      KernelSizeMax = 15,
      StrideSizeMax = 3,
      ApplicationMaxTensorSize = 65535,
      MMUAddrWidth = 39,
      LLCSourceMaxNum = 64,
      MemorysourceMaxNum = 64,
      Tensor_M = 256,
      Tensor_N = 256,
      Tensor_K = 64,
      Matrix_M = 8,
      Matrix_N = 8,
      ReduceWidthByte = 32,
      ResultWidthByte = 4,
      ResultFIFODepth = 8,
      VecTaskInstBufferDepth = 32,
      VecTaskInstBufferSize = 8,
      VecTaskDataBufferDepth = 4,
      MMUParams = CuteMMUParams(
        vpnBits = 12,
        ppnBits = 12,
        pgIdxBits = 12,
        vaddrBits = 39,
        paddrBits = 39,
        corePAddrBits = 64
      ),
      FPEparams = CuteFPEParams(
        MinGroupSize = 16,
        MinDataTypeWidth = 4,
        ScaleElementWidth = 8,
        cmptreelayers = 4,
        fp8cmptreelayers = 4
      ),
      EnablePerfCounter = false
    )

  // 8Tops + 512x512x64 tile
  def CUTE_8Tops_512SCP: CuteParams = CuteParams(
      outsideDataWidth = 512,
      MemoryDataWidth = 64,
      VectorWidth = 256,
      ConvolutionDIM_Max = 65535,
      Convolution_Input_Height_Weight_Dim_Max = 16383,
      KernelSizeMax = 15,
      StrideSizeMax = 3,
      ApplicationMaxTensorSize = 65535,
      MMUAddrWidth = 39,
      LLCSourceMaxNum = 64,
      MemorysourceMaxNum = 64,
      Tensor_M = 512,
      Tensor_N = 512,
      Tensor_K = 64,
      Matrix_M = 8,
      Matrix_N = 8,
      ReduceWidthByte = 32,
      ResultWidthByte = 4,
      ResultFIFODepth = 8,
      VecTaskInstBufferDepth = 32,
      VecTaskInstBufferSize = 8,
      VecTaskDataBufferDepth = 4,
      MMUParams = CuteMMUParams(
        vpnBits = 12,
        ppnBits = 12,
        pgIdxBits = 12,
        vaddrBits = 39,
        paddrBits = 39,
        corePAddrBits = 64
      ),
      FPEparams = CuteFPEParams(
        MinGroupSize = 16,
        MinDataTypeWidth = 4,
        ScaleElementWidth = 8,
        cmptreelayers = 4,
        fp8cmptreelayers = 4
      ),
      EnablePerfCounter = false
    )

  val byId: Map[String, CuteParams] = Map(
    "CUTE_05Tops_64SCP" -> CUTE_05Tops_64SCP,
    "CUTE_16Tops_256SCP" -> CUTE_16Tops_256SCP,
    "CUTE_16Tops_512SCP" -> CUTE_16Tops_512SCP,
    "CUTE_1Tops_128SCP" -> CUTE_1Tops_128SCP,
    "CUTE_1Tops_64SCP" -> CUTE_1Tops_64SCP,
    "CUTE_2Tops_128SCP" -> CUTE_2Tops_128SCP,
    "CUTE_2Tops_256SCP" -> CUTE_2Tops_256SCP,
    "CUTE_2Tops_64SCP" -> CUTE_2Tops_64SCP,
    "CUTE_32Tops_512SCP" -> CUTE_32Tops_512SCP,
    "CUTE_4Tops_128SCP" -> CUTE_4Tops_128SCP,
    "CUTE_4Tops_256SCP" -> CUTE_4Tops_256SCP,
    "CUTE_4Tops_512SCP" -> CUTE_4Tops_512SCP,
    "CUTE_4Tops_64SCP" -> CUTE_4Tops_64SCP,
    "CUTE_8Tops_128SCP" -> CUTE_8Tops_128SCP,
    "CUTE_8Tops_256SCP" -> CUTE_8Tops_256SCP,
    "CUTE_8Tops_512SCP" -> CUTE_8Tops_512SCP
  )

  def get(id: String): Option[CuteParams] = byId.get(id)

  def requireById(id: String): CuteParams =
    byId.getOrElse(id, throw new NoSuchElementException(
      "unknown CUTE hardware config: " + id))
}
