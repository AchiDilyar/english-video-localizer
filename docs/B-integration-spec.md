# B 模块详细对接方案

版本：0.1-draft；日期：2026-11-07。配套 [接口提案](B-interface-proposal.md)、[人工 JSON 样例](examples/B-transcript.mock.json)、[执行计划](B-execution-plan.md)、[整体规划](project-plan.md)。

这是拟实现合同，不是现有 API 文档。仓库当前尚未实现这些函数、命令或模型适配器。标为候选的名称可由 F 统一调整，调整后必须同步调用方、样例和测试。

## 1. 工作流与所有权

```text
B: CLI 参数 → F: run/resume 调度
                 ↓
     B: 素材解析 → 媒体检查 → 音频归一化 → ASR/说话人 → 标准转写/翻译块
                 ↓
     C: 翻译 → 审核 ──问题──→ F 路由回 C
                 ↓
     D: TTS/测时 ──超时──→ F 路由到 C 重写与复审，再回 D
                 ↓
     E: 中文编辑/字幕/合成 → F: 检查未解决问题 → 正式 ZIP 或待复核报告
```

- B 拥有素材清单、原始转写、标准英文分段、全片时间与说话人标签。C/D/E 不能覆盖这些文件。
- F 拥有图状态与恢复策略。节点返回新增产物引用，不直接改写其他节点文件或共享可变字典。
- C 拥有中文稿、术语与审校记录，D 拥有音色映射、音频与时长，E 拥有编辑文案、字幕和成片。
- B–E 负责各自正常/异常检查；F 负责全图与对照评测。内容返工次数按片段累计，每段最多两次；首次生成不计返工。技术重试单独计数，不能通过重新生成任务绕开上限。

## 2. 共享数据与标识

所有 JSON 使用 UTF-8；时间字段整数毫秒，不能接受浮点数或布尔值冒充整数。字段缺失和 null 有不同含义；下表未声明可空的必填字段不能用 null。

### 2.1 标识

| 标识 | 所有者与范围 |
|---|---|
| job_id | F 创建的一次执行任务 ID |
| asset_id | 素材登记 ID，B 分配；单独使用不足以证明文件内容相同 |
| content_sha256 | 原片字节 SHA-256；下载和本地输入均在真实模式计算 |
| transcript_revision | 该素材的转写版本，如 r0001；英文、分段、说话人或时间改变则递增 |
| segment_id | 本素材转写版本内唯一，如 seg_000001；完整引用为 asset_id + transcript_revision + segment_id |
| chunk_id | 本素材转写版本内唯一的翻译块编号 |
| text_revision | C 对单个片段中文内容的版本；D 缓存必须包含实际 zh_dub 内容与版本 |

格式版本提案使用 `0.1-draft`。未经冻结不宣称兼容未来版本；加载方检查版本并拒绝未知版本。格式冻结后新增可选字段可讨论兼容；改名、类型或语义变化需要版本升级和迁移说明。

### 2.2 TranscriptBundle 必填字段

| 字段 | 类型 | 说明 |
|---|---|---|
| schema_version | string | 本轮为 0.1-draft |
| asset_id / transcript_revision | string | 非空；下游结果回传两者 |
| mode | mock 或 real | 不允许失败后静默切到 mock |
| language | string | 本项目首版 en |
| duration_ms | integer | 原片统一时间轴的总时长，必须 > 0 |
| source | object | kind、content_sha256、manifest_ref；人工样例的哈希与引用可空 |
| audio | object 或 null | 真实模式提供归一化音频引用和格式；人工纯文本样例可空 |
| provenance | object | ASR/说话人后端、模型版本、参数引用；未知值显式 null |
| speakers | array | 说话人标签表，含 label_method |
| segments | array | 按时间排序的短片段 |
| chunks | array | 翻译块的 ID 引用，见下节 |
| issues | array | 尚未解决的问题，空数组表示无记录问题 |

`source.kind` 候选值为 local / registered_url / synthetic。`manifest_ref` 指向任务根目录内的素材清单。真实输出 `content_sha256` 为 64 位小写十六进制字符串；人工样例必须明确 synthetic，不编造哈希。

`audio` 字段为 path、sample_rate_hz、channels、sample_format、timeline_origin_ms；提议归一化为 16000 Hz、单声道、PCM s16le WAV，`timeline_origin_ms=0`。这只是 ASR 输入，原片保留供 E 合成。该参数属于团队提议，实际后端若需变更先同步，不能在未验证时宣称兼容。

### 2.3 speakers、segments 和 chunks

`speakers` 每项：`speaker_id`、`label_method`。方法取 synthetic / single_speaker_assumption / diarization / manual_verified。标签只代表全片同一个声音，不表示真实人物身份，不把假设写成识别结论。

`segments` 每项必填：

| 字段 | 类型 | 规则 |
|---|---|---|
| segment_id | string | 唯一非空 |
| speaker_id | string 或 null | 非空值须存在于 speakers；无法判断时为 null 并添加阻断 issue |
| start_ms / end_ms | integer | 0 <= start_ms < end_ms <= duration_ms |
| en | string | 非空英文转写；原始错误与后续更正均可追溯 |
| words | array 或 null | 可选细粒度证据；不可用时为 null，不平均分配伪造词时间 |

`words` 非空时每项为 text、start_ms、end_ms，必须位于父片段内、按时间排序，首版非重叠模式下词区间不得交叠。不声明通用 confidence：后端分数含义不同，需要时在原始输出保留原字段及定义。

正常首版 segment 不交叠，但允许静音间隔。检测到重叠语音要记录阻断 issue；可保存供诊断的重叠片段，但不能继续当作已验证普通配音输入。没有识别到语音不生成空的成功结果，返回 NO_SPEECH。

`chunks` 每项为 `chunk_id`、`segment_ids`、`context_before_ids`。segment_ids 为本块本次要生成结果的片段；全部块拼接后必须恰好覆盖所有 segment，一次且有序。context_before_ids 最多引用前一块结尾两个片段，不计入本块输出，第一块为空。

分块按首段开始至末段结束的跨度在自然句边界向约 60–90 秒聚合；最后一块可短。长静音、超长句、说话人切换先保留真实边界，超过目标记录 warning，由 B/C/F 约定细化；绝不为凑时长裁掉文字。chunk 不代表连续可播放音频。

## 3. 时间轴和媒体处理

1. B 用媒体探测记录视频、所选音轨的起点、时基、时长与音轨索引，多音轨时记录选择。未经确认不随意切换音轨。
2. 全片时间 0 定义为原片演示时间轴起点。音轨较晚开始要补前置静音；较早开始则按原片起点裁齐，并记录转换。VAD 可以跳过静音计算，但不得压缩输出时间轴。
3. 分块处理时，将后端局部时间加切块偏移；音轨起点差异已在归一化中消除，不能再次加一遍。
4. 秒到毫秒使用十进制非负数的半入舍入：floor(seconds * 1000 + 0.5)，避免各模块自行 round。只转换一次，随后始终用毫秒。小于 1 ms 的区间若舍入后坍缩，不自动扩展，记入诊断并重新分段或人工检查。
5. 小负数、越界或交叠不静默截断成合法结果；如确需修正，保留原值、依据和新转写版本。
6. 英文修改后检查词时间戳是否仍有效；不再匹配则重新对齐或置 null 并说明。下游中文长度变化不改变 B 时间轴。
7. E 复用同样的原片起点与媒体流处理约定；先用带已知声画标记的测试素材核对起点，再用真实片头/中/尾检查同步。不能仅凭 JSON 数值合法宣称音画同步。

## 4. 候选 Python 调用接口：B ↔ F

以下是职责签名，不是可直接导入的实现。共享类型提议由 F 汇总，B/C/D/E 审核各自字段。

```python
parse_cli(argv: list[str]) -> RunRequest | ResumeRequest
resolve_source(request: RunRequest, context: JobContext) -> AssetManifest
probe_media(asset: AssetManifest, context: JobContext) -> MediaInfo
extract_audio(asset: AssetManifest, media: MediaInfo, context: JobContext) -> AudioArtifact
transcribe(audio: AudioArtifact, media: MediaInfo, config: ASRConfig,
           context: JobContext) -> TranscriptBundle
validate_bundle(bundle: TranscriptBundle) -> ValidationReport
```

- `transcribe` 封装 ASR、全片说话人归属、标准化和分块；内部适配器可拆分，不要求全部写成一个大函数。
- RunRequest 包含 input、mode、sources_file、fixture、asr_model、speakers_mode、audio_stream_index；speakers_mode 提议为 single / diarize。ResumeRequest 仅 job_id，不接受替换 input 或模型。
- JobContext 由 F 提供 job_id、任务根目录、事件记录器和经团队确定的资源限制。根路径由 F 解析一次；产物引用统一相对任务根目录，读取时验证没有逃逸。
- ValidationReport 包含 valid、blocking_issue_ids 和 errors。`valid` 指结构与不变量通过；阻断问题另由 F 检查，即使结构正确也不能发布。
- 节点失败抛 ModuleError，由 F 统一序列化。节点不直接退出进程；只有顶层 CLI 转成退出码。
- F 在校验成功后写入状态引用；B 不持有 SQLite 连接，不自行推进任务状态。整文件原子写入后才更新引用。

建议共享类型模块 `localizer/contracts.py`、B 模块 `localizer/ingest/`、命令解析 `localizer/cli.py`、F 图与执行入口 `localizer/workflow/`。都是候选路径，首轮由 F 统一创建骨架；B 只开发自己路径，避免同时修改主图。

## 5. CLI 对接

下列命令为拟议语法，当前不可执行：

```powershell
# 人工样例联调：mode 与 fixture 均显式指定
python -m localizer run --input .\media\demo.mp4 --mode mock --fixture .\docs\examples\B-transcript.mock.json
# 本地真实转写，具体模型标识由本机资源配置确定
python -m localizer run --input .\media\demo.mp4 --mode real --asr-model <model-id> --speakers-mode single
# 已登记链接，示意 ID 必须换成登记表内实际视频 ID
python -m localizer run --input "https://www.youtube.com/watch?v=<registered-id>" --sources-file .\sources.json --mode real --asr-model <model-id> --speakers-mode diarize
# 同一任务恢复，配置从原任务清单读取
python -m localizer resume --job <job-id>
```

mock 可以在不打开媒体的情况下加载人工转写，输入路径此时仅作模拟来源标识，并明确输出未做媒体验收；它不是本地媒体读取通过的证据。real 必须检查媒体、依赖和配置，缺失则失败。不得缺省启动真实收费调用；提议 run 强制显式指定 mode。

B 负责参数合法性、互斥检查与帮助信息；F 负责创建 job、加载模型/工作流适配器、resume、状态和退出码。`--help` 不初始化模型、不读密钥、不发网络请求。

## 6. 素材登记和链接解析

sources.json 留本地，模板只放虚构值。候选结构：

```json
{
  "schema_version": "0.1-draft",
  "entries": [
    {
      "youtube_id": "AbCdEf12345",
      "asset_id": "demo_001",
      "media_url": "https://media.example.org/authorized-demo.mp4",
      "authorization_status": "pending",
      "authorization_note": "Replace with a verified permission reference.",
      "expected_sha256": null
    }
  ]
}
```

上例为虚构、待授权，不可用于验收。real 模式只允许 authorization_status=confirmed 且依据非空的条目；本地素材也登记授权状态。B 负责记录证据，不能由模型自动判断获得授权。

只接受明确允许的 YouTube URL 主机和路径形式，解析 watch?v=ID、youtu.be/ID；本轮不支持播放列表、起始时间裁片或任意 URL 直传。未知形式返回 INPUT_UNSUPPORTED。下载对象只能来自登记表的 HTTPS 地址。

B 负责流式下载、大小/超时限制、失败中间文件清理、实际哈希与预期哈希核对；F 提供显式配置的 timeout、max_bytes、重试上限和预算。不能将“未知大小”当作无限大小。每次重定向重新校验 HTTPS 与团队允许主机，日志仅记录 asset_id 与去敏 URL 标识；原始带令牌地址不进报告。下载完成前不将临时文件当成可复用输入。

## 7. C / D / E 的详细交接

### 7.1 B → C：翻译和审校

C 接收 TranscriptBundle 与 chunk_id，按 segment_ids 顺序输出。context_before_ids 是只读上下文，不得重复返回译文。共享术语表由 C 维护，F 保存其版本并参与下游失效判断。

C 结果候选字段：schema_version、asset_id、transcript_revision、chunk_id、glossary_revision、items、issues。

items 每项：segment_id、text_revision、zh_subtitle、zh_dub。返回 ID 集合必须等于该 chunk 的 segment_ids，不重、不漏、不出现外部 ID；中文非空。B 原片段时间不拷贝到可修改译文，合并时由 F 按 ID 关联。

审校 issue 包含具体 segment_ids、owner=C、code、reason、suggestion、blocking 和 status。若怀疑英文识别错误，返回 owner=B 的问题交 F，不能自行改英文并假装是原始转写。术语更新后，F/C 检查哪些已有译文受影响，不能只更新术语表而保留冲突成片。

### 7.2 B → D：说话人、窗口和配音

D 按 speaker_id 建立全片固定音色映射。窗口默认 `[start_ms, end_ms)`，可容纳时长为 end_ms-start_ms。未确定说话人的片段先停在待复核状态，不随机选音色。

D 接收 B 时间轴与 C 的 zh_dub/text_revision，返回 asset_id、transcript_revision、segment_id、text_revision、voice_id、audio_path、raw_duration_ms、playback_rate、final_duration_ms、status、issues。时长来自实际音频，不能以字数估计冒充测量。

status 提议为 ready / needs_rewrite / blocked。所需速度为 raw_duration_ms/window_ms；若 <=1 则补尾部静音；若 >1 且 <=1.15 可加速，处理后仍需实测；若 >1.15 或实测仍超时返回 needs_rewrite。分段音轨应占满该窗口，窗口外静音由 D 在全片组装时补齐。不因毫秒舍入导致误判，D/F 在实现中用样本数核对，并记录采样率和舍入规则。

F 将 needs_rewrite 的指定片段交 C 重写与复审，仅这些片段重新 TTS；其他音频通过缓存校验后复用。两次内容返工后仍失败保留 blocked 报告，不能无限循环。

### 7.3 B → E：字幕与成片

E 使用 B 的英文与原时间，关联 C 的 zh_subtitle 生成双语字幕；使用 D 已组装中文轨替换原混音。E 负责字体、换行、字幕文件和封面，保留原画面并核对原片时长与起点。

默认字幕沿用短片段边界。若需拆为多个字幕 cue，可以创建子 cue ID，但保留 parent_segment_id；所有子区间位于父段内，不能复制或遗漏文本。若必须跨越或改变原片段边界，返回请求给 F/B，不直接覆盖 B 数据。

E 检查 B/C/D 的素材和转写版本匹配；正式 ZIP 前 F 检查所有必需产物存在、模式符合验收、阻断问题已解决。mock 发布包名称与报告必须标明模拟，不算真实成片验收。

## 8. 统一问题与错误处理

Issue 为可保存的质量反馈：issue_id、segment_ids、owner、code、reason、suggestion、blocking、status。status 为 open / resolved，解决记录由处理模块追加，F 汇总；不能简单删除问题当作解决。

ModuleError 表示节点未完成：code、stage、asset_id（未知可空）、segment_ids、message、retryable。不含异常堆栈里的密钥或敏感 URL。详细去敏诊断写本地日志。

| code | 责任处理 | 自动重试建议 |
|---|---|---|
| INPUT_NOT_FOUND / INPUT_UNSUPPORTED | B 解释输入错误 | 否 |
| SOURCE_NOT_REGISTERED / SOURCE_UNAUTHORIZED | B 补登记或授权依据 | 否 |
| DOWNLOAD_TIMEOUT / DOWNLOAD_LIMIT / HASH_MISMATCH | B 诊断；F 决定重试 | 仅 timeout 可在配置上限内重试 |
| DEPENDENCY_MISSING / MODEL_UNAVAILABLE | B 检查实际环境 | 否，不静默换模型 |
| MEDIA_INVALID / AUDIO_MISSING / NO_SPEECH | B 检查素材与音轨 | 否 |
| TIMELINE_INVALID / DUPLICATE_ID / VERSION_MISMATCH | 产生该数据的模块修正 | 否 |
| SPEAKER_UNCERTAIN / OVERLAPPING_SPEECH | B 复核或换素材 | 作为阻断 issue，不循环识别 |
| ASR_FAILED | B 诊断原始错误 | 默认否；只有明确瞬时故障再标 retryable |

F 提议顶层退出码：0 成功；2 CLI 参数错误；3 素材/配置/数据错误；4 运行故障；5 已保存待复核结果。退出码本轮须团队确认；B 函数内部不返回进程退出码。

## 9. 产物、状态和续跑

候选目录（均相对仓库根，jobs/ 已在 .gitignore）：

```text
jobs/<job_id>/
  job.json                         # F：冻结配置、模式、状态、资源限制
  ingest/asset.json                 # B：来源、授权依据引用、原片哈希/路径
  ingest/media.json                 # B：流、起点、时基、时长
  ingest/audio.wav                 # B：全片归一化音频
  ingest/asr.raw.json               # B：原始转写与后端信息
  ingest/diarization.raw.json       # B：适用时保存原始说话人结果
  ingest/transcript.r0001.json      # B：通过结构校验的标准产物
  translate/                       # C：按版本保存译文、术语、审核记录
  dub/                             # D：音色映射、音频、时长、缓存清单
  render/                          # E：字幕、封面、成片、ZIP
  logs/events.jsonl                # F 定事件结构，各模块写去敏事件
  report.json                      # F：产物索引、模式、指标、未解决问题
```

SQLite 文件位置由 F 统一配置，不让每个模块各建一份检查点库。每阶段成功产物原子写入，F 再登记完成状态。恢复时同时核对状态和文件存在/哈希，不能仅看 SQLite 中的 completed。

B 转写缓存输入至少包括：模式、原片哈希、音轨选择、音频归一化参数与实现版本、ASR/说话人模型精确标识和可得的修订、影响输出的配置、分段实现版本、schema_version。模型版本无法确认时禁用跨任务复用并注明限制。同名路径不代表同一素材。

D 缓存另包含 transcript_revision、segment_id、zh_dub 实际内容、text_revision、TTS 模型、音色、参数和窗口。仅凭 ID 一致不能复用。

修改转写时保留旧文件，新建 r0002；首版建议 F 使整个旧转写版本的翻译/配音/成片失效，优先保证正确。只改某段中文时可局部使该段音频和最终合成失效。术语更新要由 C/F 确认受影响段，不能无证据直接复用。恢复不是允许忽略配置变化。

## 10. 联调安排与验收矩阵

| 步骤 | 发起/参与 | 输入 | 交付与通过条件 |
|---|---|---|---|
| 1 冻结合同 | F + B/C/D/E | 本提案、各自需求 | 字段、类型、责任、命令与错误确认；记录版本，不靠口头猜测 |
| 2 离线读取 | B → C/D/E/F | 人工 JSON 样例 | 各模块读入；C 返回精确 ID 集合；D/E 时间无需额外换算 |
| 3 异常合同 | B–E 自测，F 汇总 | 故意改坏样例 | 重复 ID、负值/倒序/越界、未知说话人、漏段、版本不符均被定位 |
| 4 模拟全图 | F + B–E | 同一人工分段、模拟模型与 WAV | 正常/审校退回/TTS 超时/中断恢复；说明复用哪些产物 |
| 5 真实短片 | B 先跑，F 接入 | 有权使用的清晰短片 | 原始输出、时间轴与文字抽查、配置与耗时；不以“能运行”代替质量 |
| 6 首版验收 | F 组织，B–E 参与 | 10 分钟双入口；2–3 分钟双人 | 完整真实发布包；至少 10 处交接检查；保留失败与人工更正 |
| 7 长任务 | F 组织 | 30/60 分钟样片、明确资源上限 | 30 分钟任务中断续跑；记录实耗、复用与失败，不要求掩盖失败 |

专门的时间轴用例：

- 局部 1.25–2.5 秒、切块偏移 60000 ms，应输出 61250–62500 ms。
- 1.2345 秒应转换为 1235 ms；1.2344 秒为 1234 ms。
- 片段 5000–7000 ms 后接 9000–11000 ms，中间 2000 ms 静音保留。
- 非零音轨起点先归一化；恢复后的第一个声音与原画面标记一致，防止多加或漏加起点。
- 初始译文返回两个 ID，修改后不能少一个；context 引用不得多返回一条。
- 依赖缺失或网络失败时 real 必须失败，不回落到 mock。

当前人工样例只验证合同阅读和时间/ID关系，不代表真实识别、字幕质量或声画同步。本版不先规定未经数据支持的识别准确率门槛；真实实验前 B/F 记录参考标注方法与可接受误差，不能看完结果再改标准。

## 11. 交付、变更与团队沟通

建议第一份 B PR 包含接口文档、人工样例、参数解析与校验、针对边界/单位/ID 的检查和运行说明；第二份接入真实适配器并附实际证据。PR 至少一位队友审核；共享接口由 F 和受影响模块共同审核。本文不代替远程认领 Issue 或发送消息。

交给 F 的说明模板：

```text
模块：B 素材与语音识别
接口版本：<实际版本>
实现提交：<实际 SHA，未提交写未提交>
模式：mock / real
输入：<素材或人工样例>
调用方式：<已实际运行的命令/函数>
输出：<文件/字段与任务 ID>
已验证：<检查、日志与实际结果>
未完成/阻塞：<具体问题及需要谁协助>
耗时/显存/调用量/费用：<实测；未测写 unknown>
需要 F/C/D/E 确认：<具体字段或行为>
```

任何命名、字段、时间单位、版本或路径变更，先提出影响范围，再更新合同、样例、校验与调用方，不静默修改。交给 A/G 的材料仅使用已经获得的证据；DeepSeek 本轮未参与。
