"""
Background worker for consolidation and ingestion - invoked as subprocess by CLI.

Usage:
    # Consolidation mode
    python -m remind.background_worker --db /path/to/db.db --llm anthropic --embedding openai

    # Ingest mode (triage + consolidation on a chunk)
    python -m remind.background_worker --db /path/to/db.db --llm anthropic --embedding openai \
        --ingest-chunk-file /path/to/chunk.json
"""

import argparse
import asyncio
import json
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


def main():
    parser = argparse.ArgumentParser(description="Background worker for consolidation and ingestion")
    parser.add_argument("--db", required=True, help="Database path")
    parser.add_argument("--llm", required=True, help="LLM provider")
    parser.add_argument("--embedding", required=True, help="Embedding provider")
    parser.add_argument("--ingest-chunk-file", help="Path to temp JSON file with chunk to ingest")
    args = parser.parse_args()

    logger = setup_logging()

    if args.ingest_chunk_file:
        run_ingest(args, logger)
    else:
        run_consolidation(args, logger)


if __name__ == "__main__":
    main()
