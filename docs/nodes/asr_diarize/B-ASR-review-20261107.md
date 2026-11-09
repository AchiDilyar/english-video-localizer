# 英文语音识别：人工核对入口

> 历史阶段记录：代码与文档已按 v1.2.0 迁移。旧路径、命令和“尚未实现”等状态仅对应记录当时，不作为当前入口；当前使用与限制见 [节点说明](README.md) 和 [迁移记录](B-layout-v1.2.0.md)。历史任务未修改。
日期：2026-11-07。真实本地推理已完成；人工正确性核验尚未完成。本轮没有冻结或更改团队共享接口。

## 先打开这里

[视频与英文同步核对页](../../../jobs/B-ASR-MIT-base-en-20261107-02/review.html)。用浏览器打开本地 HTML；页面通过相对路径读取同一项目内的视频，移动页面时请保留目录关系。

1. 播放视频，逐段比较实际声音和机器英文。
2. 点击每行的开始时间跳转重听，必要时使用 0.75 倍速。
3. 展开词级时间，点击单词定位。机器词时间不是人工精确边界。
4. 写下错词、漏词和时间偏移；若听到其他人插话，修改说话人编号并记录位置。
5. 点击“下载我的核对记录”保存 JSON。页面不会联网，也不自动写回磁盘；关闭或刷新前一定下载，否则编辑会丢失。

CSV 方式：[分段更正表](../../../jobs/B-ASR-MIT-base-en-20261107-02/segments-review.csv)，在 human_en、human_start_sec、human_end_sec、human_speaker、notes 填更正，机器列保留。

## 已获得的真实结果

- faster-whisper 1.2.1，模型 Systran/faster-whisper-base.en，CPU int8，4 线程，beam_size=5，temperature=0，显式英文，开启词时间，未开启 VAD。
- 45.012 秒 WAV，模型加载约 0.315 秒，推理约 3.071 秒；这些不含安装、42.335 秒模型下载、文件导出与整轮交互耗时。
- 18 个模型分段、148 个词。机器可能在句中分段，例如将 computation 单独分开；不把分段直接当成完善的字幕断句。
- 本轮检查通过：分段与词时间均在音频范围内、CSV/HTML 数量一致、视频引用存在、页面 JavaScript 语法有效。没有因此宣称内容准确率、时间误差或浏览器完整交互已经验收。
- 模型修订：`3d3d5dee26484f91867d81cb899cfcf72b96be6c`；权重 SHA-256：`2a166925539a16005f14ff328359f9b9adb9dc4fb631bb3b227526862e93e2ef`。

原始结果：[asr.raw.json](../../../jobs/B-ASR-MIT-base-en-20261107-02/asr.raw.json)；[纯英文与时间](../../../jobs/B-ASR-MIT-base-en-20261107-02/transcript.txt)；[词时间和后端分数](../../../jobs/B-ASR-MIT-base-en-20261107-02/words.csv)；[英文 SRT](../../../jobs/B-ASR-MIT-base-en-20261107-02/english.srt)；[完整执行记录](../../../jobs/B-ASR-MIT-base-en-20261107-02/execution.json)。概率分数是后端输出，未经校准，不能当作客观正确率。

## 说话人必须注意

**没有运行自动说话人区分。** 本次全部 SPEAKER_00 来自“单人假设”，不是模型自动识别或人工确认的结果。它仅方便先核对这段以讲师为主的课堂片段，不可拿来证明双人识别成功。若发现学生声音或其他发言，需要单独记录并修正；后续多人样片再接说话人区分。

## 建议优先检查的位置

- 00:00–00:02.36：机器写“first name Anna, last name Bell.”，但官方讲师页姓名是 Ana Bell。优先听辨，不静默覆盖原始预测。
- 00:06.40–00:16.04：介绍其他授课者的句子，重点核对人名、代词及断句。
- 00:23.64–00:25.56：“what is computation” 被模型拆成两个片段，核对时间及是否需要在字幕阶段合并。
- 00:43.86–00:44.82：结尾“all the slides and codes.”可能是被裁断的句子；样片本身来自整课中间，不能把没截进来的后续内容算作模型漏译。

以上是核对提示，不是已经人工听写确认的结论。原课时间 = 样片时间 + 60 秒；不要把两套时间混用。

## 环境与返工

本轮只在项目 .venv 安装了识别依赖，未改系统 Python、驱动或 CUDA。首次运行在音频解码前失败：faster-whisper 1.2.1 调用 PyAV 19.0.2 已不支持的 metadata_errors 参数。失败保留在 [failure.json](../../../jobs/B-ASR-MIT-base-en-20261107/failure.json)，未得到识别结果。

将项目 PyAV 固定为 16.1.0 后，用同一音频、同一模型及参数完成推理；没有为“选最好结果”重复识别。当前精确依赖见 [requirements-asr.lock.txt](environment/requirements-asr.lock.txt)，源码快照与脚本哈希保留在成功运行目录。

复现命令（指定新的输出目录，已有目录不会覆盖）：

```powershell
.\.venv\Scripts\python.exe tools/transcribe_sample.py --model-dir .\models\faster-whisper-base.en --output .\jobs\B-ASR-MIT-new-run
```

不需要为人工核对重新运行。直接打开现有 HTML/CSV 即可。模型运行完全本地，模型下载只读取公开权重；未上传音频，无付费 API 调用。显存峰值未测，CPU 推理；整体交互耗时 unknown。DeepSeek 未参与。

素材来源、署名和 CC BY-NC-SA 4.0 条件见 [样片说明](B-MIT-test-sample.md)，分享片段或其转写请保留来源、许可与修改说明。运行文件位于忽略目录 jobs/，不会自动上传 GitHub。
