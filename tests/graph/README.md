# graph 测试

从仓库根运行 `uv run --locked --extra b-asr pytest tests/graph`。

- test_registry.py：真实/模拟切换只在 registry 发生、未列出默认真实、非法配置失败。
- test_builder.py：完整基本版拓扑、汇合执行一次、失败不进入下游。
- test_b_c_integration.py：真实短片、B/C 真实节点、F 真实工具；B 模型使用已有预测，C 模型使用人工固定响应。审校后的节点使用空增量 mock，断言只校验 B/C 产物。

样例在 tests/data/asr_diarize/real_dialogue 与 tests/data/graph/b_c_dialogue；单文件均小于 1 MB。缺少 NumPy 的基础环境会明确跳过 B/C 媒体联调文件，完整验证需 b-asr。FFmpeg/ffprobe 需 PATH 或仓库本地工具可用。

设置 B_C_F_OUTPUT_DIR 为 tests/tmp 下尚不存在的目录可保留阶段产物；普通 pytest 不使用固定输出目录。全部调用不下载模型、不发起付费接口请求。此测试不代替真实翻译、D/E 或整片人工验收。
