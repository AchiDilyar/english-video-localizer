# 测试数据

- `probe_input/`：固定 ffprobe JSON；媒体测试现场生成合成音视频。
- `asr_diarize/`：固定句子、历史手工/模拟例子、旧素材登记模板、语义分界反例；单文件小于 1 MB。

`asr_diarize/segments.json` 是通过共享 Segment 契约的无密钥固定输出，供 F/C/D 对接；英文来自人工合成例子，不冒充真实识别。`node-sentences.json` 是同一例子的 B 内部输入结构。
- `_large/asr_diarize/`：负责人本地提供的授权视频/音频/完整任务副本，整个目录忽略。普通回归不依赖它。MIT 来源与许可见 docs/nodes/asr_diarize/B-MIT-test-sample.md。

旧 registry 本地样例指向 `_large/asr_diarize/mit_lecture1_0060_0105.mp4`。历史真实 DeepSeek 响应只提取公开 tokens 和分界结果到 semantic-boundary.json，不带凭据或调用元数据；测试不会重新调用 API。

现场生成的文件和日志放 `tests/tmp/`，不放本目录或历史 jobs。不要提交私人视频和凭据。

`asr_diarize/real_dialogue/` 提供可共享的 14 秒双人短片（约 0.72 MB）、11 条真实机器预测分段和 CC BY 3.0 来源记录；这是对视频忽略规则的单文件例外。`graph/b_c_dialogue/responses.json` 是人工固定的中文接口响应，供 F 主图联调，不是实际 DeepSeek 译文或人工验收真值。
