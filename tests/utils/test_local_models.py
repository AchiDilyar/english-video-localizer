import pytest
from utils.local_models import require_whisper_model


def test_missing_or_partial_model_has_clear_local_error(tmp_path):
    missing = tmp_path / "missing-model"
    with pytest.raises(FileNotFoundError, match="本地 Whisper"):
        require_whisper_model(missing)
    missing.mkdir()
    (missing / "model.bin").write_bytes(b"weights")
    with pytest.raises(FileNotFoundError, match="config.json.*tokenizer.json"):
        require_whisper_model(missing)
    (missing / "config.json").write_text("{}")
    (missing / "tokenizer.json").touch()
    with pytest.raises(FileNotFoundError, match="tokenizer.json"):
        require_whisper_model(missing)


def test_valid_local_model_stays_local(tmp_path):
    for filename in ("model.bin", "config.json", "tokenizer.json"):
        (tmp_path / filename).write_bytes(b"nonempty fixture")
    assert require_whisper_model(tmp_path) == str(tmp_path.resolve())
