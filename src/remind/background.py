"""
Background processing support for Remind CLI.

Provides non-blocking consolidation and ingestion by spawning background
subprocesses. Uses file locking to prevent concurrent consolidation.
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
from uuid import uuid4

from filelock import FileLock, Timeout

from remind.config import REMIND_DIR

logger = logging.getLogger(__name__)

# Lock timeout in seconds (30 minutes)
LOCK_TIMEOUT = 1800

# Grace period (seconds) the ingest worker waits after the queue empties
# before exiting, to catch late arrivals.
INGEST_WORKER_GRACE_SECONDS = 2

# Recall worker defaults
DEFAULT_RECALL_WORKER_IDLE_SECONDS = 600
# Keep startup wait modest, but long enough for first-call model warmup.
RECALL_WORKER_STARTUP_TIMEOUT_SECONDS = 12.0
RECALL_WORKER_RPC_TIMEOUT_SECONDS = 30.0


def _db_hash(db_url: str) -> str:
    return hashlib.md5(db_url.encode()).hexdigest()[:12]


def _stable_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.md5(raw.encode()).hexdigest()[:16]


def build_recall_worker_key(
    db_url: str,
    llm_provider: str,
    embedding_provider: str,
    config_fingerprint: str,
) -> str:
    """Build a stable key for one recall-worker identity.

    The key is used to isolate workers across db/provider/config combinations.
    """
    return _stable_hash({
        "db_url": db_url,
        "llm_provider": llm_provider,
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
    llm_provider: str,
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
        "--llm",
        llm_provider,
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
    llm_provider: str,
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
        llm_provider=llm_provider,
        embedding_provider=embedding_provider,
        worker_key=worker_key,
        idle_seconds=idle_seconds,
        remind_dir=remind_dir,
    )
    if not spawned and not is_recall_running(db_url, worker_key, remind_dir=remind_dir):
        # Not running and we could not spawn — nothing to wait on.
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


def get_consolidation_lock_path(db_url: str, remind_dir: Optional[Path] = None) -> Path:
    """Get lock file path for a database.

    Uses a hash of the db_url to create a unique lock file name.
    Stored in *remind_dir* when provided, otherwise falls back to ~/.remind.
    """
    base = remind_dir if remind_dir is not None else REMIND_DIR
    return base / f".consolidate-{_db_hash(db_url)}.lock"


def is_consolidation_running(db_url: str, remind_dir: Optional[Path] = None) -> bool:
    """Check if consolidation is already running for this database.

    Returns True if another process holds the lock, False otherwise.
    """
    lock_path = get_consolidation_lock_path(db_url, remind_dir=remind_dir)

    # Ensure the lock directory exists
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    lock = FileLock(str(lock_path), timeout=0)
    try:
        # Try to acquire lock without waiting
        lock.acquire(blocking=False)
        # We got the lock, release it and return False
        lock.release()
        return False
    except Timeout:
        # Lock is held by another process
        return True


def spawn_background_consolidation(
    db_url: str,
    llm_provider: str,
    embedding_provider: str,
    remind_dir: Optional[Path] = None,
) -> bool:
    """
    Spawn a background process to run consolidation.

    Args:
        db_url: Database URL or file path.
        llm_provider: LLM provider name (anthropic, openai, etc.)
        embedding_provider: Embedding provider name (openai, ollama, etc.)
        remind_dir: Project-local .remind directory for locks/logs. Falls back
            to ~/.remind when not provided.

    Returns:
        True if spawned successfully, False if consolidation already running.
    """
    if is_consolidation_running(db_url, remind_dir=remind_dir):
        logger.debug(f"Consolidation already running for {db_url}")
        return False

    cmd = [
        sys.executable,
        "-m",
        "remind.background_worker",
        "--db",
        db_url,
        "--llm",
        llm_provider,
        "--embedding",
        embedding_provider,
    ]
    if remind_dir is not None:
        cmd += ["--remind-dir", str(remind_dir)]

    logger.debug(f"Spawning background consolidation: {' '.join(cmd)}")

    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    return True


def get_ingest_queue_dir(db_url: str, remind_dir: Optional[Path] = None) -> Path:
    """Get the queue directory for ingest chunks for a database."""
    base = remind_dir if remind_dir is not None else REMIND_DIR
    return base / "ingest-queue" / _db_hash(db_url)


def get_ingest_lock_path(db_url: str, remind_dir: Optional[Path] = None) -> Path:
    """Get lock file path for the ingest worker for a database."""
    base = remind_dir if remind_dir is not None else REMIND_DIR
    return base / f".ingest-{_db_hash(db_url)}.lock"


def is_ingest_running(db_url: str, remind_dir: Optional[Path] = None) -> bool:
    """Check if an ingest worker is already running for this database."""
    lock_path = get_ingest_lock_path(db_url, remind_dir=remind_dir)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    lock = FileLock(str(lock_path), timeout=0)
    try:
        lock.acquire(blocking=False)
        lock.release()
        return False
    except Timeout:
        return True


def enqueue_ingest_chunk(
    db_url: str,
    chunk: str,
    source: str = "conversation",
    topic: Optional[str] = None,
    instructions: Optional[str] = None,
    remind_dir: Optional[Path] = None,
) -> Path:
    """Write a chunk to the ingest queue directory for later processing.

    File is named with a timestamp prefix for FIFO ordering.

    Returns:
        Path to the enqueued file.
    """
    queue_dir = get_ingest_queue_dir(db_url, remind_dir=remind_dir)
    queue_dir.mkdir(parents=True, exist_ok=True)

    ts = f"{time.time():.6f}"
    suffix = uuid4().hex[:8]
    path = queue_dir / f"{ts}-{suffix}.json"
    payload: dict = {"chunk": chunk, "source": source}
    if topic is not None:
        payload["topic"] = topic
    if instructions is not None:
        payload["instructions"] = instructions
    path.write_text(json.dumps(payload))

    logger.debug(f"Enqueued ingest chunk: {path.name} ({len(chunk)} chars)")
    return path


def spawn_ingest_worker(
    db_url: str,
    llm_provider: str,
    embedding_provider: str,
    remind_dir: Optional[Path] = None,
) -> bool:
    """Spawn a single background ingest worker that drains the queue.

    Only one worker runs per database (enforced via FileLock).
    If a worker is already running it will pick up newly enqueued chunks
    on its own, so this returns False without spawning.

    Returns:
        True if a new worker was spawned, False if one is already running.
    """
    if is_ingest_running(db_url, remind_dir=remind_dir):
        logger.debug(f"Ingest worker already running for {db_url}")
        return False

    cmd = [
        sys.executable,
        "-m",
        "remind.background_worker",
        "--db",
        db_url,
        "--llm",
        llm_provider,
        "--embedding",
        embedding_provider,
        "--ingest-worker",
    ]
    if remind_dir is not None:
        cmd += ["--remind-dir", str(remind_dir)]

    logger.debug(f"Spawning ingest worker: {' '.join(cmd)}")

    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    return True
