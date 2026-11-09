# 句首/句尾短暂重叠的主要说话人归属

按用户要求增加边界例外：在句子主体明确属于同一人的情况下，少量边缘重叠不再让整句变成未知。现有严格归属规则保留，只有其拒绝时才检查边界例外。

## 新规则

- 句子至少 2.5 秒，主要说话人覆盖至少 80% 的整句时间，且占检测语音至少 80%。
- 边界区为首尾各 `min(1500 毫秒, 句长的 20%)`；其他说话人的语音不得进入中间主体。
- 其他说话人的总区间长度不超过 `min(1500 毫秒, 句长的 20%)`，至少一半与主要说话人同时出现。
- 真正仅有另一人、没有主要说话人的时间不超过 `min(500 毫秒, 句长的 10%)`。
- 满足时分配主要 speaker_id，decision 为 dominant_with_boundary_overlap，保留 speaker_boundary_overlap 人工核对提示。
- 句中明显交替、长时间同时说话、覆盖不足、短句不使用此例外，继续未知。不是将所有空值填成占时最长者。

这些阈值是明确的工程策略，尚未由人工标签校准，不是正确概率，也不能纠正底层模型把两个人合成一个聚类的问题。

## 本次实际检查

复用已有三分钟访谈的自动人数说话轮次，使用新 LangGraph reassign_speakers → review_sentences → export_sentences，不重新运行 ASR 或神经模型。旧任务不覆盖。

| 条目 | 新归属 | 依据 |
|---|---|---|
| sentence_000049 | speaker_001 | 主要声音覆盖约 94.5%，另一个组仅在句首边缘且大部分同时出现 |
| sentence_000064 | speaker_002 | 主要声音覆盖约 94.8%，第二组仅在句尾短暂重叠 |
| sentence_000065 | speaker_001 | 主要声音覆盖全句，上一组只在句首短暂残留 |

总计 65 条：原先 53 条归属 / 12 条未知 → 56 条归属 / 9 条未知，新增的三条均保留边界提示。文字、ID、起止时间逐项不变。结构检查通过，5 个 SQLite 检查点未发现原始 ASR 时间结构。73 项测试通过，包括边缘重叠允许、同长度句中重叠拒绝、真实顺序换人拒绝、短句不放宽。

输出：`jobs/B-two-person-boundary-auto-20261108-01/review.html`、timetable.json、sentences.csv、speaker-turns.json、boundary-verification.json。测试日志：`jobs/B-speaker-boundary-tests-20261108.log`。

命令：

```powershell
& .venv/Scripts/python.exe -m tools.diarize_existing --source-job jobs/B-two-person-video-auto-20261108-01 --job-dir jobs/new-boundary-review --reuse-turns
```

--reuse-turns 会核对来源音频哈希，不能同时改变人数参数；复用结果不记作新增模型推理。当前已知双人模式曾把主要声音合并的问题没有因此解决，不将减少空值当成模型准确率提升的证明。

## 更新的模型候选

截至 2026-11-08 查阅官方模型说明，尚未下载或部署以下候选，也未调用收费服务：

| 候选 | 与当前任务相关的能力 | 接入限制 |
|---|---|---|
| [pyannote speaker-diarization-community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) | 官方报告相比旧 3.1 改善说话人计数/归属，提供 exclusive_speaker_diarization，便于与转写时间对齐；可本地离线运行。并非所有基准都更好，也不能据此保证本片更准。 | 需要 Hugging Face 登录、用户本人接受模型条件并取得访问 token；还需独立配置 pyannote/PyTorch。 |
| [NVIDIA Nemotron-3-Diarization](https://huggingface.co/nvidia/Nemotron-3-Diarization) | 100M 参数，输出最多 8 个说话人活动通道，支持重叠和流式/分块推理，官方提供 Transformers/NeMo 等运行路径。 | 需另配依赖、核对运行硬件和模型许可；当前机器耗时/准确率未知，模型内部流式窗口不代表需要修改本项目的全片 ASR。 |
| [NVIDIA Streaming Sortformer 4spk v2.1](https://huggingface.co/nvidia/diar_streaming_sortformer_4spk-v2.1) | 端到端四说话人流式路线，作为已有生态候选。 | 官方模型页已提示存在更新版本；若选 NVIDIA 新路线，应先比较 Nemotron-3，而不是把 v2.1 称为最新模型。 |

建议优先把 Community-1 作为本片离线对照候选，因为其 exclusive 输出专门针对说话轮次与转写对齐这一问题。这是基于官方功能说明的选择判断，不是本机实验结论。模型条件需用户自行审阅接受，不代替用户提交个人信息或创建凭据。
