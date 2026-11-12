# tts_align 节点说明

`workflow.md` 第 3 节的 `tts_align`，负责 D 角色的配音与同步。

**职责**：按说话人音色合成中文口播音频，测时长并对齐原时间窗，组装整条中文配音音轨。

## 输入与输出

| 方向 | 内容 |
|---|---|
| 读 `state.reviewed_blocks` | 取 `zh_dub` 作为口播稿 |
| 读 `state.segments` | 按 `segment_id` 取 `start_ms` / `end_ms` / `speaker_id` |
| 写 `tts/<segment_id>.wav` | 逐段中文口播音频，文件名即 `TTSClip.audio_path` |
| 写 `tts/clips.json` | 分段音频清单，`list[TTSClip]` |
| 写 `audio/dub.wav` | 组装后的整条中文配音音轨 |
| 返回增量 | `{"tts_clips": [...]}` |

节点签名与失败行为遵循 `architecture.md` 第 3 节与第 8 节：内部异常直接抛出，图终止，不捕获、不降级。

## 配置

配置在 `config/tts.toml`，由 D 维护。音色映射是配置项（`workflow.md` 第 3 节），改配置不需要改代码。

| 键 | 说明 |
|---|---|
| `model` | 合成模型标识，原样写入 `TTSClip.model` |
| `sample_rate` | 逐段音频与 `dub.wav` 的采样率，默认 24000（CosyVoice 原生） |
| `voices` | 音色池，按说话人首次出现顺序依次分配 |
| `unknown_speaker` | 未知说话人的 `speaker_id`，默认 `spk_unknown`；该值固定用 `fallback_voice` |
| `fallback_voice` | `unknown_speaker` 固定使用的音色，不占音色池名额 |
| `[overrides]` | 手工指定 `speaker_id -> voice_id`，优先级最高 |

### 为什么用"音色池 + 手工覆盖"而不是逐个 speaker_id 写死

B 的长视频验证出现过"14 个模型声音组不等于人工确认的 14 个真人"的情况。若 pyannote 把一个人拆成两个 `speaker_id`，逐个写死的映射会给同一个人配两个音色，直接影响"同一人音色一致性"验收。

- **音色池**保证任意数量的说话人都能自动拿到音色，双人素材天然是两种音色；
- **`[overrides]`** 让人工回听确认后，把过分割的两个 ID 指到同一音色即可合并，不用改代码；
- **`spk_unknown`** 走独立兜底音色，不占用音色池，避免"为了接口非空随意指派某个人"，且实际用的音色如实写入 `TTSClip.voice_id`，可事后审计。

## 时长对齐

1. 合成音频实测时长；
2. 短于时间窗 → 尾部补静音；
3. 超时 → `atempo` 加速，上限 **1.15 倍**；
4. 加速后仍超时 → 裁剪到时间窗，并写 `WARNING` 日志列出被裁剪的片段。

`workflow.md` 第 5 节明确"配音超时退回"不在基本版范围，因此本节点**不实现返工分支**，也不新增任何状态字段。超时信息目前只通过日志留痕；若后续要把"哪一段需要重写"传回主图，必须走 `CHANGELOG.md` 流程加契约字段。

## 音轨组装

`dub.wav` 采用"静音填充 + 按 `start_ms` 顺序拼接"，而不是 `adelay` + `amix`：

- 复杂度 O(n)，长视频（数百段）不会因为同时打开大量输入而耗尽资源；
- 每段都已被裁剪到恰好等于时间窗长度，因此摆位是精确的；
- 段与段重叠时后一段覆盖前一段的重叠部分并记录 `WARNING`。B 生成的 `segments` 实测不重叠。

## 目录职责

节点**不创建任何目录**（`dataflow.md` 第 4 节），`tts/`、`audio/` 由 CLI 初始化时创建。节点只在系统临时目录放合成中转文件，返回前清理。

## 测试

```bash
uv run --locked pytest tests/nodes/tts_align
```

18 项，覆盖音色映射（首次出现顺序、同一说话人一致、`spk_unknown` 兜底、override 优先、音色池复用、非法配置）、时长对齐（补静音、无需变速、超时裁剪、零时间窗）、节点整体行为（三个产物落盘、`clips.json` 通过契约校验、`dub.wav` 首段之前为静音、空输入返回空增量、缺 `segments` 与错位 `segment_id` 抛异常）。

测试用假合成器替代真实 TTS，**不需要 `DASHSCOPE_API_KEY`**；需要 `ffmpeg`（加入 PATH 或设置 `LOCALIZER_FFMPEG`），缺失时自动跳过依赖 ffmpeg 的用例。

## 接入真实 TTS

`project/nodes/tts_align.py` 的 `synthesize_clip()` 调用 DashScope CosyVoice：

1. `.env` 中配置 `DASHSCOPE_API_KEY`（见 `.env.example`）；
2. `uv sync --locked --extra speech` 安装 `dashscope`；
3. F 在 `config/mock.toml` 把 `tts_align` 改为 `false`。

**当前状态**：真实合成调用尚未用密钥验证，需要一次带凭据的双人短片实测确认音色一致性与实际时长分布。

## 待确认

- `dub.wav` 采样率定为 24000Hz 单声道，需与 E 的 `compose_video` 对齐；E 若要求其它规格，改 `config/tts.toml` 的 `sample_rate` 即可。
- 未知说话人的最终表示（`spk_unknown` 是否为合法 `speaker_id`）仍挂在 `docs/design/increments/README.md` 的"待解决的契约问题"，需与 F、B 共同确认。本节点已按"允许 `spk_unknown`"实现，不依赖该结论也能工作。
