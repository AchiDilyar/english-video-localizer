# 基于多智能体协作的英文视频本地化系统

七人课程团队项目。计划用 LangGraph 把英语视频转写、翻译审校、分角色配音和成片制作串成一个可回退、可续跑的工作流。

**当前阶段：项目启动。** 先冻结接口并用模拟响应跑通工作流，随后接入真实模型，最后用已授权视频验收。

**B 节点（已按 architecture v1.2.0 整理）**：[probe_input](docs/nodes/probe_input/README.md) · [asr_diarize](docs/nodes/asr_diarize/README.md) · [迁移与验证记录](docs/nodes/asr_diarize/B-layout-v1.2.0.md)。两个入口为 `nodes.probe_input.probe_input` 和 `nodes.asr_diarize.asr_diarize`。测试统一使用 `uv run --extra b-asr pytest tests/nodes`；F 的公共工具已实现，B 已增加真实 utils 联调用例；完整主图联调另行验收。

- [整体项目规划书](docs/project-plan.md) · 项目范围、七人分工、接口、10 天排期和课堂汇报
- [开发环境](docs/development.md) · 安装依赖并验证字幕、封面与成片工具
- [成员工作记录](docs/roles/README.md) · A–G 的分工、交接和进度
- **Issues** · 领任务、更新进度和记录阻塞
- **Milestones** · D3 模拟闭环、D5 真实模型联调、D10 成果与汇报

组员加入后先读规划书，在对应 Issue 用 A–G 角色代号认领任务。A 主要负责理解整体方案、准备讲稿并独立上台展示。B–F 分工开发与联调。G 独立制作和整合 PPT，其他成员提交各自模块的证据和素材。

全员在本地 `main` 开发。先提交本地修改，再运行 `git pull --rebase origin main`，同步后运行 `git push origin main`。遇到冲突时先在本地解决。
