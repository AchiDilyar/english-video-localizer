# 接口定义

> 本文件由 `project/contracts/generate_interfaces.py` 从 Pydantic 模型自动生成，请勿手工修改。
> 字段名、类型、必填性以本文件与 `project/contracts/` 为准。

## MediaInfo

输入视频的媒体信息，不落盘，仅在 GraphState 中传递。

| 字段 | 类型 | 必填 | 约束/说明 |
|---|---|---|---|
| `duration_ms` | `int` | 是 | 视频时长，毫秒整数；minimum=0 |
| `video_info` | `VideoStreamInfo` | 是 | — |
| `audio_info` | `AudioStreamInfo` | 是 | — |
| `ffprobe_raw` | `dict[str, Any]` | 是 | ffprobe 原始输出，供排查使用 |

## VideoStreamInfo

视频流信息。

| 字段 | 类型 | 必填 | 约束/说明 |
|---|---|---|---|
| `codec` | `str` | 是 | 视频编码，如 h264 |
| `width` | `int` | 是 | 宽度，像素；exclusiveMinimum=0 |
| `height` | `int` | 是 | 高度，像素；exclusiveMinimum=0 |
| `fps` | `UnionType[float, None]` | 否 | 帧率；ffprobe 无法解析时为 None |

## AudioStreamInfo

音频流信息。

| 字段 | 类型 | 必填 | 约束/说明 |
|---|---|---|---|
| `codec` | `str` | 是 | 音频编码，如 aac |
| `sample_rate` | `int` | 是 | 采样率，Hz；exclusiveMinimum=0 |
| `channels` | `int` | 是 | 声道数；exclusiveMinimum=0 |

## Segment

全片时间轴分段，由 asr_diarize 生成，落盘为 segments/segments.json。

| 字段 | 类型 | 必填 | 约束/说明 |
|---|---|---|---|
| `segment_id` | `str` | 是 | 全片唯一分段 ID，格式 seg_ 加至少 4 位数字，如 seg_0001；pattern=^seg_\d{4,}$ |
| `speaker_id` | `str` | 是 | 全片唯一说话人 ID，格式 spk_ 加字母数字下划线，如 spk_1；pattern=^spk_[A-Za-z0-9_]+$ |
| `start_ms` | `int` | 是 | 起始时间，毫秒整数；minimum=0 |
| `end_ms` | `int` | 是 | 结束时间，毫秒整数，必须大于 start_ms；exclusiveMinimum=0 |
| `text_en` | `str` | 是 | 英文转写文本 |

运行时校验（JSON Schema 不表达）：`end_ms > start_ms`。

## TranslationBlock

翻译块，由 build_blocks 生成，落盘为 segments/blocks.json。

| 字段 | 类型 | 必填 | 约束/说明 |
|---|---|---|---|
| `block_id` | `str` | 是 | 全片唯一翻译块 ID，格式 blk_ 加至少 4 位数字，如 blk_0001；pattern=^blk_\d{4,}$ |
| `segment_ids` | `list[str]` | 是 | 该翻译块包含的分段 ID，按时间顺序排列；minLength=1 |

## TranslatedSegment

翻译结果与审校结果的元素，两者同构。

    翻译结果落盘为 translated/translated_blocks.json，
    审校结果落盘为 translated/reviewed_blocks.json。
    不保留 en 原文与冗余时间戳，原文与时间戳通过 segment_id 回溯 segments。

| 字段 | 类型 | 必填 | 约束/说明 |
|---|---|---|---|
| `segment_id` | `str` | 是 | 对应分段 ID，沿用 Segment.segment_id；pattern=^seg_\d{4,}$ |
| `block_id` | `str` | 是 | 所属翻译块 ID，沿用 TranslationBlock.block_id；pattern=^blk_\d{4,}$ |
| `zh_subtitle` | `str` | 是 | 中文字幕文本 |
| `zh_dub` | `str` | 是 | 中文口播稿 |

## TTSClip

逐段中文口播音频记录，由 tts_align 生成。

    音频文件落盘于 tts/ 下，完整路径通过
    artifact_path("tts_clips", filename) 获取；audio_path 只保存文件名。

| 字段 | 类型 | 必填 | 约束/说明 |
|---|---|---|---|
| `segment_id` | `str` | 是 | 对应分段 ID，沿用 Segment.segment_id；pattern=^seg_\d{4,}$ |
| `audio_path` | `str` | 是 | 音频文件名，如 seg_0001.wav；完整路径由 artifact_path 生成；pattern=^[\w.-]+\.wav$ |
| `duration_ms` | `int` | 是 | 实测音频时长，毫秒整数；minimum=0 |
| `text` | `str` | 是 | 合成所用中文口播稿文本 |
| `voice_id` | `str` | 是 | 合成所用音色标识 |
| `model` | `str` | 是 | 合成所用模型标识 |

## EditAssets

发布文案，由 edit_assets 生成，不落盘，仅在 GraphState 中传递。

    package_zip 从 GraphState 读取，序列化为 ZIP 内 edit_assets.json，
    并在 PackageManifest 中作为普通 ManifestEntry 列出。

| 字段 | 类型 | 必填 | 约束/说明 |
|---|---|---|---|
| `title` | `str` | 是 | 标题 |
| `description` | `str` | 是 | 简介 |
| `cover_text` | `str` | 是 | 封面文案 |

## ManifestEntry

发布包清单条目。

| 字段 | 类型 | 必填 | 约束/说明 |
|---|---|---|---|
| `name` | `str` | 是 | 产物名 |
| `zip_path` | `str` | 是 | ZIP 内相对路径，如 video/final.mp4 |
| `description` | `UnionType[str, None]` | 否 | 可选说明 |

## PackageManifest

发布包清单，由 collect_manifest 生成，落盘为 package/manifest.json。

    entries 必须包含 manifest.json 自身，即存在一条
    name="manifest", zip_path="manifest.json" 的条目。

| 字段 | 类型 | 必填 | 约束/说明 |
|---|---|---|---|
| `entries` | `list[ManifestEntry]` | 是 | 发布包内文件清单；minLength=1 |

## GraphState

流程顶层状态容器，`TypedDict`，`total=False`。

| 字段 | 类型 | 必填 | 约束/说明 |
|---|---|---|---|
| `input_video` | `str` | 否 | — |
| `media_info` | `MediaInfo` | 否 | — |
| `segments` | `list[Segment]` | 否 | — |
| `blocks` | `list[TranslationBlock]` | 否 | — |
| `terminology` | `dict[str, str]` | 否 | — |
| `translated_blocks` | `list[TranslatedSegment]` | 否 | — |
| `reviewed_blocks` | `list[TranslatedSegment]` | 否 | — |
| `tts_clips` | `list[TTSClip]` | 否 | — |
| `edit_assets` | `EditAssets` | 否 | — |
| `manifest` | `PackageManifest` | 否 | — |

说明：`GraphState` 为 `TypedDict`，JSON Schema 不强制禁止额外键；节点返回增量的键必须在 `GraphState` 中已定义，该约束由 `graph/` 合并逻辑与测试保证。
