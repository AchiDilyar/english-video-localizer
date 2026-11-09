# B LangGraph 实际运行记录

2026-11-07，北京时间。最新入口：[接口与命令](B-LangGraph-API.md)。本记录补充、更新旧文档中“LangGraph 尚未运行”的历史状态。

后续人工反馈：用户表示本次结果“人工核对无误”，已单独记录在 [human-review.json](../jobs/B-LangGraph-MIT-20261107-01/human-review.json)，绑定原台词表哈希。原始预测、台词表和缓存未覆盖；下文“待人工核对”描述自动流程完成时的状态，最新人工结论以该记录为准。这不代表自动说话人区分或长视频已验收。

下载状态澄清：日志中的首次5xx是已恢复的历史失败，随后45秒样片已成功下载。源视频是一部长课，但本轮只保存节选，未下载完整长视频；当前120秒处理上限不变。

## 真实链接流程

任务：[B-LangGraph-MIT-20261107-01](../jobs/B-LangGraph-MIT-20261107-01/evidence-summary.json)。登记素材 mit-python-remote-45s，MIT OCW / Ana Bell 6.0001 第一讲，原课60–105秒节选。许可与来源由登记表保留，不自动抓取任意视频。

实际节点：resolve_source → acquire_media → prepare_audio → transcribe → group_sentences → validate_timetable → export_timetable。

首次下载源站返回5xx；保存检查点和失败事件后，明确重试一次，跳过已完成的 resolve_source。成功下载与检查约12.000秒、音频准备约0.153秒、模型加载0.305秒、ASR推理3.487秒。上述为子阶段墙钟，不是整轮交互耗时。

识别后在 transcribe 节点暂停，SQLite 的 next_nodes 为 group_sentences。接着用 resume 命令继续，只有分组、校验和导出执行，未重复下载或ASR。完成后再次 resume，也没有新增识别执行；日志中 transcribe 完成次数为1。

输出18个原始片段、148个词、11个候选分组。音频、原始英文和词时间与既有样片参考匹配，才重放参考分组。结果处于 ready_for_human_review，不是准确率或全流程科研结论。

证据：[节点事件](../jobs/B-LangGraph-MIT-20261107-01/events.jsonl)、[SQLite旁的状态报告](../jobs/B-LangGraph-MIT-20261107-01/run-status.json)、[ASR记录](../jobs/B-LangGraph-MIT-20261107-01/asr/execution.json)、[校验](../jobs/B-LangGraph-MIT-20261107-01/validation.json)、[首次下载失败摘要](../jobs/B-LangGraph-MIT-20261107-01/initial-failure-record.json)。checkpoints.sqlite、阶段缓存、冻结输入、源码快照、样片及音频保留在任务目录。

## 本地文件流程

独立任务：[B-LangGraph-local-auto-20261107-01](../jobs/B-LangGraph-local-auto-20261107-01/evidence-summary.json)。使用已登记本地样片，无网络、无专用分组方案，实际跑完同样的节点。得到18段、148词、11个通用规则候选分组；ASR加载0.335秒、推理3.217秒。

运行本地路线是为了验证不同素材入口与通用分组，不是根据同一视频成绩挑选更好的模型。两条路线模型和主要推理参数相同；没有进行识别准确率对照评测。

## 测试与返工

全套21项检查通过、0跳过：[原始测试日志](../jobs/B-LangGraph-MIT-20261107-01/tests.stderr.txt)、[测试执行记录](../jobs/B-LangGraph-MIT-20261107-01/tests-result.json)。运行器报告0.735秒，不包括子进程启动及其他处理。

覆盖既有媒体/时间轴10项、分组不变量5项、新增来源许可/范围/陌生链接拒绝、原始词追踪、未知说话人策略与真实LangGraph非法结果路由6项。非法结果路由用模拟校验结果触发，不能称为真实ASR错误样片评测。

首轮新增6项检查有1项失败：标准化输出与原始词对象共享引用，修改一方可能影响另一方。已用独立深拷贝修正，再跑6项通过，最后全套21项通过。真实样片和源站失败记录保留，没有为选最优结果重复模型实验。

review.html 的脚本语法、视频相对路径、输出数量及 load_timetable 加载都已检查；没有宣称完整浏览器交互或所有台词时间经过人工验收。

## 交付状态与限制

- 已实现来源登记选择、链接节选下载、本地媒体、ASR、原片段保留、句子分组、结构化导出、条件路由及SQLite暂停恢复。
- 已提供 run_b / resume_b / build_b_graph / load_timetable 和 list_sources / select_source 接口；配置字段、状态与错误见接口文档。
- B子图已运行，全队翻译、审校、配音、编辑与成片主图尚未在本地接入；不能称完整多智能体项目完成。
- 未运行自动说话人区分；SPEAKER_00为单人假设。文字、边界、分组尚未对本轮每条结果人工确认。
- 当前限制短样片≤120秒，长视频与多说话人是后续工作；没有租GPU、运行训练或开启付费服务。
- 付费API调用0，费用0；显存未测/CPU未用GPU，本地电费与网络费unknown。整轮交互耗时unknown。
- 安装/下载按权限流程执行，未要求用户额外人工处理登录或环境配置；DeepSeek未参与。
- 未提交/推送远程。已记录运行代码指纹与源码快照，不把当前main基础提交当成本轮业务代码提交。

素材使用与分发遵守 MIT OCW 的 CC BY-NC-SA4.0，保存署名、修改说明和原课偏移。jobs/、models/、media/、.tools/均在忽略范围，队友需用命令本地重现或通过团队授权空间获取产物。
