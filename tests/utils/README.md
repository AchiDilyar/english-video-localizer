# utils 测试

运行：`uv run pytest tests/utils/`

临时目录：由 pytest 在 `tests/tmp/pytest/` 下分配独立 utils 目录，每个测试再分配子目录。
不清空整个 tests/tmp，不删除其他角色的日志；session 结束后保留，便于排查。

## conftest.py

提供 `tmp_dir`（每个测试独立目录）与 `work_dir`（在 `tmp_dir` 下建全部子目录
并调用 `set_work_dir`）两个 fixture。其它测试文件都依赖 `work_dir`。

## test_artifacts.py

验证 `ARTIFACT_SPECS` 与 `dataflow.md` §3 产物表一致：
- 登记的产物名称集合完整；
- JSON 产物（`segments`、`blocks`、`translated_blocks`、`reviewed_blocks`、
  `tts_clips`）有非 None 的校验类型且路径为 `fixed`；
- 二进制产物校验类型为 None；
- `fixed` 必须有非空 path（构造时 `ValidationError`）；
- 规格不可变（赋值 `ValidationError`）。

新增产物后若测试失败，先核对 `dataflow.md` §3，再看 `ARTIFACT_SPECS` 是否漏项。

## test_paths.py

验证 `artifact_path`：
- `fixed` 产物传名称即返回绝对路径，传 filename 抛 `ValueError`；
- `dir` 产物必须传 filename，返回文件夹下的文件路径；
- `input_video` 的 path 为空字符串，返回工作目录根下的文件；
- 未知名称抛 `KeyError`；未设置工作目录抛 `RuntimeError`。

## test_io.py

验证 `read_artifact` / `write_artifact`：
- 模型实例读写往返，返回 `list[Segment]` 而非裸 dict；
- 裸 dict 列表写入时被归一化为模型实例；
- 校验失败时不覆盖磁盘上的旧文件（先校验、后写盘）；
- 对二进制产物调用抛 `ValueError`，错误信息含 `artifact_path`；
- 未知名称抛 `KeyError`；读文件不存在抛 `FileNotFoundError`；
- 写时不创建目录，父目录缺失抛 `FileNotFoundError`。

## test_config.py

验证 `load_config`：`config/` 目录存在，且能加载任意一个 `.toml` 返回 dict。

## test_log.py

验证 `setup_logging`：日志写入指定文件，logger 名称与级别出现在日志中。
使用独立的 `tmp_dir`，不影响其它测试的 logger 状态。