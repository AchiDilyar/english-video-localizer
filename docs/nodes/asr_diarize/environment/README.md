# B 环境准备

本页集中维护 B 的环境说明；接口见 [节点说明](../README.md)，验证结果见 [验证与待办](../validation.md)。旧的五份独立依赖快照已移除，准确版本只以仓库根 pyproject.toml 和 uv.lock 为准。

## 依赖和安装

团队使用 Python 3.11 和 uv。新增依赖用 uv add（开发依赖用 uv add --dev，可选依赖用 uv add --optional），不使用 pip，不手改 uv.lock。

| 依赖组 | 用途 |
|---|---|
| 默认依赖、dev | 公共工具与基础测试 |
| b-asr | Whisper、PyAV、NumPy、spaCy 英文模型、下载辅助工具及 B 完整测试 |
| speech | Community-1 所需语音依赖，实际运行时与 b-asr 一起启用 |
| b-legacy | 历史 sherpa 后端，非默认识别方案 |

从仓库根目录运行：

```powershell
# B 识别与完整测试依赖
uv sync --locked --extra b-asr
uv run --locked --extra b-asr pytest tests/nodes/asr_diarize tests/nodes/probe_input

# 包含 B 依赖的全仓库测试
uv run --locked --extra b-asr pytest tests

# 实际运行 Community-1 时启用
uv sync --locked --extra b-asr --extra speech
```

默认 uv run pytest 不启用语音 extra 时，相关 B 测试会明确跳过，不能作为完整 B 验证。真实模型测试另需显式启用 B_RUN_REAL_MODELS。

## 本地工具与权重

- FFmpeg/ffprobe：放在 PATH 或仓库 .tools/ffmpeg/bin。多音轨选择见 config/probe_input.toml。
- Whisper：本地模型默认 models/faster-whisper-base.en，可通过 config/asr_diarize.toml 修改。
- Community-1：使用者本人接受 Hugging Face 模型条件后准备权重，默认缓存 models/community-1-hf-cache；节点运行时只读取本地权重，不自动下载或上传音频。
- 下载辅助可能需要本地 Node；网址下载属于素材准备，不在团队标准 ASR 节点内。

community1_python 保持为空，子进程沿用当前 uv 解释器；不切换到手工安装的其他 Python。CPU/CUDA 选择和缓存路径以配置文件为准，不在本文另行维护硬编码版本清单。

模型、虚拟环境、工具二进制和缓存不上传。此前本机用 UV_PROJECT_ENVIRONMENT 指向 .venv-uv 保护旧实验环境；团队通常直接由 uv 管理 .venv。GPU 验收范围与待办见验证页，不把旧 Python 3.12 实验当作当前 uv GPU 验证。
