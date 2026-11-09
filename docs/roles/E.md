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

B 的现行入口是 `python -m b_pipeline run`。它在自己的模型环境运行，交付完整任务目录，包含 `timetable.json`、`media.json`、`request.json` 和 `source/video.*`。请使用 sentence-v2 的已导出任务。B 的测试记录和模型环境见 [B 交接说明](../B-README.md)。

在团队项目根目录，先将该任务转换为共享分段：

```bash
uv run --locked python -m project.e_handoff prepare \
  --b-job jobs/b-sample --work-dir jobs/e-sample
```

`prepare` 校验 B 表结构、原片哈希、视频流和时长，写入 `segments/segments.json` 与 `handoff.json`。分段 ID 与说话人 ID 在同一次交接内稳定，交接表保留 B 的句子 ID、原说话人和复核标记。缺少说话人归属时记录 `spk_unknown`，D 需要先确认音色归属。B 的句子级英文和毫秒时间不被重写。

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

联调测试使用符合 B 导出格式的固定英文转写、固定中文译文和一条测试音轨，实际生成 E 的 MP4 与 ZIP。运行 `uv run --locked python -m pytest -q tests/test_e_handoff.py` 可复现。WebUI 中选择「转写与说话人 → 预览 → 打开 B 时间表」可查看 B 导出的前 20 句和未知说话人数量。
