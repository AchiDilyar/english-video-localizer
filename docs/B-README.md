# B 模块交接入口

截至 2026-11-09：核心素材、识别、语义分句、局部复识别、说话人区分已独立运行；**尚未适配 F v1.1.0 节点契约，尚未完成 C/D/F 联调或 Issue #3 全部验收**。

## 先读这些

- [微信群进度说明](B-WeChat-progress-20261109.md)：完成项、待完成项及沟通事项。
- [与 F 最新契约的逐项比较](B-F-interface-review-20261109.md)：共享节点、字段、路径、Python 版本和待确认问题。
- [当前独立接口 V2](B-sentence-v2.md)：CLI、Python 调用、输出与恢复边界；当前接口不能直接作为 F 新节点签名。
- [80 分钟多人长视频记录](B-long-multiperson-YouTube-20261108.md)：来源、耗时、统计、失败记录及人工核对限制。
- [整句多数说话人归属](B-speaker-majority-policy-20261108.md)、[Community-1 接入](B-community1-trial-20261108.md)。
- [语义审查](B-semantic-review.md)、[残句复识别](B-audio-recheck-20261107.md)。

## 代码清单

| 目录/文件 | 用途 |
|---|---|
| `b_pipeline/__main__.py` | 当前 CLI：run / resume / download |
| `b_pipeline/sentence_mode.py` | 当前 LangGraph 子流程、检查点与输出 |
| `b_pipeline/video_inputs.py` | 本地/YouTube 输入、英文音轨选择 |
| `b_pipeline/sentence_rules.py`、`semantic_review.py` | 语义分句、检查及可选 DeepSeek 接口 |
| `b_pipeline/audio_recheck.py` | 疑似残句的有界局部复识别 |
| `b_pipeline/diarization.py` | 旧本地说话人模型及共享的整句归属算法 |
| `tools/community1_worker.py` | Community-1 独立进程；支持 CPU/CUDA |
| `tools/diarize_existing.py` | 导入 Community-1 结果，接入归属/审查/输出图 |
| `tools/report_long_multiperson.py` | 长视频核对统计和按说话人跳转页面 |
| `tools/b_media.py`、`bootstrap_*.py` | 本地媒体检查和工具准备 |
| `tests/` | 固定输入、模拟错误及合成媒体的回归检查 |
| `configs/`、`docs/examples/` | 历史登记配置与人工模拟样例，非 F 新契约样例 |

`workflow.py`、`chunking.py`、旧分组工具及相关文档/测试用于复现历史版本；默认 V2 不使用外部音频分块，不输出原始词时间。历史双人聚类失败记录也保留，不作为当前模型的准确性证明。

## 独立环境与复现

从仓库根目录运行，B 模块目前作为源码导入；尚未加入团队安装包。不要把 B 环境锁直接覆盖到团队 `uv.lock`。

已验证的 B 主环境为 Python 3.12；`requirements-sentence-v2.lock.txt` 是该环境的版本快照，不保证直接适用于团队 Python 3.11。Community-1 的 CPU / CUDA 独立快照分别见 `requirements-community1.lock.txt` 和 `requirements-community1-gpu.lock.txt`。不提交虚拟环境本身。

```powershell
# 在单独准备的 B 环境中安装；首次安装需要联网
python -m pip install -r requirements-sentence-v2.lock.txt

# 无下载、无识别模型、无付费调用的回归测试（需已安装 spaCy 英文模型）
python -m unittest discover -s tests -v

# 当前命令说明
python -m b_pipeline --help

# 真实识别前须自行准备 FFmpeg/ffprobe 与本地 Whisper 模型
python -m b_pipeline run --input 'C:/path/video.mp4' --job-dir jobs/new-video
```

媒体集成测试自动生成音频/视频；缺少 FFmpeg 时会明确跳过。请求参数边界测试使用临时占位文件，不依赖本机下载的样片，也不把它当作解码验证。Community-1 权重需要使用者本人接受 Hugging Face 条件并在本机登录；无需把 token 发给队友。

Community-1 当前通过 worker 运行再导入，**不是 CLI `--diarize` 的默认模型**；`--diarize` 仍调用旧 sherpa 模型。完整三步命令及模型准备见长视频记录和 Community-1 说明。

本仓库提交代码、依赖快照、测试、历史提案 PDF 和文字记录。`jobs/`、`media/`、`models/`、工具二进制和虚拟环境留在本地；文档中这些路径是证据位置，GitHub 检出后不会自动拥有相关媒体。历史 PDF 不作为 F 当前接口依据。

## 验收边界

实际长片跑通和时间结构检查通过，不代表英文/人物全部人工验收。没有 D 音色联合验收、全片人工标注或 DER。DeepSeek 仅此前一次公开台词小样调用，本次整理与提交没有新调用。
