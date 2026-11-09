# 基于多智能体协作的英文视频本地化系统

七人课程团队项目。计划用 LangGraph 把英语视频转写、翻译审校、分角色配音和成片制作串成一个可回退、可续跑的工作流。

**当前阶段：项目启动。** 先冻结接口并用模拟响应跑通工作流，随后接入真实模型，最后用已授权视频验收。

**B 阶段成果（2026-11-09）**：[代码与交接入口](docs/B-README.md) · [可发微信群的进度](docs/B-WeChat-progress-20261109.md) · [F 最新接口适配差异](docs/B-F-interface-review-20261109.md)。B 独立流程已做长视频验证，统一节点适配与 C/D/F 联调尚未完成。下方保留各阶段记录，最新状态以上述交接入口为准。

**B 最新接口 V2（2026-11-07）：完整本地视频 / YouTube 单视频 → LangGraph → 按句整理的英文与最终时间戳。** 上限两小时，初次识别不切音频块，新任务不保存原始 ASR 分段和词时间。已加入残句局部复识别和可选 --diarize 真实说话人区分，完整课堂已运行；团队主图、D 联调及共享接口验收尚待完成。

- [B V2 使用与对接说明](docs/B-sentence-v2.md) · 当前入口、逐句 schema、自动审查与恢复限制
- [语义拆分与 DeepSeek 审查接口](docs/B-semantic-review.md) · 长句不只按句号判断，外部调用预算、真实小样与 VideoCaptioner 调研
- [新版 43 分钟长视频验证](docs/B-semantic-long-validation-20261107.md) · 654 条、最长合并修正、无漏词对照；全片语义审查尚待完成
- [疑似残句音频复识别](docs/B-audio-recheck-20261107.md) · 实际检查 65 处，暂修订 5 处，含第 416 条；60 项测试通过
- [真实说话人区分](docs/B-real-diarization.md) · sherpa-onnx 本地模型，双人样音与完整课堂已运行；共享接口和 D 联调待后续验证
- [真实双人访谈视频验证](docs/B-two-person-video-validation-20261108.md) · 连续三分钟真实问答，两模式对照；发现已知人数聚类缺陷，尚未通过准确性验收
- [边界重叠归属更新](docs/B-speaker-boundary-update-20261108.md) · 第 49/64/65 条已归给主要说话人并保留提示；73 项测试通过，附更新模型候选
- [Community-1 本地试跑](docs/B-community1-trial-20261108.md) · 已授权下载并实测：三分钟访谈自动 2 人、59 条归属/6 条未知，保留新旧对照与残留问题
- [当前整句多数归属规则](docs/B-speaker-majority-policy-20261108.md) · 按最新要求忽略边界冲突；同一访谈 65 条均获得编号，78 项测试通过，尚未人工确认准确性
- [YouTube 完整多人长视频验证](docs/B-long-multiperson-YouTube-20261108.md) · 实测 80 分 47 秒圆桌/采访节目，Community-1 GPU，901 条中 883 条归属；保留 18 条未知及质量问题，待人工验收
- [B V2 真实运行记录](docs/B-sentence-v2-run-20261107.md) · 完整 YouTube 素材与单次全片识别证据

下面的 B 初版文档保留为历史方案；其中“音频分块、原始词时间、额外句子分组”等行为已由 V2 取代，不作为当前默认入口。

- [B LangGraph 已实现接口与命令](docs/B-LangGraph-API.md) · 素材范围接口、台词表接口、真实运行结果和F接入方式
- [B LangGraph 运行证据](docs/B-LangGraph-run-20261107.md) · 21项检查通过，含失败恢复与局限
- [B 长视频扩展](docs/B-long-video.md) · 完整文件断点下载、按音频块识别、全片时间映射与块级恢复
- [43分钟完整课程实测成果](docs/B-long-video-run-20261107.md) · 已下载并识别全课；674段、6,774词、480候选分组，33项检查通过

- [整体项目规划书](docs/project-plan.md) · 项目范围、七人分工、接口、10 天排期和课堂汇报
- [开发环境](docs/development.md) · 安装依赖并验证字幕、封面与成片工具
- [成员工作记录](docs/roles/README.md) · A–G 的分工、交接和进度
- [B 模块执行计划与团队交接](docs/B-execution-plan.md) · 按新版分工整理的本地草案，含 CLI/集成边界、接口提案与阶段验收
- [B 接口提案](docs/B-interface-proposal.md) · 可直接用于组内讨论的简版提案
- [B 详细对接方案](docs/B-integration-spec.md) · 数据字段、调用职责、异常、缓存与联调验收；尚待团队冻结
- [B 接口与对接方案 PDF](output/pdf/B-interface-and-integration-v0.1.pdf) · 群内分享版，含提案、详细方案与人工 JSON 样例
- [B 本地媒体准备工具](docs/B-local-tools.md) · 独立环境检查、媒体检查、音频提取与素材登记模板，不依赖共享接口冻结
- [B 本地工作完成记录](docs/B-local-progress-20261107.md) · 合成媒体 10 项检查通过，含真实证据、失败记录与剩余限制
- [MIT 英文教学测试片](docs/B-MIT-test-sample.md) · 已下载约 45 秒真实课堂视频，附许可、署名与音频验证记录
- [真实英文转写与人工核对](docs/B-ASR-review-20261107.md) · 已完成本地 ASR，18 个分段、148 个词时间戳；说话人为单人假设，待人工核对
- [句子分组与 LangGraph 接入](docs/B-sentence-grouping-and-LangGraph.md) · 保留18段，新增11个候选分组；附模型说明和F接入步骤
- **Issues** · 领任务、更新进度和记录阻塞
- **Milestones** · D3 模拟闭环、D5 真实模型联调、D10 成果与汇报

组员加入后先读规划书，在对应 Issue 用 A–G 角色代号认领任务。A 主要负责理解整体方案、准备讲稿并独立上台展示。B–F 分工开发与联调。G 独立制作和整合 PPT，其他成员提交各自模块的证据和素材。

全员在本地 `main` 开发。先提交本地修改，再运行 `git pull --rebase origin main`，同步后运行 `git push origin main`。遇到冲突时先在本地解决。
