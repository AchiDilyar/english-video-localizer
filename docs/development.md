# 开发环境

从仓库根目录运行以下命令。团队使用 Python 3.11 和 `uv.lock` 统一依赖。准备 uv 和能从终端调用的 `ffprobe`。环境自检会用 Python 依赖中的 FFmpeg 烧录字幕，也可以通过 `LOCALIZER_FFMPEG` 指向已有的 FFmpeg。

```bash
uv sync --locked
uv run --locked python scripts/check_environment.py
```

自检用临时素材验证 LangGraph 的 SQLite 检查点、Pillow 中文封面、双语字幕烧录和 H.264/AAC 成片。默认选择系统中已知的中文字体。自检报缺少字体时，设置 `LOCALIZER_FONT_PATH` 指向本机中文字体文件再运行。也可以用 `LOCALIZER_FFPROBE` 指定 ffprobe。

如需把虚拟环境放在仓库外，先设置 `UV_PROJECT_ENVIRONMENT` 指向本机可写的绝对路径，再运行同步和自检命令。同一个终端中执行后续的 `uv run` 时沿用此设置。

B 和 D 接入真实转写、说话人区分和语音 API 时，可用 `uv sync --locked --extra speech` 安装额外依赖。团队在开始接真实模型时，按需把 `.env.example` 复制成 `.env` 并配置本机凭据。D1–D3 的模拟模块与环境自检可以先用无密钥环境开发。

每个模块先用小样本开发，并把接口变化、验证命令、结果和待联调事项写到对应的成员记录。记录里统一使用 A–G 代号。 [成员工作记录](roles/README.md)

## 多人开发主线

先用一段约 30–60 秒的模拟素材打通流程，再逐步换成真实模型和长视频。B、C、D、E 各自在约定的模块文件内开发，F 在流程文件里把模块连起来。开工前在对应 Issue 说明要改的文件，改动接口时先通知下游。

| 角色 | 建议模块 | 先交付的模拟接口 |
|---|---|---|
| B | 素材与转写 | 输入视频，输出含 `segment_id`、`speaker_id`、`start_ms`、`end_ms`、`en` 的片段 |
| C | 翻译与审校 | 输入 B 的片段，补 `zh_subtitle`、`zh_dub`，审校返回待重做片段的 ID 和原因 |
| D | 配音与同步 | 输入片段及口播稿，输出对齐音轨和超时片段 |
| E | 字幕、封面与打包 | 输入视频、对齐音轨、双语片段和任务报告，输出 SRT、MP4、JPG、发布文案和 ZIP |
| F | LangGraph 编排 | 定义状态、节点、条件边和 SQLite 检查点，验收模块能用模拟输入串起来 |

每人先在本地 `main` 用固定样例把自己的模块跑通，把验证命令和输出记进角色文档。需要交付共享改动时先提交、再执行 `git pull --rebase origin main`，解决冲突并复跑受影响模块后推送。跨模块改动可先约好合入顺序。

## 工作流和界面

LangGraph 的节点调用 Python 模块，状态在节点之间传递片段、文件路径和任务结果。条件边把有问题的片段送回翻译或配音，处理完再进入成片环节。首版主线为素材校验 → 转写与区分说话人 → 断句 → 翻译与审校 → 配音测时 → 字幕和视频合成 → 打包。

- B 本地用 faster-whisper 获取英文词级时间戳，并用 VAD 定位有声音的语音段。先依据说话人切换、停顿和标点断句，再把字幕段按上下文分批交给翻译。 [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
- B 本地用 pyannote Community-1 区分谁在何时说话，按时间对齐到转写。D 将同一个说话人映射到固定的 CosyVoice 音色。分离混音里的背景音乐和人声是独立的音频处理能力。首版合成中文音轨时替换原混音。 [pyannote Community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)
- 首版入口为 CLI，任务输出到本地，课堂可展示流程图、运行记录和成片。LangSmith Studio 的 Graph 模式能查看代码定义的节点图和运行状态，需要单独配置 Agent Server。可在 CLI 闭环完成后再给项目加上传、进度、预览和下载页面。 [LangSmith Studio](https://docs.langchain.com/langsmith/studio)

仓库已有一个可运行的翻译和审校小图。默认用固定模拟响应演示一次返工，`--graph` 输出 Mermaid 源码。

```bash
uv run --locked python -m video_localizer.translation_demo
uv run --locked python -m video_localizer.translation_demo --graph
```

## DeepSeek 接入

在 DeepSeek 开放平台创建 API Key，将 `.env.example` 复制到本机 `.env`，填入 `DEEPSEEK_API_KEY`。翻译示例默认使用 `deepseek-flash`，通过 `DEEPSEEK_MODEL` 可显式指定其他模型。 [DeepSeek 开放平台](https://platform.deepseek.com/api_keys) · [DeepSeek JSON 输出](https://api-docs.deepseek.com/guides/json_mode/)

```bash
uv run --locked python -m video_localizer.translation_demo --live
```

`--live` 会向 DeepSeek 发送一条固定的英文测试句和它的译稿，用于验证翻译和审校。模型调用会计入 API 用量。后续 C 的翻译与审校、E 的中文编辑可以复用 `video_localizer.deepseek.generate_json`，分别定义提示词和输出字段。

本地模型的准备由 B 负责。faster-whisper 需要先下载模型文件。pyannote Community-1 需要登录 Hugging Face 并接受模型页条件，首次下载时读取本机 `HF_TOKEN`。文件准备后可以在本机运行。D 接入 CosyVoice 时单独配置百炼凭据。 [pyannote 权限与本地运行](https://huggingface.co/pyannote/speaker-diarization-community-1#setup)

## 本地工作流画布

```bash
uv run --locked --extra b-asr python scripts/serve_workflow_ui.py
```

浏览器打开 `http://127.0.0.1:8765/`，直接进入工作流画布。端口占用时使用 `--port 8766`。

在「视频输入」选择本地 MP4，再点击「运行」。WebUI 通过 F 的 CLI 调用正式 LangGraph 主图，显示任务状态、日志及已生成的字幕。节点与运行配置从后端读取。服务仅监听本机地址。

完整操作、参数范围、已验证能力和后端接入约定见 [WebUI 使用与开发说明](webui.md)。
