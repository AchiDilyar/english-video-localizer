# B 本地媒体准备工具

本轮先保留接口提案，推进不依赖共享模型或 LangGraph 主图的独立本地工具。它们放在 tools/ 下，不实现或替代团队的最终 `localizer run/resume` 入口。

## 1. 已提供的内容

- `tools/b_media.py`：环境检查、本地视频媒体检查、标准 WAV 提取。仅用 Python 标准库，不发起网络请求、ASR 或文本模型调用。
- `tools/bootstrap_ffmpeg.py`：下载并校验便携版 FFmpeg，放在忽略目录 `.tools/ffmpeg/`，不修改系统 PATH。
- `tools/verify_b_media.py`：生成合成媒体、运行针对时间轴和异常情况的检查，将结果留在 `jobs/B-media-<时间>/`。
- `tests/test_b_media.py`：真实 FFmpeg 集成检查，素材由程序生成，包含晚开始/早开始音轨、非零画面起点、缺音轨、损坏文件、已有输出保护等。工具缺失时跳过并明确记录，不把跳过当作通过。
- [素材登记模板](examples/B-assets.template.csv)：各行都是待填写候选任务，不是真实素材或已取得的授权。

## 2. 运行方法

以下相对命令在仓库根目录执行。本机已用 Codex 捆绑 Python 3.12.14 创建项目 `.venv`，未因此修改团队原定 Python 3.11；后者兼容性仍待实测。当前隔离环境没有安装第三方 Python 包或 pip。

```powershell
.\.venv\Scripts\python.exe tools/b_media.py check
.\.venv\Scripts\python.exe tools/b_media.py inspect --input .\media\demo.mp4
.\.venv\Scripts\python.exe tools/b_media.py extract --input .\media\demo.mp4 --output .\jobs\demo-audio
.\.venv\Scripts\python.exe tools/verify_b_media.py
```

FFmpeg 可以来自 PATH、项目 `.tools/ffmpeg/bin/`，或在 inspect/extract/check 命令中用 `--ffmpeg`、`--ffprobe` 显式指定可执行文件路径。两者都不会写系统配置。

本地可选准备命令：

```powershell
.\.venv\Scripts\python.exe tools/bootstrap_ffmpeg.py
```

下载脚本会联网读取构建，使用固定的发布方 SHA-256 核对，不上传素材；受网络权限和来源可用性影响。当前固定下载发布方官方 GitHub 9.0.2 7z 构建，单次限制 60 MiB 和 180 秒（网络阻塞还受单次读超时影响），失败即停止。已有 FFmpeg 时拒绝覆盖。构建来自 [Gyan Windows builds](https://www.gyan.dev/ffmpeg/builds/) 的 [官方发布资产](https://github.com/GyanD/codexffmpeg/releases/expanded_assets/9.0.2)，不自动升级版本。

## 3. 检查与提取行为

inspect 只接受本地文件，使用 FFprobe 的 [JSON 输出、流和容器信息](https://www.ffmpeg.org/ffprobe.html)；返回实际哈希、流索引、起点、时长与警告。必须有视频和音频；音频文件本身不属于本工具当前输入范围。

多音轨或多视频流不擅自选择，要求用 `--audio-stream` / `--video-stream` 提供 FFprobe 的绝对流索引。封面附图不当成视频主流。

extract 将所选视频流的起点作为 0，保留原始 PTS 后移动音频时间轴：早到的音频裁齐，晚到的音频补静音，并保留中间时间间隔。按视频总时长补尾部静音或裁尾，输出 16000 Hz、单声道、16-bit PCM WAV。不是降噪或背景声分离。

时长优先取视频流时长。缺失时由容器末端减去所选视频起点估计演示区间并记录明确警告，需人工核对末尾画面。起点或正时长未知时拒绝提取，避免将未知时间当成 0。

结果放在指定目录：`audio.wav` 和 `media-report.json`。报告含原始 FFprobe 信息、输入输出哈希、真实命令、FFmpeg/FFprobe 版本和本次处理耗时。报告指向已提交的 audio.wav；命令中的临时输出路径仅是原始执行记录，不能原样作为新的输出位置复用。

不会覆盖这两个已有文件；请使用新的输出目录。当前以单个写入者为使用前提；消费者需要同时确认两个文件存在，不把孤立 WAV 当作完整结果。

本地错误使用明确错误码和非零退出状态。它们是独立工具的诊断格式，不自动冻结团队共享异常结构。

## 4. 当前限制

- 没有接 ASR、说话人区分、链接入口、LangGraph 或项目正式 CLI；接口议题仍保留。
- 结构与合成音频校验不证明真实视频语音识别准确或中文字幕同步质量。
- 没有删除静音，也没有将声音片段拼接成压缩后的时间轴。
- 尚未解决未知/异常时间戳与复杂编辑列表等所有容器问题；遇到异常应保存原始信息再诊断，不自动猜测。
- 不自动下载真实教学视频。登记表需要填来源、许可/授权依据与本地位置后，才能开始真实样片验证。
- 本机工具结果只代表实际记录的环境；不能宣称已经通过团队 Python 3.11 或第二台机器验证。

参见 [执行计划](B-execution-plan.md) 与 [本轮完成记录](B-local-progress-20261107.md)。DeepSeek 未参与工具实现。
