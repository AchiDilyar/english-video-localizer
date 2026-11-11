# smoke 测试

从仓库根运行：

```bash
uv run pytest tests/smoke
```

无需 FFmpeg、ASR 模型、Community-1、API key，也不发起任何外部调用。

## 覆盖

| 文件 | 覆盖内容 |
| --- | --- |
| `test_c_chain.py` | C 三节点（`build_blocks → translate_blocks → review_blocks`）在 `segments.json` 输入上的成功路径：三个 JSON 产物落盘、`read_artifact` 反读通过、`segment_id` 顺序不变、`TranslationBlock` 用 `block_id`；1 个失败路径：LLM 返回缺 ID 时 `validate_items` 抛 `ValueError`，`translated_blocks.json` 与 `reviewed_blocks.json` 均未写出 |

## 边界

+   **不进图**：按联调决策，smoke 只覆盖 C 子链，不调用 `build_graph()`，不触发 B 真实节点，不依赖 FFmpeg、faster-whisper、Community-1 或 API key。
    
+   **不改 `config/mock.toml`**：若未来 smoke 扩为“全图 B+C”并走 `build_graph()`，用 `monkeypatch` patch `graph.registry.load_config` 返回自定义 flags，不修改 `config/mock.toml`。当前设计不走图，此方案暂不启用。
    
+   **LLM 边界替身**：`conftest.llm_stub` patch `nodes.translate_blocks._text_model.request_json`。阶段 3 已证该模块对象同时被 `translate_blocks` 与 `review_blocks` 使用。若 C 改为直接 `from ... import request_json`，替身会失效；`test_c_chain_produces_readable_artifacts` 中 `calls["review"] >= 1` 会暴露。
    
+   **不验收**：C 的真实 DeepSeek 调用、B 真实节点、D/E 产物、最终 ZIP。这些留到 D/E 真实接入后的端到端验收。
    

## 输入

`tests/data/asr_diarize/real_dialogue/segments.json`，由 B 提供，已验证可通过 `list[Segment]` 校验。smoke 不把它当作 B 的“预期产物”，只作为 C 子链的合法输入。

## 临时工作目录

每个测试用 `tmp_path` 下的独立 `work/`，通过 `set_work_dir` 设置全局工作目录；不写 `tests/tmp/`，不污染其他测试。

## 维护

`tests/smoke/` 由 F 维护（`architecture.md` 9.1）。C 的 `validate_items` 四模式测试由 C 放 `tests/nodes/`；B 的严格失败条件测试由 B 在 `tests/nodes/asr_diarize/` 维护，smoke 不重复。

```bash
uv run pytest tests/smoke -v
```

预期 2 个测试 PASS：

+   `test_c_chain_produces_readable_artifacts`
    
+   `test_c_chain_fails_when_llm_missing_id`