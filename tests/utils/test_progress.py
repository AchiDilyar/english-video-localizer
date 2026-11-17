import json

from utils.progress import stream_with_progress


def test_progress_records_only_task_metadata(tmp_path):
    class Graph:
        def stream(self, state, *, stream_mode):
            assert stream_mode == "tasks"
            yield {"name": "probe_input", "input": {"private": "not-for-ui"}}
            yield {
                "name": "probe_input",
                "result": [("media_info", {"private": "not-for-ui"})],
                "error": None,
            }

    path = tmp_path / "progress.jsonl"
    stream_with_progress(Graph(), None, path)
    content = path.read_text()
    assert "not-for-ui" not in content
    events = [json.loads(line) for line in content.splitlines()]
    assert [item["event"] for item in events] == ["started", "finished"]
    assert events[-1]["has_output"] is True
