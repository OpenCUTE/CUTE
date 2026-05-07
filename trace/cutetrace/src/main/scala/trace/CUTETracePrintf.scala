package cute.trace

import chisel3._

object CUTETracePrintf {
  def emit(
    cond: Bool,
    categoryId: Int
  )(compact: => Unit, human: => Unit)(implicit ctx: CUTETraceContext): Unit = {
    if (ctx.params.isEnabledFor(categoryId)) {
      ctx.params.printMode match {
        case CUTETracePrintMode.Off =>
        case CUTETracePrintMode.Compact =>
          when(cond) {
            compact
          }
        case CUTETracePrintMode.Human =>
          when(cond) {
            human
          }
        case CUTETracePrintMode.Both =>
          when(cond) {
            compact
            human
          }
      }
    }
  }
}
