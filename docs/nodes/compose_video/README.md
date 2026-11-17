# 成片背景音与混音

audio/dub.wav保留纯中文，audio/mixed.wav为最终立体声混音。字幕依据最终中文语音定位，混音不改台词、字幕分片或语音开始时间。

## 处理入口

1. nodes.background_audio.separate或python -m nodes.background_audio：本地HDEMUCS_HIGH_MUSDB_PLUS分离人声与其他声部；background.wav为非人声声部之和，不直接混回整条原声。分离回执绑定源摘要、模型、时长和输出摘要。
2. nodes.audio_mixing.mix_background：背景增益0.7，中文增益1.0，中文发声时轻度压低背景，限幅并补偿滤镜延迟。输出48kHz立体声及mix回执；不自动把中文音量减半。
3. compose_video通过select_prepared_mix校验mixed.wav与当前视频/配音摘要后使用；未准备混音时保持纯配音，不匹配则明确失败。配音更新后必须重混，不能复用旧mixed.wav。

背景可提前分离；在配音完成后准备mixed.wav、compose_video执行前写入。更改背景增益不需要重新调用TTS。背景分离分窗仅用于推理内存控制，不修改B句子或配音分组。

## 环境与边界

torch、torchaudio、numpy已在speech可选依赖声明。本次复用既有Python3.12.14、torch/torchaudio2.8.0+cu128的GPU worker，经uv run --no-project --python指定该环境运行；主流程仍用Python3.11的uv环境，不将二者混为同一依赖验收。没有pip安装或手改uv.lock。

权重仅首次显式下载到models/background-demucs，不上传。音频全程本地，不发生新的分离服务费用。音乐声部分离模型可能损失部分环境声，或留下人声残响；没有干净背景真值，不能承诺完全去人声。五分钟背景的本地英文ASR/VAD未检出台词，只是辅助检查。

产物、回执和复现位于本机tests/tmp/five-minute-background-20261114/，中间文件不上传；本次源码见交付分支（本轮按用户授权发布main）。参考：[Torchaudio官方教程](https://docs.pytorch.org/audio/2.8/tutorials/hybrid_demucs_tutorial.html)。

## 非语言人声

nodes.nonverbal_events新增笑声、轻笑、清嗓、吸气等事件候选识别。先对分离的人声声部做AudioSet AST滑窗筛选，再从候选中减掉本地英文逐词识别区间（前后各80ms保护），对剩余间隙单独复检。只有事件分数满足阈值且高于讲话分数时回填原始人声声部；不能因为“没识别出文字”就混回整段原声。回填以30ms淡入淡出，原背景在选定区间外保持逐样本一致。

该功能支持笑声，但模型事件分数不是校准概率；与讲话同时发生、无法可靠分离的笑声可能保守舍弃。最新五分钟回填35.30–36.84秒及291.18–292.08秒，背景复识别只返回hahahaha，无其他英文台词；这仍不等于人工确认完全无讲话残留。

新增CPU ONNX运行依赖由uv add --optional sound-events声明并写入uv.lock；使用uv run --locked --extra b-asr --extra tts --extra sound-events运行相关流程。AST使用固定版本ONNX权重，本地特征预处理沿用既有Torch worker，音频不外发。主模型来源：[MIT AudioSet AST](https://huggingface.co/MIT/ast-finetuned-audioset-10-10-0.4593)，[固定ONNX转换版本](https://huggingface.co/onnx-community/ast-finetuned-audioset-10-10-0.4593-ONNX/tree/2fe67046c486b8b8bc90a7b469239b2dec822f72)。
