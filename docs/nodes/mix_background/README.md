# mix_background：主图增量混音

节点入口 `from nodes.mix_background import mix_background`。F 主图等待字幕与 b_environment 后调度，返回 mixed_audio 增量。缺少 environment_audio 时返回 {}；其他异常由 F 代理隔离。

配置 config/mix_background.toml。dub.wav 保持纯中文，mixed.wav 独立发布。compose_video 没有当前有效 mixed_audio 时使用纯配音，磁盘旧文件不能替代状态。详见 [对接文档](../localize_video/HANDOFF-20261117.md)。

2026-11-17 按用户要求启用真实处理，config/mock.toml 中 mix_background=false。背景增益通过 WebUI 节点参数或 config/mix_background.toml 设置，默认0.7。配音出现时自动压低背景，最终限幅，音轨裁剪/补齐至原视频长度。仅使用通过原片、台词与音轨摘要校验的本次产物。

测试位于 tests/nodes/mix_background 与 tests/smoke/test_environment_pipeline.py。真实本地模型验证见 tests/smoke/test_background_local_models.py，合成中文人声在该测试中由正弦音替身代替，不调用收费配音。
