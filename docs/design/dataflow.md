**本文档不保证同步维护，仅供参考。所有角色都可修改该文档和project/contracts**

# 项目数据流设计

版本：v1.9.0
最后更新：2026-11-17

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
| 最终产物 | 第 6 节 最终产物说明 | 唯一最终产物是成片`final_video` |
| 增量产物与字段兼容规则 | 第 5 节 数据流规则 | 增量节点不得覆盖基础版产物；新增产物名须登记；增量新增 GraphState 字段必须可选 |

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

`GraphState` 是流程顶层状态容器，保存所有逻辑对象，以及输入视频的文件名或显式绝对路径字符串。

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
| `EnvironmentAudio` | 可选环境音来源回执 |
| `MixedAudio` | 可选混音来源回执 |

说明：

- 各数据类的字段、类型、必填性与约束由 `contracts/` 下的 Pydantic 模型定义，本文档不展开。
- 术语表使用 `dict[str, str]`，不单独定义类。
- `GraphState` 是流程顶层状态容器，不是节点产物；为完整说明其程序内结构和不落盘属性，列入第 3 节产物表。GraphState 与其它数据类一样是 Pydantic `BaseModel`，字段约束由 `contracts/` 定义。

---

## 3. 产物表

| 产物 | 名称 | 版本归属 | 描述 | 程序内数据结构 | 磁盘路径 |
| --- | --- | --- | --- | --- | --- |
| `GraphState` | — | 基础版 | 流程顶层状态容器 | `GraphState` | 不落盘 |
| 输入视频 | `input_video` | 基础版 | 只读原视频文件 | 文件名或显式绝对路径字符串 | 文件名方式兼容工作目录根；绝对路径方式直接读取首次素材目录，不复制 |
| 媒体信息 | — | 基础版 | 输入视频的时长、分辨率、音视频流信息 | `MediaInfo` | 不落盘 |
| 提取音频 | `source_audio` | 基础版 | 从输入视频提取的英文音轨 | - | `audio/source.wav` |
| 分段结果 | `segments` | 基础版 | 全片时间轴分段 | `list[Segment]` | `segments/segments.json` |
| 翻译块 | `blocks` | 基础版 | 翻译与审校的单位 | `list[TranslationBlock]` | `segments/blocks.json` |
| 术语表 | — | 基础版 | 翻译与审校共享的术语映射 | `dict[str, str]` | 不落盘 |
| 翻译结果 | `translated_blocks` | 基础版 | 翻译智能体输出 | `list[TranslatedSegment]` | `translated/translated_blocks.json` |
| 审校结果 | `reviewed_blocks` | 基础版 | 审校智能体输出 | `list[TranslatedSegment]` | `translated/reviewed_blocks.json` |
| 修复结果 | `repaired_blocks` | 增量 | 定向返工后的修复结果 | `list[TranslatedSegment]` | `translated/repaired_blocks.json` |
| 分段音频清单 | `tts_clips` | 基础版 | 逐段中文口播音频的元数据清单 | `list[TTSClip]` | `tts/clips.json` |
| 分段音频文件 | `tts_audio` | 基础版 | 逐段中文口播 WAV 音频 | - | `tts/`，文件名由 `TTSClip.audio_path` 提供 |
| 中文配音音轨 | `dub_audio` | 基础版 | 组装后的整条中文配音 | - | `audio/dub.wav` |
| 原文 SRT | `english_srt` | E 本地实现，待确认 | 转写分段的英文原文 | - | `subtitles/english_segmented.srt` |
| 译文 SRT | `chinese_srt` | E 本地实现，待确认 | 审校后的中文字幕 | - | `subtitles/chinese.srt` |
| 双语 SRT | `bilingual_srt` | 基础版 | 发布用双语字幕 | - | `subtitles/bilingual.srt` |
| 烧录字幕 | `burnin_subtitle` | 基础版 | 供 FFmpeg 烧录的字幕 | - | `subtitles/burnin.ass` |
| 环境音 | `environment_bed` | 增量 | B 分离背景并保守恢复非语言声音 | - | `audio/environment.wav` |
| 环境音来源回执 | `environment_audio` | 增量 | 与当前源视频及分段摘要绑定 | `EnvironmentAudio` | `audio/environment.source.json` |
| 混合音轨 | `mixed_track` | 增量 | 环境音与中文配音混合，不覆盖纯配音 | - | `audio/mixed.wav` |
| 混音来源回执 | `mixed_audio` | 增量 | 与当前源视频、背景及中文配音摘要绑定 | `MixedAudio` | `audio/mixed.mix.json` |
| 成片 | `final_video` | 基础版 | 中文配音成片 | - | `video/final.mp4` |

补充说明：

- 各产物的读写规范请参照 `5.1` 节和 `5.2` 节。**请务必阅读这两个小节**。
- “程序内数据结构”为 `-` 的产物不进入 `GraphState`。
- “分段音频清单”`tts_clips` 是 JSON 元数据清单，“分段音频文件”`tts_audio` 是 `tts/` 下的逐段 WAV 文件；两者通过 `TTSClip.audio_path` 保存的文件名关联。
- 名称为 `—` 的产物不落盘、不登记名称、不参与产物规格表，仅在 `GraphState` 中传递。
- “版本归属”取值固定为“基础版 / 增量”。基础版产物供基础版主图使用；增量产物由增量节点新增并须在此登记，增量节点不得覆盖基础版产物名/路径。

---

## 4. 工作目录结构

```text
work_dir/
  audio/
    source.wav           # 从输入视频提取的英文音轨
    dub.wav              # 组装后的中文配音音轨
    environment.wav      # 增量环境音
    environment.source.json # 增量环境音回执
    mixed.wav            # 增量混音
    mixed.mix.json       # 增量混音回执
  segments/
    segments.json        # 分段结果，内容模型 list[Segment]
    blocks.json          # 翻译块，内容模型 list[TranslationBlock]
  translated/
    translated_blocks.json   # 翻译结果，内容模型 list[TranslatedSegment]
    reviewed_blocks.json     # 审校结果，内容模型 list[TranslatedSegment]
    repaired_blocks.json     # 修复结果，内容模型 list[TranslatedSegment]
  tts/
    clips.json           # 分段音频清单，内容模型 list[TTSClip]
    seg_0001.wav         # 逐段中文口播音频
    seg_0002.wav
    ...
  subtitles/
    english_segmented.srt # 原文字幕
    chinese.srt           # 审校后译文字幕
    bilingual.srt         # 双语字幕
    burnin.ass           # 烧录用字幕
  video/
    final.mp4            # 中文配音成片
  logs/
    run.log              # 运行日志（运行副产品，非产物）
```

说明：

- 工作目录必须预先存在；CLI 在初始化时创建子目录，节点不创建任何目录。
- 新任务原视频保留在首次素材目录，不进入任务目录；input_video 为显式绝对路径。兼容旧任务文件名方式，默认 input.mp4。所有处理结果仍只写任务子目录。
- 媒体信息、术语表不落盘，因此不出现在目录树中。
- `GraphState` 不落盘，不在此目录树中。
- `logs/run.log` 是运行日志，由 CLI 初始化、贯穿整次运行；它不是流程产物，不进入第 3 节产物表，不被节点消费，路径由 CLI 直接构造。

---

## 5. 数据流规则

### 5.1 路径与校验规则

utils 提供三类函数：

- **获取绝对路径的函数**，位于 `utils/paths.py`：输入名称和可选文件名，返回绝对路径；
- **读取结构化数据的函数**，位于 `utils/io.py`：按名称读取 JSON 并按产物规格表登记的校验类型做 Pydantic 校验；
- **写入结构化数据的函数**，位于 `utils/io.py`：按名称写入 JSON 并按产物规格表登记的校验类型做 Pydantic 校验。

三类函数的签名、职责与使用约束见 `architecture.md` 第 6 节。本节和 5.2 中统称后两类函数为 utils 的读写函数。

落盘产物管理规则如下：
1. 每个落盘的产物在第 3 节产物表中登记一个名称；名称是英文标识符，全项目唯一。
2. 名称与磁盘格式一一对应：每个名称的磁盘格式（单个 JSON / 二进制）在产物表中唯一确定，不随调用场景变化。若同一逻辑概念需要多种落盘形态，必须登记为多个不同名称。
3. 对于路径不确定的产物，其路径由 产物表规定的基本路径 与 文件名 共同确定。文件名保存在承载它的数据类中。输入视频直接在 `GraphState` 中保存文件名或显式绝对路径；字段仍可选默认 None。
4. `utils/artifacts.py`代码实现产物规格表，完成名称到路径和校验类型的映射，实现约定参考`architecture.md` 6.4 节。本文档第 3 节的产物表为该映射的唯一事实源，出现不一致时应以本文档第 3 节为准，并尽快修改代码。
5. 修改路径或校验类型时，先改本文档产物表，再改 `utils/artifacts.py`，两者放在同一个变更中。

落盘产物的读写和获取路径的规则如下：
1. 所有读写、获取路径操作必须按照 `architecture.md` 6.1 节、6.2节和 6.5 节的规范调用utils的函数完成。**不可自行拼接路径、自行进行读写操作**
2. 对于路径确定的产物，读写和获取路径时需提供名称；对于路径不确定的产物，获取路径时需提供名称和文件名

### 5.2 结构化落盘数据读写规则

1. 需要落盘的结构化对象及对应名称见第 3 节产物表。判定条件为：程序内数据结构不是路径字符串，且落盘为单个 JSON 文件的结构化产物。
2. 对上述对象，节点从 `GraphState` 直接读取结构化对象，**不从磁盘重新读取上游**。
3. 节点处理完成后，将需要落盘的结构化对象**写入磁盘**，然后**返回 `GraphState` 增量**。
4. 写磁盘操作应当遵循5.1节的路径使用规则。
5. 写磁盘失败时 `write_artifact` 直接抛出异常，不存在“State 已更新但磁盘未写”的中间状态。基础版节点不捕获该异常，图终止，State 不合并该节点的增量；增量节点的异常处理按 `architecture.md` 8.2 由 `graph/` 层统一代理捕获，返回空增量，图继续执行。
6. 磁盘 JSON 是持久化副本和调试依据，不是节点间传递数据的通道；节点间传递以 `GraphState` 中的对象为准。
7. 媒体信息、术语表不落盘，只在 GraphState 中传递
8. 二进制媒体产物（音频、视频、字幕）的内容不进入 `GraphState`。
9. `GraphState` 在基本版不落盘。若后续版本需要落盘（如检查点），按照5.1节的规则进行更改与管理。

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

8. **顶层状态模型**
   `GraphState` 是 Pydantic 模型；其字段的必填性、类型与嵌套模型由 `contracts/` 定义。落盘或跨进程传递时，必须以 `GraphState` 模型实例的形式恢复，禁止直接使用反序列化得到的裸 dict。

9. **增量产物与字段兼容规则**
   - 增量节点不得覆盖基础版产物名/路径；新增产物名必须按第 3 节产物表登记。
   - 增量节点新增的 `GraphState` 字段必须可选、默认 `None`；字段必填性、类型与语义以 `contracts/` 为准。
   - 基础版节点不得把增量字段或增量产物作为必需输入；读取时必须处理缺失，缺失时行为与无增量一致。

### 5.4 路径处理与输入文件约定

1. **绝对路径**  
   utils 的路径操作与读写函数内部解析出的路径统一为绝对路径，不依赖当前工作目录。

2. **子目录创建**  
   CLI 在初始化时，必须保证工作目录存在，然后在工作目录下创建子目录。节点不创建任何目录。

3. **输入视频**  
   输入视频可为显式绝对路径，直接读取首次下载/上传目录的原文件；不得为每次任务复制原片。旧文件名方式兼容工作目录根，默认 input.mp4。节点仍通过名称 input_video 与该引用调用 utils 获取路径。相对引用不接受目录穿越或带子目录的路径。

---

## 6. 最终产物说明

- 唯一对外交付的最终产物是 `final_video`，由 `compose_video` 落盘到 `video/final.mp4`。

- `compose_video` 完成后主流程进入 END。

- 原文、译文及双语 SRT、烧录字幕、中文配音音轨、分段音频、分段与翻译审校 JSON 等均为中间产物或调试副本，不构成对外交付的最终产物。

- CLI 输出运行状态与 `final_video` 的路径。

## 2026-11-17 增量环境音接入说明

`GraphState.environment_audio` 与 `mixed_audio` 均为可选、默认 None，不改变基础字段。B 仅返回环境音回执，E 混音节点仅返回混音回执，避免并行写同一字段。固定媒体路径不放入 State，按产物名称获取。JSON 通过公共 write_artifact 校验写盘后返回增量；下游读取 State 中的模型，不把回执 JSON 当节点间通道。分离临时 stems、AST 特征与底层工具诊断仅为节点私有临时文件，成功/失败后清理，不作为跨组产物。

`mix_background` 没有 environment_audio 时返回 {}；compose_video 没有有效 mixed_audio 时使用 dub_audio，不根据磁盘是否存在旧 mixed.wav 猜测成功。摘要失配、媒体缺失时警告并回退，不要求基础链具备增量产物。

EnvironmentAudio 的恢复区间 restored_intervals_ms 使用毫秒整数；工具内部秒值只在发布时转换。duration_sec 为带单位的媒体时长统计，不作为分段时间戳。

### 2026-11-17 素材共享目录

新 YouTube 原片直接下载到 media/downloads/<视频ID>/video.mp4；来源登记为同目录 source.json。历史已下载原片只原地登记其现有绝对路径，不移动或复制。相同链接校验来源摘要后复用。上传文件首次保存到 media/downloads/uploads/<内容摘要>.mp4；重复任务选择已有素材直接使用它，不在任务目录创建副本或硬链接。

web-run.json、source.json 是入口管理/来源配置，不是新增业务节点产物；不作为 C/D/E 之间的数据通道。入图仅传 GraphState.input_video。原视频只读；audio/source.wav 是必要的派生音轨，其他转写、译文、配音、字幕和成片仍留在每次任务目录。源文件移走或摘要不匹配时明确报错，不偷偷复制或重下。
