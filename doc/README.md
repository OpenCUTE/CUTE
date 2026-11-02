# OpenCUTE 文档入口

OpenCUTE 的核心愿望是用自然语言完成 RTL SoC 开发。这套文档解释怎样把愿望逐层
具体化，让各子项目通过明确的接口协作，再用工程实践检验结果。
网站分为三个入口：

| 入口 | 讨论什么 | 章节 |
|---|---|---|
| [OpenCUTE：从愿望到可以验证的 SoC](docs/index.md) | 总体介绍、愿望与目的、实现方式 | 目标分解、组件承诺、配置依赖、Only One Truth 与增量开发 |
| [上手 demo](docs/demo/index.md) | 跟随小实验逐步动手 | 环境、RTL、golden、trace、离线/在线检查及 BERT 阶段实践；每步配验收图 |
| [工程组件](docs/engineering/index.md) | 工程操作、接口与子项目文档 | 配置、构建、运行、验证、Trace、SDK、硬件设计与维护 |

主文档面向人解释目的和协作关系，也为 AI 提供可继续追踪的定义、实现和验收入口。
字段、命令、API 和硬件细节由相应参考章节维护。源码、配置和带版本的运行报告共同
决定当前能力状态。

## 工程组件与维护位置

| 阅读目标 | 入口 | 维护位置 |
|---|---|---|
| 定位各组件的工程目录 | [目录与职责](docs/repository.md) | `doc/docs/` |
| 第一次配置与构建 | [构建系统](docs/build-system.md) | 主仓库；命令均从 CUTE 根目录执行 |
| 运行和定位失败 | [运行与结果](docs/running.md) | 主仓库 runner 与 verifier |
| 维护 trace | [trace 开发文档](../trace/docs/index.md) | `trace/`；catalog 是事件定义源 |
| 使用软件 API、增加负载 | [SDK 文档](sdk-doc/docs/index.md) | 独立 `doc/sdk-doc` 子模块 |
| 阅读硬件模块 | [设计文档](design-doc/docs/index.md) | 独立 `doc/design-doc` 子模块 |
| 查清哪些能力已验证 | [能力与验收边界](docs/status.md) | 已测 profile、case 与证据，不以功能名代替验收 |
| 审阅、修改和定稿文档 | [文档维护与预览](docs/documentation.md) | 预览入口、导航位置与定稿检查 |

## VS Code 实时审阅与修改

用 VS Code Remote-SSH 打开 CUTE 仓库文件夹（本服务器为 `/home/admin-yjp/CUTE`），
在仓库根目录的集成终端运行：

```sh
python3 tools/docs/preview_docs.py
```

也可以按 `Ctrl+Shift+P`，选择 **Tasks: Run Task → OpenCUTE: 文档实时预览**，或打开
[preview_docs.py](../tools/docs/preview_docs.py) 后点击 Python 扩展的“在终端运行 Python 文件”。
不要求 VS Code 当前选中的 Python 已安装 MkDocs；脚本会单独寻找可用的文档解释器。

仓库的 `.vscode/settings.json` 为 `8010` 配置了自动转发和打开浏览器。脚本打印
`http://127.0.0.1:8010/` 后，Remote-SSH 会根据终端输出发现端口。网站只监听服务器的
loopback 地址，通过 VS Code 转发访问。若没有自动转发，在 **Ports/端口** 面板添加
`8010`，然后点击浏览器图标；本地端口被占用时，以该面板显示的 **Forwarded Address** 为准。
参见 [VS Code 官方端口转发说明](https://code.visualstudio.com/docs/remote/ssh#_forwarding-a-port-creating-ssh-tunnel)。

| 浏览器路径 | 在 VS Code 中修改的源文件 |
|---|---|
| `/` OpenCUTE | `doc/docs/index.md` 及愿望、实现方式章节 |
| `/demo/` 上手 demo | `doc/docs/demo/index.md`、`doc/docs/practice.md` |
| `/engineering/` 工程组件 | `doc/docs/engineering/index.md` 及工程说明章节 |
| `/trace/` | `trace/docs/*.md` |
| `/sdk/` | `doc/sdk-doc/docs/` |
| `/design/` | `doc/design-doc/docs/` |

保存 Markdown、图片、样式或三份 `mkdocs.yml` 后，脚本会自动严格构建并刷新页面，通常
需要几秒。新增/删除页面也会被检测；新增页面的菜单项编辑对应的 `mkdocs.yml`。
构建失败时浏览器提示错误、终端显示诊断，并继续显示上一次成功页面；修正并保存后自动恢复。
浏览器预览仅用于阅读，源文件仍在 VS Code 编辑。生成站点位于临时目录，停止时清理。

按终端 `Ctrl+C` 停止；使用任务启动时也可执行 **Tasks: Terminate Task**。
不要同时启动两个使用 `8010` 的预览进程。需要换端口时：

```sh
python3 tools/docs/preview_docs.py --port 8011
```

解释器查找顺序：显式 `--python` / `CUTE_DOCS_PYTHON` → 当前 Python → 仓库的
`.venv-docs` / `.venv` → 本服务器 `workspace/cute-model-migration-*/tools/docs` 中的文档环境。
启动时会打印实际使用的解释器。脚本不会自动安装依赖；新机器先按下面的依赖步骤创建环境。
通过 `--port` 改端口后，可在 Ports 面板转发新端口，或调整 `.vscode/settings.json` 对应条目。

## 本地构建三个站点

依赖见 [requirements.txt](requirements.txt)。从仓库根目录执行，环境和站点使用固定的
相对路径，无需替换。`../opencute-out/` 位于源码树之外，与系统构建的输出约定一致：

Python 需支持 `venv` 和 `ensurepip`。若系统 Python 提示缺少它们，先安装发行版的
`python3-venv` 包，或激活已具备这两个模块的 Python 环境。

```sh
python3 -m venv ../opencute-out/docs-env
../opencute-out/docs-env/bin/python -m pip install -r doc/requirements.txt
../opencute-out/docs-env/bin/python tools/docs/build_docs.py --out ../opencute-out/docs-site
python3 -m http.server 8010 --bind 127.0.0.1 --directory ../opencute-out/docs-site
```

要用这个环境实时预览，可执行：

```sh
python3 tools/docs/preview_docs.py --python ../opencute-out/docs-env/bin/python
```

网页顶栏固定为 OpenCUTE、上手 demo、工程组件三个入口。Trace、`/sdk/`、`/design/`
均归入工程组件；进入 SDK 或硬件设计后仍保留三个入口，并在侧栏展开相应子项目。
统一构建从 `doc/mkdocs.yml` 派生这套导航，子项目自己的 `mkdocs.yml` 维护其内部目录。
脚本在独立临时目录汇集主指南和 trace，不复制生成文件回源目录；所有站点用
MkDocs strict 模式构建。子模块文档的修改需要在对应子模块内审阅，顶层 gitlink
本身不包含这些文件。构建文档不发布网页。输出位置须在源码仓库之外，且为空目录或本脚本此前生成的站点。

统一构建已自动检查三个站点间的本地链接与锚点。报告位于输出目录旁的
`../opencute-out/docs-site-logs/results.json` 和 `links.json`；全部退出码为 `0` 且链接错误为空
才算文档检查通过。也可单独重查：
`python3 tools/docs/check_links.py ../opencute-out/docs-site`。

Mermaid 10.4.0 脚本、许可证和来源哈希固定在主仓库的
`doc/docs/assets/vendor/mermaid-10.4.0/`。统一构建在临时目录中为设计站提供同一份脚本，
不依赖设计子模块中是否保留该资源，也不修改其源文件。图的源代码直接维护在 Markdown
的 Mermaid 代码块中；保存后预览自动更新。
