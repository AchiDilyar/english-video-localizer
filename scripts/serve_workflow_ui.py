"""Serve the local workflow canvas and its credential-free LangGraph demo."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from video_localizer.translation_demo import SAMPLE, build_graph

WEB = Path(__file__).resolve().parents[1] / "web"
ASSETS = {
    "/": ("index.html", "text/html"),
    "/workflow.css": ("workflow.css", "text/css"),
    "/workflow.js": ("workflow.js", "text/javascript"),
    "/node-schema.js": ("node-schema.js", "text/javascript"),
}
NODE_IDS = {"translate": "translate_blocks", "review": "review_blocks"}


class WorkflowHandler(BaseHTTPRequestHandler):
    def send_content(self, content: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        if self.path not in ASSETS:
            self.send_error(404)
            return
        name, content_type = ASSETS[self.path]
        self.send_content((WEB / name).read_bytes(), content_type)

    def do_POST(self) -> None:
        if self.path != "/api/demo":
            self.send_error(404)
            return
        graph = build_graph()
        events = [
            {"node": NODE_IDS[node], "data": data}
            for update in graph.stream({"segment": SAMPLE, "attempts": 0}, stream_mode="updates")
            for node, data in update.items()
        ]
        self.send_content(
            json.dumps({"sample": SAMPLE, "events": events}, ensure_ascii=False).encode("utf-8"),
            "application/json",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="打开本地视频译制工作流画布。")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), WorkflowHandler) as server:
        print(f"工作流画布  http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
