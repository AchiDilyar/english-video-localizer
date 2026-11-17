# b_environment：主图增量环境音

节点入口 `from nodes.b_environment import b_environment`，仅由 F 主图在 asr_diarize 后调度，与 C 主链并行。输入为 GraphState，返回 environment_audio 增量；不修改源台词、时间轴或基础音轨。

配置 config/b_environment.toml；权重本地预备，不自动下载。模型、失败回退、数据字段和跨组修改统一见 [对接文档](../localize_video/HANDOFF-20261117.md)。F 当前默认模拟本节点，准备模型后由 F 切换真实实现。

tests/nodes/b_environment 为节点测试；tests/graph/test_environment_pipeline.py 覆盖主图汇合及增量失败后真实 FFmpeg 合成。大模型质量和长片分离耗时不在这些测试的证明范围。
