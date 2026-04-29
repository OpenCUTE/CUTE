# Phase 1 Plan: BaseTest -> Runtime Lib 最小闭环

## 目标

Phase 1 的目标是用一个最小 BaseTest 跑通最小 runtime lib，并形成第一份可复盘 artifact。

这阶段不追求 tensor 正确性，也不追求复杂 trace。只验证：

- `HWConfig` 能解析到 `ChipyardConfig`，并生成 headers 到 `build/chipyard_configs/<id>/generated_headers/`。
- `cute-sdk/runtime/cute_runtime` 能构建最小测试。
- simulator 能运行测试。
- artifact 能保存本次 run 的证据。
- `Trace.func F0_event` 作为占位检查基础运行事件。

## 主要产物

```text
cute-sdk/runtime/cute_runtime/
├── project.yaml                        # Phase 0 已创建
├── include/
│   └── cute_runtime.h                  # Runtime lib 公共头文件
├── src/
│   └── cute_runtime.c                  # Runtime lib 实现
├── tests/
│   └── rocc_hello.c                    # 最小测试：query + fingerprint
└── build_rules/
    └── Makefile                         # 编译 runtime lib + 测试

scripts/
└── cute-run.py                         # 最小 Runner

build/
├── chipyard_configs/cute2tops_scp64/
│   ├── chipyard_config.resolved.yaml
│   ├── capability.json
│   ├── header_fingerprint.txt
│   └── generated_headers/              # 生成的 .h 文件
└── cute-runs/<run-id>/                  # Run artifact
```

---

## Task 1.1: 实现 Runtime Lib API

### 1.1.1 `cute-sdk/runtime/cute_runtime/include/cute_runtime.h`

Runtime lib 是所有上层 lib 的基础，提供最小可用的硬件交互能力。

API 设计原则：
- 直接基于 `instruction.h.generated` 的封装函数，不重新手写 funct 编号
- 头文件 include 路径：`cute-sdk/include/`(稳定头文件) + `build/chipyard_configs/<id>/generated_headers/`(配置相关)

```c
#ifndef CUTE_RUNTIME_H
#define CUTE_RUNTIME_H

#include <stdint.h>
#include "instruction.h.generated"
#include "validation.h.generated"
#include "datatype.h.generated"

/* ---- Query 指令封装 ---- */

/* 查询加速器是否正在运行，返回 1=busy, 0=idle */
static inline uint64_t cute_query_busy(void) {
    return CUTE_QUERY_ACCELERATOR_BUSY(0, 0);
}

/* 查询加速器运行时间（时钟周期） */
static inline uint64_t cute_query_runtime(void) {
    return CUTE_QUERY_RUNTIME(0, 0);
}

/* 查询访存读次数 */
static inline uint64_t cute_query_mem_read_count(void) {
    return CUTE_QUERY_MEM_READ_COUNT(0, 0);
}

/* 查询访存写次数 */
static inline uint64_t cute_query_mem_write_count(void) {
    return CUTE_QUERY_MEM_WRITE_COUNT(0, 0);
}

/* 查询计算时间 */
static inline uint64_t cute_query_compute_time(void) {
    return CUTE_QUERY_COMPUTE_TIME(0, 0);
}

/* ---- FIFO 管理封装 ---- */

/* 查询宏指令队列是否非空（有指令在执行） */
static inline uint64_t cute_query_fifo_valid(void) {
    return CUTE_QUERY_MACRO_INST_FINISH(0, 0);
}

/* 查询宏指令是否完成 */
static inline uint64_t cute_query_fifo_finish(void) {
    return CUTE_QUERY_MACRO_INST_FINISH(0, 0);
}

/* 查询宏指令队列是否已满 */
static inline uint64_t cute_query_fifo_full(void) {
    return CUTE_QUERY_MACRO_INST_FIFO_FULL(0, 0);
}

/* 查询宏指令队列中的指令数量 */
static inline uint64_t cute_query_fifo_info(void) {
    return CUTE_QUERY_MACRO_INST_FIFO_INFO(0, 0);
}

/* 清除已完成的宏指令 */
static inline uint64_t cute_fifo_dequeue(void) {
    return CUTE_CLEAR_INST(0, 0);
}

/* 查询已完成宏指令的尾编号 */
static inline uint64_t cute_fifo_get_finish_tail(void) {
    return CUTE_QUERY_INST(0, 0);
}

/* ---- 等待与超时 ---- */

/* 忙等直到加速器空闲，返回等待的周期数。若超时返回 0 */
uint64_t cute_wait_idle(uint64_t timeout_cycles);

/* 忙等直到 FIFO 中宏指令完成，返回等待的周期数 */
uint64_t cute_wait_fifo_finish(uint64_t timeout_cycles);

/* ---- 性能计数器 ---- */

typedef struct {
    uint64_t total_cycles;
    uint64_t compute_cycles;
    uint64_t mem_read_count;
    uint64_t mem_write_count;
} cute_perf_t;

/* 一次性查询所有性能计数器 */
static inline cute_perf_t cute_perf_query(void) {
    cute_perf_t p;
    p.total_cycles    = cute_query_runtime();
    p.compute_cycles  = cute_query_compute_time();
    p.mem_read_count  = cute_query_mem_read_count();
    p.mem_write_count = cute_query_mem_write_count();
    return p;
}

/* 打印性能计数器到 UART */
void cute_perf_print(const cute_perf_t *p);

/* ---- 辅助 ---- */

/* 读 rdcycle */
static inline uint64_t cute_rdcycle(void) {
    uint64_t c;
    __asm__ __volatile__("rdcycle %0" : "=r"(c));
    return c;
}

/* 打印配置 fingerprint（CONFIG 名、Tensor 维度等） */
void cute_print_config_info(void);

#endif /* CUTE_RUNTIME_H */
```

### 1.1.2 `cute-sdk/runtime/cute_runtime/src/cute_runtime.c`

```c
#include "cute_runtime.h"
#include <stdio.h>

uint64_t cute_wait_idle(uint64_t timeout_cycles) {
    uint64_t start = cute_rdcycle();
    while (cute_query_busy()) {
        if (cute_rdcycle() - start > timeout_cycles) {
            return 0;  /* timeout */
        }
    }
    return cute_rdcycle() - start;
}

uint64_t cute_wait_fifo_finish(uint64_t timeout_cycles) {
    uint64_t start = cute_rdcycle();
    while (!cute_query_fifo_finish()) {
        if (cute_rdcycle() - start > timeout_cycles) {
            return 0;  /* timeout */
        }
    }
    return cute_rdcycle() - start;
}

void cute_perf_print(const cute_perf_t *p) {
    printf("[CUTE_PERF] total=%lu compute=%lu rd_req=%lu wr_req=%lu\n",
           p->total_cycles, p->compute_cycles,
           p->mem_read_count, p->mem_write_count);
}

void cute_print_config_info(void) {
    printf("[CUTE_CONFIG] TENSOR_M=%d TENSOR_N=%d TENSOR_K=%d\n",
           CUTE_TENSOR_M, CUTE_TENSOR_N, CUTE_TENSOR_K);
    printf("[CUTE_CONFIG] MATRIX_M=%d MATRIX_N=%d\n",
           CUTE_MATRIX_M, CUTE_MATRIX_N);
    printf("[CUTE_CONFIG] OUTSIDE_DATA_WIDTH=%d VECTOR_WIDTH=%d\n",
           CUTE_OUTSIDE_DATA_WIDTH, CUTE_VECTOR_WIDTH);
}
```

### 1.1.3 验收

- `cute_runtime.h` 只 include 生成的头文件，不依赖手写 `cuteMarcoinstHelper.h`
- 所有 query/fifo 函数使用 `instruction.h.generated` 中的封装函数
- 编译通过（含 `cute_wait_idle`、`cute_perf_print`、`cute_print_config_info`）

---

## Task 1.2: 实现 BaseTest

### 1.2.1 `cute-sdk/runtime/cute_runtime/tests/rocc_hello.c`

```c
#include <stdio.h>
#include <stdint.h>
#include "cute_runtime.h"

int main(void) {
    printf("[CUTE_TEST] rocc_hello start\n");

    /* 打印配置 fingerprint */
    cute_print_config_info();

    /* 验证 query 指令能正常返回 */
    uint64_t busy = cute_query_busy();
    printf("[CUTE_TEST] initial busy=%lu (expect 0)\n", busy);

    uint64_t runtime = cute_query_runtime();
    printf("[CUTE_TEST] initial runtime=%lu\n", runtime);

    /* 性能计数器查询 */
    cute_perf_t perf = cute_perf_query();
    cute_perf_print(&perf);

    /* FIFO 状态查询 */
    uint64_t fifo_valid = cute_query_fifo_valid();
    uint64_t fifo_full  = cute_query_fifo_full();
    uint64_t fifo_info  = cute_query_fifo_info();
    printf("[CUTE_TEST] fifo valid=%lu full=%lu info=%lu\n",
           fifo_valid, fifo_full, fifo_info);

    printf("[CUTE_TEST] rocc_hello PASS\n");
    return 0;
}
```

### 1.2.2 验收

- 代码不依赖 `cuteMarcoinstHelper.h`
- 输出包含 `[CUTE_TEST] ... PASS` 标记
- 输出包含 `[CUTE_CONFIG]` fingerprint 行
- 输出包含 `[CUTE_PERF]` 行

---

## Task 1.3: 实现 Build Rules

### 1.3.1 `cute-sdk/runtime/cute_runtime/build_rules/Makefile`

```makefile
# cute-sdk/runtime/cute_runtime/build_rules/Makefile
#
# Usage:
#   make HWCONFIG_DIR=<path> [VARIANT=rocc_hello]

CUTEROOT   := $(PWD)/../../../..
RVVTOOLCHAIN := $(CUTEROOT)/tool/riscv
PREFIX     := $(RVVTOOLCHAIN)/bin/riscv64-unknown-elf-

GCC      = $(PREFIX)gcc
OBJDUMP  = $(PREFIX)objdump

ARCH = rv64imafdcv
ABI  = lp64d

CFLAGS  = -std=gnu99 -g -fno-common -fno-builtin-printf -Wall -O3
CFLAGS += -march=$(ARCH) -mabi=$(ABI)
CFLAGS += -I$(PWD)/../include
CFLAGS += -I$(CUTEROOT)/cute-sdk/include
CFLAGS += -I$(HWCONFIG_DIR)/generated_headers

libgloss_specs := htif_nano.specs
CFLAGS  += -specs=$(libgloss_specs)
LDFLAGS  = -static -specs=$(libgloss_specs)

# Runtime lib
RUNTIME_SRCS = $(PWD)/../src/cute_runtime.c
RUNTIME_OBJS = $(BUILD_DIR)/cute_runtime.o

# Test programs
VARIANT ?= rocc_hello
TEST_SRC = $(PWD)/../tests/$(VARIANT).c

BUILD_DIR ?= build

.PHONY: all clean

all: $(BUILD_DIR)/$(VARIANT).riscv

$(BUILD_DIR)/cute_runtime.o: $(RUNTIME_SRCS)
	@mkdir -p $(BUILD_DIR)
	$(GCC) $(CFLAGS) -c $< -o $@

$(BUILD_DIR)/$(VARIANT).o: $(TEST_SRC)
	@mkdir -p $(BUILD_DIR)
	$(GCC) $(CFLAGS) -c $< -o $@

$(BUILD_DIR)/$(VARIANT).riscv: $(BUILD_DIR)/$(VARIANT).o $(RUNTIME_OBJS)
	$(GCC) $(LDFLAGS) $^ -o $@

$(BUILD_DIR)/$(VARIANT).dump: $(BUILD_DIR)/$(VARIANT).riscv
	$(OBJDUMP) -D -S $< > $@

clean:
	rm -rf $(BUILD_DIR)
```

### 1.3.2 验收

- `make HWCONFIG_DIR=build/chipyard_configs/cute2tops_scp64` 编译成功
- 产出 `build/rocc_hello.riscv`

---

## Task 1.4: 实现 HWConfig Header 生成流程

### 1.4.1 `tools/runner/cute-gen-headers.py`

负责从 `hwconfig.yaml` 调用 `generate-headers.sh` 生成头文件到指定目录。

```text
Usage:
  tools/runner/cute-gen-headers.py --hwconfig configs/hwconfigs/cute2tops_scp64_dramsim32.yaml

行为:
  1. 读取 hwconfig.yaml
  2. 解析 hwconfig.chipyard_config -> configs/chipyard_configs/<id>.yaml
  3. 提取 ChipyardConfig.class
  4. 提取 ChipyardConfig.cute.generated_headers.output_dir
  5. 创建 output_dir
  6. 调用 scripts/generate-headers.sh <class> <output_dir>
  7. 计算 header fingerprint (sha256 of all .generated files)
  8. 写 chipyard_config.resolved.yaml、capability.json、header_fingerprint.txt
```

### 1.4.2 产物结构

```text
build/chipyard_configs/cute2tops_scp64/
├── chipyard_config.resolved.yaml
├── capability.json            # 从 CuteParams 推导的能力描述
├── header_fingerprint.txt     # 所有 .generated 文件的 sha256
└── generated_headers/
    ├── datatype.h.generated
    ├── validation.h.generated
    └── instruction.h.generated
```

### 1.4.3 验收

- `cute-gen-headers.py --hwconfig configs/hwconfigs/cute2tops_scp64_dramsim32.yaml` 成功
- `generated_headers/` 下包含 3 个 `.generated` 文件
- `header_fingerprint.txt` 包含有效 sha256

---

## Task 1.5: 实现最小 Runner

### 1.5.1 `tools/runner/cute-run.py`

Phase 1 的 Runner 只覆盖 base_test 最小流程，不实现 trace parser。

```text
Usage:
  tools/runner/cute-run.py \
    --hwconfig configs/hwconfigs/cute2tops_scp64_dramsim32.yaml \
    --project cute-sdk/runtime/cute_runtime \
    --variant rocc_hello

状态机:
  RESOLVE_HWCONFIG    → 读取 hwconfig.yaml，验证 schema
  GENERATE_HEADERS    → 调用 cute-gen-headers.py（如果 header_fingerprint 未变则跳过）
  RESOLVE_TARGET      → 用 cute-check-config.py 的 target matcher 判断匹配
  BUILD               → 调用 project 的 Makefile
  RUN                 → 调用 run-simulator-test.sh
  CAPTURE_LOG         → 收集 UART log 到 artifact
  CHECK_PASS          → 检查 log 中是否包含 [CUTE_TEST] ... PASS
  SAVE_ARTIFACT       → 组织 artifact 目录
```

### 1.5.2 Runner 调用的外部命令

| 步骤 | 调用的命令 |
|------|-----------|
| GENERATE_HEADERS | `tools/runner/cute-gen-headers.py --hwconfig <path>` |
| RESOLVE_TARGET | Python 内置 target matcher（复用 `cute-check-config.py` 的逻辑） |
| BUILD | `make -C <project>/build_rules HWCONFIG_DIR=<path> VARIANT=<name>` |
| RUN | `scripts/run-simulator-test.sh <CONFIG> <binary>` |
| CHECK_PASS | `grep "\[CUTE_TEST\].*PASS" <uart.log>` |

### 1.5.3 验收

```bash
tools/runner/cute-run.py \
  --hwconfig configs/hwconfigs/cute2tops_scp64_dramsim32.yaml \
  --project cute-sdk/runtime/cute_runtime \
  --variant rocc_hello
```

- 命令执行成功，退出码 0
- artifact 目录包含完整证据

---

## Task 1.6: Artifact 结构

```text
build/cute-runs/<timestamp>-rocc_hello-cute2tops_scp64_dramsim32/
├── hwconfig/
│   ├── hwconfig.resolved.yaml
│   ├── chipyard_config.resolved.yaml
│   ├── capability.json
│   ├── header_fingerprint.txt
│   └── generated_headers/ → ../../../chipyard_configs/cute2tops_scp64/generated_headers/
├── test/
│   ├── project.resolved.yaml
│   ├── target_match.json         # {"status": "MATCH", "reason": "..."}
│   └── code/
│       ├── rocc_hello.c
│       ├── rocc_hello.riscv
│       └── rocc_hello.dump
├── run/
│   ├── simulator.cmd.txt         # 实际执行的 simulator 命令
│   ├── raw.log                   # simulator stdout/stderr
│   └── uart.log                  # 提取的 UART 输出
├── func/
│   └── verify.json               # {"status": "PASS", "method": "log_pattern"}
├── status.json                   # 总体状态
└── report.md                     # 人类可读报告
```

---

## 验收标准总表

- [ ] `cute_runtime.h` 只依赖 `instruction.h.generated`，不依赖手写 funct
- [ ] `cute-gen-headers.py` 能从 hwconfig.yaml 生成 headers 到 build 目录
- [ ] `cute-run.py --hwconfig ... --project ... --variant rocc_hello` 一条命令跑通
- [ ] BaseTest 输出包含 `[CUTE_CONFIG]` fingerprint
- [ ] BaseTest 输出包含 `[CUTE_PERF]` 性能数据
- [ ] BaseTest 输出包含 `[CUTE_TEST] rocc_hello PASS`
- [ ] artifact 目录结构完整
- [ ] runtime lib 有最小可用 API（query、wait、perf）

---

## 不做事项

- 不做 tensor descriptor（Phase 2）。
- 不做 D tensor 重建（Phase 2）。
- 不做正式 Trace parser（Phase 3）。
- 不做性能 top-down（Phase 5）。
- 不迁移已有测试。

---

## 风险与应对

| 风险 | 应对 |
|------|------|
| `instruction.h.generated` 封装函数签名与 `cuteMarcoinstHelper.h` 不一致 | Phase 1 只用 query 类指令（funct 1-8），这些函数签名简单，风险低 |
| 现有 build 脚本硬编码路径 | Runner 先调用现有 `generate-headers.sh` 和 `run-simulator-test.sh`，后续再重构 |
| simulator 构建耗时 | 本阶段假定 simulator 已存在，Runner 先做 discovery |
| generated headers 与 simulator 不匹配 | artifact 中保存 fingerprint，report 中显示 |
| `YGJK_INS_RRR` 宏在 `instruction.h.generated` 的封装函数中是否正确工作 | Phase 1 优先验证 query 类指令是否返回合理值 |

---

## 与 Phase 0 的衔接

Phase 0 产出的 `hwconfig.yaml`、`project.yaml`、`cute-check-config.py` 在 Phase 1 中全部被使用：
- Runner 读取 `hwconfig.yaml` 获取 `chipyard_config`
- Runner 读取 `project.yaml` 获取 `code.entry` 和 `target`
- Runner 调用 `cute-check-config.py` 逻辑做 target match
- Artifact 保存 resolved 版本

## 与 Phase 2 的衔接

Phase 1 完成后，Phase 2 可以直接：
- 在 `cute_runtime.h` 上叠加 `cute_tensor.h`
- 复用 Runner 的 build/run/artifact 流程
- 增加 golden 生成和 actual 重建步骤
