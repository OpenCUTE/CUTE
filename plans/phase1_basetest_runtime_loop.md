# Phase 1 Plan: BaseTest -> Runtime Lib 最小闭环

## 目标

Phase 1 的目标是用一个最小 BaseTest 跑通最小 runtime lib，并形成第一份可复盘 artifact。

这阶段不追求 tensor 正确性，也不追求复杂 trace。只验证：

- `HWConfig` 能生成 headers。
- `cutetest/runtime/cute_runtime` 能构建最小测试。
- simulator 能运行测试。
- artifact 能保存本次 run 的证据。
- `Trace.func F0_event` 作为占位检查基础运行事件。

## 主要产物

```text
cutetest/runtime/cute_runtime/
├── project.yaml
├── include/cute_runtime.h
├── src/cute_runtime.c
├── tests/rocc_hello.c
└── build_rules/Makefile

scripts/cute-run.py
build/cute-runs/<run-id>/
```

## Runtime Lib 最小 API

第一版 runtime lib 只需要覆盖最基础动作：

```c
uint64_t cute_query_busy(void);
uint64_t cute_query_runtime(void);
uint64_t cute_query_mem_read_count(void);
uint64_t cute_query_mem_write_count(void);
int cute_wait_idle(uint64_t timeout_cycles);
```

如果已有 generated `instruction.h.generated` 可直接使用，runtime 只做轻封装；不要重新手写 funct。

## BaseTest 内容

最小测试建议：

```text
rocc_hello
```

测试逻辑：

- 打印 runtime/header fingerprint。
- 调用一个或多个 query 指令。
- 验证能返回。
- 可选地触发一个最小 no-op 或状态查询流程。
- 输出明确 PASS/FAIL 字符串。

## Runner 最小流程

Phase 1 的 Runner 可以很薄：

```text
resolve HWConfig
  -> generate HWConfig.generated_headers
  -> read cutetest/runtime/cute_runtime/project.yaml
  -> match target
  -> build rocc_hello
  -> run simulator
  -> capture raw log
  -> create artifact
  -> mark RUN_OK or FAIL
```

Trace 处理：

- `Trace.func F0_event` 暂时可以只检查日志中是否存在明确开始/结束/PASS 标记。
- 不需要定义正式 event schema。
- 如果结构化 trace 尚不存在，允许使用 legacy log parser。

## Artifact 要求

```text
build/cute-runs/<run-id>/
├── hwconfig/
│   ├── hwconfig.resolved.yaml
│   ├── capability.json
│   ├── header_fingerprint.txt
│   └── generated_headers/
├── test/
│   ├── project.resolved.yaml
│   ├── target_match.json
│   └── code/
│       ├── rocc_hello.c
│       ├── rocc_hello.riscv
│       └── rocc_hello.dump
├── run/
│   ├── simulator.cmd.txt
│   ├── raw.log
│   └── uart.log
├── func/
│   └── verify.json
├── status.json
└── report.md
```

## 验收标准

- 能用一条命令运行：

```text
scripts/cute-run.py --hw configs/hwconfigs/cute2tops_scp64_dramsim32.yaml --project cutetest/runtime/cute_runtime --variant rocc_hello
```

- target matcher 能输出支持/不支持原因。
- generated headers 来自 `build/hwconfigs/<name>/generated_headers`。
- BaseTest 运行成功并产生 artifact。
- runtime lib 有最小可用 API。

## 不做事项

- 不做 tensor descriptor。
- 不做 D tensor 重建。
- 不做正式 Trace schema。
- 不做性能 top-down。
- 不迁移已有大量测试。

## 风险

- 现有 build 脚本硬编码路径：先允许 Runner 调用现有脚本，后续再清理。
- simulator 构建耗时：本阶段可以假定 simulator 已存在，Runner 先做 discovery。
- generated headers 与 simulator 不匹配：必须保存 fingerprint，并在 report 中显示。

