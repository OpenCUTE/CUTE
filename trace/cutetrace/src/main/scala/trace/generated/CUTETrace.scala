// AUTO-GENERATED FROM trace/catalogs/cute_trace.json. DO NOT EDIT BY HAND.

package cute.trace.generated

import chisel3._
import cute.trace._

object CUTETrace {
  object TaskControllerTrace {
    def macroInstInsert(
      cond: Bool,
      macro_id: UInt,
      opcode: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_inst
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.TaskControllerTrace.U,
            CUTETraceIds.Event.TaskControllerTrace_macroInstInsert.U,
            macro_id,
            opcode
          )
        },
        human = {
          printf(
            "CTH c=%d task=TaskControllerTrace event=macroInstInsert macro_id=%d opcode=0x%x\n",
            ctx.cycle,
            macro_id,
            opcode
          )
        }
      )
    }
    def macroInstDecodeStart(
      cond: Bool,
      macro_id: UInt,
      opcode: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_inst
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.TaskControllerTrace.U,
            CUTETraceIds.Event.TaskControllerTrace_macroInstDecodeStart.U,
            macro_id,
            opcode
          )
        },
        human = {
          printf(
            "CTH c=%d task=TaskControllerTrace event=macroInstDecodeStart macro_id=%d opcode=0x%x\n",
            ctx.cycle,
            macro_id,
            opcode
          )
        }
      )
    }
    def macroInstDecodeEnd(
      cond: Bool,
      macro_id: UInt,
      load_tasks: UInt,
      compute_tasks: UInt,
      store_tasks: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_inst
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.TaskControllerTrace.U,
            CUTETraceIds.Event.TaskControllerTrace_macroInstDecodeEnd.U,
            macro_id,
            load_tasks,
            compute_tasks,
            store_tasks
          )
        },
        human = {
          printf(
            "CTH c=%d task=TaskControllerTrace event=macroInstDecodeEnd macro_id=%d load_tasks=%d compute_tasks=%d store_tasks=%d\n",
            ctx.cycle,
            macro_id,
            load_tasks,
            compute_tasks,
            store_tasks
          )
        }
      )
    }
    def microTaskIssue(
      cond: Bool,
      macro_id: UInt,
      micro_id: UInt,
      target_task_id: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.TaskControllerTrace.U,
            CUTETraceIds.Event.TaskControllerTrace_microTaskIssue.U,
            macro_id,
            micro_id,
            target_task_id
          )
        },
        human = {
          printf(
            "CTH c=%d task=TaskControllerTrace event=microTaskIssue macro_id=%d micro_id=%d target_task_id=%d\n",
            ctx.cycle,
            macro_id,
            micro_id,
            target_task_id
          )
        }
      )
    }
    def microTaskCommit(
      cond: Bool,
      macro_id: UInt,
      micro_id: UInt,
      target_task_id: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.TaskControllerTrace.U,
            CUTETraceIds.Event.TaskControllerTrace_microTaskCommit.U,
            macro_id,
            micro_id,
            target_task_id
          )
        },
        human = {
          printf(
            "CTH c=%d task=TaskControllerTrace event=microTaskCommit macro_id=%d micro_id=%d target_task_id=%d\n",
            ctx.cycle,
            macro_id,
            micro_id,
            target_task_id
          )
        }
      )
    }
  }
  object AMLLoad {
    def taskStart(
      cond: Bool,
      macro_id: UInt,
      micro_id: UInt,
      scp_id: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.AMLLoad.U,
            CUTETraceIds.Event.AMLLoad_taskStart.U,
            macro_id,
            micro_id,
            scp_id
          )
        },
        human = {
          printf(
            "CTH c=%d task=AMLLoad event=taskStart macro_id=%d micro_id=%d scp_id=%d\n",
            ctx.cycle,
            macro_id,
            micro_id,
            scp_id
          )
        }
      )
    }
    def taskEnd(
      cond: Bool,
      macro_id: UInt,
      micro_id: UInt,
      scp_id: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.AMLLoad.U,
            CUTETraceIds.Event.AMLLoad_taskEnd.U,
            macro_id,
            micro_id,
            scp_id
          )
        },
        human = {
          printf(
            "CTH c=%d task=AMLLoad event=taskEnd macro_id=%d micro_id=%d scp_id=%d\n",
            ctx.cycle,
            macro_id,
            micro_id,
            scp_id
          )
        }
      )
    }
  }
  object BMLLoad {
    def taskStart(
      cond: Bool,
      macro_id: UInt,
      micro_id: UInt,
      scp_id: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.BMLLoad.U,
            CUTETraceIds.Event.BMLLoad_taskStart.U,
            macro_id,
            micro_id,
            scp_id
          )
        },
        human = {
          printf(
            "CTH c=%d task=BMLLoad event=taskStart macro_id=%d micro_id=%d scp_id=%d\n",
            ctx.cycle,
            macro_id,
            micro_id,
            scp_id
          )
        }
      )
    }
    def taskEnd(
      cond: Bool,
      macro_id: UInt,
      micro_id: UInt,
      scp_id: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.BMLLoad.U,
            CUTETraceIds.Event.BMLLoad_taskEnd.U,
            macro_id,
            micro_id,
            scp_id
          )
        },
        human = {
          printf(
            "CTH c=%d task=BMLLoad event=taskEnd macro_id=%d micro_id=%d scp_id=%d\n",
            ctx.cycle,
            macro_id,
            micro_id,
            scp_id
          )
        }
      )
    }
  }
  object CMLLoad {
    def taskStart(
      cond: Bool,
      macro_id: UInt,
      micro_id: UInt,
      scp_id: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.CMLLoad.U,
            CUTETraceIds.Event.CMLLoad_taskStart.U,
            macro_id,
            micro_id,
            scp_id
          )
        },
        human = {
          printf(
            "CTH c=%d task=CMLLoad event=taskStart macro_id=%d micro_id=%d scp_id=%d\n",
            ctx.cycle,
            macro_id,
            micro_id,
            scp_id
          )
        }
      )
    }
    def taskEnd(
      cond: Bool,
      macro_id: UInt,
      micro_id: UInt,
      scp_id: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.CMLLoad.U,
            CUTETraceIds.Event.CMLLoad_taskEnd.U,
            macro_id,
            micro_id,
            scp_id
          )
        },
        human = {
          printf(
            "CTH c=%d task=CMLLoad event=taskEnd macro_id=%d micro_id=%d scp_id=%d\n",
            ctx.cycle,
            macro_id,
            micro_id,
            scp_id
          )
        }
      )
    }
  }
  object CMLStore {
    def taskStart(
      cond: Bool,
      macro_id: UInt,
      micro_id: UInt,
      scp_id: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.CMLStore.U,
            CUTETraceIds.Event.CMLStore_taskStart.U,
            macro_id,
            micro_id,
            scp_id
          )
        },
        human = {
          printf(
            "CTH c=%d task=CMLStore event=taskStart macro_id=%d micro_id=%d scp_id=%d\n",
            ctx.cycle,
            macro_id,
            micro_id,
            scp_id
          )
        }
      )
    }
    def taskEnd(
      cond: Bool,
      macro_id: UInt,
      micro_id: UInt,
      scp_id: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.CMLStore.U,
            CUTETraceIds.Event.CMLStore_taskEnd.U,
            macro_id,
            micro_id,
            scp_id
          )
        },
        human = {
          printf(
            "CTH c=%d task=CMLStore event=taskEnd macro_id=%d micro_id=%d scp_id=%d\n",
            ctx.cycle,
            macro_id,
            micro_id,
            scp_id
          )
        }
      )
    }
  }
  object MTECompute {
    def taskStart(
      cond: Bool,
      macro_id: UInt,
      micro_id: UInt,
      a_scp_id: UInt,
      b_scp_id: UInt,
      c_scp_id: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.MTECompute.U,
            CUTETraceIds.Event.MTECompute_taskStart.U,
            macro_id,
            micro_id,
            a_scp_id,
            b_scp_id,
            c_scp_id
          )
        },
        human = {
          printf(
            "CTH c=%d task=MTECompute event=taskStart macro_id=%d micro_id=%d a_scp_id=%d b_scp_id=%d c_scp_id=%d\n",
            ctx.cycle,
            macro_id,
            micro_id,
            a_scp_id,
            b_scp_id,
            c_scp_id
          )
        }
      )
    }
    def taskEnd(
      cond: Bool,
      macro_id: UInt,
      micro_id: UInt,
      a_scp_id: UInt,
      b_scp_id: UInt,
      c_scp_id: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.MTECompute.U,
            CUTETraceIds.Event.MTECompute_taskEnd.U,
            macro_id,
            micro_id,
            a_scp_id,
            b_scp_id,
            c_scp_id
          )
        },
        human = {
          printf(
            "CTH c=%d task=MTECompute event=taskEnd macro_id=%d micro_id=%d a_scp_id=%d b_scp_id=%d c_scp_id=%d\n",
            ctx.cycle,
            macro_id,
            micro_id,
            a_scp_id,
            b_scp_id,
            c_scp_id
          )
        }
      )
    }
  }
}
