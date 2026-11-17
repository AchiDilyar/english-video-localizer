# BCDE高层封装与严格单行交付

这是用户最新要求的本地高层封装，不替换F基本节点名、共享GraphState或产物规范；原节点入口继续可用。实现位于project/nodes/localize_video/，测试镜像位于tests/nodes/localize_video/。

## 职能重新解释

| 阶段 | 当前职能 | 输入与交付边界 |
|---|---|---|
| B：素材与原声理解 | 素材登记/获取、媒体探测、英文识别、说话人、原时间表；背景分离与非语言反应筛选 | 向C提供锁定英文及说话人/时间；向E提供经来源校验的environment.wav及source回执 |
| C：双语内容与配音稿 | 术语、分块、翻译、审校、定向内容返工；根据D反馈完整展开或精简配音稿；提供最终双语分句建议 | 输出既有blocks/translated_blocks/reviewed_blocks；配音后的分句服务返回文本方案，不自行决定屏幕排版 |
| D：声音与时长 | 原声复刻、TTS、实测时长、有限变速、音轨安排、触发C局部改稿 | 输出tts_clips、最终实际稿、alignment_report和纯中文dub.wav，不受字幕显示切片影响 |
| E：字幕与成片 | 根据最终音频安排显示时间；中英文按顺序切成单行，优先上下视觉长度均衡；环境混音、压制和交付验证 | 输出三份SRT、ASS、display_cues、mixed.wav、final.mp4；超宽必须再分片，不保留两行例外 |

BCDE是职能模块，不将媒体工具或排版算法冒称为四个新智能体。原翻译/审校角色仍在C内；D测时后调用C语言服务；E可调用C的最终分句建议。C会在配音前后提供服务，并非字母顺序意味着每个角色只能执行一次。F负责图集成、状态与接口协调的定位保留。

## 入口与兼容

节点式入口：from nodes.localize_video import localize_video，签名仍为GraphState→dict，仅返回已定义字段。

图入口：from nodes.localize_video import build_bcde_graph，得到B→C→D→E四阶段LangGraph。阶段入口分别为b_source.run_b、c_content.run_c、d_voice.run_d、e_delivery.run_e。

命令入口：uv run --locked --extra b-asr --extra tts --extra sound-events python -m nodes.localize_video --work-dir <已有工作目录> --input input.mp4。它复用标准CLI的校验、目录、日志和退出规则；run-input仍走原F图。真实ASR、复刻音色、密钥及模型等前置条件与原节点相同，不因封装而自动获得外部权限。

默认阶段按F的mock.toml解析原节点真实/模拟开关，不新增另一套模拟配置。StageServices允许测试或经验证缓存适配器显式注入；必须记录来源，不能将缓存重放说成重新运行真实模型。

## 服务与数据对接

B封装select_source/acquire_source以及separate_background、build_event_features、classify_events、select_nonverbal_regions、restore_nonverbal。模型下载和网络获取继续需要调用方明确参数，不能假称任意链接都能下载。B.publish_environment接收来源证据，将环境音发布为audio/environment.wav；source_sha256和environment_sha256必须与实际文件一致。

C提供plan_bilingual_parts、request_narration_change、audit_content、repair_content。定向服务适配C最新nodes.repair_blocks；默认C阶段按F约定调度repair_blocks，可能增加API审查轮次，异常仍由F代理隔离；D的时长返工仍有既有次数、数字、语义和预算约束。

D采用当前模型rate=1、后处理0.95–1.35，不叠加放慢、不裁句尾。实际最终稿由D落盘供E读取，不能再拿修改前的中文字幕替换最终稿。

E在有environment.wav时验证B的来源回执后重混；不存在时维持原节点的纯配音兼容行为，不声称已恢复背景。环境文件存在但来源缺失或不匹配时明确失败，防止错配。当前测试已提供经过验证的原片背景与非语言人声。

## 严格单行策略

config/subtitle_cover.toml启用paginate=true、strict_single_line=true。每屏允许中文一行、英文一行，禁止任何一种语言内部出现第二行；不截去文字，不改变原字词与顺序。

E优先在中文标点、常见短语边界和英文and/that/while/as等处分切，必要时在完整英文单词之间截断。依据实际字体宽度联合选择两语言切点，优先上下视觉长度接近。用户已明确不要求每屏严格语义等值，因此中英语序相反时允许局部意思不同步，但整句内容和顺序完整保留。不能继续沿用旧的“两行保义”例外。

分成多屏后，根据最终中文音频文本片段安排先后时间；片段内部使用插值，确保时间为正、不交叠、总范围不变。配音、音效、原时间表不变。字体仍只做有限调整，无法安全切分的极长单词报错，不输出两行、越界或丢字字幕。

## 本次验证

五分钟四阶段图验证中B/C/D复用同源真实结果并校验摘要，E真实重跑。83屏全部满足双语各一行，0越界、0丢字、0调序。原两处例外变为81.520–85.900/85.900–88.500秒，以及285.800–287.712/287.712–289.600秒的先后显示。配音和含笑声背景沿用上版，没有新TTS、注册或学校模型调用。

产物、阶段来源和自动检查位于本机tests/tmp/five-minute-bcde-singleline-20261114/；旧实验保留。不能据此声称B/C/D重新全量推理或原始英文识别疑点已人工修正。历史实验中间文件留在本地；2026-11-17源码以独立审核分支交付，详见[跨组交付说明](../localize_video/HANDOFF-20261117.md)。
