"""
Background consolidation support for Remind CLI.

Provides non-blocking consolidation by spawning a background subprocess.
Uses file locking to prevent concurrent consolidation processes.
"""

import hashlib
import logging
import subprocess
import sys
import time
from pathlib import Path

from filelock import FileLock, Timeout

from remind.config import REMIND_DIR

logger = logging.getLogger(__name__)

# Lock timeout in seconds (30 minutes)
LOCK_TIMEOUT = 1800


def get_consolidation_lock_path(db_path: str) -> Path:
    """Get lock file path for a database.

    Uses a hash of the db_path to create a unique lock file name.
    """
    # Create a short hash of the db path for the lock file name
    db_hash = hashlib.md5(db_path.encode()).hexdigest()[:12]
    return REMIND_DIR / f".consolidate-{db_hash}.lock"


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
