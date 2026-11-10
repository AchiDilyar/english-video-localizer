"""Serve the local workflow canvas and run English transcription jobs."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.util import find_spec
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock, Thread
from time import time
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import uuid4

from subtitle_preview import subtitle_stage

from video_localizer.translation_demo import SAMPLE, build_graph

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
NODE_IDS = {"translate": "translate_blocks", "review": "review_blocks"}
MODEL_FILES = ("config.json", "model.bin", "tokenizer.json", "vocabulary.txt")
MAX_UPLOAD = 2 * 1024**3
JOB_ROUTE = re.compile(
    r"/api/(?:workflow-runs|transcriptions)/([0-9a-f]{32})"
    r"(?:/(preview-video|subtitles/(initial|segmented|draft|final)))?"
)
PROJECT_ID = re.compile(r"[0-9a-f]{32}")
PROJECT_ROUTE = re.compile(r"/api/projects/([0-9a-f]{32})")
MAX_PROJECT_BYTES = 1024 * 1024
BYTE_RANGE = re.compile(r"bytes=(\d*)-(\d*)")
B_MODULE = "nodes.asr_diarize.pipeline"


def write_status(job: Path, **status) -> None:
    temporary = job / "web-status.tmp"
    temporary.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    temporary.replace(job / "web-status.json")


def job_stage(job: Path) -> tuple[str, str]:
    events = job / "b" / "events.jsonl"
    if not events.is_file():
        return "probe_input", "正在加载转写环境"
    # Only the tail is needed and the final line may still be in flight.
    with events.open("rb") as stream:
        stream.seek(max(0, events.stat().st_size - 8192))
        lines = stream.read().splitlines()
    labels = {
        "resolve_input": "检查视频文件",
        "download_video": "准备本地视频",
        "prepare_full_audio": "提取音轨",
        "asr_and_sentence_formation": "识别英文并生成句子时间轴",
        "recheck_incomplete_audio": "复查疑似残句",
        "review_sentences": "检查英文时间轴",
        "export_sentences": "导出英文 SRT",
    }
    for line in reversed(lines):
        try:
            entry = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        if entry.get("stage") in labels:
            stage = entry["stage"]
            node = "probe_input" if stage in {
                "resolve_input", "download_video", "prepare_full_audio",
            } else "asr_diarize"
            return node, labels[stage]
    return "probe_input", "正在准备转写"


class WorkflowServer(ThreadingHTTPServer):
    def __init__(self, port: int, asr_python: Path, model_dir: Path):
        super().__init__(("127.0.0.1", port), WorkflowHandler)
        self.asr_python = asr_python
        self.model_dir = model_dir
        self.jobs = ROOT / "jobs" / "webui"
        self.projects = ROOT / "jobs" / "webui-projects"
        self.worker_lock = Lock()
        self.active_job = None

    def read_run_status(self, job: Path) -> dict:
        status_file = job / "web-status.json"
        status = json.loads(status_file.read_text(encoding="utf-8"))
        if status["state"] == "running":
            if self.active_job != job.name:
                status = json.loads(status_file.read_text(encoding="utf-8"))
                if status["state"] == "running":
                    status = {"state": "failed", "message": "服务已重启，请重新运行视频。"}
            else:
                status["node"], status["message"] = job_stage(job)
                status["completed_nodes"] = ["probe_input"] if status["node"] == "asr_diarize" else []
        # Older jobs recorded an artifact path. Surface only readiness.
        artifacts = status.pop("artifacts", {})
        if artifacts.get("english_srt") == "english.srt" or status["state"] == "complete":
            status["english_srt_ready"] = (job / "b" / "english.srt").is_file()
        return status

    def project_runs(self, project_id: str):
        if not self.jobs.is_dir():
            return
        for job in self.jobs.iterdir():
            if not PROJECT_ID.fullmatch(job.name) or (job / "queue-cleared").exists():
                continue
            try:
                if not (job / "web-status.json").is_file():
                    continue
                meta = json.loads((job / "web-run.json").read_text(encoding="utf-8"))
                if not isinstance(meta, dict) or meta.get("project_id") != project_id:
                    continue
                timestamp = (job / "input.mp4").stat().st_mtime
            except (OSError, ValueError):
                continue
            yield job, timestamp, meta

    def list_runs(self, project_id: str, offset: int, limit: int = 25) -> dict:
        jobs = sorted(self.project_runs(project_id),
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
                "completed_nodes": status.get("completed_nodes", []),
            })
        return {
            "jobs": result,
            "total": len(jobs),
            "has_finished": any(job.name != self.active_job for job, _, _ in jobs),
        }

    def clear_project_queue(self, project_id: str) -> None:
        for job, _, _ in self.project_runs(project_id):
            if job.name != self.active_job:
                # Preserve the video, subtitles and status for existing project references.
                (job / "queue-cleared").touch(exist_ok=True)

    def list_projects(self) -> list[dict]:
        projects = []
        for path in self.projects.glob("*.json"):
            if not PROJECT_ROUTE.fullmatch(f"/api/projects/{path.stem}"):
                continue
            try:
                stat = path.stat()
                if stat.st_size > MAX_PROJECT_BYTES:
                    continue
                data = json.loads(path.read_bytes())
                if data.get("format") != "video-localizer-ui" or data.get("id") != path.stem:
                    continue
                name = data.get("name")
                projects.append({
                    "id": path.stem,
                    "name": name[:80] if isinstance(name, str) else "未命名工程",
                    "updated_at": stat.st_mtime,
                })
            except (OSError, ValueError, AttributeError):
                continue
        return sorted(projects, key=lambda project: project["updated_at"], reverse=True)

    def run_transcription(self, job: Path) -> None:
        command = [
            str(self.asr_python), "-m", B_MODULE, "run",
            "--input", str(job / "input.mp4"), "--job-dir", str(job / "b"),
            "--model-dir", str(self.model_dir),
        ]
        env = {**os.environ, "PYTHONPATH": str(ROOT / "project")}
        try:
            with (job / "runner.log").open("wb") as log:
                run = subprocess.run(
                    command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
                    timeout=3 * 60 * 60, check=False,
                )
            srt = job / "b" / "english.srt"
            if run.returncode == 0 and srt.is_file() and srt.stat().st_size > 1:
                self.save_initial_preview(job, env)
                write_status(
                    job, state="blocked", node="build_blocks", code="NODE_NOT_CONNECTED",
                    completed_nodes=["probe_input", "asr_diarize"],
                    english_srt_ready=True,
                    message="断句与术语节点尚未接入，工作流已停止。",
                )
                return
            message = "英文转写失败，请检查任务日志 runner.log。"
            with (job / "runner.log").open("rb") as log:
                log.seek(max(0, log.seek(0, 2) - 8192))
                lines = log.read().decode("utf-8", errors="replace").splitlines()
            for line in reversed(lines):
                try:
                    detail = json.loads(line)
                except ValueError:
                    continue
                if isinstance(detail, dict) and detail.get("ok") is False:
                    message = str(detail.get("message", message))[-500:]
                    break
            node, _ = job_stage(job)
            write_status(job, state="failed", node=node, message=message,
                         completed_nodes=["probe_input"] if node == "asr_diarize" else [])
        except subprocess.TimeoutExpired:
            write_status(job, state="failed", message="转写超过 3 小时，任务已停止。")
        except OSError:
            write_status(job, state="failed", message="无法启动 B 的 Python 环境或写入任务文件。")
        finally:
            self.active_job = None
            self.worker_lock.release()

    def save_initial_preview(self, job: Path, env: dict) -> None:
        # This review snapshot is ancillary. Keep the successful B result on failure.
        with (job / "runner.log").open("ab") as log:
            try:
                subprocess.run(
                    [str(self.asr_python), str(ROOT / "scripts/subtitle_preview.py"), str(job / "b")],
                    cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=30, check=False,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                log.write(f"Initial subtitle preview unavailable: {type(exc).__name__}\n".encode())


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

    def send_preview_video(self, video: Path) -> None:
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

    def do_PUT(self) -> None:
        match = PROJECT_ROUTE.fullmatch(self.path)
        if not match:
            self.send_error(404)
            return
        if not self.local_request():
            return
        if self.headers.get_content_type() != "application/json":
            self.send_json({"message": "项目必须是 JSON。"}, 415)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = 0
        if not 0 < size <= MAX_PROJECT_BYTES:
            self.send_json({"message": "项目 JSON 不能为空或超过 1 MB。"}, 413)
            return
        try:
            project = json.loads(self.rfile.read(size))
            if (not isinstance(project, dict) or project.get("format") != "video-localizer-ui"
                    or project.get("version") not in (3, 4) or project.get("id") != match[1]
                    or not isinstance(project.get("nodes"), dict)
                    or not isinstance(project.get("edges"), list)
                    or not isinstance(project.get("view"), dict)):
                raise ValueError
            payload = json.dumps(project, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        except (ValueError, RecursionError):
            self.send_json({"message": "项目 JSON 格式或版本不正确。"}, 400)
            return

        path = self.server.projects / f"{match[1]}.json"
        temporary = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                    suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
            temporary.replace(path)
        except OSError:
            self.send_json({"message": "无法保存本机项目文件。"}, 500)
            return
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        self.send_json({"saved": True})

    def do_GET(self) -> None:
        if self.path in ASSETS:
            name, content_type = ASSETS[self.path]
            self.send_content((WEB / name).read_bytes(), content_type)
            return
        request = urlsplit(self.path)
        if request.path == "/api/workflow-runs":
            if not self.local_request():
                return
            query = parse_qs(request.query)
            project_id = self.queue_project_id(query)
            if project_id is None:
                return
            try:
                offset = int(query.get("offset", ["0"])[0])
                if not 0 <= offset <= 1_000_000:
                    raise ValueError
            except ValueError:
                self.send_json({"message": "任务页码无效。"}, 400)
                return
            self.send_json(self.server.list_runs(project_id, offset))
            return
        if request.path == "/api/projects":
            if self.local_request():
                self.send_json({"projects": self.server.list_projects()})
            return
        project = PROJECT_ROUTE.fullmatch(self.path)
        if project:
            if not self.local_request():
                return
            path = self.server.projects / f"{project[1]}.json"
            try:
                content = path.read_bytes()
            except FileNotFoundError:
                self.send_json({"message": "本机没有找到该项目。"}, 404)
                return
            self.send_content(content, "application/json")
            return
        match = JOB_ROUTE.fullmatch(self.path)
        if not match:
            self.send_error(404)
            return
        if not self.local_request():
            return
        job = self.server.jobs / match[1]
        status_file = job / "web-status.json"
        if not status_file.is_file():
            self.send_json({"message": "没有找到该转写任务。"}, 404)
            return
        if match[2] == "preview-video":
            self.send_preview_video(job / "input.mp4")
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

    def queue_project_id(self, query: dict) -> str | None:
        project_id = query.get("project_id", [""])[0]
        if PROJECT_ID.fullmatch(project_id):
            return project_id
        self.send_json({"message": "请选择有效的工程。"}, 400)
        return None

    def do_DELETE(self) -> None:
        request = urlsplit(self.path)
        if request.path != "/api/workflow-runs":
            self.send_error(404)
            return
        if not self.local_request():
            return
        project_id = self.queue_project_id(parse_qs(request.query))
        if project_id is None:
            return
        try:
            self.server.clear_project_queue(project_id)
        except OSError:
            self.send_json({"message": "无法清空工程队列，请刷新后重试。"}, 500)
            return
        self.send_json(self.server.list_runs(project_id, 0))

    def do_POST(self) -> None:
        if self.path in {"/api/workflow-runs", "/api/transcriptions"}:
            if self.local_request():
                self.start_transcription()
            return
        if self.path != "/api/demo":
            self.send_error(404)
            return
        graph = build_graph()
        events = [
            {"node": NODE_IDS[node], "data": data}
            for update in graph.stream({"segment": SAMPLE, "attempts": 0}, stream_mode="updates")
            for node, data in update.items()
        ]
        self.send_json({"sample": SAMPLE, "events": events})

    def start_transcription(self) -> None:
        project_id = self.headers.get("X-Project-Id")
        if (project_id is not None or self.path == "/api/workflow-runs") and not PROJECT_ID.fullmatch(
            project_id or ""
        ):
            self.send_json({"message": "请从已打开的工程运行工作流。"}, 400)
            return
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
        if self.server.asr_python == Path(sys.executable).absolute() and any(
            find_spec(name) is None for name in ("faster_whisper", "spacy", "en_core_web_sm")
        ):
            self.send_json({"message": "缺少 B 的转写依赖，请使用 uv run --locked --extra b-asr 启动。"}, 503)
            return
        if not self.server.asr_python.is_file() or not all(
            (self.server.model_dir / name).is_file() for name in MODEL_FILES
        ):
            self.send_json({"message": "缺少 B 的 Python 环境或 Whisper 模型，请按 WebUI 文档准备。"}, 503)
            return
        if not self.server.worker_lock.acquire(blocking=False):
            self.send_json({"message": "本机已有转写任务在运行，请等它完成。"}, 409)
            return

        job = self.server.jobs / uuid4().hex
        try:
            job.mkdir(parents=True, exist_ok=False)
            with (job / "input.mp4").open("wb") as output:
                while size:
                    chunk = self.rfile.read(min(size, 1024 * 1024))
                    if not chunk:
                        raise OSError("Incomplete upload")
                    output.write(chunk)
                    size -= len(chunk)
            filename = unquote(self.headers.get("X-Video-Name", "")[:4096])
            filename = re.split(r"[/\\]", filename)[-1]
            filename = "".join(character for character in filename if character.isprintable())[:180]
            (job / "web-run.json").write_text(
                json.dumps({"filename": filename, "created_at": time(), "project_id": project_id},
                           ensure_ascii=False),
                encoding="utf-8",
            )
            self.server.active_job = job.name
            write_status(job, state="running")
            Thread(target=self.server.run_transcription, args=(job,), daemon=True).start()
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
    parser.add_argument("--asr-python", type=Path, default=Path(sys.executable),
                        help="覆盖转写解释器路径，默认继承当前 uv 环境")
    parser.add_argument("--asr-model-dir", type=Path, default=ROOT / "models/faster-whisper-base.en")
    args = parser.parse_args()
    # Keep the virtualenv executable path, even if it is a symlink.
    with WorkflowServer(args.port, args.asr_python.expanduser().absolute(),
                        args.asr_model_dir.expanduser().resolve()) as server:
        print(f"工作流画布  http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
