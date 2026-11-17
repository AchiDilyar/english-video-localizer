# mocks 测试

维护者：F｜运行：`uv run pytest tests/mocks -q`｜共 84 条

## 环境

- 需要 `tests/data/asr_diarize/real_dialogue/input.mp4`（仓库内唯一提交的小视频）；
- 需要 `.tools/ffmpeg/bin/ffmpeg.exe` 与 `ffprobe.exe`；缺失时相关用例 `pytest.skip`；
- 不需要 API key，不联网。

## 文件与覆盖

| 文件 | 条数 | 覆盖 |
|---|---|---|
| `test_probe_input.py` | 5 | 快照命中、指纹失配回源、快照缺失回源、ffprobe 缺失、ffprobe 执行失败 |
| `test_asr_diarize.py` | 9 | 正常输出与产物、与上游 fixture 一致、三份数据指纹一致、指纹不符 warning、越界丢弃、全部丢弃返回空、缺 `media_info`、视频缺失、覆盖重跑 |
| `test_build_blocks.py` | 9 | 单块覆盖、术语表透传、`None` 报错、空数组、重复 ID、两个长度阈值、小块无告警、覆盖重跑 |
| `test_translate_blocks.py` | 13 | 静态译文覆盖、数据 ID 一致、重复归属、未覆盖省略、`blocks`/`segments` 空、`None` 报错、重复 ID、译文回退、指纹一致/不符、覆盖重跑 |
| `test_review_blocks.py` | 9 | 透传、覆盖不符、`None`/空数组、重复 ID、覆盖重跑 |
| `test_tts_align.py` | 5 | 空/`None` reviewed、长度对齐音频、缺 `segments`、ID 不在 `segments` |
| `test_subtitle_cover.py` | 2 | SRT/ASS 结构与字段数、覆盖重跑 |
| `test_compose_video.py` | 2 | 成片可解析、ffmpeg 缺失报错 |
| `test_video_helpers.py` | 4 | 指纹与快照一致、`input_path`、缺文件、指纹比对 |
| `test_mock_skeleton.py` | 25 | 模块存在、同名函数、参数名为 `state`、`mock.toml` 键集合（节点清单取自 `graph.registry.NODE_NAMES`；`_*` 内部模块不计入） |
| `test_end_to_end.py` | 1 | `slow`：patch 全 mock 后经 CLI 跑通，校验全部产物与日志 |

## 目录约定

- 工作目录：`tests/tmp/mocks/<模块名>/<用例名>/`，用例前清空、用例后保留，已被 `.gitignore` 排除；
- fixture 自行创建 CLI 的 7 个子目录（`audio/ segments/ translated/ tts/ subtitles/ video/ logs/`），
  因为节点本身不创建目录；
- 端到端用例固定使用 `tests/tmp/mocks/end_to_end/all_mock/`。

## 排查提示

- **指纹或长度断言失败**：演示视频被换过，需重新生成 `project/mocks/data/*.json`（步骤见 `docs/mocks/README.md`）；
- **端到端失败**：先看 `tests/tmp/mocks/end_to_end/all_mock/logs/run.log`，
  里面的 `[xxx]` 标记能直接指出是哪个 mock 的降级分支被触发；
- **`test_end_to_end.py` 不走 subprocess**：它进程内调用 `cli.main`，
  因此不受 `tests/cli` 中 `uv run run-input` 的环境问题影响；
- **`test_mock_skeleton.py` 出现 UserWarning**：`mocks/` 下多了非节点模块（下划线开头的不算）。
