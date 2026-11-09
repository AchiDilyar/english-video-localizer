# YouTube 完整多人长视频验证

> 历史阶段记录：代码与文档已按 v1.2.0 迁移。旧路径、命令和“尚未实现”等状态仅对应记录当时，不作为当前入口；当前使用与限制见 [节点说明](README.md) 和 [迁移记录](B-layout-v1.2.0.md)。历史任务未修改。
2026-11-08，实际下载并完整处理 Wiki In Africa 的 **WikiAfrica Hour #38: Wikimania: a Collaboration of the Open**。

## 素材与范围

- [原 YouTube 视频](https://www.youtube.com/watch?v=jMbGRk8Y9uA)
- [发布方节目介绍](https://www.wikiinafrica.org/wikiafrica-hour/page/3/)；[节目回顾（含预录采访介绍）](https://diff.wikimedia.org/fr/2024/11/20/wikiafrica-hour-38-wikimania-une-collaboration-ouverte/)
- 账号/作者：Wiki In Africa。YouTube 元数据标注 `Creative Commons Attribution license (reuse allowed)`；保留原始许可描述，没有自行推定具体许可版本。
- YouTube 标称 4,848 秒；下载后媒体实际时长 **4,847.567 秒，即 80 分 47.567 秒**。处理整片，没有用短片拼接，也没有只运行其中三分钟。
- 现场画面可见主持人与多位嘉宾；节目另有预录采访，因此声音来源不限于圆桌画面同时显示的五个窗口。人数需独立核对，不以窗口数强制设置模型人数。
- MP4：223,657,467 字节；SHA256：`63280b324b014be197e136d5af925471563fa6b7e96669e23cd9b7fec0213db7`。
- 默认格式 18 下载持续零进度，已中止并保留部分文件。改为同一原视频的公开格式 134 画面 + 140 英文音轨下载合并，实测 150.108 秒；这是传输格式切换，不是 ASR 音频分块。

下载来源：`media/wikiafrica-hour38-separate/download.json`。原片、测试图和完整音频只在本地，未提交仓库。已在核对页和 ATTRIBUTION.txt 写明来源、作者、许可原文及机器处理说明。

## 实际运行结果

| 项目 | 实测 |
|---|---:|
| 完整视频时长 | 80 分 47.567 秒 |
| 最终台词条目 | 901 |
| Community-1 自动匿名声音组 | 14，未预设人数 |
| 最终 exclusive 说话轮次 | 619 |
| 按整句多数时长获得归属 | 883 条 |
| 仍未归属 | 18 条 |
| 时间结构错误 | 0 |
| 仍需补定时间的短语 | 1 |
| 全片 ASR 推理 | 456.457 秒，CPU int8 |
| 疑似残句复查 | 83 处、166 次局部调用，168.534 秒 |
| 局部复查暂应用修订 | 3 处，未人工确认 |
| Community-1 全片 GPU 处理 | 153.734 秒，含模型加载/处理阶段 |
| GPU | 本机 RTX 5060 Laptop，未使用云端算力 |
| CUDA 张量峰值分配 | 1,707,943,936 字节，约 1.59 GiB；不是整个设备峰值显存 |
| 付费模型 API / DeepSeek 调用 | 0 / 0 |

ASR 对完整 WAV 调用一次 transcribe，外部初次识别音频分块为 0；随后进行 166 次有针对性的局部复查，总 ASR 调用数 167。原始 ASR 分段/词时间只在内存，不写入文件或检查点。

Community-1 对同一完整音频调用一次 pipeline，模型内部窗口由其原生实现管理，没有用多个短片结果拼接冒充整片。使用 exclusive_speaker_diarization 输出，再接入 LangGraph 的归属、审查与导出节点。按用户最新规则分配：整句检测到的说话时长超过 50% 的人获得编号，边界冲突不单独拒绝归属。

最终台词的 ID、英文、起止时间逐项与说话人处理前一致。检查 5 个导出任务 SQLite 检查点、最终 JSON 和输出文件，未发现原始 ASR words/segments 结构。最终 exclusive 轮次均在视频范围内、正时长且互不重叠。页面引用的视频存在，脚本语法检查通过。

## 18 条为什么仍未知

18 条全部是 **Community-1 没有在该条时间区间检出说话人覆盖**；本次没有因为边界冲突、时长并列或无绝对多数而拒绝归属。`speaker-unresolved.csv` 提供完整清单。

没有模型覆盖不代表原录音一定没有人声，也可能是漏检、背景声或 ASR 误识别，需回听判断。不能把上一人的编号直接延续来消灭空值。

另观察到 **5 组连续相同的转写文本**，已列入 repeated-text-to-review.json。尤其是后段一些重复短句与说话人无覆盖同时出现，需要听辨是否真实重复、非英文/背景声影响或识别幻听。本轮没有无依据删词或把这些行当作准确真值。

## 验证结论与局限

**工程长视频运行和时间结构检查通过；真人标签稳定性、英文准确率尚未通过人工验收。**

14 是模型聚类数，不是人工确认的 14 个真人。节目有圆桌和预录采访，不能仅拿五个画面窗口与 14 个聚类直接比较，也不能因两者有差异就认定模型全错或全对。

核对页按每个编号列出早/中/晚台词、首次/末次出现、检测说话时长以及每十分钟跳转入口。这些是方便观察串人的统计；同一编号跨越长时间，不等于已证明同一个真人始终保持该编号。尚无逐帧人工参考标签，未计算 DER，未与 D 验证音色映射，也未代 F 完成共享接口验收。

901 条中 237 条带各种复核项；包含 18 条说话人未知以及原有的转写/语义/增补提示，不能把已获得 speaker_id 理解为英文和语义也已通过。

## 安装、失败记录与复现

本次一次性 GPU 准备耗时较长，**不计入 153.734 秒模型处理时间**，也不把整个任务说成仅用 154 秒。官方 CUDA PyTorch wheel 约 3.46 GB，普通下载反复中断；使用官方服务器的字节范围续传，最后与官方索引 SHA256 核对通过才安装，没有第三方镜像。安装过程临时目录清理警告保留，没有修改系统安全设置或删除不明文件。

GPU 环境为 `.venv-community1-gpu`，Torch/Torchaudio 2.8.0+cu128，Pyannote 4.0.7，驱动 592.82。它通过 .pth 只读复用 CPU 环境的相容依赖，但 GPU Torch/Torchaudio 安装在自身目录；实际导入路径、CUDA 张量运算与 16 秒模型短样均验证成功。原 `.venv` 与 `.venv-community1` 未被升级成 CUDA 环境。

CPU 完整长片曾作为等待安装时的备用尝试启动，进入特征提取后中止，以使用已验证的 GPU 路径；没有产生完整结果，不计作成功实验。记录在 interrupted-cpu-attempt.json，原日志保留在 `jobs/B-WAH38-community1-cpu-20261108.log`。GPU 16 秒短样实际 4.434 秒、2 组/4 轮次，之后才运行正式长片；不把短样当长视频验收。

Windows 的 TorchCodec 共享 FFmpeg 解码警告依然存在，使用官方支持的内存 waveform 路径成功完成。短序列标准差警告也保留在日志，不冒称已经消除。

78 项项目测试通过；GPU 环境 pip check 通过。依赖版本在 requirements-community1-gpu.lock.txt，带官方 CUDA 包索引，不保留本机 wheel 文件 URI。代码快照与模型权重哈希、快照 ID 均随本地任务保存。

## 输出入口

最终任务：`jobs/B-WAH38-Community1-long-20261108-01/`

- **long-speaker-review.html**：完整视频、各编号早/中/晚回听及十分钟跳转，是优先核对入口。
- review.html：全部 901 条台词、最终时间和 speaker_id。
- timetable.json、sentences.csv、english.srt、speaker-turns.json：实际交付格式。
- speaker-unresolved.csv、repeated-text-to-review.json：未定和疑似重复内容。
- long-multiperson-verification.json、verification.json：统计、结构检查与实际模型版本/耗时。
- code-snapshot/、community1-model-provenance.json、official-gpu-wheel-sha256.txt：复现证据；不含登录凭据或声纹向量。

源 ASR 任务：`jobs/B-WAH38-long-ASR-20261108-01/`。GPU 原始最终说话轮次结果与日志：`jobs/B-WAH38-community1-gpu-20261108/result.json`、`jobs/B-WAH38-community1-gpu-20261108.log`。

```powershell
& .venv/Scripts/python.exe -m b_pipeline run --input media/wikiafrica-hour38-separate/video.mp4 --job-dir jobs/new-long-asr
& .venv-community1-gpu/Scripts/python.exe -m tools.community1_worker --audio jobs/new-long-asr/audio.wav --output jobs/new-long-speakers/result.json --device cuda
& .venv/Scripts/python.exe -m tools.diarize_existing --source-job jobs/new-long-asr --job-dir jobs/new-long-final --speaker-result jobs/new-long-speakers/result.json
```

所有路径需使用新任务目录；已有证据可直接读取，不必为查看报告重跑。正式结果仅包含成功的 GPU 长片输出，没有将中止 CPU 结果与 GPU 结果拼接。验证范围为约 80 分钟，不宣称两小时真实推理已验证。本轮未提交或关闭 Issue #3。
