# b_environment：主图增量环境音

节点入口 `from nodes.b_environment import b_environment`，仅由 F 主图在 asr_diarize 后调度，与 C 主链并行。输入为 GraphState，返回 environment_audio 增量；不修改源台词、时间轴或基础音轨。

配置 config/b_environment.toml；权重本地预备，不自动下载。模型、失败回退、数据字段和跨组修改统一见 [对接文档](../localize_video/HANDOFF-20261117.md)。2026-11-17 按用户要求启用真实处理，config/mock.toml 中 b_environment=false；仍由 F 注册与代理调度。

tests/nodes/b_environment 为节点测试；tests/smoke/test_environment_pipeline.py 覆盖主图汇合及增量失败后真实 FFmpeg 合成；tests/smoke/test_background_local_models.py 是显式选择本地视频后的真实模型验证。19秒样本本地 Demucs、AST 和混音已跑通，未证明整片质量或长片耗时。

工作方式：Demucs 在整条音轨上分离背景，包括人在说话期间的背景，并非只截取停顿。AST 仅检查已识别句子之外的间隙，保守回添笑声等非语言事件；与台词重叠的笑声可能被排除，唱歌或残留人声也无法保证完全消除。不是仅凭语义完美分离所有说话声。

本地准备：uv sync --locked --extra b-asr --extra speech --extra sound-events。权重为 models/background-demucs/torchaudio/models/hdemucs_high_trained.pt，事件模型为 models/ast-audioset/model.onnx 及 config.json。WebUI 对应节点可调路径、设备、事件阈值、对白保护间隔和非语言增益。无需背景音云 API，不上传音频。
