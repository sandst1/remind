"""
Background worker for consolidation - invoked as subprocess by CLI.

Usage:
    python -m remind.background_worker --db /path/to/db.db --llm anthropic --embedding openai
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from filelock import FileLock, Timeout

from remind.background import get_consolidation_lock_path, LOCK_TIMEOUT
from remind.config import REMIND_DIR


def setup_logging() -> logging.Logger:
    """Set up logging to a file."""
    log_dir = REMIND_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        filename=str(log_dir / "consolidation.log"),
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
    return logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Background consolidation worker")
    parser.add_argument("--db", required=True, help="Database path")
    parser.add_argument("--llm", required=True, help="LLM provider")
    parser.add_argument("--embedding", required=True, help="Embedding provider")
    args = parser.parse_args()

    logger = setup_logging()

    # Acquire lock
    lock_path = get_consolidation_lock_path(args.db)
    lock = FileLock(str(lock_path), timeout=0)

    try:
        lock.acquire(blocking=False)
    except Timeout:
        # Another process has the lock
        logger.info(f"Consolidation already running for {args.db}")
        return

    try:
        logger.info(f"Starting background consolidation for {args.db}")

        # Run consolidation
        from remind.interface import create_memory

        memory = create_memory(
            llm_provider=args.llm,
            embedding_provider=args.embedding,
            db_path=args.db,
        )

        async def run_consolidation():
            return await memory.consolidate(force=False)

        result = asyncio.run(run_consolidation())

        logger.info(
            f"Consolidation complete for {args.db}: "
            f"processed={result.episodes_processed}, "
            f"created={result.concepts_created}, "
            f"updated={result.concepts_updated}"
        )

    except Exception as e:
        logger.exception(f"Consolidation failed for {args.db}: {e}")

    finally:
        # Release lock
        lock.release()


if __name__ == "__main__":
    main()
