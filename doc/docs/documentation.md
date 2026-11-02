# 文档维护与预览

## 维护愿望与实现的对应关系

网站分为 OpenCUTE、上手 demo、工程组件三个入口。OpenCUTE 包含总体介绍、愿望与目的、
实现方式；demo 包含 BERT 实践；工程组件包含操作参考及各子项目文档。
新增内容先说明服务哪个目标，再解释它怎样分解、有哪些接口，最后链接到实现和可复核
的实践。目录、字段、CLI 和调试细节放在工程组件中。

一次增量改变组件承诺时，应同步维护目标关系、事实来源、消费者和验收范围。内部
实现变化而接口不变时，更新相关实现说明和证据即可。组件介绍采用
[目标分解章](decomposition.md) 中的共同结构；新术语应能帮助解释责任或交接。

目标架构、已有实现和已有证据分别表述。增量任务说明是协作约定，尚未实现的自动化
是后续目标；示例配置与命令从当前代码核对，验收数据引用 [状态页](status.md)。

## 修改与构建入口

以下命令从 CUTE 仓库根目录执行。主指南、trace、SDK 和设计文档合并预览，
修改源文件后自动重建；生成的 HTML 不回写源码目录。

## 启动实时预览

```sh
python3 tools/docs/preview_docs.py
```

本服务器已有可用的文档 Python 环境，脚本会自动查找并打印所用解释器。
在 VS Code Remote-SSH 中打开 `/home/admin-yjp/CUTE`，也可以执行任务
**Tasks: Run Task → OpenCUTE: 文档实时预览**。仓库配置会尝试转发 `8010`
并打开浏览器；未自动打开时，在 Ports 面板转发该端口，使用面板中的地址。

| 页面 | 源文件 | 导航配置 |
|---|---|---|
| `/` OpenCUTE | `doc/docs/index.md` 及愿望、实现方式章节 | `doc/mkdocs.yml` 的第一个入口 |
| `/demo/` 上手 demo | `doc/docs/demo/index.md`、`doc/docs/practice.md` | `doc/mkdocs.yml` 的上手 demo 项 |
| `/engineering/` 工程组件 | `doc/docs/engineering/index.md` 及工程说明章节 | `doc/mkdocs.yml` 的工程组件项 |
| `/trace/` | `trace/docs/` | 工程组件下的 Trace 项 |
| `/sdk/` | `doc/sdk-doc/docs/` | `doc/sdk-doc/mkdocs.yml` |
| `/design/` | `doc/design-doc/docs/` | `doc/design-doc/mkdocs.yml` |

统一构建以 `doc/mkdocs.yml` 为顶栏导航来源，将 SDK 和硬件设计的内部目录嵌入
工程组件。子项目单独构建时仍使用各自导航；维护其章节时只需修改对应子项目配置。

保存 Markdown、图片、样式和导航配置后，浏览器会自动刷新。新增页面还需加入
对应导航。构建失败时页面提示错误并保留上一次成功版本，终端显示详细原因；
修正后自动恢复。`Ctrl+C` 停止服务。换端口使用 `--port 8011`，并转发该端口。

## 新机器的文档环境

先初始化 `doc/sdk-doc`、`doc/design-doc` 两个文档子模块，再创建独立环境。
Python 需支持 `venv` 和 `ensurepip`；若缺失，先安装发行版的 `python3-venv` 包，
或激活具有这些模块的 Python 环境。
下列命令使用相对于仓库根目录的固定路径，无需替换：

```sh
python3 -m venv ../opencute-out/docs-env
../opencute-out/docs-env/bin/python -m pip install -r doc/requirements.txt
python3 tools/docs/preview_docs.py --python ../opencute-out/docs-env/bin/python
```

也可通过 `CUTE_DOCS_PYTHON` 指定解释器。预览脚本不会自动安装依赖。
页面和导航采用三个站点合并后的 URL；单独启动子站时，跨站导航不一定可用。

## 定稿检查

1. 对照当前代码核对命令、参数、默认值、路径及阶段编号。历史流程须注明来源和范围。
2. 能力结论指向绑定源码和产物的报告。当前验收数字集中维护在
   [状态页](status.md#model-acceptance)，SDK 和设计页链接引用。
3. 从仓库根目录执行统一构建，检查三个站点以及跨站链接和锚点：

   ```sh
   ../opencute-out/docs-env/bin/python tools/docs/build_docs.py \
     --out ../opencute-out/docs-site
   ```

4. 审阅 `../opencute-out/docs-site-logs/results.json` 和 `links.json`，所有构建退出码应为
   `0`，链接错误应为空。在浏览器确认导航、表格、代码块和修改涉及的图示。
5. 分别查看主仓库、`doc/sdk-doc`、`doc/design-doc` 的 diff。两个文档子模块是
   独立仓库，顶层 gitlink 不包含子模块尚未提交的内容。

输出目录须位于源码树之外，且为空目录或该脚本此前生成的站点。此构建只生成
本地网站；发布或提交文档是后续独立操作。历史论文数据与当前实验报告分开标明，
文档检查通过不构成新的功能或性能验收。
