# B V2 完整视频实测（2026-11-07）

## 实际完成

素材为 MIT OpenCourseWare《1. What is Computation?》，YouTube 单视频入口：
https://www.youtube.com/watch?v=nykOeWgQcHM

对应课程来源与署名：Ana Bell，MIT 6.0001 Fall 2016，MIT OpenCourseWare。
https://ocw.mit.edu/courses/6-0001-introduction-to-computer-science-and-programming-in-python-fall-2016/resources/lecture-1-what-is-computation/

课程页面许可为 CC BY-NC-SA 4.0；保留原署名及许可，修改后的分享需标明修改。通用 YouTube 下载接口不替用户判断其他素材的使用许可。

本次从 YouTube 完整下载，明确选中 `140-drc`、`en-US`、English (US) original (default) 音轨；下载 76.665 秒。最终 MP4 84,845,570 字节，SHA256：`5859430322e13e40c57686eafc259c35e48c9c7f091b48d4e0c99d982e2b8e27`。

全片时长 2,585.850 秒（43 分 05.850 秒）。LangGraph 先暂停在音频准备完成处，再从 SQLite 续跑完成识别、审查和导出。对全片只调用 **1 次** `transcribe`，外部音频分块 **0**。实际 ASR 推理耗时 **1,625.744 秒**（约 27 分 06 秒），模型加载 0.363 秒；CPU int8，本地 base.en。耗时来自本次记录，不外推两小时视频速度。

## 结果与质量状态

| 项目 | 实测 |
|---|---:|
| 带最终时间的句子 | 579 |
| 从句或延续表达自动合并 | 80 |
| 疑似残句等人工复核项 | 59 句 |
| 零时长、待人工补定的短语 | 8 条，均为 Okay. |
| 句子时间结构错误 | 0 |
| 已解码检查的 SQLite 检查点 | 8 |
| 发现原始 ASR 分段/词时间结构 | 0 |
| 付费 API 调用 / DeepSeek 使用 | 0 / 未使用 |

本次尚未人工核对全片。自动审查通过不等于文字正确或句子语义完整；speaker_id 均为 null，未做说话人区分。8 条无可靠时长短语保留在人工补定表，不编造时间，不纳入当前 SRT。故这是可核对的机器初稿，并非已经准确验收的最终字幕。

两小时上限及 7201 秒拒绝行为有单元测试；**尚未运行两小时真实视频识别**。原先短片的人工通过结论不自动适用于本次完整视频。

## 文件位置

任务目录：`jobs/B-sentence-v2-YouTube-full-20261107-01/`

- `review.html`：可播放完整视频、点击句子时间跳转，展示待复核项。
- `timetable.json`、`sentences.csv`、`english.srt`：只包含最终句子级时间。
- `untimed-review.csv`：8 条短语的人工补定栏。
- `verification.json`：本次结构、检查点及识别调用检查结果。
- `source/download.json`、`media.json`、`request.json`、`events.jsonl`：素材来源、哈希、环境版本与实际节点耗时；没有原始 ASR 时间。
- `code-snapshot/`：本次 B 代码快照；依赖锁定记录另存于快照目录。

原有分块实验保留在其他历史目录；本次任务没有原始 ASR 时间文件或音频块目录。

## 已执行检查

```powershell
& .venv/Scripts/python.exe -m unittest discover -s tests -v
& .venv/Scripts/python.exe -m tools.verify_sentence_v2 jobs/B-sentence-v2-YouTube-full-20261107-01
```

45 项测试全部通过；日志位于 `jobs/B-v2-tests-20261107.log`，测试媒体证据位于独立 `jobs/B-v2-validation-20261107/`，未混入生产任务。核对页脚本已通过 Node `--check`，视频相对路径存在。验证工具会解码检查点，检查不存在原始 ASR 结构，并验证全片单次识别、无外部分块及最终句子时间有效。
