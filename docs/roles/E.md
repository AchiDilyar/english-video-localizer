# E · 字幕、封面与成片

**交付物**为中文编辑智能体、可播放的中文配音 MP4、独立双语 SRT、中文封面 JPG、发布文案和完整 ZIP。

| 需要的输入 | 对接人 |
|---|---|
| 原视频、片段 ID、英文文本和毫秒时间戳 | B |
| 通过审校的中文字幕及可供中文编辑使用的文本 | C |
| 按原片时间轴对齐的中文音轨 | D |
| 任务状态、运行报告和输出目录约定 | F |

- [ ] 先用模拟的中英文本、短视频和 WAV 跑通双语字幕与中文配音合成。
- [ ] 验证 SRT 与成片一致，长字幕换行、相邻时间戳和中文字体渲染正确。
- [ ] 生成中文标题、简介与封面文案，再用 Pillow 生成封面。
- [ ] 打包前确认 MP4 可播放，ZIP 包含成片、SRT、JPG、发布文案和运行报告。
- [ ] 提交正常合成与字体或渲染失败的验证记录给 F，提供一段成片给 A 和 G。

下一步可先实现 SRT 生成，使用模拟输入确认片段顺序、时间格式和中英行顺序，再联调渲染。

| 日期 | 完成事项 | 证据或文件 | 阻塞与下一步 |
|---|---|---|---|
| 2026-11-07 | 搭好共享 Python 环境，验证中文封面、双语字幕烧录和 H.264/AAC 成片 | `uv run --locked python scripts/check_environment.py` 通过。已抽查成片帧和封面的中文显示 | 用模拟时间戳和双语文本开始实现 SRT 生成 |
| 2026-11-07 | 准备中文编辑可复用的 DeepSeek JSON 调用接口 | `video_localizer.deepseek.generate_json` 已通过模拟 HTTP 和 LangGraph 翻译审校返工验证 | 配置密钥后验证真实接口。E 继续用模拟双语片段开发 SRT |
| 2026-11-09 | 重制节点 WebUI，增加 11 节点的 118 项参数草稿、撤销重做、本地保存与 JSON 导入导出，以及字幕与封面预览 | `web/`、`docs/webui.md`；`tests/webui.spec.cjs` 通过桌面与移动端交互检查；Python Ruff 与 JavaScript 语法检查通过 | 配置仍为 UI 草稿，真实视频渲染和参数执行待 B–F 接入；本次未推送远程 |

## B → C / D → E 文件联调

B 的标准入口已迁为 `nodes.probe_input.probe_input` 和 `nodes.asr_diarize.asr_diarize`，见 [B 节点说明](../nodes/asr_diarize/README.md)。以下 E 文件交接工具仍消费历史 sentence-v2 的完整任务目录（timetable.json、media.json、request.json、source/video.*），不是标准节点主流程；不要把历史格式要求当作新的 B 接口。

运行以下历史文件交接命令前，将仓库 project 设为模块搜索根目录：PowerShell 使用 `$env:PYTHONPATH = (Resolve-Path project).Path`，bash 使用 `export PYTHONPATH="$PWD/project"`。pytest 已在团队配置中设置该搜索路径。

在团队项目根目录，先将该任务转换为共享分段：

```bash
uv run --locked python -m project.e_handoff prepare \
  --b-job jobs/b-sample --work-dir jobs/e-sample
```

`prepare` 校验 B 表结构、原片哈希、视频流和时长，写入 `segments/segments.json` 与 `handoff.json`。分段 ID 与说话人 ID 在同一次交接内稳定，交接表保留 B 的句子 ID、原说话人和复核标记。缺少说话人归属时记录 `spk_unknown`，D 需要先确认音色归属。B 的句子级英文和毫秒时间不被重写。

`spk_unknown` 是此文件交接原型的处理方式，尚不能视为 F/D 已冻结的共享策略；当前标准 B 节点遇到未知说话人会明确报错，等待策略确认。

| 放到同一交接目录的文件 | 交付方和约定 |
|---|---|
| `translated/reviewed_blocks.json` | C。使用 `list[TranslatedSegment]`，每个共享分段恰好有一份审校译文 |
| `audio/dub.wav` | D。从视频时间零点开始的整条 PCM WAV，包含段间静音，时长与 B 时间轴一致 |
| `editor.json` | E。暂由操作者填写 `title`、`description`、`cover_text` 三个 JSON 字符串，符合 `EditAssets` |

```bash
uv run --locked python -m project.e_handoff render \
  --b-job jobs/b-sample --work-dir jobs/e-sample --edit-assets jobs/e-sample/editor.json
```

成功时输出 `jobs/e-sample/e-preview/package/review.zip`。ZIP 包含烧录双语字幕的 H.264/AAC MP4、SRT、ASS、中文封面、文案、产物清单和复核报告。合成使用带 libass 的 FFmpeg，并需要可用中文字体。可通过 `LOCALIZER_FFMPEG`、`LOCALIZER_FFPROBE` 和 `LOCALIZER_FONT_PATH` 指定本机路径。输出按待人工审阅处理；真实样片需要复核句子、音色交接、配音同步、字幕换行与封面显示。

`render` 会复核 B 表和交接分段，拒绝缺段、重复译文、原片变化和整轨时长偏差超过 50 ms 的输入。当前 C/D 产物需要组员确认来自同一任务。正式图接入时由 F 绑定任务 ID 与产物版本，并调用 E 的媒体处理逻辑。当前文件入口未替代 F 的主图、检查点和产物工具。

联调测试使用符合 B 导出格式的固定英文转写、固定中文译文和一条测试音轨，实际生成 E 的 MP4 与 ZIP。运行 `uv run --locked python -m pytest -q tests/test_e_handoff.py` 可复现。WebUI 顶部的「字幕查看」页可对照源视频查看 B 的识别初版及断句后字幕。

## 下一版交接约定

这节记录 E 的下一版实现要求，供与 B、C、D、F 联调。上面的审阅包仍可用于验证旧原型。合入正式主图前由 F 同步节点、产物规格和清单契约。

- **英文字幕留在任务内。** B 产生英文 SRT 初稿和结构化分段。C 从分段读取 `segment_id`、原文和时间轴，执行翻译初稿、审校、定向修正与有限次数复审。英文 SRT 可作为内部校对副本。C 用结构化分段保留说话人和时间戳，审校通过后再交 E。
- **字幕压制与封面分开。** E 将通过审校的中文与 B 的英文按 ID 关联，生成内部双语 SRT。根据用户选择的模板和输入画面尺寸生成 ASS，生成带中英样式的 ASS。FFmpeg 用 ASS 烧录画面，同时保留既定的配音音轨处理。以输入视频流的平均码率作为重编码目标，并保留分辨率、宽高比和帧时间轴。实测码率可能有偏差，验收时同时记录源值和输出值。取不到原视频流码率或无法保留编码参数时，先记录原因，再按团队确认的策略处理。
- **封面默认关闭。** 本地视频勾选后由用户提供原封面。YouTube 链接勾选后从同一视频的元数据获取缩略图。用 OCR 或视觉模型检查有无待翻译文字。有则调用可配置的图像编辑模型，将原文字换成中文并尽量保留画面、构图和字体风格。无待翻译文字则原样保留图片字节、尺寸和格式，跳过编辑请求。因为原图可能是 JPEG、PNG 或 WebP，正式产物路径需支持实际扩展名。
- **发布包汇合。** F 汇总压制后的成片和封面分支。封面关闭时，清单省略封面。封面开启时，展示封面结果或失败原因。最终结果统一展示发布包，英文和双语 SRT、ASS 留在任务目录供处理和排查。

建议先落地模板选择、双语 SRT 到 ASS 和 FFmpeg 参数保留，再做独立封面适配，最后由 F 将两个分支接入结果汇总。首轮用横屏 720p、1080p 和 2160p 短视频检查样式与码率，用有文字和无文字的原封面检查编辑与原样保留行为。

## 批量制作 ASS 样张

`config/subtitle_styles.json` 是浏览器和 E 压制共用的模板配置。修改三类样式的 1080p 基准字号、描边、阴影和边距后，运行：

```bash
uv run --locked python -m project.subtitle_templates --output jobs/subtitle-style-samples
```

命令生成 27 份带示例字幕的 ASS。可加 `--font-name` 指定本机已安装的字体名称，然后用 Aegisub 或 FFmpeg 逐类预览。实际审阅包使用 `LOCALIZER_FONT_PATH` 指定字体，并用 `render --subtitle-style <clean|cinema|contrast> --subtitle-layout <zh_only|zh_top|zh_bottom>` 选择样式。内部双语 SRT 保留中文在上、英文在下，画面上的语言顺序由 ASS 决定。

自动匹配规则按画面高度选档，720 及以下用 720p，721–1080 用 1080p，更高用 2160p。ASS 脚本宽度按原画面宽高比计算。首版验收横屏，竖屏仍可通过当前入口，暂用同一套规则且不承诺排版效果。WebUI 的模板选择随项目保存，接入主图后再传给正式压制节点。
