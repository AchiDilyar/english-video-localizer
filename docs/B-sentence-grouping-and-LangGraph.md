# B 句子分组交付与 LangGraph 接入说明

日期：2026-11-07。保留已有识别结果，额外提供句子分组；没有冻结团队共享接口，也没有接管 F 主图。

后续已实现并运行 B LangGraph 子流程：[接口与命令](B-LangGraph-API.md)、[真实运行记录](B-LangGraph-run-20261107.md)。下文“尚未运行 LangGraph”为当时历史状态，最新以这两个入口为准。

## 1. 本次已完成

原始 ASR 的 18 段保留，新增 11 个候选句子分组，148 个词的原始时间、文字与后端分数全部保留。没有再次运行 ASR。

- [合并前后视频对照页](../jobs/B-MIT-sentence-groups-20261107/comparison.html)：浏览器打开，点击时间可重听。
- [分组 CSV](../jobs/B-MIT-sentence-groups-20261107/sentence-groups.csv)：逐组来源、起止、原文拼接、阅读版本和原因。
- [分组 JSON](../jobs/B-MIT-sentence-groups-20261107/sentence-groups.json)：含 original_segments 和 sentence_groups，不覆盖旧文件。
- [执行信息](../jobs/B-MIT-sentence-groups-20261107/execution.json)：文件哈希、完整命令与实际耗时。
- [样片专用分组方案](examples/B-MIT-sentence-plan.json)、[生成脚本](../tools/group_sample_sentences.py)、[验证代码](../tests/test_sentence_groups.py)。

| 新分组 | 原始片段 | 样片时间（秒） | 说明 |
|---|---|---|---|
| 1 | 1 | 0.000–2.360 | 保留；片头可能句子不完整 |
| 2 | 2 | 3.180–4.900 | 独立句 |
| 3 | 3、4、5 | 6.400–13.700 | 合并授课安排、补充说明及关系从句 |
| 4 | 6 | 14.360–16.040 | 保留独立句 |
| 5 | 7、8 | 16.660–22.260 | 合并课程安排介绍 |
| 6 | 9、10 | 23.640–25.560 | computation 不再单独成为一组 |
| 7 | 11、12 | 26.160–30.440 | 合并逗号后的目的说明 |
| 8 | 13 | 31.420–33.580 | 独立句 |
| 9 | 14、15 | 34.180–36.920 | 合并 operations 与 you can do with Python |
| 10 | 16 | 38.100–40.520 | 独立句 |
| 11 | 17、18 | 41.320–44.820 | 合并前置说明与后文；结尾截断，未补造缺失内容 |

分组由 Codex 根据当前样片语境提出，尚未获得用户对每一组的逐项确认。用户已反馈“除分段外没有错误”，但这不等于声纹识别或本轮具体分组通过人工验收。全部 SPEAKER_00 仍明确为单人假设。

## 2. 保留与变更的边界

每组包含 source_segment_ids、start_sec/end_sec、en_exact_join、en_reading、reason 和 words。words 每项含 source_segment_id、source_word_index 和原样 word_data，能定位回原始预测。

en_exact_join 只按顺序拼接原文本；en_reading 用于阅读，可以做有记录的标点、大小写调整。本次只有原段14+15移除句中句号并把 You 改为 you，词汇没有增加、删除或替换。两种版本均保留。姓名 Anna 等其他原始内容未静默修改。

合并后开始取首段开始、结束取末段结束，保留组内静音间隔，不拉伸或重算任何词时间。原始识别结果文件哈希保持不变。

这份分组是翻译的语义参考，不自动成为字幕条目或配音窗口。D/E 可继续用原片段；若需按整句配音或重新切字幕，应与 C/F 一起确认中文与时间的对应规则。

当前生成脚本使用绑定原始 ASR 哈希的样片专用方案，不是对任何视频都能用的自动句子检测器。换视频会拒绝复用，避免把当前手动分组当成通用科研结论。后续泛化需要单独实现候选规则、语义复核及新样片验证。

## 3. 识别到底用了什么

| 层次 | 本次实际使用 |
|---|---|
| 识别实现 | faster-whisper 1.2.1 |
| 识别模型 | Whisper 英文 base.en 的 CTranslate2 转换版，Systran/faster-whisper-base.en |
| 推理引擎 | CTranslate2 4.8.5 |
| 执行位置 | 本机 CPU，int8，4 线程；没有使用 GPU 或云端 API |
| 关键参数 | language=en、beam_size=5、temperature=0、word_timestamps=True、vad_filter=False |
| 依赖兼容 | PyAV 16.1.0；首次 PyAV 19 解码失败已保留 |
| 说话人 | 没有运行 diarization；SPEAKER_00 为假设标签 |
| 本轮句子整理 | 样片专用的明确分组方案与 Python 校验，无额外大模型调用 |

模型修订、哈希和依赖锁见 [ASR 运行说明](B-ASR-review-20261107.md)。Whisper 模型负责听声音；faster-whisper/CTranslate2 负责本地执行；LangGraph 负责把任务步骤组织起来，三个层次可以同时使用。

## 4. 满足 LangGraph 要求还要做什么

目前尚未安装或运行 LangGraph，现有 Python 脚本不能宣称已完成多智能体框架。按 [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)，普通函数可以成为读取状态、执行处理并返回更新的节点；不要求 ASR 本身是大语言模型智能体。

F 在统一主图中接入：

```text
素材准备(B) → 本地ASR(B) → 句子分组(B) → 分组校验(B/F)
                                      ├─有问题 → 待复核/修改分组
                                      └─通过 → 翻译智能体(C) → 审校智能体(C)
                                                        ├─需修改 → 返回翻译
                                                        └─通过 → 配音(D) → 字幕/编辑(E) → 成片
```

每个职责不一定都单独成为节点，具体粒度由 F 统一确定。ASR 和分组属于工具/处理节点；翻译、审校、中文编辑才是当前规划里的三个智能体。仅把几个普通函数串在 LangGraph 中，不足以证明已经实现多智能体协作，还需要真实智能体及其反馈路由。

B 向 F 提供：

1. 原始转写文件、模型参数和词时间；后续可将本地推理封装为可调用函数。
2. 当前可调用的 `group_bundle(raw, plan, source_bytes)`，返回分组及原始片段副本，不修改输入对象。
3. 输出路径/版本/哈希、验证结果与错误；当前命名只用于本地示范，按 F 最终共享合同适配。

F 负责：

1. 在共享状态保留 raw_asr_ref、sentence_groups_ref、源哈希、分组方案版本、审核问题等信息；这些字段名是建议，未冻结。
2. 包装 B 函数为节点，在节点正常完成并校验后返回状态更新；失败不伪装成功，不直接交给 C。
3. 将节点接到统一 StateGraph，编译并实际运行。用日志显示 ASR → 分组 → 翻译的实际调用。
4. 配置 SQLite 检查点和任务标识，恢复时核对文件与参数；已完成 ASR 不因单纯改分组重复运行。
5. 分组变更后重新检查依赖其上下文的译文；如 D/E 改用组边界，也需使相关音频/字幕失效，不复用错误缓存。
6. 展示一次真实返工与中断续跑，保留对照、节点日志与产物。不要把读取旧 ASR 文件的演示称为“图内已运行真实 ASR”。

最小节点适配示意（未执行的接入示例，不是已验证主图）：

```python
from pathlib import Path
import json
from tools.group_sample_sentences import group_bundle

def b_sentence_group_node(state):
    source_bytes = Path(state['raw_asr_ref']).read_bytes()
    raw = json.loads(source_bytes)
    plan = json.loads(Path(state['group_plan_ref']).read_text(encoding='utf-8'))
    result = group_bundle(raw, plan, source_bytes)
    # F 统一负责原子保存产物并返回其路径；这里仅示意节点如何返回新增状态。
    return {'sentence_groups': result['sentence_groups'],
            'grouping_source_sha256': result['source_asr_sha256']}

# F 在共享状态中声明上述字段，再在现有主图加入节点与边。
# builder.add_node('b_sentence_groups', b_sentence_group_node)
# builder.add_edge('b_asr', 'b_sentence_groups')
# builder.add_edge('b_sentence_groups', 'c_translate')
```

上述样片方案绑定本次转写；新任务必须先获得自己的分组方案，不能直接复用。主图共享模型、条件路由、检查点及产物写入仍由 F 落地，不在 B 里另建竞争主图。

## 5. 验证、命令与限制

5 项针对性检查通过：保留输入和词时间、拒绝漏/重/乱序覆盖、拒绝改写词汇、允许标点/大小写调整、拒绝误用源文件。实际样片也独立检查了全部18段和148词一一覆盖，原始 ASR 文件哈希未变。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_sentence_groups.py -v
.\.venv\Scripts\python.exe tools/group_sample_sentences.py --asr-json jobs/B-ASR-MIT-base-en-20261107-02/asr.raw.json --plan docs/examples/B-MIT-sentence-plan.json --video media/mit_ocw_6_0001_lecture1/mit_lecture1_0060_0105.mp4 --output jobs/B-MIT-sentence-groups-new
```

已有结果无需重跑。当前生成耗时约0.008秒，不含编写、检查及人工交互；模型调用0、付费调用0、显存未测/不适用。全部运行产物位于忽略目录 jobs/，未推送远程；DeepSeek 未参与。

素材是 Ana Bell / MIT OCW 6.0001 Fall 2016，原课60–105秒节选。转写、候选分组、标点整理为新增处理，分享时保留来源、修改说明及 [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)。
