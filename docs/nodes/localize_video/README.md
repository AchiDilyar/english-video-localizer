# 历史 BCDE 工具目录（不作为运行入口）

2026-11-17 已按 F 新主图收敛：唯一主图为 project/graph/builder.py，唯一 CLI 为 uv run run-input。

旧 python -m nodes.localize_video 已停用；pipeline.build_bcde_graph 仅弃用转调 F 主图，不创建另一张图，也不接受旧 StageServices 注入。保留的 B/C/D/E 帮助函数和单行字幕工具供既有代码引用，不承诺各阶段可独立构成完整生产流程。

背景分离与非语言声音回添现由 nodes.b_environment 执行；混音现由 nodes.mix_background 执行。它们在 F 主图内运行，异常由统一增量代理隔离。缺少它们的状态数据时基础成片使用纯中文配音。

[完整跨组修改及对接说明](HANDOFF-20261117.md) · [运行说明](../../../README.md) · [主图事实源](../../design/workflow.md)

历史35分钟实验、五分钟样例及中间文件留在本地，原实验 Release 不作本次新主图的全量验证证明。
