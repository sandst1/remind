"""
Background worker for consolidation and ingestion - invoked as subprocess by CLI.

Usage:
    # Consolidation mode
    python -m remind.background_worker --db /path/to/db.db --llm anthropic --embedding openai

    # Ingest worker mode (drains the queue, one chunk at a time)
    python -m remind.background_worker --db /path/to/db.db --llm anthropic --embedding openai \
        --ingest-worker

    # Legacy: single-chunk ingest (kept for backward compat)
    python -m remind.background_worker --db /path/to/db.db --llm anthropic --embedding openai \
        --ingest-chunk-file /path/to/chunk.json
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from pathlib import Path

from filelock import FileLock, Timeout

from remind.background import (
    get_consolidation_lock_path,
    get_ingest_lock_path,
    get_ingest_queue_dir,
    LOCK_TIMEOUT,
    INGEST_WORKER_GRACE_SECONDS,
)
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


def run_consolidation(args, logger):
    """Run consolidation with file locking."""
    lock_path = get_consolidation_lock_path(args.db)
    lock = FileLock(str(lock_path), timeout=0)

    try:
        lock.acquire(blocking=False)
    except Timeout:
        logger.info(f"Consolidation already running for {args.db}")
        return

    try:
        logger.info(f"Starting background consolidation for {args.db}")

        from remind.interface import create_memory

        memory = create_memory(
            llm_provider=args.llm,
            embedding_provider=args.embedding,
            db_path=args.db,
            ingest_background=False,
        )

        async def _consolidate():
            return await memory.consolidate(force=False)

        result = asyncio.run(_consolidate())

        logger.info(
            f"Consolidation complete for {args.db}: "
            f"processed={result.episodes_processed}, "
            f"created={result.concepts_created}, "
            f"updated={result.concepts_updated}"
        )

    except Exception as e:
        logger.exception(f"Consolidation failed for {args.db}: {e}")

    finally:
        lock.release()


def run_ingest(args, logger):
    """Run triage + consolidation on a chunk from a temp file."""
    chunk_path = Path(args.ingest_chunk_file)

    try:
        data = json.loads(chunk_path.read_text())
        chunk = data["chunk"]
        source = data.get("source", "conversation")
    except Exception as e:
        logger.exception(f"Failed to read ingest chunk file {chunk_path}: {e}")
        return
    finally:
        try:
            chunk_path.unlink(missing_ok=True)
        except Exception:
            pass

    logger.info(f"Starting background ingest for {args.db} ({len(chunk)} chars, source={source})")

    try:
        from remind.interface import create_memory

        memory = create_memory(
            llm_provider=args.llm,
            embedding_provider=args.embedding,
            db_path=args.db,
            ingest_background=False,
        )

        async def _ingest():
            return await memory._process_ingest_chunk(chunk, source)

        episode_ids = asyncio.run(_ingest())

        logger.info(
            f"Background ingest complete for {args.db}: "
            f"{len(episode_ids)} episodes created"
        )

    except Exception as e:
        logger.exception(f"Background ingest failed for {args.db}: {e}")


def _next_queued_chunk(queue_dir: Path) -> tuple[Path, str, str] | None:
    """Pop the oldest chunk file from the queue directory.

    Returns (path, chunk_text, source) or None if queue is empty.
    """
    if not queue_dir.is_dir():
        return None

    files = sorted(queue_dir.glob("*.json"))
    if not files:
        return None

    path = files[0]
    try:
        data = json.loads(path.read_text())
        chunk = data["chunk"]
        source = data.get("source", "conversation")
    except Exception:
        path.unlink(missing_ok=True)
        return None

    path.unlink(missing_ok=True)
    return path, chunk, source


def run_ingest_worker(args, logger):
    """Drain the ingest queue one chunk at a time under a file lock."""
    lock_path = get_ingest_lock_path(args.db)
    lock = FileLock(str(lock_path), timeout=0)

    try:
        lock.acquire(blocking=False)
    except Timeout:
        logger.info(f"Ingest worker already running for {args.db}")
        return

    try:
        logger.info(f"Ingest worker started for {args.db}")

        from remind.interface import create_memory

        memory = create_memory(
            llm_provider=args.llm,
            embedding_provider=args.embedding,
            db_path=args.db,
            ingest_background=False,
        )

        queue_dir = get_ingest_queue_dir(args.db)
        total_episodes = 0
        chunks_processed = 0

        while True:
            item = _next_queued_chunk(queue_dir)
            if item is None:
                # Grace period: wait briefly for late arrivals, then check once more
                time.sleep(INGEST_WORKER_GRACE_SECONDS)
                item = _next_queued_chunk(queue_dir)
                if item is None:
                    break

            _, chunk, source = item
            logger.info(
                f"Processing queued chunk ({len(chunk)} chars, source={source})"
            )

            try:
                episode_ids = asyncio.run(
                    memory._process_ingest_chunk(chunk, source)
                )
                total_episodes += len(episode_ids)
                chunks_processed += 1
                logger.info(
                    f"Chunk done: {len(episode_ids)} episodes "
                    f"(total: {chunks_processed} chunks, {total_episodes} episodes)"
                )
            except Exception as e:
                logger.exception(f"Failed to process queued chunk: {e}")

        logger.info(
            f"Ingest worker finished for {args.db}: "
            f"{chunks_processed} chunks, {total_episodes} episodes"
        )

    except Exception as e:
        logger.exception(f"Ingest worker failed for {args.db}: {e}")

    finally:
        lock.release()


def main():
    parser = argparse.ArgumentParser(description="Background worker for consolidation and ingestion")
    parser.add_argument("--db", required=True, help="Database path")
    parser.add_argument("--llm", required=True, help="LLM provider")
    parser.add_argument("--embedding", required=True, help="Embedding provider")
    parser.add_argument("--ingest-worker", action="store_true", help="Run as queue-draining ingest worker")
    parser.add_argument("--ingest-chunk-file", help="(Legacy) Path to temp JSON file with chunk to ingest")
    args = parser.parse_args()

    logger = setup_logging()

    if args.ingest_worker:
        run_ingest_worker(args, logger)
    elif args.ingest_chunk_file:
        run_ingest(args, logger)
    else:
        run_consolidation(args, logger)


if __name__ == "__main__":
    main()
