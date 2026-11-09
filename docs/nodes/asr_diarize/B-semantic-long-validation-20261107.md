# 长视频验证：语义审查接口版本

> 历史阶段记录：代码与文档已按 v1.2.0 迁移。旧路径、命令和“尚未实现”等状态仅对应记录当时，不作为当前入口；当前使用与限制见 [节点说明](README.md) 和 [迁移记录](B-layout-v1.2.0.md)。历史任务未修改。
2026-11-07，使用已经下载的 MIT OpenCourseWare《1. What is Computation?》完整视频，真实运行新版本 LangGraph，没有截取或拼接短片代替长视频。

原网址：https://www.youtube.com/watch?v=nykOeWgQcHM

署名：Ana Bell，MIT 6.0001 Fall 2016，MIT OpenCourseWare。课程来源与 CC BY-NC-SA 4.0 许可：https://ocw.mit.edu/courses/6-0001-introduction-to-computer-science-and-programming-in-python-fall-2016/resources/lecture-1-what-is-computation/

## 验证结论

**完整长视频处理与时间结构验证通过，语义分段质量尚未通过全片验收。** 本次只运行本地识别、句法整理和检查，没有新增 DeepSeek 付费调用。此前只获准的一次小样调用不能算作全片语义审查。

| 指标 | 旧版完整视频 | 本次完整视频 |
|---|---:|---:|
| 视频时长 | 43 分 05.850 秒 | 相同 |
| 台词条目数 | 579 | 654 |
| 最长单条词数（按空格统计） | 679 | 57 |
| 最长单条时长 | 255.860 秒 | 19.920 秒 |
| 超过 32 词的条目 | 15 | 15 |
| 超过 10 秒的条目 | 23 | 24 |
| 人工复核/语义待审条目 | 59 | 105 |
| 无可靠正时长、需人工补定的短语 | 8 | 9 |
| 时间结构错误 | 0 | 0 |

最长异常合并已解决，但其余超长项还在，所以不能根据最长条目缩短就宣称分句全部改善。超过 32 词与超过 10 秒的集合有重叠，不能直接相加。新版待审数量增加也包括新增的语义审查未执行标记，并不等于 ASR 准确率降低。

将最终条目和待补时间短语按原顺序合回后，忽略大小写/标点的词序与旧版完全一致；这是防漏词检查，不是与人工真值比较，不能据此宣称英文全对。内存使用的对齐词数两版均为 6,762。

## 真实执行与持久化检查

- 本地 faster-whisper base.en，CPU int8，4 线程。
- ASR 推理实测 236.353 秒（约 3 分 56 秒），模型加载 0.349 秒；不根据单次耗时推测两小时视频耗时。
- 完整 WAV 只调用一次 transcribe，外部音频分块为 0。
- LangGraph 从素材解析、获取、全片音频准备，运行至识别整理、审查和导出全部完成，无节点报错。
- 检查 8 个解码后的 SQLite 检查点、最终 JSON 和输出目录，未发现原始 ASR 分段或词时间结构；保留的时间是最终单元时间。
- 每个最终条目均满足时间在全片范围内、正时长、前后不重叠；核对页视频路径存在，页面脚本通过 Node 语法检查。
- DeepSeek 请求 0，新增付费 API 请求 0；DeepSeek HTTP 全片集成未实测。未发表团队材料未外发。

当前 semantic_review 元数据中 provider 显示 injected_callback、transport_calls 为 null，是未传 reviewer 时默认标签不够准确；实际调用以 execution.deepseek_used=false、paid_api_calls=0、semantic_review.attempted=0 为准，不能把该标签当作运行了回调或外部模型。

此前 56 项测试已通过；本次没有修改 B 核心代码，未重复运行同一组测试。此次新增的是独立结果比较脚本，并已在真实输出上运行。

## 输出与复现

目录：`jobs/B-semantic-long-validation-20261107-01/`

- `review.html`：完整视频、逐条定位及审查理由。
- `sentences.csv` / `timetable.json` / `english.srt`：新的最终台词时间表；仍为机器初稿。
- `flagged-review.csv`：105 条待审条目，优先供人工核对。
- `untimed-review.csv`：9 条需补定时间短语；未编造时间，当前 SRT 未包含它们。
- `long-units-to-review.json`：超长单元清单，包含当前英文和问题标记。
- `long-validation.json`：新旧量化比较及验证范围。
- `verification.json`：结构、单次识别及持久化检查。
- `code-snapshot/`、`request.json`、`events.jsonl`：本次代码与环境指纹、节点耗时。

```powershell
& .venv/Scripts/python.exe -m b_pipeline run --input jobs/B-sentence-v2-YouTube-full-20261107-01/source/video.mp4 --job-dir jobs/B-semantic-long-validation-20261107-01 --semantic-provider none
& .venv/Scripts/python.exe -m tools.verify_sentence_v2 jobs/B-semantic-long-validation-20261107-01
& .venv/Scripts/python.exe -m tools.report_long_semantic_validation jobs/B-semantic-long-validation-20261107-01 --previous jobs/B-sentence-v2-YouTube-full-20261107-01
```

任务目录已存在时不要重新执行第一条；新实验应使用新目录。历史全片输出没有覆盖。尚未做两小时真实视频推理、全片英文人工核对或全片 DeepSeek 语义质量验收。

下一步若要完成 105 条候选的 DeepSeek 审查，需要明确新的付费调用预算并配置本地可用的 API；不能把现有学校聊天工具的一次授权自动扩展为全片外发。由于按用户要求不保存原始词时间，若再采用不同语义断点生成精确新时间，仍需重新取得内存词对齐。
