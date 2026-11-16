# mocks 模块说明

`project/mocks/` 是各节点的模拟实现。每个节点在 `config/mock.toml` 中独立开关，
切换只发生在 `graph/registry.py`（architecture.md 第 4 节）。

## 核心预期：保证结构性正确，不保证结果正确

mocks 的职责是**让整条链路能跑通**，不是产出可用结果。

**结构正确**——必须满足：

- 产物能通过 `read_artifact` / `write_artifact` 的 Pydantic 校验；
- 字段齐全、`GraphState` 键已定义、路径符合产物规格表；
- 下游真实节点能消费（不因缺字段、越界、类型不符而崩）。

**结果可以假**——明确接受：

- 静音音频、1 秒黑屏成片、占位字幕、静态译文；
- 长度、内容、语义都可能与真实结果不同。

因此：切到 mock 就等同于**接受不正确的结果**。凡是「结果可能不对」的情况，
mock 都会留下固定前缀的 warning（见下表），排查靠 `grep` 日志。
只有「数据自身非法」（JSON 坏、ID 重复、`Segment` 校验失败）才直接抛出。

## 文件一览

| 文件 | 说明 |
|---|---|
| `probe_input.py` | 快照优先；指纹失配时回源 ffprobe |
| `asr_diarize.py` | 静态真实转写 + 指纹与时长校验 |
| `build_blocks.py` | 全部 segments 放进单块 + 长度阈值告警 |
| `translate_blocks.py` | 静态真实译文 + 反查表填 `block_id` + 指纹分支 |
| `review_blocks.py` | 原样透传 `translated_blocks` |
| `repair_blocks.py` | 增量节点，空实现（返回 `{}`） |
| `tts_align.py` | 长度对齐静音，24 kHz |
| `subtitle_cover.py` | 占位双语 SRT + 烧录 ASS |
| `compose_video.py` | 1 秒黑屏 MP4 |
| `_video.py` | **内部辅助**（下划线前缀）：输入路径 + 前 64KB SHA-256，不是节点 mock |
| `data/*.json` | 静态数据，见下 |

## 静态数据

| 文件 | 内容 | 使用者 |
|---|---|---|
| `data/probe_input.json` | 演示视频的完整 ffprobe 输出 + 指纹 | `probe_input` |
| `data/asr_diarize.json` | 11 条真实转写 + 视频指纹 | `asr_diarize` |
| `data/translate_blocks.json` | 11 条中文译文 + 视频指纹 | `translate_blocks` |

三份数据的 `source.head_sha256` / `size_bytes` 必须指向同一个视频，
`tests/mocks` 有对应用例保证。

## 换视频怎么办

1. 重新生成 `data/probe_input.json`（结构见现有文件，含完整 `ffprobe_raw`）；
2. 用新的 `source` 与 `segments` 更新 `data/asr_diarize.json`；
3. 用新的 `source` 与译文更新 `data/translate_blocks.json`。

未更新时的降级行为：

- `probe_input` 回源 ffprobe，结果仍正确；
- `asr_diarize` 记 `[指纹不符]` 后继续（`segments` 可能与真实视频不符）；
- `translate_blocks` 记 `[指纹不符]` 后**全部改用** `[模拟译文] <原文>`。

## 告警标记

| 标记 | 出处 | 含义 |
|---|---|---|
| `probe_input mock: 快照不可用` | probe_input | 快照缺失 / 指纹不符 / 内部矛盾，已回源 ffprobe |
| `[指纹不符]` | asr_diarize、translate_blocks | 静态数据与输入视频不是同一个 |
| `[校验跳过]` | asr_diarize | 缺 `media_info`，跳过时长校验（info 级） |
| `[丢弃]` / `[丢弃汇总]` | asr_diarize | 分段 `end_ms` 超出视频时长，整条丢弃 |
| `[空结果]` | asr_diarize | 全部分段被丢弃，返回空 `segments` |
| `[单块过大]` | build_blocks | 单块分段数 > 50，或时间跨度 > 90s |
| `[重复归属]` | translate_blocks | 一个分段属于多个块，取第一个 |
| `[未覆盖]` | translate_blocks | 分段不属于任何块，已省略 |
| `[译文缺失]` | translate_blocks | 该 `segment_id` 没有静态译文，改用占位文本 |
| `[覆盖不符]` | review_blocks | 译文与分段的 ID 集合不一致 |
| `[segments 为空]` / `[blocks 为空]` / `[translated_blocks 为空]` / `[reviewed_blocks 为空]` | 各节点 | 空数组输入，输出空结果 |

另有文本标记 `[模拟译文]`：`translate_blocks` 写进 `zh_subtitle` 的占位前缀，不是日志。

## 边界

- mock 不 import `nodes/`；`nodes/` 也不 import `mocks/`；
- 产物覆盖写入。真实节点在部分产物已存在时会抛 `FileExistsError`，mock 有意放宽；
- mock 的字段、路径、校验类型与真实节点一致，**内容不同**；
- 所有增量节点保持空实现，所有增量节点新增的产物不会产生。
