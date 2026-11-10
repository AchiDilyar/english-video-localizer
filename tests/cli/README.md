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
| 命令行调用与默认 `--input` | `test_run_input_command_default_input`（**当前失败，见第 3 节**） |

---

## 2. 环境约定

- 临时目录：`tests/tmp/cli/<用例名>/`，用例前清空，**结束后保留**（含 `run.log`），便于排查；已被 `.gitignore` 排除。
- autouse fixture 重置 `utils.paths._work_dir` 与 root logger handlers/level，用例间无污染。
- 命令行用例以项目根为 `cwd` 执行 `uv run run-input --work-dir <tmp>`，等效于在项目根敲同一条命令；临时目录无 `input.mp4`，命令在启动前检查阶段失败，不触发图。

---

## 3. 已知失败：`test_run_input_command_default_input`

**现象**：`ModuleNotFoundError: No module named 'cli'`。

**原因**：`[project.scripts] run-input = "cli:main"` 要求安装环境中 `cli` 为可导入顶层模块，但当前
`[tool.uv.build-backend] module-name = "video_localizer"` 未把 `project/` 下的 `cli.py` 安装为顶层模块；
`[tool.pytest.ini_options] pythonpath = ["project"]` 只对 pytest 生效，不影响 console script 运行时的 `sys.path`。

**处置**：属于“标准包布局”决策范围（`project/` → `video_localizer/`，导入改包内相对导入，入口点改 `video_localizer.cli:main`），已知且暂不处理。进程内用例已覆盖同一默认参数行为，功能不受影响。

**恢复条件**：完成标准包布局迁移后，此用例应直接通过；迁移时同步把 `import cli` 改为 `from video_localizer import cli`。

---

## 4. 排查提示

- 失败用例现场保留在 `tests/tmp/cli/<用例名>/`，先看 `logs/run.log`。
- 用例间疑似串扰：检查 `utils.paths._work_dir` 与 root logger 是否被上一用例残留；autouse fixture 已处理，若仍出现说明有代码绕过 fixture 直接改全局状态。