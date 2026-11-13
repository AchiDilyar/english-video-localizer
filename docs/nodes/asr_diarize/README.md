# asr_diarize：B 节点使用与对接

本页是 B 转写节点的当前入口。共享规则以 [architecture](../../design/architecture.md)、[workflow](../../design/workflow.md)、[dataflow](../../design/dataflow.md) 和 project/contracts 为准。

## 入口与交付

```python
from contracts import GraphState
from nodes.asr_diarize import asr_diarize

delta = asr_diarize(GraphState(input_video="input.mp4"))
# {"segments": list[Segment]}
```

由 F 主图调用；前序为 [probe_input](../probe_input/README.md)，后序为 C 的 build_blocks。主图只接受工作目录根目录下的本地 MP4 文件名；网址下载不在共享节点内。

- CLI 预先创建工作目录、子目录并初始化统一日志，节点不创建目录。
- 配置经 F 的 load_config 读取；产物路径由 artifact_path 获取。
- 提取完整 16 kHz、单声道 PCM16 音轨至 audio/source.wav。
- faster-whisper 对全片初次识别，不做外部音频分块；spaCy 按句法/语义整理，疑似残句可局部复识别。原始 ASR 分段和词时间只在内存，不写文件或检查点。
- Community-1 处理说话人；整句检测说话时长超过 50% 的人获得归属，边界小冲突不单独否决。编号只在片内有效，不代表已确认身份。
- 输出 seg_0001 等 segment_id、spk_1 等 speaker_id、start_ms、end_ms、text_en。write_artifact("segments", segments) 成功写入 segments/segments.json 后才返回增量；不修改输入 State。
- 节点错误直接抛出，日志交给统一 logger；不会额外生成检查点、HTML、字幕或第二套业务报告。

共享 Segment 不允许空说话人：未知时抛 UNRESOLVED_SPEAKER，未定时间短语抛 UNTIMED_UTTERANCES，不猜测标签或丢词来通过校验。失败可能留下已提取音频，应排查后换新工作目录，不覆盖旧输出。

## 环境与配置

安装、uv 命令、依赖组和本地模型准备统一见 [环境说明](environment/README.md)，本页不重复维护。依赖版本以 pyproject.toml / uv.lock 为准。

配置源：config/asr_diarize.toml、config/probe_input.toml。

| 设置 | 当前默认与含义 |
|---|---|
| model_dir | models/faster-whisper-base.en，使用本地权重 |
| max_duration_sec | 7200 秒；两小时上限不等于两小时实测 |
| audio_recheck | true，疑似残句可局部复识别 |
| community1_cache / device | 本地模型缓存；默认 cpu，可明确选择 cuda |
| community1_python | 保持空值，子进程沿用当前 uv 解释器 |
| num_speakers | 可选，未指定时由模型推断 |
| worker_timeout_sec | 7200 秒 |
| semantic_provider | none；DeepSeek 需明确启用、联网许可及预算 |

模型路径相对仓库根解析。DeepSeek 配置不代表付费调用授权；完整 GPU/真实模型联调范围见 [验证与待办](validation.md)。

## 对接与资料

### 英文字幕分句

`config/asr_diarize.toml` 的 `[subtitle]` 配置控制每次显示的英文字幕：`target_min_chars=35`、`max_chars=42`（空格和标点计入）、`min_duration_sec=2.0`、`max_duration_sec=4.0`、`max_cps=20.0`。

当前 WebUI 将嵌套的字幕策略作为只读项，调参请修改上述 TOML；保存其他顶层配置会保留 `[subtitle]` 表，新增顶层参数写在表之前。

先整理语义，再利用仅在内存中的词时间选择字幕切点。完整短句尽量保留；过长时优先在标点、从句或短语边界切开，避免拆开姓名、所有格和否定结构。42 字符及 4 秒优先约束；35 字符和 2 秒是软目标，不强行合并短回答。不可拆的超长单词或重叠对齐簇保留并标记例外，不删词、不截掉内容。

阅读速度超过 20 字符/秒会标记 `subtitle_reading_speed_high`。快速原话不能仅靠再分句消除阅读负担；不会虚改时间或覆盖下一句话来达标。共享 Segment 字段不变，异常由节点日志报告，独立核对表保留详细标记。截图中的中文显示宽度还需 E 在翻译和成片阶段检查，英文字符限制不能保证中文最终宽度。

此规则也用于局部复识别结果。历史产物没有保存原始词时间，不能准确地直接切割旧 JSON；应从源音频重新运行 B，再让 C/D/E 基于新 ID 和时间戳重新生成下游结果。

- [F 主图与 B→C 阶段联调](../../graph/README.md)：build_graph 入口、模拟开关与阶段边界。
- [真实短片及共享分段](../../../tests/data/asr_diarize/real_dialogue/README.md)：14 秒、两位匿名说话人、11 条机器预测；附来源、许可和未确认标记。
- [测试说明](../../../tests/nodes/asr_diarize/README.md)：可选依赖与真实模型测试的启用方式。
- [验证与待办](validation.md)：当前验收证据和限制。

历史只保留两份：[关键设计与失败教训](archive/design-evolution.md)、[80 分钟实验摘要](archive/long-video-validation.md)。pipeline/、standalone/ 中历史实现不作为团队基本版入口。
