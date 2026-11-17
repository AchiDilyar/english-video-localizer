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

`argparse` 解析，`prog="run-input"`；本模块只做解析，不做额外校验。

---

## 3. 执行流程

```text
解析参数
→ 检查 work_dir 存在且为目录
→ set_work_dir(work_dir)
→ 检查输入视频存在（artifact_path("input_video", args.input)）
→ 创建子目录：audio segments translated tts subtitles cover video package logs
→ setup_logging(work_dir/logs/run.log)
→ GraphState(input_video=args.input)
→ build_graph().invoke(state)
→ 输出 artifact_path("final_zip")
→ 返回 0
```

---

## 4. 实现决策

- **先检查后副作用**：输入视频缺失时不创建子目录、不写日志。
- **`logs/` 由 CLI 创建**：列入子目录列表；`setup_logging` 内部的 `mkdir` 保留为防御，与 CLI 创建幂等。
- **子目录列表硬编码**：`logs/` 不在产物规格表中，无法从 `ARTIFACT_SPECS` 推导。
- **初始 State 只传 `input_video`**。

---

## 5. 错误处理

```python
except Exception as exc:
    logger.exception("运行失败")
    print(f"运行失败: {exc}", file=sys.stderr)
    raise
```

补充实现细节：日志未初始化时 `logger.exception` 走 `lastResort` 到 stderr，摘要仍由 `print` 保证可见。

---

## 6. 测试

`tests/smoke/test_cli.py`，`uv run pytest tests/smoke/test_cli.py`，`tmp_path` 造临时目录与空 `input.mp4`。

| 用例 | 断言 |
|---|---|
| work_dir 不存在 | 非 0 退出，stderr 含摘要 |
| 输入视频不存在 | 非 0 退出，且不创建任何子目录（含 `logs/`） |
| 正常流程（mock 全开） | 返回 0，stdout 含 `package/final.zip`，9 个子目录与 `logs/run.log` 存在 |
| 图中抛异常（monkeypatch `build_graph`） | 非 0 退出，`run.log` 含异常类型与 traceback |

`setup_logging` 会 `handlers.clear()`，用 autouse fixture 保存/恢复 root logger handlers 与 level。

---

## 7. 汇报要点

- **薄入口**：`cli.py` 不 import 任何节点/适配器，业务全在图内。
- **事实源驱动**：默认值、路径、子目录、日志位置均落在上表依据范围内。
- **mock 透明**：CLI 完全不知道跑的是真实还是 mock，便于演示与单测解耦。
- **单一错误链路**：节点抛 → 图终止 → CLI 记录+摘要+重新抛出 → 非 0 退出；日志与 stderr 双通道可观测。
- **可测试**：`main(argv)` 接受参数列表，配合 `tmp_path` + `monkeypatch` 覆盖成功/失败路径，无需真实视频或完整 mock。