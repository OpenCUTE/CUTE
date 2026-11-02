# 核心子模块简介

前面拆出了构建、计算、观测和验证这些小愿望。现在打开仓库，先看看它们分别落在
哪个文件夹，再逐个理解核心模块负责什么、与谁配合。

## 先看目录：核心模块在哪里 {#directories}

下面按仓库中的真实路径列出核心目录。点击三角或目录行展开子目录，点击“介绍”跳到
对应说明。只展开与主线相关的目录，构建产物和历史实验不在这里铺开。

<nav class="repo-tree" aria-label="OpenCUTE 核心模块目录">
  <div class="repo-tree-heading"><strong>CUTE/</strong><span>仓库根目录</span></div>
  <ul class="repo-tree-list">
    <li data-repo-path="configs">
      <details>
        <summary><code>configs/</code><span class="repo-tree-desc">构建目标与配置</span> <a class="repo-tree-jump" href="#opencute">介绍<span aria-hidden="true"> →</span></a></summary>
        <ul>
          <li data-repo-path="configs/hwconfigs"><div class="repo-tree-row"><code>hwconfigs/</code><span class="repo-tree-desc">本次构建的总入口</span></div></li>
          <li data-repo-path="configs/chipyard_configs"><div class="repo-tree-row"><code>chipyard_configs/</code><span class="repo-tree-desc">处理器、计算部件与互联组合</span></div></li>
          <li data-repo-path="configs/cute_configs"><div class="repo-tree-row"><code>cute_configs/</code><span class="repo-tree-desc">CUTE 本体参数</span></div></li>
          <li data-repo-path="configs/cute_isa_versions"><div class="repo-tree-row"><code>cute_isa_versions/</code><span class="repo-tree-desc">指令与数据类型编码</span></div></li>
          <li data-repo-path="configs/isa_profiles"><div class="repo-tree-row"><code>isa_profiles/</code><span class="repo-tree-desc">目标必须提供的能力</span></div></li>
          <li data-repo-path="configs/memory_maps"><div class="repo-tree-row"><code>memory_maps/</code><span class="repo-tree-desc">内存、设备地址与保留区布局</span></div></li>
          <li data-repo-path="configs/execution_profiles"><div class="repo-tree-row"><code>execution_profiles/</code><span class="repo-tree-desc">软件运行与后端策略</span></div></li>
        </ul>
      </details>
    </li>
    <li data-repo-path="src">
      <details>
        <summary><code>src/</code><span class="repo-tree-desc">CUTE 硬件本体</span> <a class="repo-tree-jump" href="#opencute">介绍<span aria-hidden="true"> →</span></a></summary>
        <ul>
          <li data-repo-path="src/main/scala"><div class="repo-tree-row"><code>main/scala/</code><span class="repo-tree-desc">计算、存储、控制和 CPU 接口</span></div></li>
        </ul>
      </details>
    </li>
    <li data-repo-path="CPU">
      <details>
        <summary><code>CPU/</code><span class="repo-tree-desc">处理器实现</span> <a class="repo-tree-jump" href="#platform">介绍<span aria-hidden="true"> →</span></a></summary>
        <ul>
          <li data-repo-path="CPU/shuttle"><div class="repo-tree-row"><code>shuttle/</code> <span class="repo-tree-badge">Git 子模块</span><span class="repo-tree-desc">Shuttle</span></div></li>
          <li data-repo-path="CPU/rocket"><div class="repo-tree-row"><code>rocket/</code> <span class="repo-tree-badge">Git 子模块</span><span class="repo-tree-desc">Rocket</span></div></li>
          <li data-repo-path="CPU/boom"><div class="repo-tree-row"><code>boom/</code> <span class="repo-tree-badge">Git 子模块</span><span class="repo-tree-desc">BOOM</span></div></li>
        </ul>
      </details>
    </li>
    <li data-repo-path="Vector">
      <details>
        <summary><code>Vector/</code><span class="repo-tree-desc">向量计算实现</span> <a class="repo-tree-jump" href="#platform">介绍<span aria-hidden="true"> →</span></a></summary>
        <ul>
          <li data-repo-path="Vector/saturn"><div class="repo-tree-row"><code>saturn/</code> <span class="repo-tree-badge">Git 子模块</span><span class="repo-tree-desc">Saturn 向量单元</span></div></li>
          <li data-repo-path="Vector/titan-I"><div class="repo-tree-row"><code>titan-I/</code> <span class="repo-tree-badge">Git 子模块</span><span class="repo-tree-desc">T1 向量实现</span></div></li>
        </ul>
      </details>
    </li>
    <li data-repo-path="chipyard">
      <div class="repo-tree-row repo-tree-leaf"><code>chipyard/</code> <span class="repo-tree-badge">Git 子模块</span><span class="repo-tree-desc">组合 SoC、生成硬件与仿真环境</span> <a class="repo-tree-jump" href="#platform">介绍<span aria-hidden="true"> →</span></a></div>
    </li>
    <li data-repo-path="cute-sdk">
      <details open>
        <summary><code>cute-sdk/</code> <span class="repo-tree-badge">Git 子模块</span><span class="repo-tree-desc">CUTE-SDK · 软件与预期结果</span> <a class="repo-tree-jump" href="#sdk">介绍<span aria-hidden="true"> →</span></a></summary>
        <ul>
          <li data-repo-path="cute-sdk/cuteisa"><div class="repo-tree-row"><code>cuteisa/</code><span class="repo-tree-desc">软件使用的指令接口</span></div></li>
          <li data-repo-path="cute-sdk/cutelib"><div class="repo-tree-row"><code>cutelib/</code><span class="repo-tree-desc">运行时与计算库</span></div></li>
          <li data-repo-path="cute-sdk/targets"><div class="repo-tree-row"><code>targets/</code><span class="repo-tree-desc">目标适配与能力需求</span></div></li>
          <li data-repo-path="cute-sdk/cuteqemu"><div class="repo-tree-row"><code>cuteqemu/</code> <span class="repo-tree-badge">Git 子模块</span><span class="repo-tree-desc">QEMU ISA 模拟器</span> <a class="repo-tree-jump" href="/qemu/">介绍<span aria-hidden="true"> →</span></a></div></li>
          <li data-repo-path="cute-sdk/tests"><div class="repo-tree-row"><code>tests/</code><span class="repo-tree-desc">用例、输入与参考结果</span></div></li>
        </ul>
      </details>
    </li>
    <li data-repo-path="cute-fpe">
      <details>
        <summary><code>cute-fpe/</code> <span class="repo-tree-badge">Git 子模块</span><span class="repo-tree-desc">CUTE-FPE · 浮点部件</span> <a class="repo-tree-jump" href="#fpe">介绍<span aria-hidden="true"> →</span></a></summary>
        <ul>
          <li data-repo-path="cute-fpe/fpe"><div class="repo-tree-row"><code>fpe/</code><span class="repo-tree-desc">浮点硬件实现</span></div></li>
          <li data-repo-path="cute-fpe/ccode"><div class="repo-tree-row"><code>ccode/</code><span class="repo-tree-desc">数值参考代码</span></div></li>
        </ul>
      </details>
    </li>
    <li data-repo-path="trace">
      <details>
        <summary><code>trace/</code><span class="repo-tree-desc">CUTE-Trace · 执行记录</span> <a class="repo-tree-jump" href="#trace">介绍<span aria-hidden="true"> →</span></a></summary>
        <ul>
          <li data-repo-path="trace/catalogs"><div class="repo-tree-row"><code>catalogs/</code><span class="repo-tree-desc">事件与字段的定义</span></div></li>
          <li data-repo-path="trace/cutetrace"><div class="repo-tree-row"><code>cutetrace/</code><span class="repo-tree-desc">硬件侧事件接口</span></div></li>
          <li data-repo-path="trace/python"><div class="repo-tree-row"><code>python/</code><span class="repo-tree-desc">日志读取与解码</span></div></li>
          <li data-repo-path="trace/docs"><div class="repo-tree-row"><code>docs/</code><span class="repo-tree-desc">事件与协议说明</span></div></li>
        </ul>
      </details>
    </li>
    <li data-repo-path="tools">
      <details open>
        <summary><code>tools/</code><span class="repo-tree-desc">构建、运行与检查工具</span> <a class="repo-tree-jump" href="#verify">介绍<span aria-hidden="true"> →</span></a></summary>
        <ul>
          <li data-repo-path="tools/runner"><div class="repo-tree-row"><code>runner/</code><span class="repo-tree-desc">配置、构建和运行入口</span> <a class="repo-tree-jump" href="#opencute">介绍<span aria-hidden="true"> →</span></a></div></li>
          <li data-repo-path="tools/trace"><div class="repo-tree-row"><code>trace/</code><span class="repo-tree-desc">事件生成与日志解码工具</span> <a class="repo-tree-jump" href="#trace">介绍<span aria-hidden="true"> →</span></a></div></li>
          <li data-repo-path="tools/verify"><div class="repo-tree-row"><code>verify/</code><span class="repo-tree-desc">CUTE-Verify · 正确性检查</span> <a class="repo-tree-jump" href="#verify">介绍<span aria-hidden="true"> →</span></a></div></li>
          <li data-repo-path="tools/docs"><div class="repo-tree-row"><code>docs/</code><span class="repo-tree-desc">网站构建与实时预览</span></div></li>
        </ul>
      </details>
    </li>
    <li data-repo-path="doc">
      <details>
        <summary><code>doc/</code><span class="repo-tree-desc">主指南与子项目文档</span></summary>
        <ul>
          <li data-repo-path="doc/docs"><div class="repo-tree-row"><code>docs/</code><span class="repo-tree-desc">当前主指南</span></div></li>
          <li data-repo-path="doc/sdk-doc"><div class="repo-tree-row"><code>sdk-doc/</code> <span class="repo-tree-badge">Git 子模块</span><span class="repo-tree-desc">软件接口与实现文档</span> <a class="repo-tree-jump" href="/sdk/">介绍<span aria-hidden="true"> →</span></a></div></li>
          <li data-repo-path="doc/design-doc"><div class="repo-tree-row"><code>design-doc/</code> <span class="repo-tree-badge">Git 子模块</span><span class="repo-tree-desc">硬件设计文档</span> <a class="repo-tree-jump" href="/design/">介绍<span aria-hidden="true"> →</span></a></div></li>
        </ul>
      </details>
    </li>
  </ul>
</nav>

“Git 子模块”标记表示该目录连接到独立仓库。本文按职责介绍核心模块，其中
CUTE-Trace 位于 `trace/`，CUTE-Verify 位于 `tools/verify/`，它们目前属于主仓库目录。

第一次阅读，可以先认住四个位置：`configs/` 保存系统选择，`src/main/scala/` 实现
CUTE 硬件，`cute-sdk/` 提供软件，`trace/` 与 `tools/verify/` 配合检查实际执行。
CPU、向量单元和 Chipyard 为这些部件组成 SoC 提供基础。

下面从系统构建开始介绍。需要查每个目录的维护检查时，参见 [仓库与文档职责](repository.md)。

## OpenCUTE：把 CONFIG 中的选择变成 SoC {#opencute}

对应目录：`configs/`、`src/main/scala/`、`tools/runner/`。

开发者已经选好了 CPU、向量单元、矩阵加速器和内存组合，希望直接构建出对应的系统。
OpenCUTE 接住这个愿望：沿配置的引用关系，找到 Chipyard、CPU、Vector、CUTE 等
部件，把参数交给实现，生成 RTL 和 simulator。

软件随后还需要知道这个系统提供什么。当前 system 构建会读取同次硬件生成的 DTS，
核对 ISA、内存和接口要求，再生成 SDK 目标包。SDK 和 runner 继续使用这份产物，
减少在下游手工重写平台参数的机会。

所以，OpenCUTE 的交付既包含硬件，也包含其他组件能够理解的目标描述。一个 CONFIG
能通过字段检查，是开始构建的条件；它选出的组合能否运行，还要通过软件、后端和
系统测试。对象关系见 [配置依赖图](config-architecture.md)，命令见 [构建](build-system.md)。

### Chipyard、CPU 与 Vector：把各部件接成系统 {#platform}

`src/main/scala/` 中的 CUTE 是一个计算部件。要让程序调用它，还需要处理器执行指令、
内存保存数据，以及连接这些部件的系统基础。

`CPU/` 放置处理器实现，`Vector/` 放置向量单元实现；`chipyard/` 根据配置把部件
组合起来，并提供硬件生成和仿真环境。例如当前上手实验使用 Shuttle 处理器与 Saturn
向量单元。目录中存在某种实现，表示仓库有这个组件，具体配置能否协作仍要检查和验收。

## CUTE-SDK：把“算这个”变成程序和预期结果 {#sdk}

对应目录：`cute-sdk/`；其中 `cuteqemu/` 是 SDK 使用的 QEMU ISA 模拟器。

有了 SoC，我们还要把“做一次矩阵乘法，再量化和转置”变成可以运行的程序。
SDK 接收目标提供的 ISA 和内存信息，提供 runtime、数值核及组合阶段，说明怎样
提交计算、怎样等待、结果放在哪里。

SDK 也要把软件的需求说清楚。一个程序需要哪些指令、多少工作空间、哪个执行核，
通过 requires 交给目标检查器。这样，能力不匹配可以在运行前被发现。

验证时，QEMU 和 reference 都服务于这段软件，但分别回答不同的问题：

- reference 按约定独立计算预期值，检查数值规则。
- QEMU 按 ISA 定义的指令语义执行程序，在 checkpoint 导出任务输出，并接受 reference 校准。
- 校准后的 QEMU 输出作为 golden，继续与 RTL 的输出逐字节比较。

例如 BERT 的 Q/K/V 投影，除了最终 INT8 结果，还会检查 INT32 累加值和转置输出。
中间结果明确，失败时才容易知道问题出在哪一段。
具体接口见 [SDK 文档](/sdk/)、[QEMU](qemu.md) 和 [模型 case](/sdk/testing/model-case/)。

## CUTE-Trace：把“硬件正在做什么”记录下来 {#trace}

对应目录：`trace/`、`tools/trace/`。

只看到仿真进程还活着，很难知道它是否正常推进。只看到最终答案，也很难判断中间
有没有错误的数据交接。cute-trace 要让这些行为变得可观察。

当前系统路径记录 CUTE/RVV 的访存请求、响应、checkpoint 和端口水位。
其中，“请求写入”表示发出了请求；“成功写响应”才支持检查器把相应字节视为已写入。
把这两个时刻分清，才能检查后一个任务有没有过早读取结果。

事件名字、编号和字段在 catalog 中定义，再生成发出端和读取端使用的 API。
维护者新增观测时，从这个定义开始，重新生成并构建消费者。AI 观察日志，也就能沿
这些明确的事件追踪进度，而不用猜一段 printf 到底表示什么。

事件含义、完整性和接入位置见 [Trace 总览](trace/index.md) 与 [事务协议](trace/protocol.md)。

## CUTE-FPE：把“用这种精度计算”落实到部件 {#fpe}

对应目录：`cute-fpe/fpe/`、`cute-fpe/ccode/`。

“支持一种浮点格式”包含不少具体决定：输入如何编码，乘法和累加用什么精度，在哪一步
舍入，溢出和异常值怎么处理。只有把这些说清楚，硬件、软件和参考模型才能算同一种结果。

cute-fpe 负责相应的浮点部件与数值参考代码。当前硬件实现位于 `cute-fpe/fpe`，
参考相关代码位于 `cute-fpe/ccode`。ISA 中的 datatype 编码帮助各处识别格式，完整
运算规则还需要对应的实现和测试。

目前已有浮点硬件和部分 CPU/RVV 浮点路径的测试，CUTE 浮点矩阵的 QEMU 位级模型与
系统验收仍需补齐。因此新增浮点能力时，可以先交付一种明确运算的参考和边界向量，
再逐步接上硬件、SDK 与系统验证。当前范围见 [进展](status.md) 和
[硬件数据类型](/design/datatypes/)。

## CUTE-Verify：拿真实记录判断这次运行对不对 {#verify}

对应目录：`tools/verify/`。

现在我们知道预期结果，也拿到了 RTL 的执行记录。verify 把它们接起来：从已知初态
开始，根据真实请求和成功响应重建内存，在任务完成时比较约定的全部输出。

如果少了一段日志、一个字节从未被观察到，或者仿真异常退出，检查器必须把问题指出来。
用 golden 填补未知的 actual，虽然可能得到相同结果，却已经失去检查的意义。

当前在线和离线模式使用同一个 C++ 检查引擎。在线模式一边运行一边检查，帮助及早
停止已确定失败的实验；离线模式用保存的日志独立回放，方便复核和定位。
正例证明它能接受正确执行，反例证明它确实能抓住错误。

具体流程见 [系统级验证](system-verification.md)，可以先跟随
[离线实验](demo/offline.md) 和 [在线实验](demo/online.md) 看一遍真实结果。

## 它们怎样共同交付一个结果

沿着一次实验看，交接顺序就清楚了：

| 交接 | 下一环节需要拿到什么 |
|---|---|
| OpenCUTE → SDK | 这套目标的 ISA、内存视图、向量参数和启动约定 |
| SDK → QEMU、reference、RTL | 同一段计算的程序、输入、数值规则和任务输出描述 |
| QEMU、reference → verify | 经过校准、对应本次任务的 golden |
| RTL → trace → verify | 实际发生的请求、响应和完成事件 |
| 构建与 runner → 结果使用者 | 本次源码、配置、工具、输入和产物的身份记录 |

软件等待、硬件完成、trace 事件和 verify 的比较时刻必须对齐。哪个环节改变了对外
含义，就沿这张交接表检查它的消费者。subagent 可以分头实现，父任务仍要检查最终
合作结果。

接下来沿 [Config-first 对象与依赖](config-architecture.md)，看配置怎样生成产物、
保持交接一致，并接住下一次增量。
