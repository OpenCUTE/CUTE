package cute.trace

sealed trait CUTETracePrintMode

object CUTETracePrintMode {
  case object Off extends CUTETracePrintMode
  case object Compact extends CUTETracePrintMode
  case object Human extends CUTETracePrintMode
  case object Both extends CUTETracePrintMode
}

final case class CUTETraceParams(
  enable: Boolean = false,
  printMode: CUTETracePrintMode = CUTETracePrintMode.Compact,
  enabledCategories: Set[Int] = Set.empty[Int]
) {
  def mode: CUTETracePrintMode = printMode

  def isEnabledFor(categoryId: Int): Boolean = {
    enable && (enabledCategories.isEmpty || enabledCategories.contains(categoryId))
  }
}

object CUTETraceParams {
  val default: CUTETraceParams = CUTETraceParams()
}
