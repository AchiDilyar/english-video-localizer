"""Final preview falls back to the published repair result before subtitle export."""
import json
import sys
from pathlib import Path

from utils.artifacts import ARTIFACT_SPECS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from subtitle_preview import subtitle_stage


def test_final_preview_uses_repaired_translation(tmp_path):
    rows = {
        "segments": [{"segment_id": "seg_0001", "speaker_id": "spk_1",
                      "start_ms": 0, "end_ms": 1000, "text_en": "Hello, world."}],
        "reviewed_blocks": [{"segment_id": "seg_0001", "block_id": "blk_0001",
                             "zh_subtitle": "初稿"}],
        "repaired_blocks": [{"segment_id": "seg_0001", "block_id": "blk_0001",
                             "zh_subtitle": "你好 世界"}],
    }
    for name, data in rows.items():
        path = tmp_path / ARTIFACT_SPECS[name].path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    result = subtitle_stage(tmp_path, "final")
    assert result["ready"]
    assert result["cues"][0]["translation"] == "你好 世界"
    assert result["cues"][0]["original"] == "Hello, world."
