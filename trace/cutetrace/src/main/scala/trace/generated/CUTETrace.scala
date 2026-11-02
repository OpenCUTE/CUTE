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
      task_count: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.AMLLoad.U,
            CUTETraceIds.Event.AMLLoad_taskStart.U,
            task_count
          )
        },
        human = {
          printf(
            "CTH c=%d task=AMLLoad event=taskStart task_count=%d\n",
            ctx.cycle,
            task_count
          )
        }
      )
    }
    def taskEnd(
      cond: Bool,
      task_count: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.AMLLoad.U,
            CUTETraceIds.Event.AMLLoad_taskEnd.U,
            task_count
          )
        },
        human = {
          printf(
            "CTH c=%d task=AMLLoad event=taskEnd task_count=%d\n",
            ctx.cycle,
            task_count
          )
        }
      )
    }
  }
  object BMLLoad {
    def taskStart(
      cond: Bool,
      task_count: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.BMLLoad.U,
            CUTETraceIds.Event.BMLLoad_taskStart.U,
            task_count
          )
        },
        human = {
          printf(
            "CTH c=%d task=BMLLoad event=taskStart task_count=%d\n",
            ctx.cycle,
            task_count
          )
        }
      )
    }
    def taskEnd(
      cond: Bool,
      task_count: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.BMLLoad.U,
            CUTETraceIds.Event.BMLLoad_taskEnd.U,
            task_count
          )
        },
        human = {
          printf(
            "CTH c=%d task=BMLLoad event=taskEnd task_count=%d\n",
            ctx.cycle,
            task_count
          )
        }
      )
    }
  }
  object CMLLoad {
    def taskStart(
      cond: Bool,
      task_count: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.CMLLoad.U,
            CUTETraceIds.Event.CMLLoad_taskStart.U,
            task_count
          )
        },
        human = {
          printf(
            "CTH c=%d task=CMLLoad event=taskStart task_count=%d\n",
            ctx.cycle,
            task_count
          )
        }
      )
    }
    def taskEnd(
      cond: Bool,
      task_count: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.CMLLoad.U,
            CUTETraceIds.Event.CMLLoad_taskEnd.U,
            task_count
          )
        },
        human = {
          printf(
            "CTH c=%d task=CMLLoad event=taskEnd task_count=%d\n",
            ctx.cycle,
            task_count
          )
        }
      )
    }
  }
  object CMLStore {
    def taskStart(
      cond: Bool,
      task_count: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.CMLStore.U,
            CUTETraceIds.Event.CMLStore_taskStart.U,
            task_count
          )
        },
        human = {
          printf(
            "CTH c=%d task=CMLStore event=taskStart task_count=%d\n",
            ctx.cycle,
            task_count
          )
        }
      )
    }
    def taskEnd(
      cond: Bool,
      task_count: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.CMLStore.U,
            CUTETraceIds.Event.CMLStore_taskEnd.U,
            task_count
          )
        },
        human = {
          printf(
            "CTH c=%d task=CMLStore event=taskEnd task_count=%d\n",
            ctx.cycle,
            task_count
          )
        }
      )
    }
    def storeData(
      cond: Bool,
      task_count: UInt,
      vaddr: UInt,
      data: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_loadstore
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.CMLStore.U,
            CUTETraceIds.Event.CMLStore_storeData.U,
            task_count,
            vaddr,
            data
          )
        },
        human = {
          printf(
            "CTH c=%d task=CMLStore event=storeData task_count=%d vaddr=0x%x data=0x%x\n",
            ctx.cycle,
            task_count,
            vaddr,
            data
          )
        }
      )
    }
  }
  object MTECompute {
    def taskStart(
      cond: Bool,
      task_count: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.MTECompute.U,
            CUTETraceIds.Event.MTECompute_taskStart.U,
            task_count
          )
        },
        human = {
          printf(
            "CTH c=%d task=MTECompute event=taskStart task_count=%d\n",
            ctx.cycle,
            task_count
          )
        }
      )
    }
    def taskEnd(
      cond: Bool,
      task_count: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.cute_task
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.MTECompute.U,
            CUTETraceIds.Event.MTECompute_taskEnd.U,
            task_count
          )
        },
        human = {
          printf(
            "CTH c=%d task=MTECompute event=taskEnd task_count=%d\n",
            ctx.cycle,
            task_count
          )
        }
      )
    }
  }
  object VectorStore {
    def storeData(
      cond: Bool,
      task_count: UInt,
      vaddr: UInt,
      data: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.vector_loadstore
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.VectorStore.U,
            CUTETraceIds.Event.VectorStore_storeData.U,
            task_count,
            vaddr,
            data
          )
        },
        human = {
          printf(
            "CTH c=%d task=VectorStore event=storeData task_count=%d vaddr=0x%x data=0x%x\n",
            ctx.cycle,
            task_count,
            vaddr,
            data
          )
        }
      )
    }
  }
  object SystemMemory {
    def request(
      cond: Bool,
      hart: UInt,
      engine: UInt,
      port: UInt,
      event_seq: UInt,
      source: UInt,
      opcode: UInt,
      address: UInt,
      lg_size: UInt,
      width_bytes: UInt,
      mask: UInt,
      data: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.system_memory
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x,%x,%x,%x,%x,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.SystemMemory.U,
            CUTETraceIds.Event.SystemMemory_request.U,
            hart,
            engine,
            port,
            event_seq,
            source,
            opcode,
            address,
            lg_size,
            width_bytes,
            mask,
            data
          )
        },
        human = {
          printf(
            "CTH c=%d task=SystemMemory event=request hart=0x%x engine=0x%x port=0x%x event_seq=0x%x source=0x%x opcode=0x%x address=0x%x lg_size=0x%x width_bytes=0x%x mask=0x%x data=0x%x\n",
            ctx.cycle,
            hart,
            engine,
            port,
            event_seq,
            source,
            opcode,
            address,
            lg_size,
            width_bytes,
            mask,
            data
          )
        }
      )
    }
    def response(
      cond: Bool,
      hart: UInt,
      engine: UInt,
      port: UInt,
      event_seq: UInt,
      source: UInt,
      opcode: UInt,
      lg_size: UInt,
      width_bytes: UInt,
      denied: UInt,
      corrupt: UInt,
      data: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.system_memory
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x,%x,%x,%x,%x,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.SystemMemory.U,
            CUTETraceIds.Event.SystemMemory_response.U,
            hart,
            engine,
            port,
            event_seq,
            source,
            opcode,
            lg_size,
            width_bytes,
            denied,
            corrupt,
            data
          )
        },
        human = {
          printf(
            "CTH c=%d task=SystemMemory event=response hart=0x%x engine=0x%x port=0x%x event_seq=0x%x source=0x%x opcode=0x%x lg_size=0x%x width_bytes=0x%x denied=0x%x corrupt=0x%x data=0x%x\n",
            ctx.cycle,
            hart,
            engine,
            port,
            event_seq,
            source,
            opcode,
            lg_size,
            width_bytes,
            denied,
            corrupt,
            data
          )
        }
      )
    }
    def progress(
      cond: Bool,
      hart: UInt,
      engine: UInt,
      port: UInt,
      next_seq: UInt,
      outstanding: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.system_memory
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.SystemMemory.U,
            CUTETraceIds.Event.SystemMemory_progress.U,
            hart,
            engine,
            port,
            next_seq,
            outstanding
          )
        },
        human = {
          printf(
            "CTH c=%d task=SystemMemory event=progress hart=0x%x engine=0x%x port=0x%x next_seq=0x%x outstanding=0x%x\n",
            ctx.cycle,
            hart,
            engine,
            port,
            next_seq,
            outstanding
          )
        }
      )
    }
  }
  object SystemCheckpoint {
    def mark(
      cond: Bool,
      hart: UInt,
      seq: UInt,
      key: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.system_control
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.SystemCheckpoint.U,
            CUTETraceIds.Event.SystemCheckpoint_mark.U,
            hart,
            seq,
            key
          )
        },
        human = {
          printf(
            "CTH c=%d task=SystemCheckpoint event=mark hart=0x%x seq=0x%x key=0x%x\n",
            ctx.cycle,
            hart,
            seq,
            key
          )
        }
      )
    }
    def returned(
      cond: Bool,
      hart: UInt,
      seq: UInt,
      key: UInt
    )(implicit ctx: CUTETraceContext): Unit = {
      CUTETracePrintf.emit(
        cond = cond,
        categoryId = CUTETraceIds.Category.system_control
      )(
        compact = {
          printf(
            "CT,1,%x,%x,%x,%x,%x,%x\n",
            ctx.cycle,
            CUTETraceIds.Task.SystemCheckpoint.U,
            CUTETraceIds.Event.SystemCheckpoint_returned.U,
            hart,
            seq,
            key
          )
        },
        human = {
          printf(
            "CTH c=%d task=SystemCheckpoint event=returned hart=0x%x seq=0x%x key=0x%x\n",
            ctx.cycle,
            hart,
            seq,
            key
          )
        }
      )
    }
  }
}
