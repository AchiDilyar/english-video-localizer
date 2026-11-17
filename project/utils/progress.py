"""Optional UI telemetry for the single main graph; no model inputs or outputs are logged."""

import json
from pathlib import Path
from time import time


def stream_with_progress(graph, state, destination: Path) -> None:
    """Observe LangGraph task events without adding nodes or replacing its scheduler."""
    with destination.open("w", encoding="utf-8") as output:
        for event in graph.stream(state, stream_mode="tasks"):
            finished = "result" in event or "error" in event
            kind = "failed" if event.get("error") else "finished" if finished else "started"
            record = {"node": event["name"], "event": kind, "time": time()}
            if finished:
                record["has_output"] = bool(event.get("result"))
            output.write(json.dumps(record, ensure_ascii=False) + "\n")
            output.flush()
