"""Check explicitly local Whisper assets before the SDK interprets paths as model names."""

from pathlib import Path


def require_whisper_model(directory: str | Path) -> str:
    path = Path(directory).expanduser().resolve()
    required = ("model.bin", "config.json", "tokenizer.json")
    missing = [
        name
        for name in required
        if not (path / name).is_file() or (path / name).stat().st_size == 0
    ]
    if missing:
        raise FileNotFoundError(
            f"本地 Whisper 模型不存在或不完整：{path}；缺少 {', '.join(missing)}。"
            "请在 WebUI 对应节点或 TOML 中设置正确模型目录，或按 README 准备本地模型。"
            "更新代码不会自动下载模型；本次不会联网下载。"
        )
    return str(path)
