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

2026-11-13 按用户要求恢复字幕拆短优化前的按句输出：撤销 `5c687b2` 引入的 35–42 字符、2–4 秒自动拆分及相关配置。保留原有 spaCy 句法整理、可选语义审查和局部复识别；超过 32 词或 10 秒仅标记复核，不按显示长度强制拆开。长句仍可能超出画面，显示排版需下游处理。旧短分句产物不会自动恢复，需从源视频重新运行 B 及下游。

本地后续未定时警告/并入下一条实验已备份，未纳入本次回退；原有未定时交付校验行为也随旧版恢复。此次使用新的反向提交保留团队最新主线，不重置或强推仓库历史。

- [F 主图与 B→C 阶段联调](../../graph/README.md)：build_graph 入口、模拟开关与阶段边界。
- [真实短片及共享分段](../../../tests/data/asr_diarize/real_dialogue/README.md)：14 秒、两位匿名说话人、11 条机器预测；附来源、许可和未确认标记。
- [测试说明](../../../tests/nodes/asr_diarize/README.md)：可选依赖与真实模型测试的启用方式。
- [验证与待办](validation.md)：当前验收证据和限制。

历史只保留两份：[关键设计与失败教训](archive/design-evolution.md)、[80 分钟实验摘要](archive/long-video-validation.md)。pipeline/、standalone/ 中历史实现不作为团队基本版入口。
