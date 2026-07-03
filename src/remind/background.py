"""
Background processing support for Remind CLI.

Provides a recall worker that runs as a background subprocess.
"""

import hashlib
import json
import logging
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from filelock import FileLock, Timeout

from remind.config import REMIND_DIR

logger = logging.getLogger(__name__)

# Recall worker defaults
DEFAULT_RECALL_WORKER_IDLE_SECONDS = 600
RECALL_WORKER_STARTUP_TIMEOUT_SECONDS = 12.0
RECALL_WORKER_RPC_TIMEOUT_SECONDS = 30.0


def _db_hash(db_url: str) -> str:
    return hashlib.md5(db_url.encode()).hexdigest()[:12]


def _stable_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def build_recall_worker_key(
    db_url: str,
    embedding_provider: str,
    config_fingerprint: str,
) -> str:
    """Build a stable key for one recall-worker identity."""
    return _stable_hash({
        "db_url": db_url,
        "embedding_provider": embedding_provider,
        "config_fingerprint": config_fingerprint,
    })


def get_recall_lock_path(
    db_url: str,
    worker_key: str,
    remind_dir: Optional[Path] = None,
) -> Path:
    """Get lock file path for a recall worker identity."""
    base = remind_dir if remind_dir is not None else REMIND_DIR
    return base / f".recall-{_db_hash(db_url)}-{worker_key}.lock"


def get_recall_socket_path(
    db_url: str,
    worker_key: str,
    remind_dir: Optional[Path] = None,
) -> Path:
    """Get Unix socket path for a recall worker identity."""
    base = remind_dir if remind_dir is not None else REMIND_DIR
    sockets_dir = base / "sockets"
    return sockets_dir / f"recall-{_db_hash(db_url)}-{worker_key}.sock"


def is_recall_running(
    db_url: str,
    worker_key: str,
    remind_dir: Optional[Path] = None,
) -> bool:
    """Check whether recall worker lock is held."""
    lock_path = get_recall_lock_path(db_url, worker_key, remind_dir=remind_dir)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    lock = FileLock(str(lock_path), timeout=0)
    try:
        lock.acquire(blocking=False)
        lock.release()
        return False
    except Timeout:
        return True


def _rpc_call_unix_socket(
    socket_path: Path,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> Optional[dict[str, Any]]:
    """Send a newline-delimited JSON request and parse one JSON response."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout_seconds)
    try:
        sock.connect(str(socket_path))
        sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))

        data = b""
        while b"\n" not in data:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
        if not data:
            return None
        line = data.split(b"\n", 1)[0]
        return json.loads(line.decode("utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    finally:
        sock.close()


def _ping_recall_socket(socket_path: Path) -> bool:
    """Probe a recall worker socket and verify protocol responsiveness."""
    resp = _rpc_call_unix_socket(
        socket_path,
        {"action": "ping"},
        timeout_seconds=1.0,
    )
    return bool(resp and resp.get("ok") and resp.get("pong") is True)


def spawn_recall_worker(
    db_url: str,
    embedding_provider: str,
    worker_key: str,
    idle_seconds: int,
    remind_dir: Optional[Path] = None,
) -> bool:
    """Spawn a background recall worker for one worker identity.

    Returns True if a new worker was spawned, False if one is already running.
    """
    if is_recall_running(db_url, worker_key, remind_dir=remind_dir):
        logger.debug(f"Recall worker already running for {db_url} ({worker_key})")
        return False

    socket_path = get_recall_socket_path(db_url, worker_key, remind_dir=remind_dir)
    socket_path.parent.mkdir(parents=True, exist_ok=True)

    # Defensive cleanup for stale socket files from crashed workers.
    if socket_path.exists() and not _ping_recall_socket(socket_path):
        try:
            socket_path.unlink()
        except OSError:
            pass

    cmd = [
        sys.executable,
        "-m",
        "remind.background_worker",
        "--db",
        db_url,
        "--embedding",
        embedding_provider,
        "--recall-worker",
        "--recall-worker-key",
        worker_key,
        "--recall-socket",
        str(socket_path),
        "--recall-idle-seconds",
        str(max(5, idle_seconds)),
    ]
    if remind_dir is not None:
        cmd += ["--remind-dir", str(remind_dir)]

    logger.debug(f"Spawning recall worker: {' '.join(cmd)}")

    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return True


def ensure_recall_worker(
    db_url: str,
    embedding_provider: str,
    worker_key: str,
    idle_seconds: int,
    remind_dir: Optional[Path] = None,
    startup_timeout_seconds: float = RECALL_WORKER_STARTUP_TIMEOUT_SECONDS,
) -> Optional[Path]:
    """Ensure recall worker is running and responsive; return socket path."""
    socket_path = get_recall_socket_path(db_url, worker_key, remind_dir=remind_dir)
    socket_path.parent.mkdir(parents=True, exist_ok=True)

    if _ping_recall_socket(socket_path):
        return socket_path

    spawned = spawn_recall_worker(
        db_url=db_url,
        embedding_provider=embedding_provider,
        worker_key=worker_key,
        idle_seconds=idle_seconds,
        remind_dir=remind_dir,
    )
    if not spawned and not is_recall_running(db_url, worker_key, remind_dir=remind_dir):
        return None

    deadline = time.monotonic() + max(0.5, startup_timeout_seconds)
    while time.monotonic() < deadline:
        if _ping_recall_socket(socket_path):
            return socket_path
        time.sleep(0.1)
    return None


def request_recall_worker(
    socket_path: Path,
    *,
    query: Optional[str],
    k: int,
    episode_k: int,
    context: Optional[str],
    entity: Optional[str],
    topic: Optional[str],
    raw: bool,
    timeout_seconds: float = RECALL_WORKER_RPC_TIMEOUT_SECONDS,
) -> Optional[dict[str, Any]]:
    """Send a recall request to a running recall worker."""
    payload = {
        "action": "recall",
        "query": query,
        "k": k,
        "episode_k": episode_k,
        "context": context,
        "entity": entity,
        "topic": topic,
        "raw": raw,
    }
    return _rpc_call_unix_socket(socket_path, payload, timeout_seconds=timeout_seconds)
