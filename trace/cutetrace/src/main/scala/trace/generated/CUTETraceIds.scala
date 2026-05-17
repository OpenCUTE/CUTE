// AUTO-GENERATED FROM trace/catalogs/cute_trace.json. DO NOT EDIT BY HAND.

package cute.trace.generated

object CUTETraceIds {
  object Category {
    val cute_inst: Int = 0
    val cute_task: Int = 1
    val cute_loadstore: Int = 2
    val cute_compute: Int = 3
    val vector_loadstore: Int = 4
  }
  object Module {
    val TaskController: Int = 1
    val AML: Int = 2
    val BML: Int = 3
    val CML: Int = 4
    val MTE: Int = 5
    val LocalMMU: Int = 6
    val Vector: Int = 7
  }
  object Task {
    val TaskControllerTrace: Int = 1
    val AMLLoad: Int = 2
    val BMLLoad: Int = 3
    val CMLLoad: Int = 4
    val CMLStore: Int = 5
    val MTECompute: Int = 6
    val VectorStore: Int = 7
  }
  object Event {
    val TaskControllerTrace_macroInstInsert: Int = 1
    val TaskControllerTrace_macroInstDecodeStart: Int = 2
    val TaskControllerTrace_macroInstDecodeEnd: Int = 3
    val TaskControllerTrace_microTaskIssue: Int = 4
    val TaskControllerTrace_microTaskCommit: Int = 5
    val AMLLoad_taskStart: Int = 6
    val AMLLoad_taskEnd: Int = 7
    val BMLLoad_taskStart: Int = 8
    val BMLLoad_taskEnd: Int = 9
    val CMLLoad_taskStart: Int = 10
    val CMLLoad_taskEnd: Int = 11
    val CMLStore_taskStart: Int = 12
    val CMLStore_taskEnd: Int = 13
    val MTECompute_taskStart: Int = 14
    val MTECompute_taskEnd: Int = 15
    val CMLStore_storeData: Int = 16
    val VectorStore_storeData: Int = 17
  }
}
