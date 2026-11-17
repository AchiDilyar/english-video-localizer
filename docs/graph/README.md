> 2026-11-17 修订：以下联调记录为历史资料，不作现行拓扑/配置依据。唯一主图及新并行背景链以 [workflow.md 第4节](../design/workflow.md) 为准；[节点对齐及回退说明](../nodes/localize_video/HANDOFF-20261117.md)。不再提供独立 BCDE 运行图。

# F 主图与 B→C 接口联调

2026-11-13。按当前 design v1.5.0 的基本版连接节点，不修改共享 schema、业务节点名或设计文档。

## 主图入口

```python
from contracts import GraphState
from graph import build_graph

app = build_graph()
# 由 CLI 事先设置工作目录、创建子目录、初始化日志后再调用
result = app.invoke(GraphState(input_video="input.mp4"))
```

源码导入以 project 为模块根目录。graph 包只公开 build\_graph；registry.py 从 F 的 config/mock.toml 逐节点选择真实/模拟函数，未列出的节点默认真实，并按 `graph/incremental.py` 的 `INCREMENTAL_NODE_NAMES` 对增量节点应用异常隔离代理。不存在节点内部的模拟切换，也不提供第二套命令参数覆盖 mock 配置。**build\_graph() 不接受任何参数；阶段停点、续跑不在基本版范围。**

连接顺序：probe\_input → asr\_diarize → build\_blocks → translate\_blocks → review\_blocks。之后 tts\_align 与 subtitle\_cover 并行；compose\_video 等待 tts\_align 与 subtitle\_cover，完成后进入 END。等待边保证汇合节点只执行一次。

异常行为按 `workflow.md` 第 3 节“版本归属”列区分：基础版节点异常直接抛出，图终止，CLI 非零退出，不自动重试或切换模型（`architecture.md` 8.1）；增量节点异常由 graph/ 层代理捕获，记录 warning 日志、返回空增量、图继续执行（`architecture.md` 8.2）。代理位于 `graph/incremental.py`，`builder.py` 与 `cli.py` 不感知节点是基础版还是增量。当前 `INCREMENTAL_NODE_NAMES` 为空，8 个节点均为基础版，全部按 8.1 处理；新增增量节点时需同步 `workflow.md`、`NODE_NAMES`、`INCREMENTAL_NODE_NAMES`、`WORKFLOW_EDGES` 与 `mock.toml`。代理只保证异常不外抛并返回空增量，不负责回滚节点内部原地修改或已写磁盘文件。

当前 mock.toml 由 F 维护：probe\_input、asr\_diarize、build\_blocks、translate\_blocks、review\_blocks 为 false（真实实现）；tts\_align、subtitle\_cover、compose\_video 为 true（模拟实现）。

D/E 尚缺的真实节点不在本次实现；将其开关改为 false 而没有实现时，会明确导入失败。

正式启用真实 B/C 时，由 F 在 mock.toml 将上述五个节点设为 false，并准备本地模型、b-asr/speech extras、C 的模型配置和调用授权。未准备的尾段继续保持模拟，验收只覆盖到审校产物。本次没有新增付费调用。

## B→C 阶段验证

v1.2 的阶段验证使用过 `interrupt_after`，v1.3 已移除该参数。当前测试通过无参 `build_graph()` 运行正式图，在测试内选择真实 B/C 节点、F 的 config/paths/io 和尾段 mock。使用真实 FFmpeg 探测和提取音频。B 复用真实预测的缓存，C 使用人工固定响应，全程无需调用 DeepSeek。

断言覆盖共享 segments → blocks → translated\_blocks → reviewed\_blocks 的读写、状态字段与片段关联，并检查源英文、speaker\_id 和毫秒时间。审校后的节点返回空增量，未执行实际配音、合成或生成成片。

定向返工暂不接入默认主图。现行 workflow 明确排除退回分支；C 的 find\_review\_issues / should\_repair / repair\_segments 保留供后续由 F 确认接入时机，未擅自加状态字段或循环。

## 真实短片交付

+   tests/data/asr\_diarize/real\_dialogue/input.mp4：14 秒，约 0.72 MB，符合小测试样例可提交要求。
    
+   同目录 segments.json：11 条、两个匿名说话人，严格通过共享 Segment 校验。
    
+   provenance.json、ATTRIBUTION.txt：来源 ConversationEDU，Commons 的 Interview with Steve Wozniak，CC BY 3.0；原视频 00:10–00:24，修改及哈希已记录。
    
+   台词与标签从此前 B-community1-majority 任务导出，并非本次重新 ASR；未完成人工确认，不当作英文/人物真值。
    
+   tests/data/graph/b\_c\_dialogue/responses.json 是人工编写的接口测试响应，不冒充模型译文。
    

本机实际阶段输出位于 tests/tmp/B-C-F-dialogue-handoff-20261110，含共享 segments、blocks、translated\_blocks、reviewed\_blocks、source.wav 与检查记录；该目录不提交。D 可用 reviewed 的 zh\_dub 加 segments 的时间窗验证配音，E 可用 zh\_subtitle 与 segments 的 text\_en/时间生成双语字幕。使用前需确认译文只是固定测试内容，不能作为真实翻译质量验收。

## 验证命令

```powershell
uv run --locked pytest tests/graph
uv run --locked --extra b-asr pytest tests/graph
uv run --locked --extra b-asr pytest tests
```

2026-11-10 历史实测（interrupt\_after 存在时）：图相关 7 项通过（1.06 秒）；真实短片阶段产物导出单项通过（0.82 秒）；uv Python 3.11 下全仓库 174 通过、2 默认跳过、11 子测试通过（7.20 秒）。日志分别为 tests/tmp/B-C-F-graph-first.log、B-C-F-dialogue-handoff-20261110.log、B-C-F-full-20261110.log。没有修改 C 的算法、F 的 mock.toml、共享契约或设计规范。DeepSeek 调用数为 0。