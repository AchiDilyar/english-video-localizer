# asr_diarize 测试

当前依赖与验证见 docs/nodes/asr_diarize/validation.md；使用 b-asr extra 执行完整 B 测试。不带语音依赖时明确跳过相应模块，不能算作完整 B 验证。已有真实 F utils 集成测试，不再只有公共工具替身。

从仓库根运行 `uv run --extra b-asr pytest tests/nodes/asr_diarize`。不要直接运行测试文件。

- `test_asr_diarize.py`：字段/编号转换、主要说话人、未知/未定时间拒绝、写盘失败；真实小型 LangGraph 串接 B 两节点，用真实 FFmpeg 和固定模型替身验证产物与状态。
- 其他 `test_*.py`：语义分句、复识别、归属算法、Community-1 输出、下载边界和历史算法回归。
- `support/`：历史验证/样片准备助手，普通 pytest 不触发其中的下载或识别 main，不作为直接执行测试的入口。
- 固定小样例在 `tests/data/asr_diarize/`；大样片在被忽略的 `tests/data/_large/asr_diarize/`，普通回归不依赖它们。
- 临时数据和日志在 `tests/tmp/`；conftest 为 pytest 的 tmp_path 设置专用 basetemp。原有 jobs/media 证据不修改。

Python 依赖由 b-asr extra 和 dev 组统一提供；媒体测试另需本机 FFmpeg。当前 Python 3.11 + uv 已验证；当前依赖以 pyproject.toml 和 uv.lock 为准，历史环境教训仅保留在 docs/nodes/asr_diarize/archive/ 的摘要中。

模型替身测试不等于识别准确性验收，也不代替 D/F 联调。真实模型验证见 test_real_models.py，默认跳过，不下载权重或调用付费服务。
