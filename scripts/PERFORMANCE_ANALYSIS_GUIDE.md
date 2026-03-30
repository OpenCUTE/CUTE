# CUTE 系统性能分析指南

## 目录结构

```
CUTE/
├── scripts/
│   ├── perf_analysis.py          # 性能分析脚本
│   └── run_benchmark.sh          # 运行基准测试
├── tests/
│   └── cute_benchmarks/          # CUTE测试负载
│       ├── matmul_benchmark.c    # 矩阵乘法测试
│       ├── conv_benchmark.c      # 卷积测试
│       └── gemm_test.c           # GEMM测试
└── docs/
    └── performance_analysis.md   # 本文档
```

## 自顶向下分析方法论

### Level 1: 系统级指标

**目标**：了解系统整体性能

**关键指标**：
- 总执行周期数
- 吞吐量 (OPS/s)
- 平均每条宏指令周期

**诊断方法**：
```bash
# 运行测试并获取系统级指标
./scripts/run_benchmark.sh matmul 1024 1024 1024

# 查看系统级报告
python scripts/perf_analysis.py simulator.log | grep "Level 1"
```

**优化方向**：
- 如果总周期过高 → 进入 Level 2 分析阶段瓶颈

---

### Level 2: 阶段级瓶颈分析

**目标**：找出哪个执行阶段是瓶颈

**阶段定义**：
```
Config → Load → Compute → Store → Stall
  ↓        ↓       ↓        ↓       ↓
配置    加载    计算     存储     停顿
```

**关键指标**：
- 计算阶段占比
- 加载阶段占比
- 存储阶段占比
- 停顿阶段占比

**瓶颈诊断**：

| 瓶颈类型 | 典型占比 | 诊断 | 优化方向 |
|---------|---------|------|---------|
| **Compute Bound** | Compute > 40% | 计算密集 | → Level 3 组件分析 |
| **Memory Bound** | Load+Store > 60% | 内存带宽限制 | 优化数据预取 |
| **Stall Heavy** | Stall > 30% | 资源冲突/依赖 | 优化指令调度 |

**示例输出**：
```
Level 2: 阶段级瓶颈分析
指令ID     总周期      计算%      加载%      存储%      停顿%      并行%
----------------------------------------------------------------------
0          125000     35.2       45.1       15.3       4.4        12.3
1          118000     38.5       42.8       14.2       4.5        15.1
```

---

### Level 3: 组件级瓶颈分析

**目标**：找出具体哪个组件是瓶颈

**组件分类**：
- AML/BML/CML: 内存加载器
- ADC/BDC/CDC: 数据控制器
- MTE: 矩阵张量引擎（计算单元）
- AOP: 后操作单元

**关键指标**：
- 各通道（A/B/C）负载平衡度
- MMU 请求频率和停顿率
- Scratchpad 利用率

**瓶颈诊断**：

| 瓶颈 | 症状 | 原因 | 优化 |
|-----|------|------|------|
| **通道不平衡** | A/B/C负载差异>20% | 数据布局问题 | 优化数据分块 |
| **MMU瓶颈** | MMU停顿率高 | 内存带宽不足 | 双缓冲/预取优化 |
| **Compute瓶颈** | 计算占比高 | 算法复杂度高 | 算法优化 |

---

### Level 4: 微操作级分析

**目标**：优化微指令流水线

**关键指标**：
- 计算效率 = 计算周期 / (计算周期 + 停顿周期)
- 内存绑定度 = (Load + Store) / 总周期
- 并行度 = 并行激活周期 / 总周期

**优化建议**：

| 指标低 | 症状 | 建议 |
|-------|------|------|
| 计算效率 < 70% | 停顿多 | 减少数据依赖，优化调度 |
| 并行度 < 30% | 串行执行 | 增加微指令级并行 |
| 内存绑定 > 60% | 访存密集 | 优化数据局部性 |

---

## 经典测试负载

### 1. 矩阵乘法 (GEMM)

```c
// tests/cute_benchmarks/matmul_benchmark.c
void gemm_test(int M, int N, int K) {
    // C = A * B
    // A: M x K, B: K x N, C: M x N

    for (int i = 0; i < M; i += TILE_M) {
        for (int j = 0; j < N; j += TILE_N) {
            for (int k = 0; k < K; k += TILE_K) {
                // 调用CUTE宏指令
                cute_matmul(
                    A + i*K + k,  // A的起始地址
                    B + k*N + j,  // B的起始地址
                    C + i*N + j,  // C的起始地址
                    D + i*N + j,  // D的起始地址
                    min(TILE_M, M-i),  // M维度
                    min(TILE_N, N-j),  // N维度
                    min(TILE_K, K-k),  // K维度
                    DATA_TYPE_FP16     // 数据类型
                );
            }
        }
    }
}
```

**测试配置**：

| 测试名称 | M | N | K | 预期瓶颈 |
|---------|---|---|---|---------|
| 小矩阵 | 64 | 64 | 64 | Compute |
| 方阵 | 1024 | 1024 | 1024 | Memory |
| 大K矩阵 | 512 | 512 | 4096 | Memory (A/B load) |
| 大M矩阵 | 4096 | 512 | 512 | Memory (A load) |

### 2. 卷积 (CNN)

```c
// tests/cute_benchmarks/conv_benchmark.c
void conv_test(int OH, int OW, int OC, int IC, int KH, int KW) {
    // 标准卷积
    for (int oh = 0; oh < OH; oh += TILE_OH) {
        for (int ow = 0; ow < OW; ow += TILE_OW) {
            for (int oc = 0; oc < OC; oc += TILE_OC) {
                for (int ic = 0; ic < IC; ic += TILE_IC) {
                    cute_conv(
                        input, output, kernel, bias,
                        oh, ow, oc, ic, KH, KW,
                        stride, padding
                    );
                }
            }
        }
    }
}
```

**测试配置**：

| 测试名称 | OH | OW | OC | IC | KH | KW | 预期瓶颈 |
|---------|----|----|----|----|----|----|------|
| Pointwise | 112 | 112 | 64 | 64 | 1 | 1 | Memory |
| 3x3卷积 | 56 | 56 | 128 | 64 | 3 | 3 | Compute |
| 7x7卷积 | 28 | 28 | 256 | 128 | 7 | 7 | Compute |
| Depthwise | 112 | 112 | 64 | 1 | 3 | 3 | Memory |

---

## 使用流程

### 步骤 1: 编译测试程序

```bash
cd /root/CUTE

# 编译矩阵乘法测试
make -C chipyard/tests/cute_benchmarks matmul_benchmark

# 编译卷积测试
make -C chipyard/tests/cute_benchmarks conv_benchmark
```

### 步骤 2: 运行仿真

```bash
# 使用 Verilator 仿真
cd chipyard
./scripts/build-verilator.sh

# 运行矩阵乘法测试 (1024x1024x1024)
./verilator simulations -C tests/cute_benchmarks/matmul_benchmark 1024 1024 1024 > matmul.log 2>&1
```

### 步骤 3: 分析性能

```bash
# 生成完整报告（文本 + 图表）
python scripts/perf_analysis.py matmul.log --all

# 只生成图表
python scripts/perf_analysis.py matmul.log --plot

# 只生成文本报告
python scripts/perf_analysis.py matmul.log --report matmul_report.txt
```

### 步骤 4: 自顶向下分析

**示例分析流程**：

```bash
# 1. 查看系统级指标
$ python perf_analysis.py matmul.log | grep "Level 1" -A 20

Level 1: 系统级性能指标
============================================================
总执行周期数: 12,500,000
完成的宏指令数: 64
平均每条宏指令周期: 195,312.5

阶段分布:
  计算阶段:     4,375,000 (35.0%)
  加载阶段:     5,625,000 (45.0%)  ← 瓶颈！
  存储阶段:     1,875,000 (15.0%)
  停顿阶段:       625,000 (5.0%)

结论: 内存带宽瓶颈，进入 Level 2 分析

---

# 2. 查看阶段瓶颈
$ python perf_analysis.py matmul.log | grep "Level 2" -A 15

Level 2: 阶段级瓶颈分析
============================================================
指令ID     总周期      计算%      加载%      存储%      停顿%      并行%
----------------------------------------------------------------------
0-15       195312     35.2       45.1       15.3       4.4        12.3  ← 一致性瓶颈

结论: 所有指令都表现出相同的瓶颈模式，说明是系统性问题

---

# 3. 查看组件瓶颈
$ python perf_analysis.py matmul.log | grep "Level 3" -A 15

Level 3: 组件级瓶颈分析
============================================================
A-Load%    B-Load%    C-Load%    D-Store%   AOP%
15.0       15.0       15.0       15.0       0.0   ← 均衡但总体偏高

通道负载平衡度:
  A通道加载: 1,875,000 周期
  B通道加载: 1,875,000 周期
  C通道加载: 1,875,000 周期
  不平衡度:  0.0% ✓

结论: 通道均衡但内存带宽不足

---

# 4. 查看微架构指标
$ python perf_analysis.py matmul.log | grep "Level 4" -A 15

Level 4: 微架构效率指标
============================================================
平均计算效率:     87.5%      ✓
平均内存绑定度:   60.0%      ⚠️ 偏高
平均并行度:       12.3%      ⚠️ 偏低

💡 瓶颈诊断:
  ⚠️  系统存在严重的内存瓶颈
     建议：优化数据预取、增加带宽、优化数据布局
  ⚠️  并行度不足
     建议：优化微指令调度以提高并行度
```

---

## 性能优化建议树

```
根据分析结果进行优化：

Level 2 阶段瓶颈
├─ Compute Bound (>40%)
│  └─> Level 3 组件分析
│     ├─ MTE利用率低 → 增加计算并行度
│     └─ AOP占用高 → 优化后操作
│
├─ Memory Bound (>60%)
│  ├─ Load阶段高
│  │  ├─ Level 3: 通道不平衡 → 优化数据布局
│  │  └─ Level 3: MMU停顿高 → 优化预取/双缓冲
│  └─ Store阶段高
│     └─ 优化写回策略
│
└─ Stall Heavy (>30%)
   └─> Level 4 微操作分析
      ├─ 计算效率低 → 减少依赖
      └─ 并行度低 → 优化调度
```

---

## 常见性能问题与解决方案

| 问题 | 诊断 | 解决方案 |
|-----|------|---------|
| **高延迟** | Level 1总周期高 | Level 2定位阶段 |
| **吞吐量低** | Level 4并行度低 | 增加微指令级并行 |
| **内存带宽饱和** | Level 2 Memory Bound | 数据分块优化 |
| **计算单元空闲** | Level 2 Stall高 | 优化指令调度 |
| **通道负载不均** | Level 3不平衡>20% | 调整数据布局 |

---

## 输出文件说明

运行分析后会生成以下文件：

1. **perf_breakdown.png**: 可视化性能分解图
   - 阶段分解饼图
   - 每条指令周期柱状图
   - 通道负载对比
   - 效率指标趋势

2. **perf_report.txt**: 完整文本报告
   - 所有4个级别的详细分析
   - 瓶颈诊断和优化建议

---

## 扩展分析

### 比较多个测试

```bash
# 运行多个测试并比较
for size in 512 1024 2048; do
    ./simulator matmul $size $size $size > matmul_${size}.log 2>&1
done

# 生成对比报告
python scripts/perf_analysis.py matmul_*.log --report comparison.txt
```

### 热力图分析

```python
# 生成矩阵大小热力图
sizes = [512, 1024, 2048, 4096]
for M in sizes:
    for N in sizes:
        for K in sizes:
            # 运行测试并记录结果
            pass
# 生成热力图：不同M,N,K配置下的性能
```

---

## 参考

- [CUTE 架构文档](./CUTE_Architecture.md)
- [性能计数器定义](../chipyard/generators/cute/src/main/scala/CUTEParameters.scala)
- [任务控制器实现](../chipyard/generators/cute/src/main/scala/TaskController.scala)
