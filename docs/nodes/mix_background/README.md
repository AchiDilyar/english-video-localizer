# mix_background：主图增量混音

节点入口 `from nodes.mix_background import mix_background`。F 主图等待字幕与 b_environment 后调度，返回 mixed_audio 增量。缺少 environment_audio 时返回 {}；其他异常由 F 代理隔离。

配置 config/mix_background.toml。dub.wav 保持纯中文，mixed.wav 独立发布。compose_video 没有当前有效 mixed_audio 时使用纯配音，磁盘旧文件不能替代状态。详见 [对接文档](../localize_video/HANDOFF-20261117.md)。

测试位于 tests/nodes/mix_background 与 tests/graph/test_environment_pipeline.py。
