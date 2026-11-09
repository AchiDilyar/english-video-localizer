# 整句多数说话人规则（当前默认归属策略）

按用户 2026-11-08 最新要求，取消此前边界冲突/重叠的拒绝归属规则，直接按整句检测到的说话时长判定主要说话人。此策略同时适用于 sherpa-onnx 和导入的 Community-1 结果，不更改底层说话人模型。

## 精确定义

1. 将句子最终起止区间与每个说话人的轮次取交集。
2. 对同一人的重叠/重复轮次先取并集，避免重复计时。
3. 每人的时长除以所有人时长之和，超过 50% 的人获得整句 speaker_id。静音不参与分母；不同人同时说话的时间分别计入对应人的时长。
4. 不再检查第二个人在句首、句中或句尾，也不再使用旧的 85% 主份额、35% 整句覆盖、300 毫秒/5% 次人门槛或 1.5 秒边界例外。
5. 无任何语音覆盖、时长并列，或三人以上没有一人超过 50% 时保留 null。最高 40% 的相对多数不当作超过一半的绝对多数。

speaker_assignment.method = whole_sentence_speaker_time_majority_v3；decision 为 majority_speaker / no_speech / duration_tie / no_majority。保留时长占比供核对，不把占比称为模型正确概率。清除旧 speaker_boundary_overlap 等已废弃警告，但保留转写、语义、人工增补等其他复核理由。

## 实际验证

基于已完成的 Community-1 三分钟双人访谈结果运行新的 LangGraph 归属任务，没有再次运行 ASR、神经说话人模型、下载或付费服务。新目录 `jobs/B-community1-majority-20261108-01/`，原任务不覆盖。

- 65 条台词：旧策略 59 条归属 / 6 条未知 → 新策略 65 条归属 / 0 条未知。
- speaker_001 为 48 条，speaker_002 为 17 条。
- 第 49 条 → speaker_001（检测语音份额 92.26%）。
- 第 64 条 → speaker_002（检测语音份额 100%）。
- 第 65 条 → speaker_001（检测语音份额 93.13%）。
- 英文、ID、最终起止时间逐项不变，时间结构错误 0；5 个 SQLite 检查点检查未发现原始 ASR 片段/词时间。
- 78 项测试通过，含大于半数/正好半数、三人无绝对多数、句中交替按多数、短句按多数、重复区间不重复计时、清理旧警告等。日志：`jobs/B-speaker-majority-tests-20261108.log`。

这次是归属策略变化，不是模型正确率提升的实验证明。全部有编号不等于所有编号已经人工确认；仍保留 speaker_labels_human_verified=false。底层模型若把两个人合成一个聚类，这一规则也无法恢复正确身份。

核对入口为该目录 review.html；timetable.json、sentences.csv 与 speaker-turns.json 同步导出。majority-verification.json 保存新旧统计及截图三条的判定依据。

```powershell
& .venv/Scripts/python.exe -m tools.diarize_existing --source-job jobs/B-community1-dialogue-20261108-01 --job-dir jobs/new-majority-review --reuse-turns
```

已有模型轮次通过音频哈希校验后复用，输入/输出必须使用不同任务目录。主流程后续新任务也自动使用此归属规则；先前文档里的保守边界策略均为历史版本。
