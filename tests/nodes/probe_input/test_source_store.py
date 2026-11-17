import json

import pytest
from nodes.probe_input.source_store import adopt_existing_jobs, catalog, resolve_source


def test_first_download_is_registered_in_place_without_copy(tmp_path):
    jobs = tmp_path / "jobs"
    first = jobs / "first"
    first.mkdir(parents=True)
    source = first / "input.mp4"
    source.write_bytes(b"first-original")
    (first / "web-run.json").write_text(json.dumps({"source_url": "https://youtu.be/jNQXAC9IVRw"}))
    store = tmp_path / "sources"
    adopt_existing_jobs(jobs, store)
    rows = catalog(store)
    assert len(rows) == 1 and rows[0]["path"] == str(source.resolve())
    assert resolve_source(rows[0]["id"], store) == source.resolve()
    assert not list(store.rglob("*.mp4"))
    assert source.read_bytes() == b"first-original"
    with pytest.raises(ValueError):
        resolve_source("../../unregistered.mp4", store)
