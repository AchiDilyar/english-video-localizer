# 疑似残句音频复识别：实现与实际修订

> 历史阶段记录：代码与文档已按 v1.2.0 迁移。旧路径、命令和“尚未实现”等状态仅对应记录当时，不作为当前入口；当前使用与限制见 [节点说明](README.md) 和 [迁移记录](B-layout-v1.2.0.md)。历史任务未修改。
## 已实现

主 LangGraph 新增 `recheck_incomplete_audio`：初次完整识别 → 疑似残句局部复识别 → 审查 → 导出。初次完整视频依然不分块；局部读音频是错误复查，不是把完整识别改成分块处理。没有调用外部模型或付费服务。

筛选带 `possible_*` 标记的条目，以前后邻句作听辨上下文。使用同一个本地 faster-whisper base.en 分别 beam5 / beam1、关闭跨段文字条件后复识别。两种设置不是独立模型，相同结果不能证明识别正确。

仅当两个候选词序一致、相对原文只有新增词、无删改、增量受限、词对齐有效且不侵入邻句时，暂应用修订；重新生成最终句子时间并标记 `audio_recheck_changed_needs_human_confirmation`。其他情况保留原文并展示候选。句首对齐允许落在前一句结束与当前旧起点之间的空隙，防止旧起点不准导致再次丢失句首词。零时长或边界冲突不猜测补齐。

词级时间只在内存存在，检查点和报告不保存原始词/ASR 分段时间。初次全片调用数和局部复识别调用数分别记账；不再把带复查的流程说成总共仅一次 ASR。

## 本次运行

源任务：`jobs/B-semantic-long-validation-20261107-01/`，43 分 05.850 秒完整视频。

第一次新任务：`jobs/B-audio-recheck-long-20261107-01/`，检查 65 处，130 次局部调用，实测 119.177 秒，暂修订 4 处。22 处解码设置不一致、13 处不满足仅插入规则、2 处时间边界冲突，24 处与原文一致。

在第 416 条发现旧起点会排除句首 So，修正边界选择后仅对该条复查，产生第二次任务 `jobs/B-audio-recheck-long-20261107-02/`。新增 2 次局部调用，实测 3.525 秒，保留第一次 4 处修订并新增第 416 条修订。未再次运行全片 ASR，也未无诊断地重跑所有 65 处。

最终共有 65 个不同复查目标、5 处暂修订。最终表 658 条、结构错误 0、仍有 9 条未定时短语。5 个 SQLite 检查点解码检查未发现原始 ASR 时间结构。完整识别 1 次 + 局部复查累计 132 次；付费调用 0。

第 416 条的最终候选：

| 新编号 | 最终视频时间 / 秒 | 英文 |
|---|---|---|
| sentence_000416_r01 | 1550.520–1552.580 | So in programming languages, there's only one meaning. |
| sentence_000416_r02 | 1552.920–1561.200 | But the problem that comes into play in programming languages is it's not the meaning that you might have intended as the programmer. |
| sentence_000416_r03 | 1562.660–1564.460 | So that's where things can go wrong. |

所有修改仍未经人工听辨确认。局部复识别可能幻听；仅插入检查也不能证明新增词真实存在。本机制只检测疑似残句，语法完整句中的漏词可能仍未发现；不能将本次结果称为全片无漏词。原 full-pass coverage/hash 等字段描述初次全片识别，不用于证明这些新增词；新增依据单列在 audio_recheck 报告。

## 文件和使用

最终目录 `jobs/B-audio-recheck-long-20261107-02/`：

- `audio-recheck-review.html`：合并展示 65 处最新复查结果，绿/红标出差异，播放完整原视频对应位置。该页是人工核对入口。
- `review.html`：包含 5 处暂修订的全片台词时间表。
- `timetable.json`、`sentences.csv`、`english.srt`：同步更新的接口和字幕产物。
- `audio-recheck.json`：第二次定向复查记录；前 65 处记录保存在父任务 01。
- `verification.json`、`code-snapshot/`：结构/持久化验证和代码快照。

旧结果没有覆盖。修订拆句用原编号加 `_r01` 等后缀，并记录 replacement_sentence_ids；C/D/E 应按新 timetable 重新读取受影响 ID，不将旧译文或配音直接套在新句子上。

```powershell
# 已完成全片任务后，单独启动复查；输出必须是新目录
& .venv/Scripts/python.exe -m tools.recheck_incomplete --source-job jobs/previous-full-video --job-dir jobs/new-audio-recheck

# 只复查指定句子；可多次提供 --sentence-id
& .venv/Scripts/python.exe -m tools.recheck_incomplete --source-job jobs/previous-full-video --job-dir jobs/new-one-sentence --sentence-id sentence_000416
```

独立接口为 `recheck_table(table, audio_path, model, nlp, only_sentence_ids=None)`，返回新表，不修改传入表；`recheck_node(state)` 可接入 F 主图。独立复查脚本使用真实 LangGraph + SQLite，当前只支持新任务，不提供故障中途续跑命令；原始素材、表、音频哈希先核验。

60 项测试通过，包括增词保护、删除/替换拒绝、两设置不一致不覆盖、原表不变、句首空隙恢复及全项目回归。日志：`jobs/B-audio-recheck-tests-20261107.log`。
