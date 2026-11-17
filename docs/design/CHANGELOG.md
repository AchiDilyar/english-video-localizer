# 项目设计相关文档修订记录

## 2026-11-08 chore: 初始化设计文档与 contracts 契约模型
### 版本变更

 -> `v1.0`

### 涉及文档

- `workflow.md`
- `dataflow.md`
- `architecture.md`
- `collaboration.md`

### 修改内容

- 第一版完整内容

### 修改原因

- 初始化项目设计文档

## 2026-11-09 refactor(contracts): GraphState 改为 Pydantic 模型

### 版本变更

`v1.0` -> `v1.0.1`

### 涉及文档

- `dataflow.md`
- `architecture.md`

### 修改内容

- `GraphState` 从 `TypedDict` 改为 Pydantic `BaseModel`

### 修改原因

- 统一 `contracts/` 与 `utils/io.py` 的类型体系，使 `GraphState` 可被 Pydantic 校验、可被 `read_artifact`/`write_artifact` 直接处理，消除未来落盘/检查点时的嵌套模型退化风险。

## 2026-11-09 refactor(utils): 落盘产物路径与读写管理；design文档版本管理

### 版本变更

`v1.0.1` -> `v1.1.0`

### 涉及文档

- `dataflow.md`
- `workflow.md`
- `architecture.md`
- `collaboration.md`
- `CHANGELOG.md`（按新格式重组历史条目）

### 修改内容

1. 重新设计落盘产物读写和获取路径规范

- 明确落盘产物读写和获取路径规范：只有结构化JSON数据能使用读写函数，读写函数内自动校验；二进制文件只能获取绝对路径
- 修改了`architecture.md`中`utils/`相关函数的定义，定义产物规格表，并规定由`utils/artifacts.py`管理
- 完善了`dataflow.md`和`architecture.md`中落盘产物的读写和获取路径规则，删除了重复表述

2. 修正`tts_clips`承载了两种磁盘形态的问题

- 修改了`workflow.md`和`dataflow.md`，将原`tts_clips`产物拆分为`tts_clips`和`tts_audio`，前者保存元信息，后者保存二进制数据
- 在`dataflow.md`中，将拆分后的产物视为普通产物处理，删除了针对原`tts_clips`处理引起的特例说明
- 在`dataflow.md`的工作目录结构中，新增 `tts/clips.json`。

3. 修改`docs/design`目录下的版本管理相关内容

- 删除`architecture.md`中“文档变更记录规范”章节以及文档定位、唯一事实源中的相关描述
- 在`collaboration.md`中添加“design目录下文档版本管理”章节
- 将`collaboration.md`放入`architecture.md`2.2节的代码目录结构中
- 约定四份文档的版本号变更规则
- 修改“变更记录格式”及对应示例，放入`collaboration.md`的“文档变更记录规范”章节内
- 按照“变更记录格式”重新组织`CHANGELOG.md`的历史

### 修改原因

1. 重新设计落盘产物读写和获取路径规范

- `architecture.md` 第 6.2 节原 `write_artifact` 的 docstring 要求"写入前做 Pydantic 校验"，但签名无校验类型参数，与 `dataflow.md` 第 5.2 节第 4 条矛盾，函数无法履行承诺；原 `register_model` 折中方案未注册时静默跳过校验，且无法校验 `list[Segment]` 等列表产物。
- 校验类型是产物名称的固有属性（如 `segments` 永远是 `list[Segment]`），应与路径一样由名称解析，而非由调用方每次传入。放回名称下后签名-职责矛盾从根上消除，列表产物获得统一校验方式。
- 两个文档对"JSON 用读写函数、二进制用 artifact_path"、"从规格表取校验类型"等内容存在单文档内与跨文档重复。按"函数视角归 `architecture.md` 第 6 节、数据视角归 `dataflow.md` 第 5 节"重新划分，跨视角只引用不重述。

2. 修正`tts_clips`承载了两种磁盘形态的问题

- 原 `tts_clips` 同一名称同时指代 `tts/` 下的 WAV 文件（二进制）与 `GraphState` 中的 `list[TTSClip]`（结构化元数据），违反"名称与磁盘格式一一对应"原则——同一名称在不同场景下格式不同，`read_artifact("tts_clips")` 无法定义行为。
- WAV 必须落盘（`compose_video` 用 FFmpeg 拼接），元数据也应落 JSON 以获得持久化副本与调试依据，两者本就不应挤在同一名称下。拆分后各得其所，`tts_clips` 与 `segments`、`blocks` 等结构化产物表现一致。

3. 修改`docs/design`目录下的版本管理相关内容

- 文档变更记录规范属于团队协作约定，不属于代码架构。`collaboration.md` §4 已管 CHANGELOG 的流程，唯独格式留在 `architecture.md`，流程与格式割裂；且 CHANGELOG 记录四份文档的变更，由被记录文档之一定义格式身份重叠。
- 四份文档强耦合（改节点名或产物名都要动 3 份），独立版本号会频繁出现"三份升版、一份未动"，读者难以判断是否一致。统一版本号使"文档集当前状态"一目了然，与 CHANGELOG"一段 = 一次修改 = 一个版本"的结构对齐。
- 历史 CHANGELOG 标题含单文档名与单文档版本，无法表达"一次修改涉及多文档、文档集版本是多少"。改为"日期 + 提交标题"、版本变更单列一行后，一段对应一次提交，语义完整。

## 2026-11-09 docs(architecture): 新增测试与日志组织规范

### 版本变更
`v1.1.0` -> `v1.2.0`

### 涉及文档
- `architecture.md`
- `dataflow.md`

### 修改内容
- `architecture.md` §9：新增测试与日志组织规范。测试代码位于顶层 `tests/`、结构镜像 `project/`，通过 `python -m pytest` 运行；日志统一写入 `work_dir/logs/run.log`，`logger` 使用 `__name__`。不强制每模块提供测试或日志。
- `architecture.md` 明确"不做完整测试体系"不强制每模块提供测试或日志。
- `architecture.md` 补充测试与日志组织为事实源；顶层目录新增 `tests/`；职责表新增 `tests/`、`utils/log.py`。
- `dataflow.md` 工作目录结构新增 `logs/run.log`，说明为运行副产品、非产物。

### 修改原因
- 原 `architecture.md` 未规定测试与日志的存放位置；`workflow.md`中"不包含测试体系"被误读为"不写测试或日志"，实际空档是"没有存放规范"。
- 补"组织规范"而非"强制体系"：只回答"如果有，放哪里、如何分类"，对测试内容与形式无要求；日志统一一个文件，靠 `%(name)s` 与级别区分。

## 2026-11-09 docs(architecture): 新增测试与日志组织规范

### 版本变更
`v1.1.0` -> `v1.2.0`

### 涉及文档
- `architecture.md`
- `dataflow.md`

### 修改内容
- `architecture.md` §9：新增测试与日志组织规范。测试代码位于顶层 `tests/`、结构镜像 `project/`，通过 `python -m pytest` 运行；日志统一写入 `work_dir/logs/run.log`，`logger` 使用 `__name__`。不强制每模块提供测试或日志。
- `architecture.md` 明确"不做完整测试体系"不强制每模块提供测试或日志。
- `architecture.md` 补充测试与日志组织为事实源；顶层目录新增 `tests/`；职责表新增 `tests/`、`utils/log.py`。
- `dataflow.md` 工作目录结构新增 `logs/run.log`，说明为运行副产品、非产物。

### 修改原因
- 原 `architecture.md` 未规定测试与日志的存放位置；`workflow.md`中"不包含测试体系"被误读为"不写测试或日志"，实际空档是"没有存放规范"。
- 补"组织规范"而非"强制体系"：只回答"如果有，放哪里、如何分类"，对测试内容与形式无要求；日志统一一个文件，靠 `%(name)s` 与级别区分。

## 2026-11-09 feat(utils): 按产物规格表实现 paths/io

### 版本变更
`v1.2.0` -> `v1.2.1`

### 涉及文档
- `architecture.md`

### 修改内容
- `architecture.md` 第2.1节：`docs/` 目录树新增 `utils/`，与已有 `nodes/`、`graph/`、`cli/` 并列，存放 utils 模块的补充文档。

### 修改原因
- utils 模块已有实现文档（`docs/utils/README.md`），需在目录结构事实源中登记其位置，与其它模块的补充文档保持一致。

## 2026-11-10 docs(design): 补充依赖管理并调整文档版本号规则

### 版本变更
`v1.2.1` -> `v1.3.0`

### 涉及文档
- `architecture.md`
- `collaboration.md`

### 修改内容
- `architecture.md` 新增“依赖管理”章节：`uv` 管理依赖与虚拟环境；`pyproject.toml` 声明依赖，`uv.lock` 锁定版本；运行统一用 `uv run ...`；新增依赖用 `uv add` / `uv add --dev`。
- `architecture.md` 测试章节：测试命令由 `python -m pytest` 改为 `uv run pytest`，`pyproject.toml` 的 `pythonpath` 配置保留。
- `collaboration.md` 5.1 版本管理：删除“四份文档头部显示同一版本号、每次修改必须同步更新四份”的要求；改为“四份文档使用统一版本号体系，有修改的文档更新版本号，无修改的可保留原版本号，不要求任意时刻一致”。

### 修改原因
- 团队已确认沿用 `uv` 管理依赖，需明确运行和依赖添加方式，避免裸 `python` / `pip` 导致环境不一致。
- 原“四份文档强制同版本号”在仅部分文档修改时会产生无意义升版；改为按实际修改升版，减少维护成本，同时保留统一版本号体系。

## 2026-11-12 docs(dataflow): 明确最终 ZIP 内容清单

### 版本变更
`v1.3.0` -> `v1.3.1`

### 涉及文档
- `dataflow.md`

### 修改内容
- 第 6 节明确最终 ZIP 包含五项：`final_video`、`bilingual_srt`、`cover_image`、`edit_assets.json`、`manifest.json`；`PackageManifest.entries` 必须完整列出以上五项且包含 `manifest.json` 自身。
- 明确 `dub_audio`、`source_audio`、`burnin_subtitle`、`tts_audio`、`tts_clips`、`segments`、`blocks`、`translated_blocks`、`reviewed_blocks` 为中间产物或调试副本，不进 ZIP。

### 修改原因
- 原第 6 节仅以“发布包内文件或中间产物”笼统表述，未逐项说明哪些进 ZIP；`dub_audio` 是否进 ZIP 无法从文档确定，导致 `package_zip` 实现与文档可能不一致。

## 2026-11-12 refactor(design): 删除 edit_assets、collect_manifest、package_zip，最终产物改为成片

### 版本变更
-> `v1.4.0`

### 涉及文档
- `workflow.md`
- `dataflow.md`
- `architecture.md`
- `contracts/`

### 修改内容
- 删除 `edit_assets`、`collect_manifest`、`package_zip` 节点；节点数 11 → 8；`compose_video` 为最后一个业务节点，完成后直接进入 `END`。
- 删除 `EditAssets`、`PackageManifest`、`ManifestEntry` 数据类，及 `GraphState.edit_assets`、`GraphState.manifest` 字段。
- 删除 `cover_image`、`manifest`、`final_zip` 产物和 `cover/`、`package/` 目录；基础版不再生成 ZIP。
- `subtitle_cover` 只生成双语 SRT 和烧录字幕，不再依赖发布文案。
- 最终输出改为 `compose_video` 落盘的 `final_video`；CLI 输出 `final_video` 路径。
- `architecture.md` 新增第 11 节“外部工具管理”（FFmpeg/ffprobe 查找顺序与失败行为），第 1.2 节事实源表补对应条目。

### 修改原因
- 基础版不需要中文编辑智能体、封面图和发布包 ZIP，最终成片即可交付；E 提出、F 同意。封面、标题/简介、ZIP 打包作为可选增量后续评估。
- FFmpeg 路径规范统一，避免各节点查找顺序与失败行为不一致。

## 2026-11-12 
### 版本变更
`v1.4.0` -> `v1.4.1`

### 涉及文档
- `architecture.md`

### 修改内容
- 添加 FFmpeg 跨平台已知问题说明，限制`.tools/ffmpeg/bin`的方式仅限Windows平台。

### 修改原因
- 说明已知的跨平台兼容性问题。

## 2026-11-12 docs(design): 修复设计文档collboration.md文件名拼写
### 版本变更
无

### 涉及文档
- `collaboration.md`

### 修改内容
- 修正文件名原错误拼写`collboration.md`为`collaboration.md`

### 修改原因
- 修正错误拼写

## 2026-11-13 docs(design): 统一增量节点规则并升级文档至 v1.5.0

### 版本变更
`workflow.md`: `v1.4.0` -> `v1.5.0`；`dataflow.md`: `v1.4.0` -> `v1.5.0`；`architecture.md`: `v1.4.1` -> `v1.5.0`

### 涉及文档
- `workflow.md`
- `dataflow.md`
- `architecture.md`

### 修改内容
- `workflow.md` 第 3 节节点清单新增“版本归属”列，取值基础版/增量。
- `architecture.md` 第 8 节拆分为 8.1 基础版节点、8.2 增量节点异常隔离、8.3 增量数据兼容规则；8.2 由 `graph/` 层统一代理保证。
- `dataflow.md` 5.2 第 5 条明确写磁盘失败的适用范围；5.3 新增增量产物与字段兼容规则。
- `dataflow.md` 第 3 节产物表新增“版本归属”列，取值基础版/增量。

### 修改原因
- 增量节点异常不得影响基础版主图；适用范围由节点清单统一标记，避免另立名单。
- 增量节点不得污染基础版字段与产物，基础版节点不得反向依赖增量数据。

## 2026-11-13 docs(architecture): 新增增量节点拓扑规则并明确主图结构变更由 F 执行

### 版本变更
`v1.5.0` -> `v1.6.0`

### 涉及文档
- `architecture.md`

### 修改内容
- `architecture.md` 第 8 节新增 8.4“增量节点拓扑与主图结构规则”。
- 明确 `graph/`、`contracts/` 及 `NODE_NAMES`、`WORKFLOW_EDGES` 等主图结构变更由 F 确认与执行，其他角色不可直接修改。
- 增量节点必须无条件调度、只旁路或追加、不得成为基础版唯一前驱；基础版子图须存在不经过增量节点的完整路径。
- 契约变更不得使关闭增量时基础版写盘校验失败；8.2 仅覆盖抛 `Exception`，不覆盖挂起。

### 修改原因
- 接受增量可改拓扑与数据模型后，代理只覆盖执行期异常，不覆盖调度与结构风险；需明确主图结构变更归属，防止死锁、漏执行与基础版被绕过。

## 2026-11-13 docs(design): 新增 repair_blocks 增量节点、repaired_blocks 产物与增量拓扑规则

### 版本变更
`v1.6.0` -> `v1.7.0`

### 涉及文档
- `workflow.md`
- `dataflow.md`
- `architecture.md`

### 修改内容
- `workflow.md` 第 3 节节点清单新增增量节点 `repair_blocks`；第 4 节改为 `review_blocks → repair_blocks → tts_align/subtitle_cover` 单通路；第 5 节明确增量节点始终接入、异常不改变基本版行为。
- `dataflow.md` 第 3 节产物表新增 `repaired_blocks`（`translated/repaired_blocks.json`）；第 4 节工作目录新增该文件；5.3 第 9 条覆盖增量产物与字段兼容规则。
- `architecture.md` 第 8 节拆分 8.1 基础版、8.2 增量节点异常隔离、8.3 增量数据兼容、8.4 增量节点拓扑与主图结构规则；8.4 明确增量节点始终接入、异常等价于不存在、无条件调度、禁止多前驱写同字段、主图结构变更由 F 执行。

### 修改原因
- 将 C 的审校问题清单与按片段定向返工作为增量节点接入主图；异常时由代理返回空增量，下游使用原审校结果，基础版行为不变。

## 2026-11-17 用户要求：原视频留在首次素材目录，任务只引用

### 版本变更
architecture.md / dataflow.md：v1.7.0 -> v1.9.0（衔接已有 workflow v1.8.0，新增向后兼容的输入方式）

### 修改内容与原因
- input_video 保持可选字符串、默认 None，新增显式绝对路径语义，允许从原始素材位置只读；保留旧任务文件名方式。同步 contracts 字段说明及自动生成的接口文档。
- 素材缓存与任务输出分离；YouTube 下载直接写首次素材目录，重复任务校验后引用；已有历史原片原地登记，不复制/移动。上传首次存共享素材目录，任务不再建 input.mp4 硬链接。
- CLI、真实/模拟探测及 WebUI 预览统一读取同一原片；WebUI 增加已有素材列表。graph/ 拓扑及节点名不变。
- 按用户本次明确要求取消每次工作的原片复制，输出与中间音轨仍独立保存。
