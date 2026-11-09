# 真实双人访谈视频验证

> 历史阶段记录：代码与文档已按 v1.2.0 迁移。旧路径、命令和“尚未实现”等状态仅对应记录当时，不作为当前入口；当前使用与限制见 [节点说明](README.md) 和 [迁移记录](B-layout-v1.2.0.md)。历史任务未修改。
## 素材

使用 ConversationEDU 的 *Interview with Steve Wozniak*：采访者与受访者实际交替问答，不是“课程片头一个人、课堂另一个人”，也不是重复/拼接官方声音测试文件。

- [Wikimedia Commons 来源、作者与许可页](https://commons.wikimedia.org/wiki/File:Interview_with_Steve_Wozniak.webm)
- [原 YouTube 入口](https://www.youtube.com/watch?v=920QAxtook8)
- 作者：ConversationEDU；来源页标注 CC BY 3.0，并记录过许可审查。
- 测试片段：原访谈 00:10–03:10，连续 180 秒，转为 H.264/AAC 480p。台词表以片段起点为 0；对应原片时间需加 10,000 毫秒。
- 原视频 SHA256：c808d0ab73bc3482c444e1463dda1c463215590effdb98d3d68fcdbab9493dc4。
- 片段 SHA256：63fe8ba567ec3e36eba120162108785d28fb8351c6cc2699a50d8ad07ee4f98f。

下载来自 Commons 原文件。原 YouTube 下载仅尝试作为慢下载备用，Commons 完成后已停止备用任务；本次不把备用路径算作成功下载证据。作者、许可、来源及修改说明已写入两个任务的 ATTRIBUTION.txt 和核对页。

先在原片上自动探查，再从开头附近选连续片段用于工程检查，不作为随机抽样的性能基准。该段 ASR 出现问答及短回应，例如开头受访者陈述、采访者追问、受访者回答，两个主要声音的模型轮次时长分别约 135.910 和 46.323 秒（重叠部分可能重复计入）。英文文本本身尚未人工校对，包括专有地名；不能当作字幕真值。

## 两种实际运行

先用默认自动人数模式跑完整 B LangGraph：素材准备 → 全片 ASR → 残句局部复识别 → 说话人区分 → 审查/导出。随后复用同一份 65 条台词，只改变已知人数约束再次进行说话人处理，没有重复全片 ASR。

| 指标 | 自动判断人数 | 指定已知双人 |
|---|---:|---:|
| 请求人数 | 未指定 | 2 |
| 检测聚类数 | 3 | 2（由约束指定） |
| speaker_001 台词 | 42 | 56 |
| speaker_002 台词 | 11 | 0 |
| 未确定台词 | 12 | 9 |
| 最终轮次数 | 26 | 12 |
| 模型标签切换次数 | 22 | 7 |
| 说话人处理耗时 | 7.566 秒 | 7.568 秒 |
| 时间结构错误 | 0 | 0 |

自动模式的第三组总轮次时长仅 878 毫秒，没有独立台词被分给该组；是否噪声、重叠或误分仍需听辨，不把它直接当作第三个真实人物。完整原片自动探查给出 6 组，说明“自动人数”在这份录音上有过度聚类风险。

**指定双人模式未通过本例的说话人分离验收。** 虽然结果是两个聚类，但所有已归属的台词都落在 speaker_001；另一聚类只有短暂轮次，无法覆盖独立台词。这说明“输入 2，输出 2”不能证明两个实际人的话被分开。不能推荐本例靠强制人数解决问题。

自动模式能给两组主要台词分配不同编号，具备人工核对基础，但额外短聚类和未确定条目仍在。**本次证明流程跑通，也发现聚类质量缺陷；不宣称双人标签准确率验收通过。** 未提供人工逐帧标签，未计算 DER，未与 D 验证同人音色一致性，也未替 F 确认接口。

## 文件与验证

- 自动模式：`jobs/B-two-person-video-auto-20261108-01/review.html`，是本例优先核对入口。
- 两版对照：`jobs/B-two-person-video-known2-20261108-01/comparison.html`，同一视频/台词并排看标签，可点击时间跳转。
- 每版均有 timetable.json、sentences.csv、english.srt、speaker-turns.json 和 verification.json。
- 汇总：`jobs/B-two-person-video-known2-20261108-01/two-person-validation.json`。
- 素材/来源/探查：`media/wozniak-two-person-interview/`，原片和短段仅保留本地，不提交仓库。

两版的 65 条台词、ID、起止时间逐项一致。原词时间/原始 ASR 分段没有落盘；新增的是最终说话人轮次。自动模式检查 10 个 SQLite 检查点，指定双人模式检查 5 个；时间、正时长、范围及输出结构均通过。页面视频文件存在，脚本通过 Node 语法检查。

ASR 全片调用一次，耗时 14.773 秒；12 处疑似残句做了 24 次局部复查，未暂应用文字增补。所有实际推理本地运行，DeepSeek/付费调用 0。两种模式的代码快照和依赖锁已保存。此次没有修改核心算法，没有为相同代码重复跑昂贵实验或重新运行原 43 分钟课程。

```powershell
& .venv/Scripts/python.exe -m b_pipeline run --input media/wozniak-two-person-interview/dialogue-0010-0190.mp4 --job-dir jobs/new-auto-test --diarize
& .venv/Scripts/python.exe -m tools.diarize_existing --source-job jobs/new-auto-test --job-dir jobs/new-known2-test --num-speakers 2
```

## 后续改进边界

应先人工标注该片段的一小组真实问答轮次，尤其是短回应和交叠，再判断错误出在嵌入、聚类还是台词归属。可据标注尝试更适合该录音的模型/聚类配置；不能仅调参到“恰好两组”就报告成功。本轮保留原始失败结果，没有用另一个成功样例覆盖这项反例。
