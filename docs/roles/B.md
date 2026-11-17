# B · 素材与语音识别

**交付物**为本地 MP4 和登记链接入口、命令行输入参数、英文转写及说话人时间轴。

- [ ] 向 F 提供无密钥的模拟分段及错误输入样本。
- [ ] 联调素材登记、授权地址和两种输入方式。
- [ ] 接入转写与说话人区分，验证一至两位说话人的毫秒时间戳。
- [x] 记录主样片和压测样片的授权来源、时长及输入方式。

**交接**给 C、D、F 提供稳定的片段 ID、说话人 ID、起止时间和英文文本，给 E 提供可读的原视频及时间轴。

## 下一版实施计划

- [ ] 提供同一任务的原视频、所选音轨信息和 `segments/segments.json`，保证 `segment_id`、`speaker_id`、`start_ms`、`end_ms` 和 `text_en` 能回到原片的同一条时间轴。
- [ ] 给 D 标出每位说话人清晰、连续且无重叠的候选参考片段，并提供对应英文文本。对未知说话人、串话和强背景声标记复核。D 从对白轨中选取最终参考音频。
- [ ] 保留原音轨的声道和时间信息给 D 分离、混音。保留已有的独立背景轨供 D 使用，同时交付 ASR 需要的音频。
- [ ] 准备可用于音色复刻的授权双人样片，再准备有音乐或环境声的素材，分别验证音色绑定和背景声保留。

## 工作记录

| 日期 | 完成事项 | 证据或文件 | 阻塞与下一步 |
|---|---|---|---|
| 2026-11-10 | 用户授权 B→C→F 接口与主图协作：补齐 registry/builder，提供 14 秒双人短片和 11 条共享分段，审校后阶段导出通过；全仓库 174 通过/2 默认跳过 | [F 主图与交付说明](../graph/README.md)、tests/data/asr_diarize/real_dialogue | B 使用历史真实预测缓存，C 使用固定模型响应；未做新付费调用。定向返工接入时机由 F 确认，D/E 与完整成片仍待验收 |
| 2026-11-10 | 用 uv add 补齐 b-asr/speech/b-legacy 依赖并锁定；Python 3.11 + uv 全仓库 167 通过/2 默认跳过，真实 F utils 和本地 ASR 小样通过 | [验证与待办](../nodes/asr_diarize/validation.md) | 统一依赖已完成；完整主图、uv GPU 实测及未知说话人策略仍分别验收 |
| 2026-11-09 | 对照用户提供五份 v1.2.0 文件复核，修正共享路径传递、子进程日志与测试收集；同步后修复 E 的旧 B 导入，最终全仓库 98 通过/2 默认跳过，真实 ASR 小样通过 | [验证与待办](../nodes/asr_diarize/validation.md) | B 接口检查通过不代表全仓库已完成；F 的公共工具/主图/CLI 与 3.11 联调仍待验收 |
| 2026-11-09 | 按 architecture v1.2.0 迁移 B 代码/文档/测试，提供 probe_input、asr_diarize；完整 pytest 95 通过/2 默认跳过，两项真实模型已单独通过 | [节点说明](../nodes/asr_diarize/README.md)、[迁移记录](../nodes/asr_diarize/validation.md) | F 公共 paths/io/config/artifacts 待实现；未知说话人策略、Python 3.11 与下游联合验收待完成 |
| 2026-11-09 | B 独立 LangGraph 流程、下载、语义分句、局部复识别、Community-1 及整句多数归属已运行；本次 78 项回归测试通过 | [B 交接入口](../nodes/asr_diarize/README.md)、[80 分钟实测](../nodes/asr_diarize/archive/long-video-validation.md)、[F 接口差异](../nodes/asr_diarize/archive/design-evolution.md) | 阶段交付；尚待 F 节点适配、未知说话人策略、Python 3.11 与 C/D/F 联调；不宣称完整准确性验收 |
