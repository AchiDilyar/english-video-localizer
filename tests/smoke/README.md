# smoke 测试

从仓库根运行：

```bash
uv run pytest tests/smoke
```

`test_c_chain.py` 无需 FFmpeg、ASR 模型、Community-1、API key，也不发起任何外部调用。  
`test_full_pipeline.py` 需要 FFmpeg/ffprobe（见下），不发起任何外部模型调用。

## 覆盖

| 文件 | 覆盖内容 |
| --- | --- |
| `test_c_chain.py` | C 三节点（`build_blocks → translate_blocks → review_blocks`）在 `segments.json` 输入上的成功路径：三个 JSON 产物落盘、`read_artifact` 反读通过、`segment_id` 顺序不变、`TranslationBlock` 用 `block_id`；1 个失败路径：LLM 返回缺 ID 时 `validate_items` 抛 `ValueError`，`translated_blocks.json` 与 `reviewed_blocks.json` 均未写出 |
| `test_full_pipeline.py` | 进程内调用 `cli.main` 跑全图：前 5 节点真实、`tts_align`/`subtitle_cover`/`compose_video` mock；断言 `mock.toml` 未漂移、结构化产物可反读且数量/ID 一致、二进制与文本产物非空、`final_video` 经 ffprobe 检出视频流 |

## 边界

+   **C 链不进图**：`test_c_chain.py` 按联调决策只覆盖 C 子链，不调用 `build_graph()`，不触发 B 真实节点。
    
+   **full\_pipeline 进图**：`test_full_pipeline.py` 调用 `cli.main`，走完整 `build_graph()`；后 3 节点由 `mock.toml` 切到 `mocks/`，不修改 `mock.toml`，测试内严格断言其开关值。
    
+   **不改 `config/mock.toml`**：full\_pipeline 只读断言，不写回。若未来扩为其他 mock 组合，用 `monkeypatch` patch `graph.registry.load_config` 返回自定义 flags。
    
+   **LLM 边界替身**：`test_c_chain.py` 与 `test_full_pipeline.py` 均 patch `nodes.translate_blocks._text_model.request_json`。该模块对象同时被 `translate_blocks` 与 `review_blocks` 使用；若 C 改为直接 `from ... import request_json`，替身会失效。full\_pipeline 中翻译路径按 `output_format` 是否含 `"issues"` 区分审计与翻译响应。
    
+   **不验收**：C 的真实 DeepSeek 调用、B 真实节点、D/E 真实产物内容。full\_pipeline 只验证管道结构与 `final_video` 可被 ffprobe 解析，不验证真实合成、配音与字幕内容。
    
+   zh\_dub 已弃用，仅为兼容性保留（str | None，默认 None）。smoke 的 LLM 替身只返回 segment\_id 与 zh\_subtitle，不对 zh\_dub 做任何断言；`tts_align` mock 读取 `zh_subtitle` 作为 `TTSClip.text`。
    

## 输入

+   `test_c_chain.py`：`tests/data/asr_diarize/real_dialogue/segments.json`，由 B 提供，已验证可通过 `list[Segment]` 校验。smoke 不把它当作 B 的“预期产物”，只作为 C 子链的合法输入。
    
+   `test_full_pipeline.py`：`tests/data/asr_diarize/real_dialogue/input.mp4`（14 秒小样，说明见同目录 `README.md`），复制到工作目录根作为 `input.mp4`。
    

## 外部工具（仅 full\_pipeline）

`test_full_pipeline.py` 需要 `ffmpeg`（`compose_video` mock 生成占位成片）与 `ffprobe`（测试校验视频流）。按 `architecture.md` 第 11 节查找：

1.  仓库根 `.tools/ffmpeg/bin/`；
    
2.  系统 `PATH`。
    

两处都找不到时测试 fail，不静默跳过。`test_c_chain.py` 不需要这两个工具。

## 临时工作目录

+   `test_c_chain.py`：每个测试用 `tmp_path` 下的独立 `work/`，通过 `set_work_dir` 设置全局工作目录；不写 `tests/tmp/`。
    
+   `test_full_pipeline.py`：写到 `tests/tmp/test_full_pipeline_<timestamp>/`，保留现场便于排查；`tests/tmp/` 已由 `.gitignore` 排除。
    

## 维护

`tests/smoke/` 由 F 维护（`architecture.md` 9.1）。C 的 `validate_items` 四模式测试由 C 放 `tests/nodes/`；B 的严格失败条件测试由 B 在 `tests/nodes/asr_diarize/` 维护，smoke 不重复。

```bash
uv run pytest tests/smoke -v
```

预期 3 个测试 PASS：

+   `test_c_chain_produces_readable_artifacts`
    
+   `test_c_chain_fails_when_llm_missing_id`
    
+   `test_full_pipeline_with_mocks`（标记 `slow`）
    
---

排查提示：

- full_pipeline 失败时先看 `tests/tmp/test_full_pipeline_<timestamp>/logs/run.log`，再看该目录下缺失的产物路径，测试断言消息会带绝对路径。
- `mock.toml` 断言失败会同时打印实际与预期字典，可直接对照是否为“前 5 真实 + 后 3 mock”。
- ffprobe 失败时断言消息包含 `stderr` 与 `stdout`，可区分“找不到工具”“文件不可解析”“无视频流”。
- 若只跑 C 链：`uv run pytest tests/smoke/test_c_chain.py -v`；只跑全图：`uv run pytest tests/smoke/test_full_pipeline.py -v`。
- 跳过慢测试：`uv run pytest tests/smoke -m "not slow"`。