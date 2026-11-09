# B 长视频：完整下载、分块识别与全片台词表

更新：2026-11-07。本次沿用已有 LangGraph B 子流程，不更换团队主图。新增完整文件下载和分块 ASR；旧45秒样片及用户人工核对记录保持原样。

**已完成真实43分05.85秒课程：22块识别，674原片段、6,774词、480候选句子分组；33项检查通过。** [打开成果与运行证据](B-long-video-run-20261107.md)。全课人工正确性尚未核验，具体限制见记录。

## 1. 支持的两种路线

1. **完整下载后分块识别**：登记项 kind=https_file，按HTTP文件字节下载，保留原MP4，不为了下载重新编码；然后提取全片WAV并按块识别。适合长视频与可靠续传。
2. **只取长视频中的一段**：仍可用 kind=https_excerpt，通过FFmpeg取指定区间。该路线不具备字节级断点续传，失败需重新读取该节选；完整文件续传走第一条路线。

本地文件同样支持分块。当前单片时长参数可配置到3600秒（60分钟）；默认仍120秒，避免误启动长任务。扩大上限不等于已经在所有长度和视频类型上验证。

## 2. 登记与接口

[完整MIT课程登记示例](../configs/b_sources.long.example.json)，ID为 mit-python-full，使用之前核验过的 MIT OCW / Ana Bell 6.0001 第一讲，CC BY-NC-SA4.0，原课偏移0。

新增 kind=https_file，只需要登记可信的公开HTTPS媒体地址、来源页、许可、署名和人工确认授权状态；可填 expected_sha256（若有可信原始清单）。程序实际计算的哈希用于追踪，不冒充发布方公布的哈希。

现有 list_sources、select_source、run_b、resume_b、load_timetable 接口保留。run_b 新增可选参数：

| 参数 | 默认 / 范围 | 用途 |
|---|---|---|
| max_duration_sec | 默认120，最大3600 | 全片时长上限；超过120默认启用120秒分块 |
| chunk_seconds | 默认短片不分；长片120，允许1–300 | 每块目标时长 |
| chunk_search_seconds | 默认5，范围0–10 | 目标切点附近寻找静音的范围 |
| asr_chunks_per_invocation | 默认None；可设正整数 | 每次最多计算多少新块，达到后保存并暂停；已完成块不计入新块数量 |
| asr_time_budget_sec | 默认600，最大600 | 每次识别在块与块之间检查的时间预算，不是可强制打断本地推理内核的硬超时 |
| download_timeout_sec | 默认180，最大600 | 每次下载总时限；单个阻塞网络操作另有最长15秒超时 |
| max_source_bytes | 默认256MiB，最大1GiB | 完整下载/本地输入的文件大小上限 |
| prepare_timeout_sec | 默认180，最大600 | 全片音频准备子进程超时 |
| pause_download_once_bytes | 默认None | 验证用：第一次下载到指定字节数主动暂停，恢复后不再同样暂停 |

示例命令（输出目录必须是新的；尚未运行的任务名只是示例）：

```powershell
.\.venv\Scripts\python.exe -m b_pipeline run --input mit-python-full --registry configs/b_sources.long.example.json --model-dir models/faster-whisper-base.en --job-dir jobs/B-long-new --allow-network --max-duration-sec 3600 --chunk-seconds 120 --asr-chunks-per-invocation 5 --download-timeout-sec 300 --max-source-mib 256

.\.venv\Scripts\python.exe -m b_pipeline resume --job-dir jobs/B-long-new
```

每次完成5个新块后返回 paused，再执行 resume 继续。下载超时或网络错误会保留可校验的部分文件；修复原因或确认仍有进展后明确恢复，不无限循环重试。**现有实际产物不需要为查看效果重新运行。**

## 3. 下载如何恢复

下载器位于 b_pipeline/downloads.py：

- 部分文件保存为 source/video.mp4.part，状态保存在 video.mp4.download.json。
- 保存来源URL哈希、已保存字节数、部分文件SHA-256、ETag或Last-Modified、预期完整长度和各次请求记录。
- 恢复前核对部分文件大小和哈希，发送 Range 和 If-Range；只在206返回的 Content-Range 起点、总长度及校验标识匹配时追加。
- 服务器忽略Range返回200时，不把新完整文件接到旧字节后面；旧部分文件另存 discarded 文件，重新写入。
- 无可靠校验标识时不假装支持安全续传；从头重读并保留旧部分文件。
- 429/部分5xx/连接中断可在单次时限内有限重试，默认最多2次；不跳过字节，不把截断文件当成成功。
- 成功后核对完整长度、可选发布方哈希，记录实际文件哈希，再交给媒体探测。

主动暂停、正常网络异常与超时会保存部分文件状态；**强制杀进程或突然断电可能导致部分文件与上次状态不一致，此时拒绝盲目追加，需人工检查**。目前没有宣称实现任意时刻断电恢复。

HTTP字节范围和验证器依据 [RFC9110](https://www.rfc-editor.org/rfc/rfc9110.html)。代码采用Python标准库，不调用收费下载器，也不绕过登录、DRM或站点访问限制。

## 4. 分块不改变全片时间轴

先用既有媒体工具生成全片16000Hz、单声道PCM16 WAV，保留视频起点与静音。切块操作以整数采样帧为准：上一块end_frame等于下一块start_frame，覆盖全片，没有重复音频或漏掉的间隔。

目标切点附近±5秒寻找连续至少300ms、RMS小于250（PCM16单位）的安静区间，取其附近中点；这是工程启发规则，不是经过语料验证的通用VAD。找不到就保留目标切点，明确标记 hard_cut_requires_boundary_review。不能据此保证没有切到单词。

每块保留自己的WAV、原始ASR JSON和元数据。汇总时：

```text
全片秒数 = 本块起始采样帧 / 16000 + 模型给出的块内秒数
原课毫秒数 = 全片毫秒数 + original_offset_ms
```

不删除静音，不把后半片的时间重新从0开始。每块后端原始预测不覆盖；汇总副本仅进行明确的时间平移与全局ID分配。

台词表新增可选追踪信息：segments 中的 source_chunk_id、chunk_segment_id、raw_chunk_ref；asr.raw_chunks 中包含块原始文件引用、哈希和起始采样帧。original_segments_coordinate_system 明确说明原片段列表是否是从分块坐标平移得到的全片副本。

最原始的块内文字、词时间和分数保存在 asr/chunks/*.raw.json；全片时间版保存在 asr/raw.json。不能将平移后的秒数误称为模型直接输出的局部秒数。分组仍额外提供，不覆盖这些原始证据。

## 5. 块级恢复

LangGraph仍由transcribe节点负责识别，但节点内部有持久化的块级日志和缓存：每完成一块立即保存原始预测、音频哈希、模型/代码/参数签名。节点中断后重新进入，会验证并复用已有块，仅计算未完成块。

这不是“每块一个独立LangGraph节点”；图检查点与内部块缓存共同实现恢复。下游分组、校验和导出在全部识别完成后执行。原始块文件或音频被修改时拒绝复用；不通过降低检查标准掩盖损坏。

由于请求包含代码和模型指纹，升级前的旧任务不能直接用新代码继续执行。旧结果仍可读取，旧源码快照仍保留；要续跑旧代码可使用原版本，或明确建立新任务。不要手工改request指纹假装版本未变化。

## 6. 验证与正确性边界

新增检查涵盖：正确Range恢复、服务器忽略Range、错误Content-Range/变化的ETag、部分文件被改、文件大小限制、5xx有限重试、静音切点、连续讲话时的标记、切块音频字节一一覆盖、块时间平移、块级暂停复用和缓存损坏拒绝。

这些能证明工程路径与数值映射，不证明ASR英文准确率。硬切点附近可能有断词、漏词或重复预测；本版不通过静默删除词来“修复”这些问题。需要抽查切点附近的原音、块尾/块首和汇总表，再决定引入重叠上下文及可追溯对齐策略。

长课可能含学生提问。当前仍未接自动说话人区分；single_assumed是全片单人假设，不等于实际只有讲师讲话。多人标签与长片全部内容不能沿用之前45秒样片的人工核对结论。

长片最终结果、真实耗时、失败记录与检查证据见本轮运行记录；模型与工具都在本地，无付费API，DeepSeek未参与。

## 7. 词时间与片段边界不一致时

本次真实长片发现8处词起点早于所属原片段起点。最新标准输出以原片段与所有所属词的时间包络确定片段边界，并在 timing_adjustment 中保存原起止、调整量与原因；原始片段、每个词、原始块JSON都保留。调整后仍严格检查范围、顺序、精确包络及追踪关系，不允许解释不清的时间变化。

这只解决数据结构内部不一致，不证明词对齐更准确；需要按原音抽查。

## 8. 已有识别结果重新整理，无需重跑模型

新增 `reexport_b(source_job, job_dir)`，只导入旧任务已完成且哈希一致的素材、音频、ASR和分组，创建新的后处理任务。它不伪造旧检查点，不绕过旧代码指纹恢复限制，也不调用ASR或网络。

```powershell
.\.venv\Scripts\python.exe -m b_pipeline reexport --source-job jobs/B-LangGraph-long-MIT-20261107-01 --job-dir jobs/B-long-reexport-new
```

```python
from b_pipeline import reexport_b
result = reexport_b('jobs/B-LangGraph-long-MIT-20261107-01', 'jobs/B-long-reexport-new')
```

这是确需更改整理/导出规则时的迁移方式。正常查看已完成结果不需要重新导出；现有长片成果直接打开即可。导入后保存新代码指纹、来源清单及原执行信息，ASR耗时属于原真实识别，不冒充新任务推理耗时。
