# B 对附件规范的逐项核对

日期：2026-11-09。基准提交：a19ffa4。已逐份读取 Downloads 中的 architecture.md、workflow.md、dataflow.md、collboration.md、CHANGELOG.md；按 UTF-8 文本归一换行比较，五份均与仓库 docs/design 的内容一致，均为当前 v1.2.0 文档集。

结论：B 的目录迁移与标准入口基本属实，但此前还存在旧识别函数内部重建音频路径、子进程诊断没有统一转发的细节。本次已修正。**B 的接口检查通过不等于整个项目已满足全部设计并能运行**；F 的基础实现仍缺失。

## B 范围核对

| 规范依据 | 实际检查与结果 |
|---|---|
| architecture §2.4、workflow §3 | probe_input 和 asr_diarize 两个包位于 project/nodes，分别导出同名函数；其余 B 算法、适配器放节点内部。符合。 |
| architecture §3 | 两入口输入 contracts.GraphState，返回 media_info 或 segments 增量；列表不追加，不修改原 State。固定模型测试在真实 LangGraph 中验证，未假定库内部一定调用 model_copy。 |
| dataflow §3、§5.2 | MediaInfo 只进状态；全片 WAV 写 source_audio，list[Segment] 先经 write_artifact 写盘，再返回增量；不额外保存原始词对齐或 B 报告。写失败会抛出。 |
| architecture §6、dataflow §5.1 | 共享产物路径由公共 artifact_path 提供，结构化输出交给 write_artifact。复核发现旧适配函数会重建 audio.parent/audio.name，本次抽出 recognition.py，直接消费已解析路径；保护测试禁止调用旧 artifact。 |
| architecture §5 | 运行配置为 config 下 TOML，经公共 load_config 获取，再由 B 的模型验证；不修改 F 的 mock.toml。旧 JSON registry 只是 tests/data 中的历史夹具。 |
| architecture §8、§9.2 | 共享节点错误直接抛出，局部复识别启用 strict_errors，不捕获后静默降级；logger 使用 __name__。本次将成功子进程的 stderr 诊断转交父节点 logger；失败诊断随异常由上层 CLI 处理。 |
| dataflow §5.3 | 全片毫秒整数，正时长；最终生成 seg_0001 / spk_1 等编号，字段为 text_en，固定分段例子通过共享 Segment。未知说话人或未定时间短语明确失败，不伪造可用数据。 |
| architecture §9.1 | 测试镜像放 tests/nodes，内部算法继续放 pipeline 子目录；测试数据在 tests/data，单文件小于 1 MB，大数据及临时目录受忽略。测试不改 sys.path。 |
| architecture §9.1 临时文件 | tests/conftest 设置默认 tests/tmp/pytest；本次补充禁止默认收集 tmp、data，避免临时源码副本产生重复测试。 |
| architecture §4.6 | 真实节点不导入项目 mocks 或 tests；测试替身仅在 tests 内注入。基本版真实节点不启用旧子图/CLI/检查点；本次将历史 pipeline API 改为按需导入。 |
| collaboration §4–5 | 未修改共享 contracts、docs/design、F 的图/registry/mock 配置或项目锁文件。本次不是设计变更，不擅自更新设计版本和 CHANGELOG。 |

工作目录与子目录仍由 CLI 预先准备，B 不在共享节点中创建。项目/文档/测试中的空目录使用此前已提交的 .gitkeep 跟踪；空目录不算已实现功能。

## 整个仓库仍未完成的设计要求

1. F 的 project/utils/paths.py、io.py、config.py、artifacts.py 尚未提交；当前只有 log.py 及其导出。B 的 integration.py 只转发约定调用，缺依赖明确失败，不实现另一套路径/产物管理。
2. project/graph、project/mocks 目前只有占位文件；build_graph、registry、模拟切换和 config/mock.toml 尚未实现。B 的小型图测试不能代替完整主图。
3. project/cli.py 及 run-input 统一入口未实现，因此全项目的目录初始化、日志初始化、异常栈记录和最终 ZIP 出口尚不能验收。
4. 仓库仍有 src/video_localizer 历史示例，pyproject 的打包目标仍是该包；统一到 project 架构的安装/运行方式需由 F 协调，不在本次擅自迁移其他组内容。
5. 本机 B 测试为 Python 3.12；团队 Python 3.11 下完整依赖与运行仍待验证。未知说话人语义、C/D/F 联调以及人工英文/人物核对也未验收。

同步时队友新增 06f2c13（含 E 文件交接与 WebUI 原型）。project/e_handoff.py 尚未拆成 workflow 中的 E 节点，web/ 与独立服务入口也不属于 v1.2.0 基本版主流程；需 F/E 后续协调归并。本次仅修复其依赖 B 旧路径的导入，不擅自重构其他组业务或将其当作已经符合标准的主图。

因此此前“已按要求整理并提供节点入口”可以成立；若理解为“整个团队项目已严格全部满足规范、下载源码即可跑完”，则不成立。

## 本次验证

- `python -m pytest tests -q`：97 项通过、2 项真实模型测试默认跳过，另 11 个子测试通过；6.05 秒。新检查覆盖已解析音频路径直接使用、无额外写盘及 worker 诊断日志归属。
- 显式启用单项真实 ASR 测试：1 项通过，3.35 秒；读取已有授权访谈的 16 秒本地音频，验证新内存算法连接；不重跑整片。Community-1 的模型和 stdout 协议未改变，本次只模拟验证新增日志转发，没有重复真实模型运行。
- 首次完整 pytest 因 tests/tmp 中旧源码副本被误收集而失败，修正 collect_ignore 后通过；失败日志保留在 tests/tmp/B-design-audit-20261109.log，成功日志为 B-design-audit-20261109-02.log、B-design-audit-real-ASR.log。
- 既有 80 分钟结果和历史任务未修改；本次未新下载媒体/模型、未调用 DeepSeek 或付费 API，未上传凭据、模型或测试大文件。

## 同步队友提交后的补充验证

- 新 E 测试最初因独立 B 环境未装团队已有的 imageio-ffmpeg 而无法收集。已安装 pyproject 中原有的 imageio-ffmpeg、Pillow 开发/运行依赖，没有更改共享依赖声明或锁文件。
- E 模块与测试仍引用已迁移的 tools.b_media。改为 nodes.probe_input.media，并统一为以 project 为根的 contracts / e_handoff 导入；未改变 E 的数据转换和媒体业务逻辑。
- E 的字幕断言将 Windows CRLF 归一为 LF 后检查内容与时间，不改变实际字幕。此前运行 97 通过、1 因换行差异失败，修正后 E 单测通过。
- 修正 E 文档中过期的 B 路径/链接，明确原型消费历史任务，记录源码运行需要的模块搜索路径；没有把 E 的 spk_unknown 原型规则当作 F/D 已确认的共享规则。
- 最终同步后的全仓库 `python -m pytest tests -q`：**98 通过、2 默认跳过、11 子测试通过，5.65 秒**；日志 tests/tmp/B-audit-after-team-sync-final.log。源码环境下 E 命令帮助检查通过。新 E 单测实际验证合成媒体到预览 ZIP，不代表真实译文、真实配音或团队全流程验收。
