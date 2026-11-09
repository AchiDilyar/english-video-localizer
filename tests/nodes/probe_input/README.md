# probe_input 测试

从仓库根运行 `python -m pytest tests/nodes/probe_input`，不直接执行测试文件，不修改 sys.path。

- `test_probe_input.py`：Pydantic 状态、媒体字段、非法输入及缺失公共工具。
- `test_media.py`：真实 FFmpeg 合成音视频，检查正负音轨偏移、AAC 起声、总长度、错误媒体及覆盖保护。
- `tests/data/probe_input/ffprobe.json`：固定探测响应，不是识别真值。
- 临时媒体、日志和 pytest 临时目录在 `tests/tmp/`；缺少 FFmpeg 时媒体测试明确跳过。

公共服务替身在 `tests/nodes/conftest.py`，仅测试使用，不属于 project/mocks，不被真实节点导入。
