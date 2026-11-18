"""Serve the local workflow canvas and submit jobs to the team CLI."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from datetime import datetime
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import chain
from pathlib import Path
from threading import Lock, Thread
from time import time
from urllib.parse import parse_qs, quote, unquote, urlsplit
from uuid import uuid4

from graph.registry import NODE_NAMES
from graph.incremental import INCREMENTAL_NODE_NAMES
from nodes.asr_diarize.pipeline.video_inputs import youtube_url
from nodes.probe_input.source_store import acquire_youtube, adopt_existing_jobs, catalog, resolve_source
from subtitle_preview import subtitle_stage
from utils.artifacts import ARTIFACT_SPECS
from workflow_modes import ConfigChanged, mode_snapshot, save_modes
from workflow_settings import OPTIONS, read_settings, save_settings, workflow_schema
from api_settings import snapshot as api_snapshot, save as save_api_settings
from api_settings import read_saved_key, test_speech_connection, test_translation_connection
import model_settings
from nodes.translate_blocks._deepseek import DeepSeekError
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
ASSETS = {
    "/translation-models.js": ("translation-models.js", "text/javascript"),
    "/": ("index.html", "text/html"),
    "/workflow.css": ("workflow.css", "text/css"),
    "/workflow.js": ("workflow.js", "text/javascript"),
    "/task-queue.js": ("task-queue.js", "text/javascript"),
    "/subtitle-review.js": ("subtitle-review.js", "text/javascript"),
    "/api-settings.js": ("api-settings.js", "text/javascript"),
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
    "repair_blocks": "repaired_blocks",
    "tts_align": "dub_audio",
    "subtitle_cover": "burnin_subtitle",
    "compose_video": "final_video",
}


def node_progress(job: Path) -> dict:
    """Only telemetry is read here; file existence alone cannot prove an incremental succeeded."""
    states = {}
    path = job / "logs" / "node-progress.jsonl"
    if not path.is_file():
        return states
    with path.open(encoding="utf-8") as source:
        for line in source:
            try:
                event = json.loads(line)
                name = event["node"]
                if name not in NODE_NAMES:
                    continue
                kind = event["event"]
                if kind == "started":
                    states[name] = "running"
                elif kind == "failed":
                    states[name] = "failed"
                elif kind == "finished":
                    states[name] = ("no_output" if name in INCREMENTAL_NODE_NAMES
                                    and not event.get("has_output") else "complete")
            except (ValueError, KeyError, TypeError):
                # The worker may currently be appending the last line.
                continue
    return states


def write_status(job: Path, **status) -> None:
    previous_path = job / "web-status.json"
    previous = json.loads(previous_path.read_text(encoding="utf-8")) if previous_path.exists() else {}
    metadata_path = job / "web-run.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    status["started_at"] = previous.get("started_at") or metadata.get("created_at") or time()
    if status.get("state") != "running":
        status["finished_at"] = time()
    temporary = job / "web-status.tmp"
    temporary.write_text(json.dumps(status, ensure_ascii=False), encoding="utf-8")
    temporary.replace(job / "web-status.json")


def artifact_ready(job: Path, name: str) -> bool:
    path = job / ARTIFACT_SPECS[name].path
    return path.is_file() and path.stat().st_size > 0


def video_stem(filename: str) -> str:
    name = filename[:-4] if filename.lower().endswith(".mp4") else filename
    name = re.sub(r'[<>:"/\\|?*]', "_", "".join(c for c in name if c.isprintable()))
    return name.encode("utf-8")[:160].decode("utf-8", errors="ignore").strip(" .") or "视频"


def export_final_video(job: Path, directory: Path, filename: str) -> Path:
    source = job / ARTIFACT_SPECS["final_video"].path
    folder = directory / job.name
    target = folder / f"{video_stem(filename)}[localized_final].mp4"
    same_folder = folder == job.resolve()
    if not same_folder:
        folder.mkdir()
    pending = folder / ".final.mp4.partial"
    try:
        shutil.copyfile(source, pending)
        return pending.replace(target)
    except OSError:
        pending.unlink(missing_ok=True)
        if not same_folder:
            folder.rmdir()
        raise


def save_job_input(source, size: int, job: Path, source_dir: Path | None = None) -> Path:
    """Upload once into source storage, never materialize an input in the task directory."""
    shared = source_dir or job.parent / ".inputs"
    shared.mkdir(parents=True, exist_ok=True)
    pending = shared / (uuid4().hex + ".upload")
    digest = sha256()
    try:
        with pending.open("xb") as output:
            while size:
                chunk = source.read(min(size, 1024 * 1024))
                if not chunk:
                    raise OSError("Incomplete upload")
                output.write(chunk)
                digest.update(chunk)
                size -= len(chunk)
        stored = shared / (digest.hexdigest() + ".mp4")
        try:
            os.link(pending, stored)
        except FileExistsError:
            pass
        return stored.resolve()
    finally:
        pending.unlink(missing_ok=True)


def source_video_path(job: Path) -> Path:
    meta = job / "web-run.json"
    if meta.is_file():
        data = json.loads(meta.read_text(encoding="utf-8"))
        if data.get("source_video"):
            path = Path(data["source_video"])
            if not path.is_absolute():
                raise ValueError("原视频引用必须为绝对路径")
            return path
    return job / "input.mp4"  # Old tasks remain readable in place.


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
        self.sources = ROOT / "media" / "downloads"
        self.config_dir = ROOT / "config"
        self.env_path = ROOT / ".env"
        self.mock_config = self.config_dir / "mock.toml"
        self.worker_lock = Lock()
        self.active_job = None

    def read_run_status(self, job: Path) -> dict:
        status_file = job / "web-status.json"
        status = json.loads(status_file.read_text(encoding="utf-8"))
        status["queue_cleared"] = (job / "queue-cleared").exists()
        metadata_path = job / "web-run.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
        status["started_at"] = status.get("started_at") or metadata.get("created_at")
        if status["state"] != "running" or self.active_job != job.name:
            status["finished_at"] = status.get("finished_at") or status_file.stat().st_mtime
        status["elapsed_seconds"] = (
            max(0, (status.get("finished_at") or time()) - status["started_at"])
            if status["started_at"] else None
        )
        if status["state"] == "running" and self.active_job != job.name:
            status = json.loads(status_file.read_text(encoding="utf-8"))
            if status["state"] == "running":
                status.update(state="failed", message="服务已重启，请重新运行视频。")
        # Older jobs recorded an artifact path. Surface only readiness.
        artifacts = status.pop("artifacts", {})
        if artifacts.get("english_srt") == "english.srt" or status["state"] == "complete":
            status["english_srt_ready"] = (job / "b" / "english.srt").is_file()
        completed = {node for node, artifact in NODE_ARTIFACTS.items() if artifact_ready(job, artifact)}
        progress = node_progress(job)
        status["node_states"] = progress
        status["active_nodes"] = [node for node in NODE_NAMES if progress.get(node) == "running"]
        status["input_ready"] = source_video_path(job).is_file()
        status["subtitle_srt_ready"] = all(artifact_ready(job, name) for name in SUBTITLE_SRT_ARTIFACTS)
        recorded = set(status.get("completed_nodes", []))
        recorded.discard("subtitle_cover")
        if status["state"] == "blocked" and not status.get("node"):
            if "subtitle_cover" in completed:
                status["message"] = "烧录字幕 ASS 已生成，成片尚未生成。"
            elif status["subtitle_srt_ready"]:
                status["message"] = "三份 SRT 已生成，烧录字幕 ASS 尚未生成。"
        status["completed_nodes"] = [node for node in NODE_NAMES if node in recorded or node in completed]
        if progress:
            status["completed_nodes"] = [node for node in NODE_NAMES if progress.get(node) == "complete"]
            status["node"] = next((node for node in NODE_NAMES if progress.get(node) == "failed"),
                                  next(iter(status["active_nodes"]), None))
            if status["state"] == "running":
                status["phase"] = "workflow"
                status["message"] = "正在执行主图节点：" + "、".join(status["active_nodes"])
        if status.get("node") not in NODE_NAMES:
            status.pop("node", None)
        status.pop("final_zip_ready", None)
        status["english_segments_ready"] = "asr_diarize" in completed
        status["final_video_ready"] = status["state"] == "complete" and "compose_video" in completed
        return status

    def find_run(self, job_id: str) -> Path:
        job = self.jobs / job_id
        legacy = self.jobs / "webui" / job_id
        if job.exists() or legacy.exists():
            return job if job.exists() else legacy
        for metadata in self.jobs.glob("*/web-run.json"):
            try:
                if json.loads(metadata.read_text(encoding="utf-8")).get("job_id") == job_id:
                    return metadata.parent
            except (OSError, ValueError, AttributeError):
                continue
        return legacy

    def visible_runs(self):
        for job in chain(self.jobs.glob("*"), (self.jobs / "webui").glob("*")):
            if (job / "queue-cleared").exists():
                continue
            if job.parent != self.jobs and self.find_run(job.name) != job:
                continue
            try:
                if not (job / "web-status.json").is_file():
                    continue
                meta = json.loads((job / "web-run.json").read_text(encoding="utf-8"))
                if not isinstance(meta, dict) or not JOB_ID.fullmatch(str(meta.get("job_id", job.name))):
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
                "id": meta.get("job_id", job.name),
                "filename": meta.get("filename") or "本地视频",
                "created_at": meta.get("created_at", timestamp),
                "state": status["state"],
                "node": status.get("node"),
                "message": status.get("message"),
                "english_srt_ready": status.get("english_srt_ready", False),
                "english_segments_ready": status["english_segments_ready"],
                "final_video_ready": status["final_video_ready"],
                "completed_nodes": status.get("completed_nodes", []),
                "node_states": status.get("node_states", {}),
                "input_ready": status.get("input_ready", False),
                "phase": status.get("phase"),
                "started_at": status.get("started_at"),
                "finished_at": status.get("finished_at"),
                "elapsed_seconds": status.get("elapsed_seconds"),
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
        log_path = job / "logs" / "runner.log"
        try:
            metadata = json.loads((job / "web-run.json").read_text(encoding="utf-8"))
            if metadata.get("source_url") and not metadata.get("source_video"):
                adopt_existing_jobs(self.jobs, self.sources)
                source, receipt = acquire_youtube(metadata["source_url"], self.sources)
                metadata["source_video"] = str(source)
                if isinstance(receipt.get("title"), str) and receipt["title"].strip():
                    metadata["filename"] = receipt["title"]
                (job / "web-run.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
                log_path.parent.mkdir(parents=True, exist_ok=True)
                (job / "logs/input-download.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
                write_status(job, state="running", phase="workflow", message="直接读取原视频，正在执行主图。")
            source = metadata.get("source_video") or "input.mp4"
            command = [sys.executable, "-u", "-m", "cli", "--work-dir", str(job),
                       "--input", source, "--report-progress"]
            if metadata.get("authorize_voice_clone") is True:
                command.append("--authorize-voice-clone")
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("wb") as log:
                run = subprocess.run(
                    command, cwd=ROOT, env={**os.environ,
                        **{k: v for k, v in dotenv_values(self.env_path).items() if v is not None},
                        "PYTHONIOENCODING": "utf-8"},
                    stdout=log, stderr=subprocess.STDOUT, timeout=3 * 60 * 60, check=False,
                )
            if run.returncode:
                write_status(job, state="failed", message=cli_failure(job))
            elif artifact_ready(job, "final_video"):
                directory = metadata.get("output_directory")
                if directory:
                    try:
                        exported = export_final_video(job, Path(directory), metadata.get("filename") or "视频")
                    except OSError:
                        write_status(job, state="complete",
                                     message="成片已保存在任务目录，自选目录导出失败，请检查目录权限和磁盘空间。")
                    else:
                        write_status(job, state="complete", message=f"成片已导出到 {exported}。",
                                     exported_video=str(exported))
                else:
                    write_status(job, state="complete", message="成片已生成。")
            else:
                write_status(
                    job, state="blocked",
                    message="主图已结束，未生成成片。请检查后端节点及 config/mock.toml。",
                )
        except subprocess.TimeoutExpired:
            write_status(job, state="failed", message="工作流超过 3 小时，任务已停止。")
        except ValueError as error:
            write_status(job, state="failed", message="素材准备失败：" + str(error)[:500])
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

    def send_video(self, video: Path, *, download: bool = False, filename: str = "final.mp4") -> None:
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
                self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{quote(filename)}")
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
        if self.path == "/api/translation-models":
            if not self.local_request():
                return
            if self.headers.get_content_type() != "application/json":
                self.send_json({"message": "模型配置请求必须使用 JSON。"}, 415)
                return
            if not self.server.worker_lock.acquire(blocking=False):
                self.send_json({"message": "任务运行中，请结束后再修改模型配置。"}, 409)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    raise ValueError("模型配置请求大小无效。")
                result = model_settings.save(self.server.env_path, json.loads(self.rfile.read(length)))
            except ConfigChanged as error:
                self.send_json({"message": str(error)}, 409)
            except (ValueError, TypeError, DeepSeekError):
                self.send_json({"message": "请检查模型配置、密钥、接口地址和选择项。"}, 400)
            except OSError:
                self.send_json({"message": "无法保存本机模型配置。"}, 503)
            else:
                self.send_json(result)
            finally:
                self.server.worker_lock.release()
            return
        if self.path == "/api/api-settings":
            if not self.local_request():
                return
            if self.headers.get_content_type() != "application/json":
                self.send_json({"message": "配置请求必须使用 JSON。"}, 415)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    raise ValueError
            except ValueError:
                self.send_json({"message": "配置请求大小无效。"}, 400)
                return
            if not self.server.worker_lock.acquire(blocking=False):
                self.send_json({"message": "任务运行中，请结束后再修改 API。"}, 409)
                return
            try:
                result = save_api_settings(self.server.env_path, self.server.config_dir / "tts.toml",
                                           json.loads(self.rfile.read(length)))
            except ConfigChanged:
                self.send_json({"message": "配置已变化，请重新打开 API 设置。"}, 409)
            except (ValueError, TypeError):
                self.send_json({"message": "配置无效，请检查地址、模型、地域及填写格式。"}, 400)
            except OSError:
                self.send_json({"message": "无法保存本机配置，请检查文件权限。"}, 500)
            else:
                self.send_json(result)
            finally:
                self.server.worker_lock.release()
            return
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
        if request.path == "/api/translation-models":
            if self.local_request():
                try:
                    self.send_json(model_settings.snapshot(self.server.env_path))
                except (OSError, ValueError, KeyError, DeepSeekError):
                    self.send_json({"message": "无法读取本机翻译模型配置。"}, 503)
            return
        if request.path == "/api/api-settings":
            if self.local_request():
                try:
                    self.send_json(api_snapshot(self.server.env_path, self.server.config_dir / "tts.toml"))
                except (OSError, ValueError):
                    self.send_json({"message": "无法读取本机 API 配置。"}, 503)
            return
        if request.path == "/api/workflow-schema":
            if self.local_request():
                self.send_json(workflow_schema())
            return
        if request.path == "/api/video-sources":
            if self.local_request():
                adopt_existing_jobs(self.server.jobs, self.server.sources)
                self.send_json({"sources": catalog(self.server.sources, (self.server.sources / "uploads", self.server.jobs / ".inputs"))})
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
            self.send_video(source_video_path(job))
            return
        if match[2] == "final-video":
            if not self.server.read_run_status(job)["final_video_ready"]:
                self.send_json({"message": "该任务尚无成片。"}, 404)
                return
            metadata = job / "web-run.json"
            filename = json.loads(metadata.read_text(encoding="utf-8")).get("filename") if metadata.is_file() else None
            self.send_video(job / ARTIFACT_SPECS["final_video"].path,
                            download=parse_qs(request.query).get("download") != ["0"],
                            filename=f"{video_stem(filename or '视频')}[localized_final].mp4")
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
        key_match = re.fullmatch(r"/api/translation-models/(legacy|[0-9a-f]{32})/key", self.path)
        if key_match:
            if not self.local_request():
                return
            if self.headers.get("Origin") != f"http://{self.headers.get('Host')}":
                self.send_json({"message": "请从本机工作台查看密钥。"}, 403)
                return
            try:
                self.send_json({"value": model_settings.profile_key(self.server.env_path, key_match.group(1))})
            except (ValueError, KeyError, OSError):
                self.send_json({"message": "无法读取该模型的密钥。"}, 400)
            return
        if self.path == "/api/translation-models/test":
            if not self.local_request():
                return
            if self.headers.get_content_type() != "application/json":
                self.send_json({"message": "测试请求必须使用 JSON。"}, 415)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 16384:
                    raise ValueError("测试请求大小无效。")
                payload = model_settings.test_payload(self.server.env_path, json.loads(self.rfile.read(length)))
                test_translation_connection(self.server.env_path, payload)
            except (ValueError, TypeError, OSError):
                self.send_json({"message": "请检查模型和密钥，更换接口后请填写对应密钥。"}, 400)
            except DeepSeekError as error:
                self.send_json({"message": str(error)}, 422)
            else:
                self.send_json({"message": "翻译模型连通，已返回 JSON。"})
            return
        if self.path == "/api/output-directory/pick":
            if self.local_request():
                self.pick_output_directory()
            return
        output_match = re.fullmatch(r"/api/workflow-runs/([0-9a-f]{32})/open-output", self.path)
        if output_match:
            if not self.local_request():
                return
            if self.headers.get("Origin") != f"http://{self.headers.get('Host')}":
                self.send_json({"message": "请从本机工作台打开输出目录。"}, 403)
                return
            job = self.server.find_run(output_match.group(1))
            if not job.is_dir():
                self.send_json({"message": "任务目录不存在。"}, 404)
                return
            try:
                directory = job
                if (job / "web-status.json").is_file():
                    exported = self.server.read_run_status(job).get("exported_video")
                    if exported and Path(exported).is_file():
                        directory = Path(exported).parent
                if os.name == "nt":
                    os.startfile(str(directory))
                else:
                    subprocess.Popen(
                        ["open" if sys.platform == "darwin" else "xdg-open", str(directory)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
            except (OSError, ValueError):
                self.send_json({"message": "无法打开输出目录。"}, 503)
            else:
                self.send_json({"message": "已打开输出目录。"})
            return
        if self.path.startswith("/api/api-settings/reveal/"):
            if not self.local_request():
                return
            if self.headers.get("Origin") != f"http://{self.headers.get('Host')}":
                self.send_json({"message": "请从本机 WebUI 查看已保存密钥。"}, 403)
                return
            try:
                value = read_saved_key(self.server.env_path, self.path.rsplit("/", 1)[-1])
            except ValueError:
                self.send_json({"message": "未知密钥字段。"}, 400)
            except OSError:
                self.send_json({"message": "无法读取本机密钥。"}, 503)
            else:
                self.send_json({"value": value})
            return
        if self.path == "/api/api-settings/test-translation":
            if self.local_request():
                self.test_translation_api()
            return
        if self.path == "/api/api-settings/test-speech":
            if self.local_request():
                self.test_speech_api()
            return
        if self.path != "/api/workflow-runs":
            self.send_error(404)
            return
        if self.local_request():
            self.start_workflow()

    def pick_output_directory(self) -> None:
        if self.headers.get("Origin") != f"http://{self.headers.get('Host')}":
            self.send_json({"message": "请从本机工作台选择输出目录。"}, 403)
            return
        if sys.platform != "darwin":
            self.send_json({"message": "请在输出目录输入框填写本机目录路径。"}, 501)
            return
        try:
            result = subprocess.run(
                ["/usr/bin/osascript", "-e",
                 'POSIX path of (choose folder with prompt "选择成片输出目录")'],
                capture_output=True, text=True, timeout=90, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            self.send_json({"message": "无法打开目录选择器，请手动填写输出目录。"}, 503)
            return
        if result.returncode and "(-128)" not in result.stderr:
            self.send_json({"message": "无法打开目录选择器，请手动填写输出目录。"}, 503)
            return
        self.send_json({"directory": result.stdout.rstrip("\n") if result.returncode == 0 else None})

    def test_speech_api(self) -> None:
        if self.headers.get("Origin") != f"http://{self.headers.get('Host')}":
            self.send_json({"message": "请从本机工作台测试配音 API。"}, 403)
            return
        if self.headers.get_content_type() != "application/json":
            self.send_json({"message": "测试请求必须使用 JSON。"}, 415)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16384:
                raise ValueError
            payload = json.loads(self.rfile.read(length))
        except ValueError:
            self.send_json({"message": "测试请求无效。"}, 400)
            return
        try:
            test_speech_connection(self.server.env_path, payload)
        except ValueError as error:
            self.send_json({"message": str(error)}, 400)
        except RuntimeError as error:
            self.send_json({"message": str(error)}, 422)
        except OSError:
            self.send_json({"message": "无法读取本机配音 API 配置。"}, 503)
        else:
            self.send_json({"message": "WebSocket 连接和认证成功。未发起语音合成。"})

    def test_translation_api(self) -> None:
        if self.headers.get_content_type() != "application/json":
            self.send_json({"message": "测试请求必须使用 JSON。"}, 415)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16384:
                raise ValueError
            payload = json.loads(self.rfile.read(length))
        except ValueError:
            self.send_json({"message": "测试请求无效。"}, 400)
            return
        try:
            test_translation_connection(self.server.env_path, payload)
        except DeepSeekError as error:
            self.send_json({"message": str(error)}, 422)
        except ValueError:
            self.send_json({"message": "请检查地址、模型和密钥。更换接口域名或端口后请填写对应密钥。"}, 400)
        except OSError:
            self.send_json({"message": "无法读取本机 API 配置。"}, 503)
        else:
            self.send_json({"message": "翻译 API 连通，模型已返回 JSON。"})

    def start_workflow(self) -> None:
        request_started = time()
        kind = self.headers.get_content_type()
        if kind not in ("application/octet-stream", "application/json"):
            self.send_json({"message": "请上传 MP4 或提交 YouTube 链接。"}, 415)
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = 0
        if not 0 < size <= (4096 if kind == "application/json" else MAX_UPLOAD):
            self.send_json({"message": "文件不能为空，且大小不能超过 2 GiB。"}, 413)
            return
        url = None
        selected_source = None
        output_directory = None
        encoded_directory = self.headers.get("X-Output-Directory")
        if encoded_directory:
            if self.headers.get("Origin") != f"http://{self.headers.get('Host')}":
                self.send_json({"message": "请从本机工作台设置输出目录。"}, 403)
                return
            try:
                path = Path(unquote(encoded_directory, errors="strict")).expanduser()
                if not path.is_absolute() or not path.is_dir():
                    raise ValueError("invalid output directory")
                output_directory = str(path.resolve(strict=True))
            except (OSError, ValueError, RuntimeError):
                self.send_json({"message": "输出目录无效，请选择本机已有的文件夹。"}, 400)
                return
        authorize_voice_clone = self.headers.get("X-Authorize-Voice-Clone", "false") == "true"
        if self.headers.get("X-Authorize-Voice-Clone", "false") not in ("true", "false"):
            self.send_json({"message": "音色复刻授权必须明确选择。"}, 400)
            return
        if kind == "application/json":
            try:
                payload = json.loads(self.rfile.read(size))
                if (not isinstance(payload, dict) or len(set(payload) & {"url", "source_id"}) != 1
                        or set(payload) - {"url", "source_id", "authorize_voice_clone"}
                        or type(payload.get("authorize_voice_clone", False)) is not bool):
                    raise ValueError("invalid input")
                if "url" in payload:
                    if not isinstance(payload["url"], str):raise ValueError("invalid URL")
                    url = youtube_url(payload["url"].strip())
                else:
                    if not isinstance(payload["source_id"], str):raise ValueError("invalid source")
                    selected_source = resolve_source(payload["source_id"], self.server.sources,
                        (self.server.sources / "uploads", self.server.jobs / ".inputs"))
                authorize_voice_clone = payload.get("authorize_voice_clone", False)
            except (ValueError, TypeError, RuntimeError):
                self.send_json({"message": "请输入有效 YouTube 链接，或重新选择已有素材。"}, 400)
                return
        if not self.server.worker_lock.acquire(blocking=False):
            self.send_json({"message": "本机已有工作流任务在运行，请等它完成。"}, 409)
            return

        job_id = uuid4().hex
        filename = ("YouTube · " + url.rsplit("=", 1)[-1] if url else
                    selected_source.name if selected_source else unquote(self.headers.get("X-Video-Name", "")[:4096]))
        filename = re.split(r"[/\\]", filename)[-1]
        filename = "".join(character for character in filename if character.isprintable())[:180]
        stamp = datetime.fromtimestamp(request_started).strftime("%Y-%m-%d_%H%M%S_%f")
        job = self.server.jobs / f"{stamp} {video_stem(filename)}"
        created = False
        try:
            mock = tomllib.loads(self.server.mock_config.read_text(encoding="utf-8"))
            tts = tomllib.loads((self.server.config_dir / "tts.toml").read_text(encoding="utf-8"))
            if not mock.get("tts_align", False) and tts.get("voice_mode", "system") == "cloned" and not authorize_voice_clone:
                self.server.worker_lock.release()
                self.send_json({"message": "原声复刻模式需要提供说话人授权。"}, 400)
                return
            job.mkdir(parents=True, exist_ok=False)
            created = True
            source_video = selected_source
            if url is None and selected_source is None:
                source_video = save_job_input(self.rfile, size, job, self.server.sources / "uploads")
            (job / "web-run.json").write_text(
                json.dumps({"job_id": job_id, "filename": filename, "created_at": request_started, "source_url": url,
                            "source_video": str(source_video) if source_video else None,
                            "authorize_voice_clone": authorize_voice_clone,
                            "output_directory": output_directory},
                           ensure_ascii=False),
                encoding="utf-8",
            )
            self.server.active_job = job.name
            write_status(job, state="running", phase="download" if url else "workflow",
                         message="正在下载原视频，完成后自动翻译与配音。" if url else "正在执行后端工作流。")
            Thread(target=self.server.run_workflow, args=(job,), daemon=True).start()
        except (OSError, RuntimeError, ValueError):
            if created:
                shutil.rmtree(job, ignore_errors=True)
            self.server.active_job = None
            self.server.worker_lock.release()
            self.send_json({"message": "视频读取中断或本机无法写入任务目录。"}, 400)
            return
        self.send_json({"job_id": job_id}, 202)


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
