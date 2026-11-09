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

## 2026-11-09 refactor(utils): 落盘产物路径与读写管理；拆分 tts_clips；design文档版本管理

### 版本变更

`v1.0.1` -> `v1.1.0`

### 涉及文档

- `dataflow.md`
- `workflow.md`
- `architecture.md`
- `collaboration.md`
- `CHANGELOG.md`（按新格式重组历史条目）

### 修改内容

1. 重新设计产物读写和获取路径规范

- 明确产物读写和获取路径规范：只有结构化JSON数据能使用读写函数，读写函数内自动校验；二进制文件只能获取绝对路径
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

1. 重新设计产物读写和获取路径规范

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