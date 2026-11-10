# asr_diarize（B）

2026-11-10 更新：[uv 安装、依赖组与 Python 3.11 验证](B-uv-20261110.md)。当前安装与运行以 pyproject.toml、uv.lock、uv run 为准，历史 requirements 和旧环境命令不作为现行要求。

按 architecture v1.2.0 整理；前序是 [probe_input](../probe_input/README.md)，后序是 C 的 build_blocks。

```python
from contracts import GraphState
from nodes.asr_diarize import asr_diarize

delta = asr_diarize(GraphState(input_video="input.mp4"))
# {"segments": list[Segment]}
```

## 节点行为

1. 通过 F 的 load_config 读取 config/asr_diarize.toml 和 config/probe_input.toml；通过 artifact_path 获取 input_video、source_audio、segments 的路径。
2. CLI 须预先创建工作目录和子目录。节点不创建目录；已有输出报错，不覆盖历史结果。
3. 提取全片 16 kHz 单声道 PCM16 音轨到 audio/source.wav，保留音轨延迟、静音及全片长度。
4. faster-whisper 初次处理完整音频，不作外部分块；spaCy 按句法/语义整理，必要时局部复识别。原始 ASR 片段/词时间只在内存，不落盘。
5. 独立进程运行本地 Community-1，通过内存 JSON 接收轮次，不额外保存识别报告或声纹；整句中已检测说话时长超过 50% 的人获得归属，边界冲突不单独否决。
6. 最后生成 seg_0001 等片段 ID、spk_1 等说话人 ID，以及 start_ms、end_ms、text_en。相同声音组保持相同编号；交付后下游不应改号或改时间。
7. 调用 write_artifact("segments", segments) 校验并写 segments/segments.json，成功后才返回增量；不修改输入 State。

正常日志经模块 logger 交给 CLI 的统一 logs/run.log。节点不吞异常、不创建事件文件、检查点、HTML 或字幕。pipeline/ 中独立旧流程的持久化功能不在共享节点调用链上。

附件规范复核后，共享节点直接调用 recognition.py 的内存算法，并原样传入公共工具解析的音频路径，不再借用旧图的路径适配函数。历史 API 改为按需导入；Community-1 子进程诊断通过父节点 logger 汇入统一日志。详见 [逐项规范核对](B-spec-compliance-20261109.md)。

## 配置与环境

- 模型路径相对仓库根解析，也接受绝对路径，不依赖当前目录。
- community1_python 保持为空，子进程沿用 uv 管理的当前 Python；禁止切换到另一个手工安装的解释器。Community-1 运行需同时启用 b-asr、speech extras。设备 cpu/cuda 显式指定，不静默降级。
- ASR 需要 faster-whisper、兼容的 PyAV（此前验证 16.1.0）、spaCy 和 en_core_web_sm。Community-1 需要 pyannote.audio 与匹配的 Torch/Torchaudio；历史下载辅助工具还需 yt-dlp。
- FFmpeg 和模型权重单独在本机准备。Community-1 需使用者本人同意访问条件并下载；节点只用本地模型，不上传音频、不自动下载。可用 `uv run --extra speech python project/nodes/asr_diarize/community1_worker.py --prepare-model --allow-model-download` 准备权重。
- [environment/](environment/) 保存旧 Python 3.12 独立环境快照，不覆盖团队 Python 3.11 uv.lock，不再作为安装入口；当前以 pyproject.toml、uv.lock 及 uv 验证记录为准。
- DeepSeek 默认关闭，需显式 provider、联网授权和调用预算。配置不是付费调用授权，本次迁移没有新调用。

## 依赖和限制

F 的 utils/paths.py、io.py、config.py、artifacts.py 已实现。B 已增加直接使用这些真实工具的联调用例；固定测试仍只替代模型输出，不替代该用例的公共服务。完整主图验收另行进行。

共享 Segment 不允许空说话人，F/D 尚未确认未知编号语义，因此存在未知时抛 UNRESOLVED_SPEAKER；有未定时间短语则抛 UNTIMED_UTTERANCES。不猜测标签、不丢词来通过校验。其他语义风险仍需人工核对；共享 schema 没有复核字段，仅日志记录数量，不擅自新增字段。

失败可能留下已提取的 source.wav，但不会返回成功增量。基本版不续跑，排查后用新工作目录重做。聚类编号只在片内有效，不是已验证人物身份。

## 测试与历史成果

```powershell
uv run --extra b-asr pytest tests/nodes/asr_diarize
uv run pytest tests/nodes/probe_input
```

[测试说明](../../../tests/nodes/asr_diarize/README.md) · [迁移与验证](B-layout-v1.2.0.md)。真实模型测试显式启用，默认跳过，不下载或付费调用。

旧 b_pipeline 已迁至 project/nodes/asr_diarize/pipeline/，旧 CLI、检查点和分块能力用于独立历史复现，不是团队基本版主图。生产助手在 standalone/；历史测试助手在 tests/nodes/asr_diarize/support/。

本目录历史报告和提案 PDF 保留当时的事实与命令，不作为当前入口；已有 [80 分钟实测](B-long-multiperson-YouTube-20261108.md) 不替代本次迁移后主图验收、D 音色联调或完整人工听辨。Issue #3 仍未全项完成。
