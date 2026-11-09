# B 目录与入口迁移记录

2026-11-09，依据远端 `3d6ac38` 的 architecture、workflow、dataflow、collboration 四份 v1.2.0 文档；未修改设计文档、共享 contracts、F 的图或 mock 配置。

## 位置

| 原位置 | 新位置 |
|---|---|
| `b_pipeline/*.py` | `project/nodes/asr_diarize/pipeline/` |
| `tools/b_media.py` | `project/nodes/probe_input/media.py` |
| `tools/community1_worker.py` | `project/nodes/asr_diarize/community1_worker.py` |
| 旧 FFmpeg、sherpa 模型准备工具 | probe_input/prepare_tools.py、asr_diarize/prepare_sherpa.py |
| 旧结果再识别、说话人处理工具 | `project/nodes/asr_diarize/standalone/` |
| 旧验证、报表、测试素材准备助手 | 对应节点的 `tests/nodes/<node>/support/` |
| 根目录 `tests/test_*.py`（B） | `tests/nodes/probe_input/`、`tests/nodes/asr_diarize/`，内部算法测试继续镜像到 pipeline/ |
| `docs/B*.md`、旧提案 PDF | `docs/nodes/asr_diarize/`；probe_input 新说明在对应文档目录 |
| `docs/examples/B*`、`configs/b_sources*.json` | `tests/data/asr_diarize/`，保留为历史样例，不是当前运行配置 |
| 根目录 B requirements 快照 | `docs/nodes/asr_diarize/environment/` |

新增 `config/probe_input.toml` 和 `config/asr_diarize.toml`，遵循统一 TOML 配置。源码根入口不再依赖 b_pipeline 或 tools 包；历史目录中的 Python 缓存不属于提交内容。测试不修改 sys.path。

按用户要求补齐 project/graph、project/mocks、docs/graph、docs/cli、tests/graph、tests/smoke，用 .gitkeep 跟踪尚无实现的目录。目录存在不代表 F 的 build_graph、registry、mocks 或 CLI 已实现。

## F 导入入口

```python
from nodes.probe_input import probe_input
from nodes.asr_diarize import asr_diarize

graph.add_node("probe_input", probe_input)
graph.add_node("asr_diarize", asr_diarize)
```

输入为 `contracts.GraphState`，输出分别是 `{"media_info": MediaInfo(...)}` 和 `{"segments": list[Segment]}`；新节点只写约定的 source_audio 与 segments，不调用旧 B 子图的输出、检查点或事件日志。最终编号和字段由节点转换，失败直接抛出。

F 的公共路径/配置/读写工具尚缺实现，入口按约定调用，不擅自提供另一套工具；真实主图运行仍依赖 F 补齐。未知说话人的跨组语义尚未确认，暂采取明确失败的方式，避免猜测身份或私自增加共享字段。

## 测试与数据

统一 `python -m pytest tests/nodes`。临时目录与日志放 tests/tmp；小夹具放 tests/data/<module>，大文件放被忽略的 tests/data/_large/<module>。新增的固定语义分界反例只含此前已授权小样的公开词与模型分界，不重跑外部接口。

普通回归使用固定模型替身和合成媒体，不下载模型、不做外部付费调用。小型真实 LangGraph 验证 B 两节点串接、媒体探测、音频提取、状态和写盘顺序；它使用测试版公共服务，不宣称团队全流程已集成。

真实模型测试需显式设置 B_RUN_REAL_MODELS=1；本机使用已缓存 Whisper 模型与独立 Community-1 GPU 环境，读取现有授权访谈的 16 秒音频。未重新下载视频或模型，未完整重跑 80 分钟长片。

迁移期间第一轮 76 项通过、2 项失败，原因是旧 registry 路径仍指向 configs；已改为 tests/data 后继续验证。失败日志保留在 tests/tmp/B-migration-initial-failure.log。此后节点回归 94 项通过；真实 ASR 与 Community-1 stdout 接口两项通过（34.12 秒）。最终完整 pytest 结果以本文后续补充为准。

最终完整 `python -m pytest tests -q`：95 项通过、2 项默认跳过，另有 11 个子测试通过，实测 4.65 秒。两项跳过是上述已单独启用验证的真实模型测试。日志在 tests/tmp/B-layout-final-pytest-02.log 和 B-relocated-real-models.log。顶层测试初次运行因 scoped conftest 太晚设置临时目录而失败；已将该设置放到 tests/conftest.py，默认临时目录统一为 tests/tmp/pytest，未修改 F 的测试或项目依赖。

补充共享固定 segments.json 后，最终复验仍为 95 通过、2 默认跳过、11 子测试通过，4.66 秒；日志 tests/tmp/B-layout-final-pytest-03.log。

提交 36c7344 后用 git archive 导出仅包含已跟踪文件的源码副本，再按默认 pytest 命令运行：95 通过、2 默认跳过、11 子测试通过，4.85 秒。副本不含 models、media 或大测试数据；验证复用本机 Python 3.12 依赖及 FFmpeg，不代表新机器安装或 Python 3.11 验证。日志 tests/tmp/B-layout-source-export.log。

原 jobs/media/model 证据保留，不迁移或改写历史结果；本次代码路径和指纹改变，不能用新代码直接续跑旧检查点。若需历史复现，使用原提交和记录中的环境；若用新代码重做，创建新任务。

当前测试环境 Python 3.12，尚未验证团队 Python 3.11 的全套模型依赖。英文及说话人准确性人工验收、D 音色联调、F 主图验收仍未完成。DeepSeek 本次作用：无新调用，只有历史响应的离线回归。
