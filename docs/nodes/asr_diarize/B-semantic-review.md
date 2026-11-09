# B 语义分句与 DeepSeek 审查接口

> 历史阶段记录：代码与文档已按 v1.2.0 迁移。旧路径、命令和“尚未实现”等状态仅对应记录当时，不作为当前入口；当前使用与限制见 [节点说明](README.md) 和 [迁移记录](B-layout-v1.2.0.md)。历史任务未修改。
本轮变更：不再把“语法上是一个句子”视为适合单条字幕。长句需要在语义完整的分句处拆开，句号、逗号、ASR 停顿都只作为线索。输出仍保留现有 `sentence_id/en/start_ms/end_ms` 字段，方便 C/D/E/F 接入；此处的 sentence 实际表示一个经审查的语义单元，不保证都是独立语法句。

## 工作位置和规则

LangGraph 原有节点保留。`asr_and_sentence_formation` 在词对齐仍位于内存时调用语义审查，再生成最终时间；`review_sentences` 继续独立检查结果。不能将语义调用移到“原词时间已丢弃”之后，再按字数平均分配时间。

1. 本地句法模型先提出候选句、处理明显延续表达。
2. 超过 24 个词、超过 10 秒，或本地发现疑似残句的候选，进入语义审查队列；优先最长项。阈值触发审查，不决定断点。
3. DeepSeek 只接收该候选的英文词序列及长度目标，不接收时间、视频、音频、来源路径、团队代码或凭据。
4. 目标约 8–18 词的连贯语义单元；超过 32 词须明确标记人工复核。不能为凑长度拆开条件与结果、专名、动词短语。
5. 模型只返回断点索引和不确定标记。程序检查严格递增、无漏词、无重复、完整覆盖；拒绝返回改写文本。随后进行本地保守的条件从句边界检查。
6. 用内存中每个新单元所含词的首尾对齐确定最终时间，复核非零时长和无重叠。原词时间不落盘。
7. 超长、超时、模型失败、调用额度耗尽均显式标记。网络失败不自动重试；不以“已调用模型”宣称语义准确。最终仍需人工核对。

本轮也修正了旧从句合并循环：一次从句延续合并后不再反复吞并后续全部句子，并增加超长标记。对历史全片的重新审计发现 27 条超过 32 词或 10 秒，其中最后一条特别长；旧“结构通过”的结论并不证明分句合适。

## 独立调用接口

文件：`b_pipeline/semantic_review.py`。

```python
from b_pipeline.semantic_review import DeepSeekHTTP, validate_response

reviewer = DeepSeekHTTP(allow_network=True, max_calls=1)
payload = {
    "tokens": ["Python", "is", "useful."],
    "target_unit_words": 18,
    "max_unit_words": 32,
}
proposal = validate_response(reviewer(payload), payload["tokens"])
# {"ends": [3], "needs_human_review": False}
```

`ends` 为从 0 开始的排他结束索引，最后一项必须等于词数。例如 `[7,15]` 表示前 7 个词、后 8 个词。只允许选边界，不允许模型改字或生成时间。回调接口为 `reviewer(payload) -> dict`，供 F 替换服务适配器或离线测试；`sentences_from_words(words, nlp, semantic_reviewer=reviewer)` 在对齐仍在内存时应用提案。

报告写在 `table.review.semantic_review`：attempted、accepted、failed、pending、实际 transport_calls、可得的 token usage。accepted 仅表示提案被结构校验和有限本地规则接受，不代表语义已被人工确认。提案记录只保留文本哈希、词数、输出单元数和不确定标记，不保留原始词时间。没有启用语义服务时，候选会标记 `semantic_review_pending`，不会伪称已经语义审查。

## 接入完整视频命令

运行前，在当前终端或受保护的环境配置中设置 `DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL`；不把密钥写进代码、提交到 Git 或发到聊天。模型由你们实际可用账号指定，不猜测学校工具背后的模型。默认 `DEEPSEEK_BASE_URL=https://api.deepseek.com`，可配置明确授权的兼容 HTTPS 服务地址；模型和地址写入任务复现配置，密钥不写入。

```powershell
& .venv/Scripts/python.exe -m b_pipeline run --input 'C:/path/video.mp4' --job-dir jobs/my-semantic-video --semantic-provider deepseek --allow-semantic-network --semantic-max-calls 1
```

YouTube 输入额外加 `--allow-network`。下载联网和语义台词外发分别开关。默认不启用外部模型；`--semantic-max-calls 1` 最多 1 次实际请求，其他候选标记 pending，不会继续收费。每次请求最多 1200 个空格词，返回上限 2048 tokens。当前没有自动全片调用、自动重试或自动扩大预算；具体费用和学校余额未知。

**学校聊天工具与项目 HTTP 接口不同：** 本轮获准的小样使用 `tongji_models.ask_model`；它只能在当前工具环境调用，不可凭空变成本地程序的 API Key。项目已实现 HTTP 适配器，但真实自动运行需要团队提供上述环境配置。HTTP 路径已用模拟响应验证，尚未使用真实密钥实测。

## 本轮实际验证

- 56 项自动测试全部通过：包括无句号的语义拆分、原词不变、时间来自词对齐、条件边界保护、错误响应拒绝、预算上限、HTTP 模拟、真实识别函数内的适配器集成。
- 45 秒本地真实音频重新跑完 LangGraph：11 条，结构错误 0，3 条需要复核；未调用外部模型。检查 8 个 SQLite 检查点，未发现原始 ASR 分段或词时间结构。
- 按用户授权，仅调用 DeepSeek 1 次，发送公开 MIT 台词 57 个空格词。耗时 67.285 秒；工具未披露模型名、token 用量或费用，均不估算。
- 返回 `[27,57]`，结构覆盖正确，但将 if 条件与后续解释分开。本地规则拒绝，保留原文并标记，未第二次付费调用。该结果证明接口真实可调用，也说明一次模型回答不能视为语义质量验收。
- 证据：`jobs/B-semantic-small-validation-20261107/`；回归日志：`jobs/B-semantic-tests-20261107.log`；本地实际图运行：`jobs/B-semantic-local-smoke-20261107-01/`。

旧 43 分钟输出未覆盖。因其原词时间已经按用户要求丢弃，不能仅凭旧句子首尾可靠地重定内部断点。需要应用新方案到该全片时，须新建任务重新取得词对齐；本轮未重新运行那次约 27 分钟推理，也未获准全片付费审查。

## VideoCaptioner 调研与取舍

已阅读上游固定版本 `95842ecb5618c0b6a548a336bdfb0eb859bdb501`，没有安装或导入其实现，也没有复制其代码/提示词。该仓库标明 GPL-3.0。我们参考流程思路，独立实现当前边界索引接口。

| 上游实现 | 与本项目关系 / 取舍 |
|---|---|
| [LLM 断句与验证反馈](https://github.com/WEIFENG2333/VideoCaptioner/blob/95842ecb5618c0b6a548a336bdfb0eb859bdb501/videocaptioner/core/split/split_by_llm.py) | 高度重合；可借鉴“语义提案后校验”。上游最多两轮反馈，文本相似度阈值 0.96，并在最终失败后可能返回上次提案；本项目不采用容许改词或失败仍套用的行为。 |
| [语义拆分提示](https://github.com/WEIFENG2333/VideoCaptioner/blob/95842ecb5618c0b6a548a336bdfb0eb859bdb501/videocaptioner/core/prompts/split/semantic.md) | 强调句内也可按语义拆分、保持原文；本项目用断点索引替代生成整段改写文本。该提示存在不意味着其所有入口都使用它；所读 LLM 断句实现实际加载 split/sentence。 |
| [文本对齐模块](https://github.com/WEIFENG2333/VideoCaptioner/blob/95842ecb5618c0b6a548a336bdfb0eb859bdb501/videocaptioner/core/split/alignment.py) | 是文本序列相似匹配，不是语音强制对齐；不能用它给已丢弃词时间的旧台词恢复准确音频断点。 |
| [项目总体流程](https://github.com/WEIFENG2333/VideoCaptioner) | ASR、字幕优化、翻译、合成与 B/C/E 有重合，可作为对照工具。团队继续实现自己的 LangGraph、审核记录、错误回退和接口，避免把别人的整套字幕工具当作自建多智能体流程。 |

DeepSeek HTTP 协议依据其[官方 Chat Completions 文档](https://api-docs.deepseek.com/api/create-chat-completion/)，结构化 JSON 仍须本地做业务校验。
