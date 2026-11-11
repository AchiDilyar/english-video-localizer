# C 审校问题清单与按片段定向返工

## 当前实现

负责人为 C，实现在 `project/nodes/review_blocks.py`。

- `find_review_issues(state)` 逐块对照英文、术语表和当前初稿，返回含 `segment_id`、`reason`、`target` 的 `ReviewIssue` 列表。
- `should_repair(issues)` 判断问题列表是否非空。循环次数和停止条件由调用方负责。
- `repair_segments(state, issues)` 执行一轮局部修复，返回完整的 `list[TranslatedSegment]`。只把问题片段送给模型，并按 `target` 更新字幕、口播或两者。其他片段及未指定字段沿用原结果。

输入使用现有 `GraphState.segments`、`terminology` 和 `translated_blocks`。这些函数不修改输入状态，不写盘，不新增共享契约字段。完成一轮修复后，调用方可将结果作为下一轮 `translated_blocks` 复审。

## 当前主图关系

当前基本版仍使用 `build_blocks → translate_blocks → review_blocks`，由 `review_blocks` 直接产出完整审校译文并调用公共工具写盘。

问题清单和定向返工是独立辅助接口，尚未注册到主图。登记状态为“待接入”，请 F 评估是否保留为独立增量。该状态不表示已获准增加主图分支。

如果后续需要主图自动返工，先由 F 确认其与 `workflow.md` 基本版边界的关系，再明确适配节点、允许的状态增量、逐段次数上限、复审及未解决问题的出口。涉及共享状态字段时按契约与 `CHANGELOG.md` 流程处理。这三个辅助函数不能直接按标准节点注册。

## 验证证据

`tests/nodes/test_review_blocks.py` 提供固定响应测试，覆盖无问题时不请求返工、跨块共用术语表、定位术语不一致和漏译的片段及原因、只修改指定口播、保留其他片段，以及拒绝块外 ID。

从仓库根目录运行 `uv run --locked pytest tests/nodes/test_review_blocks.py -q` 即可复现，不需要模型密钥。

此前真实 DeepSeek 短样本也验证了把“可以继续。”修正为“仅在样本量至少为十二时继续。”，保留该段字幕和另一条片段，复审通过。该结果是独立短样本验证，整片返工仍需 F 决定是否集成。
