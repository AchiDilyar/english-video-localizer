"""Serve the local workflow canvas and submit jobs to the team CLI."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import chain
from pathlib import Path
from threading import Lock, Thread
from time import time
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

from graph.registry import NODE_NAMES
from subtitle_preview import subtitle_stage
from utils.artifacts import ARTIFACT_SPECS
from workflow_modes import ConfigChanged, mode_snapshot, save_modes
from workflow_settings import OPTIONS, read_settings, save_settings, workflow_schema

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
ASSETS = {
    "/": ("index.html", "text/html"),
    "/workflow.css": ("workflow.css", "text/css"),
    "/workflow.js": ("workflow.js", "text/javascript"),
    "/task-queue.js": ("task-queue.js", "text/javascript"),
    "/subtitle-review.js": ("subtitle-review.js", "text/javascript"),
    "/subtitle-styles.json": ("../config/subtitle_styles.json", "application/json"),
    "/node-schema.js": ("node-schema.js", "text/javascript"),
}
MAX_UPLOAD = 2 * 1024**3
LOG_CHUNK_BYTES = 64 * 1024
JOB_ROUTE = re.compile(
    r"/api/workflow-runs/([0-9a-f]{32})"
    r"(?:/(preview-video|final-video|logs|subtitles/(initial|segmented|draft|final)))?"
)
SETTINGS_ROUTE = re.compile(r"/api/workflow-settings/([a-z_]+)")
JOB_ID = re.compile(r"[0-9a-f]{32}")
BYTE_RANGE = re.compile(r"bytes=(\d*)-(\d*)")
SUBTITLE_SRT_ARTIFACTS = ("english_srt", "chinese_srt", "bilingual_srt")
NODE_ARTIFACTS = {
    "asr_diarize": "segments",
    "build_blocks": "blocks",
    "translate_blocks": "translated_blocks",
    "review_blocks": "reviewed_blocks",
    "tts_align": "dub_audio",
    "subtitle_cover": "burnin_subtitle",
    "compose_video": "final_video",
}


def write_status(job: Path, **status) -> None:
    temporary = job / "web-status.tmp"
    temporary.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    temporary.replace(job / "web-status.json")


def artifact_ready(job: Path, name: str) -> bool:
    path = job / ARTIFACT_SPECS[name].path
    return path.is_file() and path.stat().st_size > 0


def save_job_input(source, size: int, job: Path) -> None:
    """Store one physical copy per upload digest, keeping the CLI's input.mp4."""
    pending = job / "input.upload"
    digest = sha256()
    with pending.open("xb") as output:
        while size:
            chunk = source.read(min(size, 1024 * 1024))
            if not chunk:
                raise OSError("Incomplete upload")
            output.write(chunk)
            digest.update(chunk)
            size -= len(chunk)

    shared = job.parent / ".inputs"
    shared.mkdir(exist_ok=True)
    stored = shared / (digest.hexdigest() + ".mp4")
    try:
        os.link(pending, stored)
    except FileExistsError:
        pass
    os.link(stored, job / "input.mp4")
    pending.unlink()


def runner_log(job: Path) -> Path:
    """后端控制台日志：新任务写入 logs/runner.log，旧任务兼容根目录。"""
    path = job / "logs" / "runner.log"
    return path if path.is_file() else job / "runner.log"


def cli_failure(job: Path) -> str:
    with runner_log(job).open("rb") as log:
        log.seek(max(0, log.seek(0, 2) - 8192))
        lines = log.read().decode("utf-8", errors="replace").splitlines()
    for line in reversed(lines):
        if line.startswith("运行失败: "):
            return line[:500]
    return "工作流执行失败，请检查任务日志 logs/run.log 或 logs/runner.log。"


class WorkflowServer(ThreadingHTTPServer):
    def __init__(self, port: int):
        super().__init__(("127.0.0.1", port), WorkflowHandler)
        self.jobs = ROOT / "jobs"
        self.config_dir = ROOT / "config"
        self.mock_config = self.config_dir / "mock.toml"
        self.worker_lock = Lock()
        self.active_job = None

    def read_run_status(self, job: Path) -> dict:
        status_file = job / "web-status.json"
        status = json.loads(status_file.read_text(encoding="utf-8"))
        if status["state"] == "running" and self.active_job != job.name:
            status = json.loads(status_file.read_text(encoding="utf-8"))
            if status["state"] == "running":
                status.update(state="failed", message="服务已重启，请重新运行视频。")
        # Older jobs recorded an artifact path. Surface only readiness.
        artifacts = status.pop("artifacts", {})
        if artifacts.get("english_srt") == "english.srt" or status["state"] == "complete":
            status["english_srt_ready"] = (job / "b" / "english.srt").is_file()
        completed = {node for node, artifact in NODE_ARTIFACTS.items() if artifact_ready(job, artifact)}
        status["subtitle_srt_ready"] = all(artifact_ready(job, name) for name in SUBTITLE_SRT_ARTIFACTS)
        recorded = set(status.get("completed_nodes", []))
        recorded.discard("subtitle_cover")
        if status["state"] == "blocked" and not status.get("node"):
            if "subtitle_cover" in completed:
                status["message"] = "烧录字幕 ASS 已生成，成片尚未生成。"
            elif status["subtitle_srt_ready"]:
                status["message"] = "三份 SRT 已生成，烧录字幕 ASS 尚未生成。"
        status["completed_nodes"] = [node for node in NODE_NAMES if node in recorded or node in completed]
        if status.get("node") not in NODE_NAMES:
            status.pop("node", None)
        status.pop("final_zip_ready", None)
        status["english_segments_ready"] = "asr_diarize" in completed
        status["final_video_ready"] = status["state"] == "complete" and "compose_video" in completed
        return status

    def find_run(self, job_id: str) -> Path:
        job = self.jobs / job_id
        return job if job.exists() else self.jobs / "webui" / job_id

    def visible_runs(self):
        for job in chain(self.jobs.glob("*"), (self.jobs / "webui").glob("*")):
            if not JOB_ID.fullmatch(job.name) or (job / "queue-cleared").exists():
                continue
            if job.parent != self.jobs and self.find_run(job.name) != job:
                continue
            try:
                if not (job / "web-status.json").is_file():
                    continue
                meta = json.loads((job / "web-run.json").read_text(encoding="utf-8"))
                if not isinstance(meta, dict):
                    continue
                timestamp = (job / "web-run.json").stat().st_mtime
            except (OSError, ValueError):
                continue
            yield job, timestamp, meta

    def list_runs(self, offset: int, limit: int = 25) -> dict:
        jobs = sorted(self.visible_runs(),
                      key=lambda item: (item[0].name == self.active_job, item[1]), reverse=True)
        result = []
        for job, timestamp, meta in jobs[offset:offset + limit]:
            try:
                status = self.read_run_status(job)
            except (OSError, ValueError, KeyError, TypeError):
                continue
            result.append({
                "id": job.name,
                "filename": meta.get("filename") or "本地视频",
                "created_at": meta.get("created_at", timestamp),
                "state": status["state"],
                "node": status.get("node"),
                "message": status.get("message"),
                "english_srt_ready": status.get("english_srt_ready", False),
                "english_segments_ready": status["english_segments_ready"],
                "final_video_ready": status["final_video_ready"],
                "completed_nodes": status.get("completed_nodes", []),
            })
        return {
            "jobs": result,
            "total": len(jobs),
            "has_finished": any(job.name != self.active_job for job, _, _ in jobs),
        }

    def clear_queue(self) -> None:
        for job, _, _ in self.visible_runs():
            if job.name != self.active_job:
                # Keep task artifacts available for subtitle and log review.
                (job / "queue-cleared").touch(exist_ok=True)

    def run_workflow(self, job: Path) -> None:
        # Use the same module as run-input in a separate process for each task.
        command = [sys.executable, "-u", "-m", "cli", "--work-dir", str(job), "--input", "input.mp4"]
        log_path = job / "logs" / "runner.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("wb") as log:
                run = subprocess.run(
                    command, cwd=ROOT, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                    stdout=log, stderr=subprocess.STDOUT, timeout=3 * 60 * 60, check=False,
                )
            if run.returncode:
                write_status(job, state="failed", message=cli_failure(job))
            elif artifact_ready(job, "final_video"):
                write_status(job, state="complete", message="成片已生成。")
            else:
                write_status(
                    job, state="blocked",
                    message="主图已结束，未生成成片。请检查后端节点及 config/mock.toml。",
                )
        except subprocess.TimeoutExpired:
            write_status(job, state="failed", message="工作流超过 3 小时，任务已停止。")
        except OSError:
            write_status(job, state="failed", message="无法启动工作流或写入任务文件。")
        finally:
            self.active_job = None
            self.worker_lock.release()


class WorkflowHandler(BaseHTTPRequestHandler):
    server: WorkflowServer
    timeout = 120

    def send_content(
        self, content: bytes, content_type: str, status: int = 200,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def send_json(self, content: dict, status: int = 200) -> None:
        self.send_content(json.dumps(content, ensure_ascii=False).encode(), "application/json", status)

    def local_request(self) -> bool:
        host = self.headers.get("Host")
        allowed = {f"{name}:{self.server.server_port}" for name in ("localhost", "127.0.0.1")}
        origin = self.headers.get("Origin")
        if host in allowed and origin in (None, f"http://{host}"):
            return True
        self.send_json({"message": "请从本机 WebUI 发起请求。"}, 403)
        return False

    def send_run_log(self, job: Path, query: str) -> None:
        try:
            offset = int(parse_qs(query).get("offset", ["0"])[0])
            if not 0 <= offset < 2**63:
                raise ValueError
        except ValueError:
            self.send_json({"message": "日志读取位置无效。"}, 400)
            return
        # Capture the worker state before reading to include its final output.
        running = self.server.active_job == job.name
        try:
            with runner_log(job).open("rb") as log:
                log.seek(offset)
                content = log.read(LOG_CHUNK_BYTES + 1)
        except FileNotFoundError:
            content = b""
        except OSError:
            self.send_json({"message": "无法读取后端日志。"}, 500)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(min(len(content), LOG_CHUNK_BYTES)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Log-Pending", "1" if running or len(content) > LOG_CHUNK_BYTES else "0")
        self.end_headers()
        self.wfile.write(content[:LOG_CHUNK_BYTES])

    def send_video(self, video: Path, *, download: bool = False) -> None:
        if not video.is_file() or not video.stat().st_size:
            self.send_error(404)
            return
        with video.open("rb") as source:
            size = os.fstat(source.fileno()).st_size
            start, end = 0, size - 1
            requested = self.headers.get("Range")
            if requested:
                match = BYTE_RANGE.fullmatch(requested)
                if match and (match[1] or match[2]) and len(match[1]) < 20 and len(match[2]) < 20:
                    if match[1]:
                        start = int(match[1])
                        end = min(end, int(match[2])) if match[2] else end
                    else:
                        start = size - min(size, int(match[2]))
                else:
                    start = size
                if not 0 <= start <= end < size:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
            remaining = end - start + 1
            self.send_response(206 if requested else 200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            if download:
                self.send_header("Content-Disposition", 'attachment; filename="final.mp4"')
            self.send_header("Content-Length", str(remaining))
            self.send_header("Cache-Control", "private, no-store")
            if requested:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            source.seek(start)
            try:
                while remaining and (chunk := source.read(min(remaining, 1024 * 1024))):
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                # Browsers cancel in-flight byte ranges when the user seeks.
                pass

    def update_workflow_config(self, node: str | None = None) -> None:
        if not self.local_request():
            return
        if self.headers.get_content_type() != "application/json":
            self.send_json({"message": "后端配置请求必须使用 JSON。"}, 415)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= 4096:
            self.send_json({"message": "后端配置请求大小无效。"}, 400)
            return
        if not self.server.worker_lock.acquire(blocking=False):
            self.send_json({"message": "任务正在运行，请等它结束后再修改后端配置。"}, 409)
            return
        try:
            payload = json.loads(self.rfile.read(length))
            snapshot = (save_modes(self.server.mock_config, payload) if node is None else
                        save_settings(self.server.config_dir / f"{node}.toml", node, payload))
        except ConfigChanged as error:
            self.send_json({"message": str(error)}, 409)
            return
        except (ValueError, TypeError) as error:
            self.send_json({"message": str(error)}, 400)
            return
        except OSError:
            self.send_json({"message": "无法写入后端 TOML 配置。"}, 500)
            return
        finally:
            self.server.worker_lock.release()
        self.send_json(snapshot)

    def do_PUT(self) -> None:
        if self.path == "/api/workflow-modes":
            self.update_workflow_config()
            return
        settings = SETTINGS_ROUTE.fullmatch(self.path)
        if settings and settings[1] in OPTIONS:
            self.update_workflow_config(settings[1])
            return
        self.send_error(404)

    def do_GET(self) -> None:
        if self.path in ASSETS:
            name, content_type = ASSETS[self.path]
            self.send_content((WEB / name).read_bytes(), content_type)
            return
        request = urlsplit(self.path)
        if request.path == "/api/workflow-schema":
            if self.local_request():
                self.send_json(workflow_schema())
            return
        settings = SETTINGS_ROUTE.fullmatch(request.path)
        if settings and settings[1] in workflow_schema()["nodes"]:
            if self.local_request():
                try:
                    self.send_json(read_settings(self.server.config_dir, settings[1]))
                except (OSError, ValueError, TypeError):
                    self.send_json({"message": "无法读取该节点的后端配置。"}, 503)
            return
        if request.path == "/api/workflow-modes":
            if not self.local_request():
                return
            try:
                snapshot = mode_snapshot(self.server.mock_config.read_bytes())
            except (OSError, ValueError, TypeError):
                self.send_json({"message": "无法读取后端节点模式，请检查 config/mock.toml。"}, 503)
                return
            self.send_json(snapshot)
            return
        if request.path == "/api/workflow-runs":
            if not self.local_request():
                return
            query = parse_qs(request.query)
            try:
                offset = int(query.get("offset", ["0"])[0])
                if not 0 <= offset <= 1_000_000:
                    raise ValueError
            except ValueError:
                self.send_json({"message": "任务页码无效。"}, 400)
                return
            self.send_json(self.server.list_runs(offset))
            return
        match = JOB_ROUTE.fullmatch(request.path)
        if not match:
            self.send_error(404)
            return
        if not self.local_request():
            return
        job = self.server.find_run(match[1])
        status_file = job / "web-status.json"
        if not status_file.is_file():
            self.send_json({"message": "没有找到该工作流任务。"}, 404)
            return
        if match[2] == "logs":
            self.send_run_log(job, request.query)
            return
        if match[2] == "preview-video":
            self.send_video(job / "input.mp4")
            return
        if match[2] == "final-video":
            if not self.server.read_run_status(job)["final_video_ready"]:
                self.send_json({"message": "该任务尚无成片。"}, 404)
                return
            self.send_video(job / ARTIFACT_SPECS["final_video"].path, download=True)
            return
        if match[3]:
            try:
                result = subtitle_stage(job, match[3])
            except (ValueError, OSError, KeyError, AttributeError, TypeError, IndexError):
                self.send_json({"message": "该阶段的字幕文件格式无效，无法预览。"}, 422)
                return
            self.send_json(result)
            return
        self.send_json(self.server.read_run_status(job))

    def do_DELETE(self) -> None:
        request = urlsplit(self.path)
        if request.path != "/api/workflow-runs":
            self.send_error(404)
            return
        if not self.local_request():
            return
        try:
            self.server.clear_queue()
        except OSError:
            self.send_json({"message": "无法清空任务队列，请刷新后重试。"}, 500)
            return
        self.send_json(self.server.list_runs(0))

    def do_POST(self) -> None:
        if self.path != "/api/workflow-runs":
            self.send_error(404)
            return
        if self.local_request():
            self.start_workflow()

    def start_workflow(self) -> None:
        if self.headers.get_content_type() != "application/octet-stream":
            self.send_json({"message": "请选择一个本地 MP4 文件。"}, 415)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = 0
        if not 0 < size <= MAX_UPLOAD:
            self.send_json({"message": "文件不能为空，且大小不能超过 2 GiB。"}, 413)
            return
        if not self.server.worker_lock.acquire(blocking=False):
            self.send_json({"message": "本机已有工作流任务在运行，请等它完成。"}, 409)
            return

        job = self.server.jobs / uuid4().hex
        try:
            job.mkdir(parents=True, exist_ok=False)
            save_job_input(self.rfile, size, job)
            filename = unquote(self.headers.get("X-Video-Name", "")[:4096])
            filename = re.split(r"[/\\]", filename)[-1]
            filename = "".join(character for character in filename if character.isprintable())[:180]
            (job / "web-run.json").write_text(
                json.dumps({"filename": filename, "created_at": time()},
                           ensure_ascii=False),
                encoding="utf-8",
            )
            self.server.active_job = job.name
            write_status(job, state="running", message="正在执行后端工作流。")
            Thread(target=self.server.run_workflow, args=(job,), daemon=True).start()
        except (OSError, RuntimeError):
            shutil.rmtree(job, ignore_errors=True)
            self.server.active_job = None
            self.server.worker_lock.release()
            self.send_json({"message": "视频读取中断或本机无法写入任务目录。"}, 400)
            return
        self.send_json({"job_id": job.name}, 202)


def main() -> None:
    parser = argparse.ArgumentParser(description="打开本地视频译制工作台。")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()
    with WorkflowServer(args.port) as server:
        print(f"工作流画布  http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
