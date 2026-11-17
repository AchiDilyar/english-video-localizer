> 2026-11-17 更新：下方早期流程记录保留历史参考。当前唯一主图仍为 graph.build_graph；--input 支持任务内文件名、原视频显式绝对路径或 YouTube 链接。新任务直接读取首次素材位置，不复制原片；最终输出为 video/final.mp4。详见 [现行输入数据流](../design/dataflow.md) 与 [WebUI说明](../webui.md)。

# CLI 模块文档

维护者：F｜代码：`project/cli.py`｜入口：`run-input`

**实现依据**：
- `architecture.md` 2.2 / 2.3 - 文件位置与目录职责
- `architecture.md` 4.2 - mock 透明
- `architecture.md` 6.1 / 6.5 - 路径函数与使用约束
- `architecture.md` 7.1–7.4 - CLI 入口、参数、出口、职责边界
- `architecture.md` 第 8 节 - 节点失败行为
- `architecture.md` 9.1 / 9.2 - 测试与日志组织
- `architecture.md` 第 10 节 - uv 运行
- `dataflow.md` 第 3 节 - 产物表
- `dataflow.md` 第 4 节 - 工作目录结构
- `dataflow.md` 5.1 / 5.4 - 路径使用与输入文件约定
- `workflow.md` 第 3 节 - 节点清单
- `contracts/state.py` - `GraphState` 字段

正文只记录实现，不重复上述事实源。

---

## 1. 定位

流水线唯一对外入口/出口，薄壳，业务全在图内。

---

## 2. 参数

`argparse` 解析，`prog="run-input"`；本模块只做解析，不做额外校验（校验在 `main`）。

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--work-dir` | `.` | 工作目录，必须已存在 |
| `--input` | `input.mp4` | 任务内文件名、原视频绝对路径（只读，不复制）或单条 YouTube 链接 |
| `--report-progress` | 关 | 记录主图 tasks 事件到 `logs/node-progress.jsonl` |
| `--authorize-voice-clone` | 关 | 确认原声授权，仅本次任务；通过环境变量 `LOCALIZER_AUTHORIZE_VOICE_CLONE` 传给节点，调用结束恢复原值 |

---

## 3. 执行流程

```text
解析参数
→ 检查 work_dir 存在且为目录
→ set_work_dir(work_dir)
→ setup_logging(work_dir/logs/run.log)        # 同时创建 logs/
→ _prepare_input_video：文件名原样；绝对路径原样；YouTube 链接下载或复用
→ _check_input_video：artifact_path("input_video", input_filename) 必须存在且为文件
→ _create_subdirs：audio segments translated tts subtitles video
→ GraphState(input_video=input_filename)
→ build_graph()
   ├─ --report-progress：_stream_with_progress(...)
   └─ 否则：graph.invoke(...)
→ 输出 artifact_path("final_video")
→ 返回 0
```

异常路径：`main` 记录日志后原样抛出；进程入口 `run()` 捕获后返回退出码 1。

---

## 4. 实现决策

- **日志前置**：工作目录检查通过后立即 `setup_logging`，因此输入缺失、链接下载失败也会留下 `logs/run.log` 作为排障依据。
- **`logs/` 不在 `_SUBDIRS`**：由 `setup_logging` 内部 `mkdir` 创建，避免两处重复创建；其余 6 个业务子目录由 `_create_subdirs` 创建。
- **输入不复制**：绝对路径原样放进 `GraphState.input_video`；YouTube 源保存在共享素材目录（`media/downloads`），`artifact_path("input_video", ...)` 对绝对路径原样返回。
- **子目录列表硬编码**：`logs/` 不在产物规格表中，无法从 `ARTIFACT_SPECS` 推导。
- **初始 State 只传 `input_video`**。
- **进度观测内联**：`_stream_with_progress` 是 CLI 私有实现，用 `graph.stream(..., stream_mode="tasks")` 代替 `invoke`，不新增节点、不改调度。

---

## 5. 错误处理

```python
except Exception as exc:
    logger.exception("运行失败: %s", exc)
    raise
```

- 日志未初始化时（工作目录不存在或不是目录），`logger.exception` 走 `lastResort` 到 stderr；
- 入口 `run()` 只把异常转换为退出码 1，因此控制台只有一份“消息 + traceback”（`StreamHandler`），解释器不再补打第二份；
- 程序化调用 `main()` 仍会收到原异常。

---

## 6. 测试

`tests/cli/test_cli.py` 与 `tests/cli/test_progress.py`，运行 `uv run pytest tests/cli`。

| 用例 | 断言 |
|---|---|
| work_dir 不存在 / 不是目录 | 抛 `FileNotFoundError` / `NotADirectoryError`，`caplog` 含“运行失败” |
| 输入视频不存在 | 抛 `FileNotFoundError`，工作目录只留 `logs/`，`run.log` 含“输入视频不存在” |
| 输入是目录 | 抛 `IsADirectoryError` |
| 正常流程（fake 图） | 返回 0，7 个子目录与 `logs/run.log` 存在 |
| 图中抛异常 | 抛原异常，`run.log` 含异常类型与 traceback，stderr 含“运行失败” |
| YouTube 链接 | 下载/复用后 `GraphState.input_video` 为返回的文件名 |
| 音色授权开关 | 每次调用独立设置 `LOCALIZER_AUTHORIZE_VOICE_CLONE`，结束后恢复原值 |

`setup_logging` 会 `handlers.clear()`，用 autouse fixture 保存/恢复 root logger handlers 与 level。

---

## 7. 汇报要点

- **薄入口**：`cli.py` 不 import 任何节点/适配器，业务全在图内。
- **事实源驱动**：默认值、路径、子目录、日志位置均落在上表依据范围内。
- **mock 透明**：CLI 完全不知道跑的是真实还是 mock，便于演示与单测解耦。
- **单一错误链路**：节点抛 → 图终止 → `main` 记录并重新抛出 → 入口 `run()` 转非 0 退出；控制台一份 traceback，`run.log` 一份完整栈。
- **可测试**：`main(argv)` 接受参数列表，配合 `tmp_path` + `monkeypatch` 覆盖成功/失败路径，无需真实视频或完整 mock。
