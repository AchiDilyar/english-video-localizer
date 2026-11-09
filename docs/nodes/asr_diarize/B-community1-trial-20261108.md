# Community-1 本地对照试跑

> 历史阶段记录：代码与文档已按 v1.2.0 迁移。旧路径、命令和“尚未实现”等状态仅对应记录当时，不作为当前入口；当前使用与限制见 [节点说明](README.md) 和 [迁移记录](B-layout-v1.2.0.md)。历史任务未修改。
2026-11-08，用户本人完成 Hugging Face 登录和 Community-1 模型页访问申请后，配置/模型下载获准。没有代用户接受条件、创建凭据或将 token 写进源码/命令/结果。

## 已实际完成

- 独立 `.venv-community1` 环境：Python 3.12、torch 2.8.0+cpu、torchaudio 2.8.0+cpu、torchcodec 0.7.0、pyannote.audio 4.0.7。现有 `.venv` 保留。
- 官方模型 pyannote/speaker-diarization-community-1，快照 `3533c8cf8e369892e6b79ff1bf80f7b0286a54ee`，10 个文件逐项记录 SHA256。
- 下载结束后，本地推理设置 HF_HUB_OFFLINE=1、关闭 pyannote 使用指标及 Hugging Face 遥测。读取本地 WAV，不上传音频，不使用 pyannoteAI 云端或收费 API。
- 先跑官方 16 秒双人样音：自动 2 人、4 个 exclusive 轮次，实测 8.340 秒。
- 再跑同一份 180 秒真实双人访谈音频：未预设人数，自动 2 人、32 个 exclusive 轮次，CPU 4 线程实测 108.205 秒（包含加载/推理阶段，不能外推长视频速度）。
- 使用新的 LangGraph 导入任务将结果映射至原有 65 条台词，未重跑 ASR、未改写英文或句子时间，结构和 5 个 SQLite 检查点检查通过。

## 同样台词、同样归属规则下的比较

| 指标 | 原 sherpa-onnx＋边界例外 | Community-1 exclusive＋同一规则 |
|---|---:|---:|
| 自动聚类人数 | 3 | 2 |
| speaker_001 台词 | 42 | 42 |
| speaker_002 台词 | 11 | 17 |
| 未确定 | 9 | 6 |
| 使用边界重叠例外分配 | 3 | 0 |

两个模型的编号分别在该次运行内定义，不能仅凭同名编号证明跨模型身份一致。Community-1 默认输出另有普通可重叠轮次；本次专门使用 exclusive_speaker_diarization，使每个时刻最多一位说话人。这种输出表示法与旧模型不同，不能将结果变化全归因于嵌入/聚类准确率。

新增可归属的条目为 6、19、25、29、43；原已用边界例外归属的第 49、65 条，在新输出下又变成未知。第 64 条在新模型下直接归给 speaker_002。没有隐藏这些变差项，也没有为了减少空值临时放宽规则。

### 第 49 / 65 条为什么仍未知

第 49 条从 114.660 秒开始，但 Community-1 在 115.304 秒才切到 speaker_001，句首 644 毫秒归另一人；第 65 条从 172.860 秒开始，模型到 173.337 秒才切换，差 477 毫秒。主要人覆盖分别约 92.26% / 93.13%，但这些是 exclusive 的顺序边界，不是“两个声音同时出现”的区间，因此不触发当前“边缘同时重叠”例外。

这里可能是转写边界偏早，也可能是模型切换点偏后，尚未人工听辨确认。不能仅因为模型更新就认定其时间是真值，或把原英文开头随意删掉。

结论：Community-1 已真实跑通，本片自动人数更符合双人设定、未知数量减少，但未进行人工标签/DER 验收，不能宣称它在本片的准确率已得到证明。现有主流程默认仍用 sherpa-onnx，没有自动替换整个工程后端；先让用户对照核对。

## 文件

优先打开 `jobs/B-community1-dialogue-20261108-01/comparison.html`：同视频、同一条英文，左右比较旧模型与 Community-1 的编号，点击时间跳转。

- 同目录 review.html / timetable.json / sentences.csv / english.srt / speaker-turns.json：Community-1 结果。
- model-comparison.json：包含所有改变的行，不只列更好的行。
- imported-speaker-result.json：本地模型结果，含音频哈希与实际耗时。
- model-provenance.json：授权模型的快照与本地哈希，无 token。
- code-snapshot/：执行代码和隔离环境依赖锁。
- 原始 worker 输出：`jobs/B-community1-interview-20261108/result.json`。
- 16 秒样音结果：`jobs/B-community1-smoke-20261108/result.json`。
- 失败/警告日志：`jobs/B-community1-smoke-20261108.log`、`jobs/B-community1-interview-20261108.log`。

两版视频均附 ConversationEDU / CC BY 3.0 的署名、来源和连续节选说明；来源见 [真实访谈说明](B-two-person-video-validation-20261108.md)。没有推送模型、音频、登录信息或运行产物。

## 调用方法

```powershell
# 已经获准模型访问后，显式下载一次；既有 hf 登录由用户自己完成
& .venv/Scripts/python.exe -m tools.community1_worker --prepare-model --allow-model-download

# 独立环境只读本地模型与音频；不要在命令中粘贴 token
& .venv-community1/Scripts/python.exe -m tools.community1_worker --audio jobs/B-two-person-video-auto-20261108-01/audio.wav --output jobs/new-community1/result.json

# 在原工程环境运行 LangGraph 导入/审查/导出，不覆盖旧任务
& .venv/Scripts/python.exe -m tools.diarize_existing --source-job jobs/B-two-person-video-auto-20261108-01 --job-dir jobs/new-community1-table --speaker-result jobs/new-community1/result.json
```

worker 可选 --num-speakers，但本轮未指定人数。--speaker-result 必须匹配音频哈希和时长，不能同时要求修改人数或复用旧轮次。worker 只返回匿名最终说话轮次，不保存声纹向量或原始 ASR 时间。

## 依赖处理与局限

首次未固定 TorchCodec 的解析曾计划将 Torch 升到其他版本，安装前已中止；依据官方兼容表固定 2.8/0.7 后完成。Windows 缺少 TorchCodec 所需的共享 FFmpeg 库，内置路径解码会警告；本次使用官方支持的内存 waveform 输入，样音与访谈均成功，不修改系统 PATH、不安装额外系统 FFmpeg。日志中的短序列 std 警告保留，没有将其掩盖为不存在。

隔离环境 pip check 通过；75 项项目测试通过，其中新增两项为输出格式、顺序/编号一致性和空结果拒绝测试，不把它们当作模型准确率测试。模型权重、缓存与 `.venv-community1/` 已在忽略范围内。

如从干净环境复现，先从官方 CPU 索引安装 torch==2.8.0 和 torchaudio==2.8.0，再安装 requirements-community1.lock.txt。CPU wheel 的 +cpu 版本来自 https://download.pytorch.org/whl/cpu ，不能假设默认包索引包含这些构建。

参考：[Community-1 官方说明](https://huggingface.co/pyannote/speaker-diarization-community-1)、[TorchCodec 兼容表](https://github.com/meta-pytorch/torchcodec#compatibility-with-torch-versions)。本轮未进行 D 联调、F 接口确认、全片 43 分钟新模型验证或 GPU 性能测试。
