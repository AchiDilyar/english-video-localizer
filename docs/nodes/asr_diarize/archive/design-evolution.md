# 关键设计演变与失败教训（历史摘要）

仅保留影响当前实现的结论，不是现行接口或安装指南。当前要求见 [节点说明](../README.md) 与 [验证与待办](../validation.md)。

## 保留下来的设计决定

- 初版曾按音频块识别、保留原片段/词时间并额外分组；用户后来要求全片识别、只交付语义分段。当前初次识别不外部分块，词时间仅在内存使用，后续局部复识别另计调用。
- 停顿不代表句子边界。spaCy 整理句法/语义单元，长句可按意义拆分；DeepSeek 仅提供可选文字分界审查，不能凭空补词或自行改时间。
- 曾有一次获准的公开课堂台词 DeepSeek 小样。响应形式正确，但分界割裂条件与后文，被本地规则拒绝；模型输出不能直接视为正确结论。后续没有全片付费语义审查。
- 对疑似残句，局部回听范围内用两个解码配置复识别；仅在一致且满足插入、时间和覆盖限制时暂应用修订，仍需人工确认，不以大模型猜词填空。
- 旧 sherpa 双人聚类曾分出多余组，强制两人还曾合并主要声音，失败结果保留。后来试用 Community-1；编号数或“全部分配成功”都不能替代人物准确性验证。
- 按用户要求，整句已检测说话时长超过 50% 的人获得归属，边界少量冲突不单独拒绝；无覆盖、并列或无多数仍未知。
- 共享接口最终统一为 GraphState、MediaInfo、Segment，由 F utils 管理路径与写盘；历史独立 CLI、报告和检查点不进入标准节点调用链。

## 运行与复现教训

- 曾遇到 PyAV 版本兼容问题；当前兼容范围由 uv 声明、版本由 uv.lock 固定，不再维护独立安装清单。
- GPU 长片成功与 CPU 中止尝试分开记录；一次性依赖下载/安装不计入模型推理耗时。
- 测试应复用合成媒体/固定小样，避免依赖本机下载路径。测试临时目录按角色隔离，不清空整个 tests/tmp。
- 当前测试命令统一 uv run；旧裸 Python、pip、旧分组格式与旧命令不作为对接要求。

## 历史素材来源

- MIT OCW 的 Ana Bell《6.0001 Introduction to Computer Science and Programming in Python, Fall 2016》第一课，历史记录许可 CC BY-NC-SA 4.0；[课程资源页](https://ocw.mit.edu/courses/6-0001-introduction-to-computer-science-and-programming-in-python-fall-2016/resources/lecture-1-what-is-computation/)。当时取原片 60–105 秒作早期测试，示例登记仍在 tests/data/asr_diarize 中；分享需保留相应署名和许可。
- ConversationEDU 双人访谈当前小样的来源、许可和裁剪范围保留在 tests/data/asr_diarize/real_dialogue/provenance.json，不在本摘要重复定义。

原始失败日志、源码快照、模型指纹与输出保留在原 jobs 任务中，不因文档精简删除；不重新运行昂贵实验来补记录，也不将历史成功当作当前主图验收。
