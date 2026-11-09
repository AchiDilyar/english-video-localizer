# B 模块 V2：完整视频逐句台词表

> 历史阶段记录：代码与文档已按 v1.2.0 迁移。旧路径、命令和“尚未实现”等状态仅对应记录当时，不作为当前入口；当前使用与限制见 [节点说明](README.md) 和 [迁移记录](B-layout-v1.2.0.md)。历史任务未修改。
2026-11-09 交接说明：本文描述 B 当前独立接口；团队共享接口以 F 的 `project/contracts/` 和 v1.1.0 设计为准，适配尚未完成。最新状态见 [B 交接入口](README.md)，差异见 [接口核对](B-F-interface-review-20261109.md)。

本版落实最新需求：输入完整本地视频或 YouTube 单视频网址，应用层不切音频块；最长输入 7200 秒；按完整句子整理英文及最终起止时间。取消旧版“原始片段 + 句子分组”双层输出。不提供视频片段编辑功能。

**后续更新：长句可拆成语义完整的字幕单元，已加入可选 DeepSeek 审查接口。** 当前说明中的“句子”不应理解为只能按句号拆分。配置、独立回调、调用预算、56 项检查和一次真实小样的局限见 [语义审查说明](B-semantic-review.md)。旧完整视频的结构通过不代表语义分段已通过。

另已实现 [可选真实说话人区分](B-real-diarization.md)，使用 --diarize 开启；以下旧版 speaker_id 为 null 的说明只适用于未启用时。默认图还已加入 [残句音频复识别](B-audio-recheck-20261107.md)，完整 ASR 之后可能产生额外局部复查调用，不应再把整个流程描述为 ASR 总调用仅一次。

## LangGraph 实际流程

`resolve_input → download_video → prepare_full_audio → asr_and_sentence_formation → recheck_incomplete_audio → diarize_speakers → review_sentences → export_sentences`

每个节点都有运行事件和 SQLite 检查点。识别节点对全片 WAV 只调用一次 faster-whisper `transcribe`。Whisper 自身的解码窗口仍由模型内部管理，不等于本项目把音频拆成多个任务。模型为本地 `base.en`，CPU int8，faster-whisper 1.2.1；不是云端语音 API。

全片暂存在内存中的词对齐用于确定句子首尾；spaCy 英文句法模型整理句子，从句和延续表达规则修正不合理断句，再由独立审查节点检查句子和时间结构。停顿长短不是分句规则。审查不添加或删掉识别出的词；疑似残句会标记人工核对。自动语法审查不能保证口语、专名、识别内容和所有句子边界都正确。

**新任务不把原始 ASR 分段、词时间或旧边界写入文件、日志、缓存或检查点。** 检查点只保存已经整理的句子表和素材元数据。历史任务保留供复现，没有删除。视频文件自身的媒体时间信息仍属于原视频。

## 使用命令

在项目目录用 PowerShell 运行：

```powershell
# 本地视频，支持完整两小时以内文件
& .venv/Scripts/python.exe -m b_pipeline run --input 'C:/path/lecture.mp4' --job-dir jobs/my-local-video

# YouTube 完整单视频，明确启用联网
& .venv/Scripts/python.exe -m b_pipeline run --input 'https://www.youtube.com/watch?v=nykOeWgQcHM' --job-dir jobs/my-youtube-video --allow-network

# 仅下载，不识别
& .venv/Scripts/python.exe -m b_pipeline download --input 'https://www.youtube.com/watch?v=nykOeWgQcHM' --output-dir media/my-video --allow-network

# 从已完成节点续跑
& .venv/Scripts/python.exe -m b_pipeline resume --job-dir jobs/my-local-video
```

每次新运行使用新的 job 目录。默认最长 7200 秒、素材上限 2 GiB；可用 `--max-source-mib` 调整（最高 8192 MiB）。下载默认超时 600 秒，可用 `--download-timeout-sec` 调整，最高 1800 秒。超过限制会报错，不会偷偷截短。依赖版本见 `requirements-sentence-v2.lock.txt`，FFmpeg 与模型使用项目现有本地配置。

YouTube 入口接受 watch、youtu.be、shorts、live 单视频链接，去除播放列表参数；优先选择明确标注的英文原音，避免自动译配音轨。不处理登录、付费或 DRM 限制；公开网址并不自动赋予素材再发布许可。下载保留标题、来源、音轨选择及哈希，不保存带签名的媒体直链。

## 给 F / 后续模块的 Python 接口

```python
from b_pipeline import run_b, resume_b, load_timetable

result = run_b(
    input_ref="C:/path/lecture.mp4",  # 或 YouTube 单视频网址
    job_dir="jobs/my-local-video",
    allow_network=False,             # YouTube 时 True
    max_duration_sec=7200,
)
table = load_timetable("jobs/my-local-video/timetable.json")
for sentence in table["sentences"]:
    print(sentence["sentence_id"], sentence["start_ms"],
          sentence["end_ms"], sentence["en"])
```

这是供 F 主图调用的 B 子图；不是团队翻译、审校、字幕三个智能体的完整主图。`build_b_graph` 导出该实际 LangGraph 子图；一般集成优先调用 `run_b`。旧 registry/chunk 参数不再用于新入口。历史格式读取和旧实现留在项目中用于复现，不应作为新接口。

新 JSON schema 为 `b-sentences-2`，根字段包括 `duration_ms`、`source`、`sentences`、`review`、`verification` 和 `execution`。每句包含：

| 字段 | 含义 |
|---|---|
| sentence_id | 本任务中稳定的句子编号 |
| start_ms / end_ms | 相对完整视频开头的最终句子起止，单位毫秒 |
| en | 该句英文 |
| speaker_id | 未开启 --diarize 时为 null；开启后为本片匿名聚类编号，未知/混合时仍为 null，不代表已验证身份 |
| review_status / review_issues | 自动检查结果与待人工复核理由 |

C 翻译时保留 sentence_id；D/E 使用最终句子边界。不要再读取原始 segments/words 或 sentence_groups，它们在本版不存在。`load_timetable` 会拒绝结构错误或时间重叠的表。输出 ready_for_human_review 只表示结构检查通过，不代表人工确认。

若模型把短语对齐成零时长，不编造时间：原文保留在 `review.untimed_utterances` 和 `untimed-review.csv`，仅给出前一句 ID，交人工听辨补定时间。在这些项目完成核对前，字幕不包含该短语。其他可疑句子仍带标记导出，方便定位。

## 交付文件与恢复限制

- `review.html`：视频播放与逐句跳转、英文、审查标记。
- `timetable.json`：供后续模块读取的句子表。
- `sentences.csv`：便于核对，可填写 human_correction；当前不自动回写 CSV 修改。
- `english.srt`：依据最终句子时间输出的英文字幕。
- `untimed-review.csv`：无可靠时长的短语与人工补定栏。
- `source/video.*`、`audio.wav`、素材 receipt、`checkpoints.sqlite`：复现与节点级恢复。

不保留原词对齐意味着：识别进行中中断，需要对全片重新识别；已完成的下载/音频准备可以复用。需要重新分句或重定时也可能需要重新 ASR。代码、模型、环境或已处理媒体变化时，旧任务拒绝直接续跑，应创建新任务。

## 验证范围

45 项自动测试通过，覆盖句中停顿、完整句分开、从句合并、疑似残句、缩写、词覆盖、零时长不编造时间、两小时参数边界、YouTube 单视频与英文音轨优先选择，并保留旧工具回归检查。两小时边界是配置/单元测试，不是两小时真实推理实测。真实长视频执行结果见同目录 `B-sentence-v2-run-20261107.md`。
