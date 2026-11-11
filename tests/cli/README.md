# cli 测试说明

维护者：F｜文件：`tests/cli/test_cli.py`｜运行：`uv run pytest tests/cli/test_cli.py`

---

## 1. 测试范围

只测 `project/cli.py` 自身行为，不联调 `nodes/`、`mocks/`、真实图。图通过 `monkeypatch` 替换为记录型 fake，校验 State 传参与异常链路。

| 覆盖点 | 用例 |
|---|---|
| `--work-dir` 不存在 / 不是目录 | `test_work_dir_missing`、`test_work_dir_is_file` |
| 输入视频不存在 / 是目录 | `test_input_missing`、`test_input_is_directory` |
| 失败时无子目录副作用 | `test_input_missing_has_no_side_effects` |
| 成功流程（默认 `--input`、9 个子目录、`logs/run.log`、State 传参） | `test_success_default_input` |
| 自定义 `--input` | `test_custom_input` |
| `--work-dir` 默认值 `.` | `test_default_work_dir_is_cwd` |
| 图抛异常 → `run.log` 含类型/消息/traceback，stderr 含摘要 | `test_graph_exception_logged` |
| `--input` 默认值 `input.mp4`（cwd 下缺失） | `test_default_input_missing_in_cwd` |
| 命令行调用与默认 `--input` | `test_run_input_command_default_input` |

---

## 2. 环境约定

- 临时目录：`tests/tmp/cli/<用例名>/`，用例前清空，**结束后保留**（含 `run.log`），便于排查；已被 `.gitignore` 排除。
- autouse fixture 重置 `utils.paths._work_dir` 与 root logger handlers/level，用例间无污染。
- 命令行用例以项目根为 `cwd` 执行 `uv run run-input --work-dir <tmp>`，等效于在项目根敲同一条命令；临时目录无 `input.mp4`，命令在启动前检查阶段失败，不触发图。

---

## 3. 排查提示

- 失败用例现场保留在 `tests/tmp/cli/<用例名>/`，先看 `logs/run.log`。
- 用例间疑似串扰：检查 `utils.paths._work_dir` 与 root logger 是否被上一用例残留；autouse fixture 已处理，若仍出现说明有代码绕过 fixture 直接改全局状态。
- `run-input` 命令行用例出现 `ModuleNotFoundError: No module named 'cli'` 时，检查 [tool.setuptools] 的 py-modules 是否包含 `cli`、package-dir 是否指向 `project/`；pytest 的 pythonpath 只对 pytest 生效，不影响 console script 运行时。