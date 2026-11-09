# probe_input（B）

遵循 architecture v1.2.0，节点名、模块名和函数名均为 probe_input。

```python
from contracts import GraphState
from nodes.probe_input import probe_input

delta = probe_input(GraphState(input_video="input.mp4"))
# {"media_info": MediaInfo(...)}
```

由 F 的图导入注册。源码运行时以 project 为模块根；pytest 已有 pythonpath 配置，不修改 sys.path。

通过 `utils.config.load_config("probe_input.toml")` 读配置，通过 `utils.paths.artifact_path("input_video", state.input_video)` 定位原片。只接受工作目录根目录下本地 MP4 的文件名，不接受网址、绝对路径或子目录路径。节点不创建目录、不写文件、不修改输入状态，失败直接抛异常。

输出全片毫秒时长、视频编码/宽高/可选帧率、音频编码/采样率/声道数、ffprobe 原始结果；媒体信息仅在 GraphState 中传递。多条候选音轨要求显式选择，不擅自决定。

`config/probe_input.toml` 可指定 ffmpeg/ffprobe 路径和绝对流索引；未指定时查找 PATH，再查仓库 `.tools/ffmpeg/bin`。`media.py` 是原媒体适配器，`prepare_tools.py` 是工具准备程序，不是团队 CLI。日志交给 CLI 初始化的统一 logger。

F 的 paths/config/io 尚无实现。`integration.py` 只转发约定调用并明确报告缺失依赖，不提供 B 专用降级实现。

测试：`python -m pytest tests/nodes/probe_input`。见 [测试说明](../../../tests/nodes/probe_input/README.md)。
