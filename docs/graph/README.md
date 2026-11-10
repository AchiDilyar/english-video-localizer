# F 主图与 B→C 接口联调

2026-11-10。按当前 design v1.3.0 的基本版连接节点，不修改共享 schema、mock.toml、业务节点名或设计文档。

## 主图入口

```python
from contracts import GraphState
from graph import build_graph

app = build_graph()
# 由 CLI 事先设置工作目录、创建子目录、初始化日志后再调用
result = app.invoke(GraphState(input_video="input.mp4"))
```
源码导入以 project 为模块根目录。graph 包只公开 build_graph；registry.py 从 F 的 config/mock.toml 逐节点选择真实/模拟函数，未列出的节点默认真实。不存在节点内部的模拟切换，也不提供第二套命令参数覆盖 mock 配置。**build_graph() 不接受任何参数；阶段停点、续跑不在基本版范围。**

连接顺序：probe_input → asr_diarize → build_blocks → translate_blocks → review_blocks。之后 tts_align 与 edit_assets 分支；subtitle_cover 等待 review_blocks 和 edit_assets；compose_video 等待 tts_align 与 subtitle_cover，再进入 collect_manifest → package_zip。等待边保证汇合节点只执行一次。异常向上传播，不自动重试或切换模型。

当前 mock.toml 仍由 F 维护，全部开关保持原值 true；现有 mock 只返回空增量。**主图可构建和模拟流转不等于能产出 ZIP。** D/E/F 尚缺的真实节点不在本次实现；将其开关改为 false 而没有实现时，会明确导入失败。

正式启用真实 B/C 时，由 F 在 mock.toml 将上述五个节点设为 false，并准备本地模型、b-asr/speech extras、C 的模型配置和调用授权。未准备的尾段继续保持模拟，验收只覆盖到审校产物。本次没有修改这些开关，也没有新增付费调用。

## B→C 阶段验证

v1.2 的阶段验证使用过 `interrupt_after`，v1.3 已移除该参数。当前测试通过无参 `build_graph()` 运行正式图，在测试内选择真实 B/C 节点、F 的 config/paths/io 和尾段 mock。使用真实 FFmpeg 探测和提取音频。B 复用真实预测的缓存，C 使用人工固定响应，全程无需调用 DeepSeek。

断言覆盖共享 segments → blocks → translated_blocks → reviewed_blocks 的读写、状态字段与片段关联，并检查源英文、speaker_id 和毫秒时间。审校后的节点返回空增量，未执行实际配音、合成或打包。

定向返工暂不接入默认主图。现行 workflow 明确排除退回分支；C 的 find_review_issues / should_repair / repair_segments 保留供后续由 F 确认接入时机，未擅自加状态字段或循环。

## 真实短片交付

- tests/data/asr_diarize/real_dialogue/input.mp4：14 秒，约 0.72 MB，符合小测试样例可提交要求。
- 同目录 segments.json：11 条、两个匿名说话人，严格通过共享 Segment 校验。
- provenance.json、ATTRIBUTION.txt：来源 ConversationEDU，Commons 的 Interview with Steve Wozniak，CC BY 3.0；原视频 00:10–00:24，修改及哈希已记录。
- 台词与标签从此前 B-community1-majority 任务导出，并非本次重新 ASR；未完成人工确认，不当作英文/人物真值。
- tests/data/graph/b_c_dialogue/responses.json 是人工编写的接口测试响应，不冒充模型译文。

本机实际阶段输出位于 tests/tmp/B-C-F-dialogue-handoff-20261110，含共享 segments、blocks、translated_blocks、reviewed_blocks、source.wav 与检查记录；该目录不提交。D 可用 reviewed 的 zh_dub 加 segments 的时间窗验证配音，E 可用 zh_subtitle 与 segments 的 text_en/时间生成双语字幕。使用前需确认译文只是固定测试内容，不能作为真实翻译质量验收。

## 验证命令

```powershell
uv run --locked pytest tests/graph
uv run --locked --extra b-asr pytest tests/graph
uv run --locked --extra b-asr pytest tests
```

基础环境缺少 NumPy 时会跳过 tests/graph/test_b_c_integration.py。设置 B_C_F_OUTPUT_DIR 为 tests/tmp 下尚不存在的目录可保留阶段产物；普通 pytest 自动创建临时目录。

2026-11-10 历史实测（interrupt_after 存在时）：图相关 7 项通过（1.06 秒）；真实短片阶段产物导出单项通过（0.82 秒）；uv Python 3.11 下全仓库 174 通过、2 默认跳过、11 子测试通过（7.20 秒）。日志分别为 tests/tmp/B-C-F-graph-first.log、B-C-F-dialogue-handoff-20261110.log、B-C-F-full-20261110.log。没有修改 C 的算法、F 的 mock.toml、共享契约或设计规范。DeepSeek 调用数为 0。