# D · 配音与同步

**交付物**为说话人音色映射、普通话配音、时长检测、超时反馈及按时间轴组装的中文音轨。

- [x] 用合成 WAV 验证时长不足、可变速对齐。（超时返工按 `workflow.md` 第 5 节不在基本版范围，改为加速到 1.15 倍上限后裁剪并记 `WARNING`）
- [ ] 接入 TTS 并验证双人素材的音色一致性。（代码已接 DashScope CosyVoice，缺 `DASHSCOPE_API_KEY`，尚未实测）
- [ ] 验证续跑时根据文本、模型和音色复用音频。（续跑与 SQLite 检查点按 `workflow.md` 第 5 节不在基本版范围）
- [x] 记录目标时窗、实测时长、对齐处理和超时原因。（`tts/clips.json` 记录实测时长，目标时窗由 `segments` 回溯，裁剪片段写入日志）

**交接**从 C 接收口播稿，向 E 提供对齐后的音轨，向 F 提供超时片段及缓存验证结果。

| 日期 | 完成事项 | 证据或文件 | 阻塞与下一步 |
|---|---|---|---|
| 2026-11-12 | 完成 `tts_align` 节点：音色映射配置化（音色池 + 手工覆盖）、时长检测与 1.15 倍变速对齐、按时间轴组装 `dub.wav`；18 项测试通过，`ruff check` 通过 | `project/nodes/tts_align.py`、`config/tts.toml`、`tests/nodes/tts_align/`、`docs/nodes/tts_align/README.md` | ① 待配 `DASHSCOPE_API_KEY` 做真实 TTS 双人验证；② `dub.wav` 采样率 24000Hz 单声道待与 E 的 `compose_video` 对齐；③ `spk_unknown` 是否为合法 `speaker_id` 待与 F、B 确认（本节点已按允许实现，不依赖该结论） |
