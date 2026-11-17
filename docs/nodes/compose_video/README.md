# 成片背景音与混音

运行统一通过 F 主图，见 [工作流第4节](../../design/workflow.md)。b_environment 与 C 主链并行，mix_background 等待背景与最终字幕，compose_video 最后执行。

- B 正式入口：nodes.b_environment.b_environment，分离全片非人声声部，并保守恢复语音区间以外的笑声等事件。参数在 config/b_environment.toml。
- E 正式入口：nodes.mix_background.mix_background，中文增益1.0、背景默认0.7、轻度压低背景、限幅与滤镜延迟补偿。参数在 config/mix_background.toml。
- compose_video 只在当前 State.mixed_audio 有效且摘要匹配时消费 mixed_track；缺失、陈旧或损坏时警告并用 dub_audio，不会仅因旧文件存在就阻断。
- 原中文 dub.wav 不覆盖，字幕继续依据纯中文最终配音生成。媒体和回执通过公共产物名称获取；回执在 State 传递。

F 当前默认将两个背景节点设为模拟；真实运行需 F 配置及本地 Demucs/AST 权重、speech/sound-events 依赖。模型不自动下载，音频不外发。声音分离并非完美，句中笑声可能保守舍弃。

[产物及 API 详细对接](../localize_video/HANDOFF-20261117.md)
