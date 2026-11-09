# B：真实说话人区分

> 历史阶段记录：代码与文档已按 v1.2.0 迁移。旧路径、命令和“尚未实现”等状态仅对应记录当时，不作为当前入口；当前使用与限制见 [节点说明](README.md) 和 [迁移记录](B-layout-v1.2.0.md)。历史任务未修改。
2026-11-07，完成真实神经网络说话人分段、聚类及台词归属的本地实现，并实际运行；没有再用固定 speaker_id 或单人假设代替识别。本轮不进行 B–D 音色联调或 F 的共享接口验收，不提交/关闭 Issue #3。

## 方法与接口

本地 sherpa-onnx 2.0.1，pyannote segmentation 3.0 ONNX + 英文 WeSpeaker VoxCeleb ResNet34 ONNX，CPU 4 线程。自动聚类默认不提供人数；可显式指定已知人数。模型首先检测说话活动，再以说话人特征聚类，并生成全片毫秒轮次。声纹向量只在内存使用，不写入导出或检查点，不推断姓名，不上传音频。

每片按首次检测出现的顺序编号 speaker_001、speaker_002……，同片内同一聚类复用相同编号；跨片编号不表示同一个人。模型仍可能误分/合并，不能将自动聚类视为真实身份识别。

台词保持原英文、原句子编号及最终句子起止时间。按每位说话人的轮次与台词时间交集归属：主说话人覆盖至少 35% 的台词区间、占已检测语音至少 85%，且没有显著第二人语音，才分配编号。多人交替、重叠或覆盖不足保留 null，并标记人工复核，不强行归为一个人。覆盖比例是几何统计，不是模型正确概率。阈值尚未基于团队数据标定。

### 新任务

```powershell
# 首次下载官方公开模型，只写项目 models/，不上传音频
& .venv/Scripts/python.exe -m tools.bootstrap_diarization

# 完整本地视频：识别 → 局部残句复识别 → 说话人区分 → 审查/导出
& .venv/Scripts/python.exe -m b_pipeline run --input 'C:/path/video.mp4' --job-dir jobs/my-speaker-job --diarize
```

YouTube 链接需额外加 `--allow-network`。默认 `--diarize` 不开启，以保留已有调用和无模型环境的兼容行为；开启时模型缺失会明确报错，不自动联网下载、不返回假标签。可用 `--num-speakers 2` 指定已知人数；这不等于验证模型能自动判断人数。本轮所有实际测试均未指定人数。

已有台词只补说话人，不需要重跑 ASR：

```powershell
& .venv/Scripts/python.exe -m tools.diarize_existing --source-job jobs/B-audio-recheck-long-20261107-02 --job-dir jobs/new-speaker-result
```

该命令以新 LangGraph 任务运行 diarize_speakers → review_sentences → export_sentences，先检查原素材和音频哈希，新建任务保留原结果。此独立补标脚本尚未提供中途失败续跑命令。默认完整 B 图已加入同名节点；启用说话人识别的新完整任务会记录模型哈希/版本，并在续跑时检查一致性。

Python 接口：

```python
from b_pipeline import diarize, assign_speakers, run_b
turns = diarize("audio.wav")  # mono, PCM16, 16kHz
new_table = assign_speakers(table, turns)  # 不修改原表
# 或 run_b(..., diarization=True)
```

结果保留 `speaker_id`，额外包含 `speaker_assignment` 依据；根字段 diarization 包含最终说话轮次、匿名编号和运行元数据。verification.automatic_diarization_executed=true，speaker_labels_human_verified=false。核对 HTML 与 sentences.csv 已展示编号；新增 speaker-turns.json 可供后续模块读取。

说话轮次时间是本轮新增的最终说话人时间轴，不是被禁止保存的原始 ASR 片段/词时间。未保存原词时间，未新增原始 words/segments 结构。

## 实际验证

| 输入 | 未预设人数的结果 | 验证边界 |
|---|---|---|
| 官方 16 秒 two-speakers-en.wav | 检测 2 个聚类，推理 0.562 秒 | 官方标为双人英文样音；尚未逐帧人工标注/计算 DER。 |
| 同一真实样音重复一次，32 秒工程输入 | 检测 2 个聚类，前后编号序列均为 001、001、002、002 | 只检验重复声音的编号一致性；不是自然对话基准，也不是 D 联调。 |
| 原有 43 分 05.850 秒课堂全片 | 338 个说话轮次、2 个聚类，推理 120.444 秒；634/658 条分配编号，24 条保留未知 | speaker_001 为 3 条，speaker_002 为 631 条。标签尚未人工核对，不据此宣称全片只有两个人。 |

全片最终英文、ID 和句子起止时间逐项与上一版比较完全相同。结构校验通过，检查 5 个 SQLite 检查点未发现原始 ASR 时间结构。原有 9 个待定时短语仍未解决。原有 5 处文字暂修订仍须人工确认；说话人识别不会自动证明这些文字正确。

69 项单元/集成检查通过，涵盖多人交替、同人回归、重叠不强判、无语音时未知、重复轮次不重复计算、文本和时间不变，以及非法 ID/轮次拒绝。没有新增付费或 DeepSeek 调用。

## 文件与复现信息

完整结果：`jobs/B-diarization-long-20261107-01/`。

- review.html：全片台词与说话人编号。
- timetable.json、sentences.csv、english.srt、speaker-turns.json：实际导出。
- speaker-unresolved.csv：24 条未知/混合说话人，便于人工核对。
- speaker-verification.json、verification.json、events.jsonl：统计、时间/文本不变检查及节点耗时。
- code-snapshot：与任务启动时的代码指纹对应的执行版本。

短样及重复一致性证据：`jobs/B-diarization-smoke-20261107/`。测试日志：`jobs/B-diarization-tests-20261107.log`。依赖：requirements-sentence-v2.lock.txt，新增 sherpa-onnx / sherpa-onnx-core 2.0.1。

模型来源和本地 SHA256 记录于 models/diarization/provenance.json（上游此发布未提供资产校验和，本地哈希用于复现，不冒称官方签名验证）。分段模型包附 MIT License，保留在本地；模型权重和样音不提交仓库。

官方来源：[sherpa 说话人区分文档](https://k2-fsa.github.io/sherpa/onnx/speaker-diarization/index.html)、[Python API 示例](https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/offline-speaker-diarization.py)、[分段模型与测试样音](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-segmentation-models)、[声纹模型](https://github.com/k2-fsa/sherpa-onnx/releases/tag/speaker-recongition-models)。仅参考 API 独立实现本项目逻辑。

## 留待之后

B–D 的双人标签/音色一致性联合验证、F/C/D/E 共享接口确认和干净检出的复现交付仍待进行。说话人功能已经实现并跑通，不代表 Issue #3 已全部完成或说话人准确率已通过人工验收。
