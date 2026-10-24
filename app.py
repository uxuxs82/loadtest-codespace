import ipaddress
import json
import math
import os
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, request, send_file

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("LOADTEST_DATA_DIR", ROOT / "results"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
CAMPAIGN_FILE = DATA_DIR / "campaign.json"
K6_BIN = os.environ.get("K6_BIN", "k6")
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
RUN_ID = re.compile(r"^[0-9a-zA-Z-]+$")
MAX_VUS = 1000
MAX_SINGLE_MINUTES = 600
MAX_CHUNK_MINUTES = 600
MAX_TOTAL_MINUTES = 10000

app = Flask(__name__, static_folder="static", static_url_path="/static")


def now():
    return time.time()


def iso(timestamp):
    if not timestamp:
        return None
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat()


def tail(path, lines=200):
    if lines <= 0:
        return ""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            block = 8192
            data = b""
            while size > 0 and data.count(b"\n") + data.count(b"\r") <= lines:
                step = min(block, size)
                size -= step
                handle.seek(size)
                data = handle.read(step) + data
    except OSError:
        return ""
    text = data.decode("utf-8", errors="replace")
    text = ANSI.sub("", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(text.splitlines()[-lines:])


def parse_int(payload, key, default, minimum, maximum, label):
    value = payload.get(key, default)
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if not minimum <= number <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return number


def parse_float(payload, key, default, minimum, maximum, label):
    value = payload.get(key, default)
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be a number") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{label} must be between {minimum} and {maximum}")
    return number


def parse_user_agent(payload):
    value = payload.get("user_agent", "loadtest-codespace/1.0")
    if not isinstance(value, str):
        raise ValueError("user_agent must be a string")
    value = value.strip() or "loadtest-codespace/1.0"
    if len(value) > 300:
        raise ValueError("user_agent is too long")
    if "\n" in value or "\r" in value:
        raise ValueError("user_agent must be a single line")
    return value


def validate_target(value):
    if not isinstance(value, str):
        raise ValueError("target must be a string")
    target = value.strip()
    if not target or len(target) > 2000:
        raise ValueError("target is empty or too long")
    parsed = urlparse(target)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("target must start with http:// or https://")
    if parsed.username or parsed.password:
        raise ValueError("target must not contain credentials")
    host = parsed.hostname
    if not host:
        raise ValueError("target has no host")
    lower = host.lower()
    if lower == "localhost" or lower.endswith(".local") or lower == "metadata.google.internal":
        raise ValueError("target host is not allowed")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError("target has an invalid port") from exc
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve target host: {exc}") from exc
    for info in infos:
        address = info[4][0].split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ValueError("target resolved to an invalid address") from exc
        if not ip.is_global:
            raise ValueError("target resolves to a non-public address")
    return target


def parse_run_config(payload):
    if not isinstance(payload, dict):
        raise ValueError("invalid json")
    return {
        "target": validate_target(payload.get("target")),
        "vus": parse_int(payload, "vus", 500, 1, MAX_VUS, "vus"),
        "duration_minutes": parse_int(payload, "duration_minutes", 10, 1, MAX_SINGLE_MINUTES, "duration_minutes"),
        "ramp_up_seconds": parse_int(payload, "ramp_up_seconds", 5, 0, 600, "ramp_up_seconds"),
        "think_time_seconds": parse_float(payload, "think_time_seconds", 1.0, 0, 60, "think_time_seconds"),
        "user_agent": parse_user_agent(payload),
    }


def parse_campaign_config(payload):
    if not isinstance(payload, dict):
        raise ValueError("invalid json")
    base = dict(payload)
    base.pop("duration_minutes", None)
    config = parse_run_config(base)
    total = parse_int(payload, "total_minutes", 1000, 1, MAX_TOTAL_MINUTES, "total_minutes")
    chunk = parse_int(payload, "chunk_minutes", 500, 1, MAX_CHUNK_MINUTES, "chunk_minutes")
    if (total + chunk - 1) // chunk > 200:
        raise ValueError("too many chunks, increase chunk_minutes")
    config["total_minutes"] = total
    config["chunk_minutes"] = min(chunk, total)
    return config


class RunManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.process = None
        self.run_id = None
        self.config = None
        self.started_at = None
        self.finished_at = None
        self.status = "idle"
        self.log_path = None
        self.summary_path = None
        self.exit_code = None
        self.error = None
        self.stop_requested = False
        self.campaign = None
        self.session_started_at = now()
        self._load_campaign()
        self._recover()

    def _archive_broken(self):
        try:
            CAMPAIGN_FILE.replace(CAMPAIGN_FILE.with_name("campaign.broken.json"))
        except OSError:
            pass

    def _load_campaign(self):
        if not CAMPAIGN_FILE.exists():
            return
        try:
            data = json.loads(CAMPAIGN_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._archive_broken()
            return
        if not isinstance(data, dict):
            self._archive_broken()
            return
        required = ("target", "vus", "chunk_minutes", "ramp_up_seconds", "think_time_seconds", "user_agent", "chunks")
        if not all(key in data for key in required) or not isinstance(data["chunks"], list):
            self._archive_broken()
            return
        for chunk in data["chunks"]:
            if not isinstance(chunk, dict):
                self._archive_broken()
                return
            if not isinstance(chunk.get("index"), int) or not isinstance(chunk.get("minutes"), int) or not isinstance(chunk.get("status"), str):
                self._archive_broken()
                return
        self.campaign = data

    def _save_campaign(self):
        if not self.campaign:
            try:
                CAMPAIGN_FILE.unlink()
            except FileNotFoundError:
                pass
            return
        temporary = CAMPAIGN_FILE.with_name("campaign.tmp")
        temporary.write_text(json.dumps(self.campaign, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(CAMPAIGN_FILE)

    def _current_chunk(self):
        if not self.campaign:
            return None
        for chunk in self.campaign["chunks"]:
            if chunk.get("status") == "running":
                return chunk
        return None

    def _next_chunk(self):
        if not self.campaign:
            return None
        for chunk in self.campaign["chunks"]:
            if chunk.get("status") in ("pending", "interrupted"):
                return chunk
        return None

    def _kill_pid(self, pid):
        try:
            with open(f"/proc/{pid}/cmdline", "rb") as handle:
                cmdline = handle.read().decode("utf-8", errors="replace")
        except OSError:
            return
        if "k6" not in cmdline or "loadtest.js" not in cmdline:
            return
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except OSError:
            return
        time.sleep(0.5)
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except OSError:
            pass

    def _recover(self):
        if not self.campaign or self.campaign.get("status") != "running":
            return
        current = self._current_chunk()
        if current:
            pid = current.get("pid")
            if pid:
                self._kill_pid(pid)
            current["status"] = "interrupted"
            current["finished_at"] = now()
            current.pop("pid", None)
        self.campaign["status"] = "paused"
        self.campaign["updated_at"] = now()
        self._save_campaign()

    def _campaign_summary(self):
        if not self.campaign:
            return None
        chunks = self.campaign["chunks"]
        total = sum(chunk["minutes"] for chunk in chunks)
        completed = sum(chunk["minutes"] for chunk in chunks if chunk.get("status") == "completed")
        current = self._current_chunk()
        return {
            "id": self.campaign.get("id"),
            "status": self.campaign.get("status"),
            "target": self.campaign.get("target"),
            "vus": self.campaign.get("vus"),
            "total_minutes": total,
            "completed_minutes": completed,
            "remaining_minutes": total - completed,
            "chunk_minutes": self.campaign.get("chunk_minutes"),
            "chunks_total": len(chunks),
            "chunks_completed": sum(1 for chunk in chunks if chunk.get("status") == "completed"),
            "current_chunk": current["index"] if current else None,
            "chunks": [
                {
                    "index": chunk["index"],
                    "minutes": chunk["minutes"],
                    "status": chunk.get("status"),
                    "run_id": chunk.get("run_id"),
                    "exit_code": chunk.get("exit_code"),
                    "summary_url": f"/summary/{chunk['run_id']}" if chunk.get("run_id") and (DATA_DIR / f"summary-{chunk['run_id']}.json").exists() else None,
                    "log_url": f"/log/{chunk['run_id']}" if chunk.get("run_id") and (DATA_DIR / f"run-{chunk['run_id']}.log").exists() else None,
                }
                for chunk in chunks
            ],
            "created_at": iso(self.campaign.get("created_at")),
            "updated_at": iso(self.campaign.get("updated_at")),
        }

    def snapshot(self):
        with self.lock:
            elapsed = 0
            if self.started_at:
                elapsed = int((self.finished_at or now()) - self.started_at)
            log_tail = ""
            if self.log_path and Path(self.log_path).exists():
                log_tail = tail(Path(self.log_path), 200)
            return {
                "status": self.status,
                "run_id": self.run_id,
                "config": self.config,
                "elapsed_seconds": elapsed,
                "session_elapsed_seconds": int(now() - self.session_started_at),
                "started_at": iso(self.started_at),
                "finished_at": iso(self.finished_at),
                "exit_code": self.exit_code,
                "error": self.error,
                "log": log_tail,
                "summary_url": f"/summary/{self.run_id}" if self.summary_path and Path(self.summary_path).exists() else None,
                "log_url": f"/log/{self.run_id}" if self.log_path and Path(self.log_path).exists() else None,
                "campaign": self._campaign_summary(),
            }

    def _start_process(self, config, chunk=None):
        if self.process and self.process.poll() is None:
            raise RuntimeError("a test is already running")
        if not shutil.which(K6_BIN):
            raise RuntimeError("k6 is not installed")
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        log_path = DATA_DIR / f"run-{run_id}.log"
        summary_path = DATA_DIR / f"summary-{run_id}.json"
        command = [
            K6_BIN,
            "run",
            "--no-color",
            "--no-usage-report",
            "--summary-export",
            str(summary_path),
            "-e",
            f"TARGET={config['target']}",
            "-e",
            f"VUS={config['vus']}",
            "-e",
            f"DURATION={config['duration_minutes']}m",
            "-e",
            f"RAMP_UP={config['ramp_up_seconds']}s",
            "-e",
            f"THINK_TIME={config['think_time_seconds']}",
            "-e",
            f"USER_AGENT={config['user_agent']}",
            str(ROOT / "loadtest.js"),
        ]
        log_file = open(log_path, "w", encoding="utf-8")
        try:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            log_file.close()
            raise RuntimeError(f"cannot start k6: {exc}") from exc
        self.process = process
        self.run_id = run_id
        self.config = config
        self.started_at = now()
        self.finished_at = None
        self.status = "running"
        self.log_path = log_path
        self.summary_path = None
        self.exit_code = None
        self.error = None
        self.stop_requested = False
        if chunk is not None:
            chunk["status"] = "running"
            chunk["run_id"] = run_id
            chunk["started_at"] = self.started_at
            chunk["finished_at"] = None
            chunk["exit_code"] = None
            chunk["pid"] = process.pid
            self.campaign["status"] = "running"
            self.campaign["updated_at"] = now()
            self._save_campaign()
        thread = threading.Thread(
            target=self._wait,
            args=(process, log_file, run_id, summary_path, chunk),
            daemon=True,
        )
        thread.start()

    def _wait(self, process, log_file, run_id, summary_path, chunk):
        code = process.wait()
        try:
            log_file.close()
        except OSError:
            pass
        with self.lock:
            if self.process is not process:
                return
            self.exit_code = code
            self.finished_at = now()
            self.process = None
            self.summary_path = summary_path if summary_path.exists() else None
            if self.stop_requested:
                self.status = "stopped"
            elif code in (0, 99):
                self.status = "completed"
            else:
                self.status = "failed"
                self.error = f"k6 exited with code {code}"
            if chunk is not None and self.campaign:
                chunk.pop("pid", None)
                chunk["finished_at"] = self.finished_at
                chunk["exit_code"] = code
                if self.stop_requested:
                    chunk["status"] = "interrupted"
                    self.campaign["status"] = "paused"
                elif code in (0, 99):
                    chunk["status"] = "completed"
                    self.campaign["status"] = "paused" if self._next_chunk() else "completed"
                else:
                    chunk["status"] = "interrupted"
                    self.campaign["status"] = "paused"
                self.campaign["updated_at"] = now()
                self._save_campaign()

    def start_single(self, config):
        with self.lock:
            if self.campaign:
                raise RuntimeError("a campaign exists, reset it first")
            self._start_process(config)

    def _start_next_chunk_locked(self):
        chunk = self._next_chunk()
        if not chunk:
            self.campaign["status"] = "completed"
            self.campaign["updated_at"] = now()
            self._save_campaign()
            return
        config = {
            "target": self.campaign["target"],
            "vus": self.campaign["vus"],
            "duration_minutes": chunk["minutes"],
            "ramp_up_seconds": self.campaign["ramp_up_seconds"],
            "think_time_seconds": self.campaign["think_time_seconds"],
            "user_agent": self.campaign["user_agent"],
        }
        self._start_process(config, chunk)

    def start_campaign(self, config):
        with self.lock:
            if self.process and self.process.poll() is None:
                raise RuntimeError("a test is already running")
            if self.campaign:
                raise RuntimeError("a campaign already exists, reset it first")
            chunks = []
            remaining = config["total_minutes"]
            index = 1
            while remaining > 0:
                minutes = min(config["chunk_minutes"], remaining)
                chunks.append({"index": index, "minutes": minutes, "status": "pending"})
                remaining -= minutes
                index += 1
            self.campaign = {
                "id": datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6],
                "target": config["target"],
                "vus": config["vus"],
                "chunk_minutes": config["chunk_minutes"],
                "ramp_up_seconds": config["ramp_up_seconds"],
                "think_time_seconds": config["think_time_seconds"],
                "user_agent": config["user_agent"],
                "created_at": now(),
                "updated_at": now(),
                "status": "paused",
                "chunks": chunks,
            }
            self._save_campaign()
            self._start_next_chunk_locked()

    def continue_campaign(self):
        with self.lock:
            if not self.campaign:
                raise RuntimeError("no campaign")
            if self.process and self.process.poll() is None:
                raise RuntimeError("a test is already running")
            if self.campaign.get("status") == "completed":
                raise RuntimeError("campaign is completed")
            if self.campaign.get("status") == "running":
                raise RuntimeError("campaign is already running")
            self._start_next_chunk_locked()

    def stop(self):
        with self.lock:
            if not self.process or self.process.poll() is not None:
                return False
            process = self.process
            self.stop_requested = True
            self.status = "stopping"
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except OSError:
                try:
                    process.terminate()
                except OSError:
                    pass

            def force_stop():
                time.sleep(5)
                if process.poll() is None:
                    try:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                    except OSError:
                        pass

            threading.Thread(target=force_stop, daemon=True).start()
            return True

    def reset_campaign(self):
        with self.lock:
            if self.process and self.process.poll() is None:
                raise RuntimeError("stop the current test first")
            if self.campaign:
                archive = DATA_DIR / f"campaign-{self.campaign['id']}.json"
                archive.write_text(json.dumps(self.campaign, indent=2, ensure_ascii=False), encoding="utf-8")
                self.campaign = None
            self._save_campaign()
            self.process = None
            self.stop_requested = False
            self.status = "idle"
            self.run_id = None
            self.config = None
            self.started_at = None
            self.finished_at = None
            self.log_path = None
            self.summary_path = None
            self.exit_code = None
            self.error = None


manager = RunManager()


@app.get("/")
def index():
    return app.send_static_file("index.html")


@app.get("/healthz")
def healthz():
    return jsonify({"status": "ok", "k6": shutil.which(K6_BIN) is not None})


@app.get("/status")
def status():
    return jsonify(manager.snapshot())


@app.post("/start")
def start():
    try:
        config = parse_run_config(request.get_json(silent=True))
        manager.start_single(config)
        return jsonify(manager.snapshot()), 202
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409
    except OSError as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/start-campaign")
def start_campaign():
    try:
        config = parse_campaign_config(request.get_json(silent=True))
        manager.start_campaign(config)
        return jsonify(manager.snapshot()), 202
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409
    except OSError as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/continue")
def continue_campaign():
    try:
        manager.continue_campaign()
        return jsonify(manager.snapshot()), 202
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409
    except OSError as exc:
        return jsonify({"error": str(exc)}), 500


@app.post("/stop")
def stop():
    if manager.stop():
        return jsonify(manager.snapshot()), 202
    return jsonify({"error": "no active test"}), 409


@app.post("/reset")
def reset():
    try:
        manager.reset_campaign()
        return jsonify(manager.snapshot()), 200
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409
    except OSError as exc:
        return jsonify({"error": str(exc)}), 500


@app.get("/summary/<run_id>")
def summary(run_id):
    if not RUN_ID.match(run_id):
        return jsonify({"error": "invalid run id"}), 400
    path = DATA_DIR / f"summary-{run_id}.json"
    if not path.exists():
        return jsonify({"error": "summary not found"}), 404
    return send_file(path, as_attachment=True, download_name=f"summary-{run_id}.json")


@app.get("/log/<run_id>")
def log(run_id):
    if not RUN_ID.match(run_id):
        return jsonify({"error": "invalid run id"}), 400
    path = DATA_DIR / f"run-{run_id}.log"
    if not path.exists():
        return jsonify({"error": "log not found"}), 404
    return send_file(path, as_attachment=True, download_name=f"run-{run_id}.log")


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        debug=False,
        use_reloader=False,
        threaded=True,
    )
