# asr_diarize 测试

从仓库根运行 `python -m pytest tests/nodes/asr_diarize`。不要直接运行测试文件。

- `test_asr_diarize.py`：字段/编号转换、主要说话人、未知/未定时间拒绝、写盘失败；真实小型 LangGraph 串接 B 两节点，用真实 FFmpeg 和固定模型替身验证产物与状态。
- 其他 `test_*.py`：语义分句、复识别、归属算法、Community-1 输出、下载边界和历史算法回归。
- `support/`：历史验证/样片准备助手，普通 pytest 不触发其中的下载或识别 main，不作为直接执行测试的入口。
- 固定小样例在 `tests/data/asr_diarize/`；大样片在被忽略的 `tests/data/_large/asr_diarize/`，普通回归不依赖它们。
- 临时数据和日志在 `tests/tmp/`；conftest 为 pytest 的 tmp_path 设置专用 basetemp。原有 jobs/media 证据不修改。

需要 pytest、Pydantic、LangGraph、spaCy 和英文模型；模拟调用测试还需 faster-whisper 可导入；媒体测试需要 FFmpeg。旧 Python 3.12 依赖快照在 `docs/nodes/asr_diarize/environment/`，不证明团队 Python 3.11 已验证。

模型替身测试不等于识别准确性验收，也不代替 D/F 联调。真实模型验证见 test_real_models.py，默认跳过，不下载权重或调用付费服务。
