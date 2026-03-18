"""
Background processing support for Remind CLI.

Provides non-blocking consolidation and ingestion by spawning background
subprocesses. Uses file locking to prevent concurrent consolidation.
"""

import hashlib
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from filelock import FileLock, Timeout

from remind.config import REMIND_DIR

logger = logging.getLogger(__name__)

# Lock timeout in seconds (30 minutes)
LOCK_TIMEOUT = 1800

# Grace period (seconds) the ingest worker waits after the queue empties
# before exiting, to catch late arrivals.
INGEST_WORKER_GRACE_SECONDS = 2


def _db_hash(db_path: str) -> str:
    return hashlib.md5(db_path.encode()).hexdigest()[:12]


def get_consolidation_lock_path(db_path: str) -> Path:
    """Get lock file path for a database.

    Uses a hash of the db_path to create a unique lock file name.
    """
    return REMIND_DIR / f".consolidate-{_db_hash(db_path)}.lock"


def is_consolidation_running(db_path: str) -> bool:
    """Check if consolidation is already running for this database.

    Returns True if another process holds the lock, False otherwise.
    """
    lock_path = get_consolidation_lock_path(db_path)

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
    db_path: str,
    llm_provider: str,
    embedding_provider: str,
) -> bool:
    """
    Spawn a background process to run consolidation.

    Args:
        db_path: Full path to the database file.
        llm_provider: LLM provider name (anthropic, openai, etc.)
        embedding_provider: Embedding provider name (openai, ollama, etc.)

    Returns:
        True if spawned successfully, False if consolidation already running.
    """
    if is_consolidation_running(db_path):
        logger.debug(f"Consolidation already running for {db_path}")
        return False

    # Build the command - use the same Python interpreter
    cmd = [
        sys.executable,
        "-m",
        "remind.background_worker",
        "--db",
        db_path,
        "--llm",
        llm_provider,
        "--embedding",
        embedding_provider,
    ]

    logger.debug(f"Spawning background consolidation: {' '.join(cmd)}")

    # Spawn detached subprocess
    # Use DEVNULL for stdin/stdout/stderr to fully detach
    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # Detach from parent process group
    )

    return True


def get_ingest_queue_dir(db_path: str) -> Path:
    """Get the queue directory for ingest chunks for a database."""
    return REMIND_DIR / "ingest-queue" / _db_hash(db_path)


def get_ingest_lock_path(db_path: str) -> Path:
    """Get lock file path for the ingest worker for a database."""
    return REMIND_DIR / f".ingest-{_db_hash(db_path)}.lock"


def is_ingest_running(db_path: str) -> bool:
    """Check if an ingest worker is already running for this database."""
    lock_path = get_ingest_lock_path(db_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    lock = FileLock(str(lock_path), timeout=0)
    try:
        lock.acquire(blocking=False)
        lock.release()
        return False
    except Timeout:
        return True


def enqueue_ingest_chunk(
    db_path: str,
    chunk: str,
    source: str = "conversation",
) -> Path:
    """Write a chunk to the ingest queue directory for later processing.

    File is named with a timestamp prefix for FIFO ordering.

    Returns:
        Path to the enqueued file.
    """
    queue_dir = get_ingest_queue_dir(db_path)
    queue_dir.mkdir(parents=True, exist_ok=True)

    ts = f"{time.time():.6f}"
    suffix = uuid4().hex[:8]
    path = queue_dir / f"{ts}-{suffix}.json"
    path.write_text(json.dumps({"chunk": chunk, "source": source}))

    logger.debug(f"Enqueued ingest chunk: {path.name} ({len(chunk)} chars)")
    return path


def spawn_ingest_worker(
    db_path: str,
    llm_provider: str,
    embedding_provider: str,
) -> bool:
    """Spawn a single background ingest worker that drains the queue.

    Only one worker runs per database (enforced via FileLock).
    If a worker is already running it will pick up newly enqueued chunks
    on its own, so this returns False without spawning.

    Returns:
        True if a new worker was spawned, False if one is already running.
    """
    if is_ingest_running(db_path):
        logger.debug(f"Ingest worker already running for {db_path}")
        return False

    cmd = [
        sys.executable,
        "-m",
        "remind.background_worker",
        "--db",
        db_path,
        "--llm",
        llm_provider,
        "--embedding",
        embedding_provider,
        "--ingest-worker",
    ]

    logger.debug(f"Spawning ingest worker: {' '.join(cmd)}")

    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    return True
