package cute.trace

import chisel3.UInt

final case class CUTETraceContext(
  cycle: UInt,
  params: CUTETraceParams = CUTETraceParams.default
)
