# Phase 0.6 进度总结与下一步

## 当前状态

Task 6（解码器 / 渲染器 / JSONL）已全部完成并通过真实 Verilator 日志验证。

### Task 6 已完成产物

| 文件 | 状态 |
|------|------|
| `trace/python/cutetrace/__init__.py` | 新建（包初始化） |
| `trace/python/cutetrace/parser.py` | 完成 |
| `trace/python/cutetrace/decoder.py` | 完成 |
| `trace/python/cutetrace/render.py` | 完成 |
| `tools/trace/decode_cute_trace.py` | 完成（CLI 入口） |
| `doc/sdk-doc/cute-trace-parser.md` | 完成 |
| `doc/sdk-doc/cute-trace-decoder.md` | 完成 |
| `doc/sdk-doc/cute-trace-render.md` | 完成 |
| `doc/sdk-doc/cute-trace-decode-cli.md` | 完成 |

### Task 6 之外同步完成的改动

| 改动 | 说明 |
|------|------|
| `tools/trace/gen_cute_trace.py` compact format | sint 字段用 `%d` 输出（不做 `.asUInt`），保留符号信息 |
| `tools/trace/gen_cute_trace.py` EVENTS_BY_ID | 补充 `method` 和 `render` 字段，decoder/render 可直接使用 |
| `trace/python/cutetrace/generated/cute_trace_catalog.py` | 随 codegen 重新生成 |

### 验证结果

- `cute_Matmul_mnk_128_128_128_zeroinit.out`：186 条 CT 行，parse→decode→render 全部成功
- `cute_Matmul_fp8_mnk_64_64_64_fullbias.out`（debug 模式）：47349 行，无 CT 行，parser 正确跳过
- text 和 jsonl 两种模式输出正确
- `-o` 写文件功能正常

---

## Phase 0.6 整体进度

| Task | 内容 | 状态 |
|------|------|------|
| 1 | JSON Schema + catalog seed | 已完成 |
| 2 | catalog.py loader + validator | 已完成 |
| 3 | gen_cute_trace.py codegen | 已完成 |
| 4 | Scala runtime（CUTETraceContext/Params/Printf） | 已完成 |
| 5 | TaskController 插入 trace | 已完成 |
| **6** | **解码器 / 渲染器 / JSONL** | **已完成** |
| 7 | 过滤器检查器 | 待开始 |
| 8 | 构建入口 | 待开始 |

---

## 下一步：Task 7 — 过滤器检查器

### 目标

校验 `configs/trace_filters/*.yaml` 中引用的 category/module/task/event 在 catalog 中存在且合法。

### 产物

```text
configs/trace_filters/func_level1_inst.yaml
configs/trace_filters/func_level2_mem_cute.yaml
configs/trace_filters/func_level2ex_all_cute.yaml
configs/trace_filters/func_level3_mem_vector.yaml
configs/trace_filters/perf_topdown_status.yaml
tools/trace/check_cute_trace.py（扩展 filter 检查功能）
```

### 验收标准

- 过滤器引用 catalog 中存在的 category/module/task/event
- 过期过滤器在检查阶段报错
- `func_level1_inst` 能选出 cute_inst 和 cute_task event
- `check_cute_trace.py --filters configs/trace_filters` 通过

### 实施步骤

| 序号 | 内容 | 说明 |
|------|------|------|
| 1 | 定义 filter YAML schema | 一个 filter 文件包含 name、include/exclude 规则（按 category/task/event name 匹配） |
| 2 | 写 `func_level1_inst.yaml` | 只保留 cute_inst + cute_task 类别的 event |
| 3 | 写其余 4 个 filter 骨架 | 按级别划分，内容可暂为空或 placeholder |
| 4 | 扩展 `check_cute_trace.py` | 加 `--filters` 逻辑：加载 YAML → 校验引用 → 报告结果 |
| 5 | 端到端验证 | 用真实 catalog 和 filter 跑通检查 |

### filter YAML 格式草案

```yaml
name: func_level1_inst
description: "Level 1 inst/task lifecycle trace"
include:
  categories: [cute_inst, cute_task]
```

过滤规则：
- `include.categories` / `include.tasks` / `include.events`：白名单
- `exclude.categories` / `exclude.tasks` / `exclude.events`：黑名单
- include 和 exclude 可组合使用
- 未指定的维度不过滤

---

## 再下一步：Task 8 — 构建入口

写 Makefile 或 `tools/trace/README.md`，让新人按文档可以：
1. 生成 trace API（`gen_cute_trace.py`）
2. 检查 catalog 和 filter（`check_cute_trace.py`）
3. 解码 trace 日志（`decode_cute_trace.py`）
