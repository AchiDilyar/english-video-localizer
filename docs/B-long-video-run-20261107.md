# 长视频实际运行：43分05.85秒 MIT 完整课程

日期：2026-11-07，北京时间。入口：[长视频使用说明](B-long-video.md)、[B接口](B-LangGraph-API.md)。这是本地真实下载和模型推理，不是模拟数据。

## 1. 最终可查看产物

- [完整视频与英文台词页](../jobs/B-LangGraph-long-MIT-20261107-final/review.html)
- [切点重点核对页](../jobs/B-LangGraph-long-MIT-20261107-final/boundary-review.html)：21个内部切点，18个需重点检查的硬切点；可播放切点前后各5秒。
- [完整 MP4](../jobs/B-LangGraph-long-MIT-20261107-final/source/video.mp4)
- [台词表 JSON](../jobs/B-LangGraph-long-MIT-20261107-final/timetable.json)
- [原片段 CSV](../jobs/B-LangGraph-long-MIT-20261107-final/segments.csv)、[句子分组 CSV](../jobs/B-LangGraph-long-MIT-20261107-final/sentence-groups.csv)、[词时间 CSV](../jobs/B-LangGraph-long-MIT-20261107-final/words.csv)
- [证据汇总](../jobs/B-LangGraph-long-MIT-20261107-final/long-evidence-summary.json)、[测试日志](../jobs/B-LangGraph-long-MIT-20261107-final/tests.stderr.txt)

HTML应与其任务目录一起保留；视频位于 source/video.mp4，不能只拷HTML到其他位置。文件在忽略目录 jobs/，不会自动随 Git 推送。

## 2. 真实输入和结果

来源为 MIT OCW / Ana Bell，6.0001 Introduction to Computer Science and Programming in Python, Fall 2016，Lecture 1: What is Computation?，来源与许可在 configs/b_sources.long.example.json，CC BY-NC-SA4.0。

| 项目 | 实测 |
|---|---|
| 完整视频时长 | 2585.850秒，即43分05.85秒 |
| 完整文件大小 | 101,137,401字节，约96.45MiB；不是整次网络流量统计 |
| 视频SHA-256 | 06236664b370ca2309aa5e74918a36a39512fad690ad9938d50b776217c02dcf |
| 音频块 | 22块，目标120秒；优先静音附近切点，尾块较短 |
| 原片段 | 674段，保留原始块预测及全片平移副本 |
| 词记录 | 6,774个，保留后端词时间和来源 |
| 候选句子分组 | 480组，独立于原片段 |
| 各块ASR推理耗时合计 | 195.243秒，不含所有下载、加载、恢复和人工交互 |
| 测试 | 33项通过，0跳过；运行器报告1.048秒 |

模型仍为本地 faster-whisper 英文 base.en，CPU int8、4线程、beam5、temperature0、词时间开启。没有使用云端语音服务、付费API、GPU训练或DeepSeek。

## 3. 完整下载与续传证据

[下载请求记录](../jobs/B-LangGraph-long-MIT-20261107-final/download-resume-proof.json)记录了：

1. 从字节0开始，按验证配置在2,097,152字节处主动暂停。
2. 恢复请求从2,097,152字节开始，服务器返回206；达到本次180秒时限时，已保存96,468,992字节，未删除部分文件。
3. 再从96,468,992字节继续，服务器再次返回206，完整长度达到101,137,401字节后完成。

ETag与总长度在续传时匹配，部分文件哈希在恢复前核对。这里没有把源站的200完整响应误追加到旧数据，也没有因第二次时限到达从头下载。首个43分钟素材处理任务为 jobs/B-LangGraph-long-MIT-20261107-01。

实际网络传输总字节数、整次下载总墙钟、峰值内存、整体交互耗时未单独完整测量，记为unknown；不以最终文件大小或195秒推理时间替代它们。

## 4. 分块与恢复证据

[分块计划](../jobs/B-LangGraph-long-MIT-20261107-final/asr/chunk-plan.json)以整数采样帧描述覆盖范围。已独立检查第一块从0开始，相邻块首尾连续，最后一块结束等于全片WAV帧数；另用合成音频逐字节检查切块重组不丢失、不重复音频。

真实识别按5、5、5、5、2个新块分批执行。恢复时核对并复用已完成块，每个真实块只推理一次。全片平移结果已逐块从原始JSON重建核对：global=start_frame/16000+local；后半片没有重新从0计时。

每块原始JSON、WAV、执行时长和哈希都保留在 asr/chunks/。没有“每块一个LangGraph节点”的虚假表述：图内 transcribe 节点使用持久化块缓存，图检查点与块缓存共同支持恢复。

## 5. 遇到的问题与修正

22块都完成后，第一版校验阻止了导出，原因是8处后端词起点比父片段起点早20–220ms。该失败结果保留在 [原始任务校验](../jobs/B-LangGraph-long-MIT-20261107-01/validation.json)和 draft-timetable.json，未删除。

修正没有修改模型词时间或重新识别，而是明确引入“标准片段包络”：标准起点取原片段与所属词起点的最小值，终点取最大值；原始片段和词记录不变。每处差异带 timing_adjustment，列明原起止、调整量和原因；句子分组的展示时间跟随标准边界，原组时间仍保留。

[8处调整记录](../jobs/B-LangGraph-long-MIT-20261107-final/timing-adjustments.json)可逐条审计。已检查调整后没有产生片段交叠；仍需满足全片边界、原词一致、精确包络与显式理由，不能随意扩窗逃过检查。

由于代码版本已改变，没有手工篡改旧任务指纹强行续跑。使用新增 reexport_b 把原任务已完成产物逐个验哈希后导入新任务，仅运行 LangGraph 的 validate_timetable → export_timetable。**新任务没有重新下载、没有重新推理**；ASR结果仍来自前述完整43分钟真实运行。

最终任务为 jobs/B-LangGraph-long-MIT-20261107-final，包含原始输入清单、来源任务请求、原始块预测、源码快照、校验和导出。原始674段及6,774词在导入前后完全一致。

## 6. 验证范围与下一步

33项检查包括原媒体、来源/授权/范围、句子分组、真实LangGraph条件路由、断点下载协议、块时间映射、音频覆盖、暂停缓存复用，以及必须显式记录的包络调整。HTTP异常单元测试用模拟响应；真实服务器的两次206续传另有上述记录。

全片结构和时间映射检查通过，不等于全课英文、词边界与句子分组人工验收。旧45秒样片已获用户人工确认，此结论不自动扩展到43分钟。

实际21个内部切点中，3个满足当前安静区规则，18个为硬切点。硬切点附近可能断词或误识别，需使用重点核对页检查。当前仍没有自动说话人区分，全片SPEAKER_00仅是单人假设；讲师与学生提问不能据此算作自动识别成功。

目前配置上限为60分钟、源文件默认256MiB（可配到1GiB），实际验证的是本片43分钟，不宣称其他片长、视频站点和多人素材均已通过。下一步先检查18个硬切点与8处时间整理，再按证据决定是否引入重叠上下文与对齐去重。

付费服务调用0，费用0，本地电费/网络费unknown。失败、原始输出和真实耗时保留；无远程推送，无邮件/群消息，无DeepSeek调用。
