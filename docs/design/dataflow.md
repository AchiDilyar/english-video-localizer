# 项目数据流设计

版本：v1.0  
最后更新：2026-11-08

---

## 1. 文档定位与事实源范围

### 1.1 本文档负责什么

本文档描述基本版项目数据流，包括：

- 数据类与产物总览；
- 产物表：产物名、描述、程序内数据结构、磁盘路径；
- 工作目录结构；
- 数据流规则；
- 最终产物说明。

### 1.2 本文档是以下内容的唯一事实源

> 唯一事实源指：以下概念**只在该文档定义**，其它文档可以引用这些概念，但**不可重新定义**。如果出现名称不一致，以该文档的名称为准，引用该概念的文档应尽快同步修改。

| 事实 | 对应章节 | 说明 |
|---|---|---|
| 数据类名称 | 第 2 节 数据类与产物总览 | 所有逻辑对象对应的 Pydantic 类名 |
| 产物名 | 第 3 节 产物表 | 所有文档、代码中出现的产物名以此为准 |
| 产物的程序内数据结构与磁盘路径 | 第 3 节 产物表 | 产物在流程中的数据结构、是否落盘及落盘路径 |
| 工作目录结构 | 第 4 节 工作目录结构 | 任务工作目录下各子目录和文件命名 |
| 数据流规则 | 第 5 节 数据流规则 | ID 规则、时间轴规则、不可修改字段、路径使用规则等 |
| 最终产物 | 第 6 节 最终产物说明 | 唯一最终产物是最终 ZIP |

### 1.3 文档引用约定

- 本文档引用的节点名与节点读写关系以 `workflow.md` 为准；
- 本文档引用的字段名、类型、必填性以 `contracts/` 与自动生成的 `interfaces.md` 为准；
- 本文档引用的代码文件名与函数名以 `architecture.md` 为准。

---

## 2. 数据类与产物总览

### 2.1 两类产物

产物分为以下两类：

- **逻辑对象**：在流程中传递的结构化数据，对应 `contracts/` 下的 Pydantic 模型；
- **磁盘文件**：落盘保存的媒体、字幕、图片、清单或压缩包，流程中通过名称和文件名访问。

`GraphState` 是流程顶层状态容器，保存所有逻辑对象，以及输入视频和最终 ZIP 的文件名字符串。

二进制媒体内容不进入 `GraphState`。落盘产物如果路径唯一确定，其路径不放入 `GraphState` 保存，使用时由 utils 按名称生成路径。需要落盘的结构化对象既进入 `GraphState`，也同步写为 JSON 文件；是否落盘见第 3 节产物表。

### 2.2 数据类清单

| 数据类 | 用途 |
|---|---|
| `GraphState` | 流程顶层状态容器 |
| `MediaInfo` | 输入视频的媒体信息 |
| `Segment` | 全片时间轴分段 |
| `TranslationBlock` | 翻译与审校的单位 |
| `TranslatedSegment` | 翻译结果与审校结果的元素 |
| `TTSClip` | 逐段 TTS 音频记录 |
| `EditAssets` | 标题、简介和封面文案 |
| `PackageManifest` | 发布包内文件清单 |

说明：

- 各数据类的字段、类型、必填性与约束由 `contracts/` 下的 Pydantic 模型定义，本文档不展开。
- 术语表使用 `dict[str, str]`，不单独定义类。
- `GraphState` 是流程顶层状态容器，不是节点产物；为完整说明其程序内结构和不落盘属性，列入第 3 节产物表。

---

## 3. 产物表

| 产物 | 名称 | 描述 | 程序内数据结构 | 磁盘路径 |
| --- | --- | --- | --- | --- |
| `GraphState` | — | 流程顶层状态容器 | `GraphState` | 不落盘 |
| 输入视频 | `input_video` | 输入视频文件 | 文件名字符串 | 工作目录根目录下，文件名由 CLI 提供，默认 `input.mp4` |
| 媒体信息 | — | 输入视频的时长、分辨率、音视频流信息 | `MediaInfo` | 不落盘 |
| 提取音频 | `source_audio` | 从输入视频提取的英文音轨 | - | `audio/source.wav` |
| 分段结果 | `segments` | 全片时间轴分段 | `list[Segment]` | `segments/segments.json` |
| 翻译块 | `blocks` | 翻译与审校的单位 | `list[TranslationBlock]` | `segments/blocks.json` |
| 术语表 | — | 翻译与审校共享的术语映射 | `dict[str, str]` | 不落盘 |
| 翻译结果 | `translated_blocks` | 翻译智能体输出 | `list[TranslatedSegment]` | `translated/translated_blocks.json` |
| 审校结果 | `reviewed_blocks` | 审校智能体输出 | `list[TranslatedSegment]` | `translated/reviewed_blocks.json` |
| 分段音频 | `tts_clips` | 逐段中文口播音频 | `list[TTSClip]` | 路径由 `TTSClip.audio_path` 确定，位于 `tts/` 下 |
| 中文配音音轨 | `dub_audio` | 组装后的整条中文配音 | - | `audio/dub.wav` |
| 发布文案 | — | 标题、简介、封面文案 | `EditAssets` | 不落盘 |
| 双语 SRT | `bilingual_srt` | 发布用双语字幕 | - | `subtitles/bilingual.srt` |
| 烧录字幕 | `burnin_subtitle` | 供 FFmpeg 烧录的字幕 | - | `subtitles/burnin.ass` |
| 封面图 | `cover_image` | 中文封面 | - | `cover/cover.jpg` |
| 成片 | `final_video` | 中文配音成片 | - | `video/final.mp4` |
| 发布包清单 | `manifest` | 发布包内文件清单 | `PackageManifest` | `package/manifest.json` |
| 最终 ZIP | `final_zip` | 对外交付的发布包 | - | `package/final.zip` |

补充说明：

- 各产物的读写规范请参照 `5.1` 节和 `5.2` 节。**请务必阅读这两个小节**。
- “程序内数据结构”为 `-` 的产物不进入 `GraphState`。
- “分段音频”是路径不确定的一组文件，由 `list[TTSClip]` 承载，`TTSClip` 数据类中包含文件路径和其它所需数据。
- 输入视频的文件名字符串保存在 `GraphState` 中；完整路径不进入 `GraphState`，由 utils 按名称和文件名生成。

---

## 4. 工作目录结构

```text
work_dir/
  audio/
    source.wav           # 从输入视频提取的英文音轨
    dub.wav              # 组装后的中文配音音轨
  segments/
    segments.json        # 分段结果，内容模型 list[Segment]
    blocks.json          # 翻译块，内容模型 list[TranslationBlock]
  translated/
    translated_blocks.json   # 翻译结果，内容模型 list[TranslatedSegment]
    reviewed_blocks.json     # 审校结果，内容模型 list[TranslatedSegment]
  tts/
    seg_0001.wav         # 逐段中文口播音频
    seg_0002.wav
    ...
  subtitles/
    bilingual.srt        # 发布用双语字幕
    burnin.ass           # 烧录用字幕
  cover/
    cover.jpg            # 封面图
  video/
    final.mp4            # 中文配音成片
  package/
    manifest.json        # 发布包清单，内容模型 PackageManifest
    final.zip          # 最终 ZIP
```

说明：

- 工作目录必须预先存在；CLI 在初始化时创建子目录，节点不创建任何目录。
- 输入视频位于工作目录根目录下，不在上述目录树中（目录树只列出子目录）。文件名由 CLI 提供，默认 `input.mp4`。
- 媒体信息、术语表、发布文案不落盘，因此不出现在目录树中。
- `GraphState` 不落盘，不在此目录树中。
- 所有任务内路径由 `utils/paths.py` 的路径函数统一生成，节点不自行拼接路径；`utils/paths.py` 的接口约定见 `architecture.md`。

---

## 5. 数据流规则

### 5.1 路径使用规则

utils 提供三类函数：

- **获取绝对路径的函数**，位于 `utils/paths.py`：输入名称和可选文件名，返回绝对路径；
- **读取结构化数据的函数**：按名称读取 JSON 并按 Pydantic 模型校验；
- **写入结构化数据的函数**：按名称写入 JSON 并做 Pydantic 校验。

后两类函数的具体位置由 `architecture.md` 约定；本节和 5.2 中统称它们为 utils 的读写函数。

路径使用规则如下：

1. 每个落盘的产物在第 3 节产物表中登记一个名称；名称是英文标识符，全项目唯一。
2. `utils/paths.py` 维护名称映射表，映射表内容与第 3 节产物表一致。路径确定的产物映射为完整相对路径；路径不确定的产物映射为所在文件夹，文件名由调用方提供。
3. 所有路径确定的产物不在 `GraphState` 中保存路径字段。路径不确定产物的路径信息由承载它的数据类保存，不额外在 `GraphState` 中设路径字段。输入视频是例外：`GraphState` 中保存其**文件名字符串**，不保存完整路径。
4. 节点**不得直接使用路径字符串**，**只能通过名称**调用 utils 的函数获取路径。对于输入视频，节点从 `GraphState` 读到的是文件名，仍需通过名称和该文件名调用 utils 获取绝对路径。
5. 对于路径不确定的产物，同样需要调用 utils 的函数，并提供名称和文件名，函数会根据名称找到对应的文件夹。**不可直接使用路径字符串**。
6. 调用外部工具需要文件路径时，统一调用 utils 的获取绝对路径函数，**不可自行生成路径字符串**。
7. 名称和相对路径的事实源是本文档第 3 节产物表，代码实现是 `utils/paths.py`；两者不一致时以本文档为准，并应尽快修正代码。
8. 修改路径时，先改本文档产物表，再改 `utils/paths.py`，两者放在同一个变更中。

### 5.2 结构化落盘数据读写规则

1. 需要落盘的结构化对象及对应名称见第 3 节产物表。判定条件为：程序内数据结构不是路径字符串，且落盘为 JSON 文件的结构化产物。分段音频虽然程序内数据结构为 `list[TTSClip]`，但落盘为 WAV 音频文件，不属于本节所指的结构化落盘数据。
2. 对上述对象，节点从 `GraphState` 直接读取结构化对象，**不从磁盘重新读取上游**。
3. 节点处理完成后，将需要落盘的结构化对象**写入磁盘**，然后**返回 `GraphState` 增量**。
4. 写磁盘通过 utils 的写函数完成，由写函数统一完成路径解析和 Pydantic 校验；节点不自行拼接路径、不自行调用 JSON 序列化。
5. 写磁盘失败时直接抛出异常，图终止，State 不合并该节点的增量；不存在“State 已更新但磁盘未写”的中间状态。
6. 磁盘 JSON 是持久化副本和调试依据，不是节点间传递数据的通道；节点间传递以 `GraphState` 中的对象为准。
7. 媒体信息、术语表、发布文案不落盘，只在 `GraphState` 中传递。
8. 二进制媒体产物（音频、视频、图片、字幕、ZIP）的内容不进入 `GraphState`；路径信息按 5.1 节处理。节点通过 utils 的读写函数获取路径或写入文件，不直接拼接路径字符串。

### 5.3 数据契约规则

1. **逻辑对象与磁盘文件的区分**  
   逻辑对象在流程中传递，磁盘文件落盘保存。二进制媒体内容不进入 `GraphState`。

2. **ID 规则**  
   `segment_id`、`block_id`、`speaker_id` 由对应生产节点生成，全片唯一；具体格式与约束由 `contracts/` 中的 Pydantic 模型定义。

3. **时间轴规则**  
   时间戳一律使用毫秒整数；起始时间小于结束时间；相邻分段允许存在间隙，不强制首尾相接。

4. **不可修改字段**  
   C 不得修改 B 写入的 `segment_id`、`speaker_id`、起始毫秒和结束毫秒；所有智能体沿用已有 ID 和时间戳。

5. **说话人一致性**  
   同一说话人在全片使用同一 `speaker_id`；D 的音色映射依赖该 ID。

6. **JSON 产物校验**  
   落盘的 JSON 产物必须通过对应 Pydantic 模型校验；校验失败时按节点失败处理，约定见 `architecture.md`。

7. **分段与分块算法的归属**  
   分段与分块的算法由 B 和 C 各自决定；本文档只约束其输出数据必须满足上述 ID、时间轴和不可修改字段规则。

### 5.4 路径处理与输入文件约定

1. **绝对路径**  
   `utils/paths.py` 中，对读写或者获取路径操作统一采用绝对路径，不依赖当前工作目录。

2. **子目录创建**  
   CLI 在初始化时，必须保证工作目录存在，然后在工作目录下创建子目录。节点不创建任何目录。

3. **输入视频**  
   输入视频必须位于工作目录的根目录下，文件名由 CLI 提供，默认 `input.mp4`。文件名保存在 `GraphState` 中；节点通过名称 `input_video` 和该文件名调用 utils 获取绝对路径。

---

## 6. 最终产物说明

- 最终 ZIP 是唯一对外交付的最终产物。
- 成片、双语 SRT、封面图、发布文案等均为发布包内文件或中间产物，不是独立对外交付的最终产物。
- `package_zip` 完成后，CLI 输出运行状态与最终产物路径；CLI 出口的具体约定见 `architecture.md`。
- `package_zip` 完成后主流程不再做业务后处理。