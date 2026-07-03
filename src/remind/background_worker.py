"""
Background recall worker - invoked as subprocess by CLI.

Usage:
    python -m remind.background_worker --db /path/to/db.db --embedding local \
        --recall-worker --recall-worker-key <key> --recall-socket /path/to.sock
"""

import argparse
import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Optional

from filelock import FileLock, Timeout

from remind.background import (
    DEFAULT_RECALL_WORKER_IDLE_SECONDS,
    get_recall_lock_path,
)
from remind.config import REMIND_DIR, load_config, setup_file_logging


def _log_dir_for_db(db_path: str, remind_dir: Path | None = None) -> Path:
    """Return the log directory for a database path."""
    if remind_dir is not None:
        return remind_dir / "logs"
    if db_path.startswith("sqlite:///"):
        db_file = Path(db_path[len("sqlite:///"):])
        return db_file.parent / "logs"
    if "://" not in db_path:
        return Path(db_path).parent / "logs"
    return REMIND_DIR / "logs"


def setup_logging(db_path: str, remind_dir: Path | None = None) -> logging.Logger:
    """Set up logging to a file next to the database."""
    log_dir = _log_dir_for_db(db_path, remind_dir=remind_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        filename=str(log_dir / "recall-worker.log"),
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    project_dir = remind_dir.parent if remind_dir is not None else None
    config = load_config(project_dir=project_dir)
    if config.logging_enabled:
        setup_file_logging(db_path, project_dir=project_dir)

    return logging.getLogger(__name__)


def _serialize_recall_raw_result(result: Any, entity: Optional[str]) -> dict[str, Any]:
    """Convert raw recall objects to JSON-safe payloads."""
    if entity:
        return {
            "result_type": "entity_raw",
            "result": [ep.to_dict() for ep in result],
        }

    return {
        "result_type": "semantic_raw",
        "result": [
            {
                "concept": ac.concept.to_dict(),
                "activation": ac.activation,
                "source": ac.source,
                "hops": ac.hops,
            }
            for ac in result
        ],
    }


def run_recall_worker(args, logger):
    """Serve recall requests over a Unix socket under a file lock."""
    if not args.recall_socket:
        logger.error("Recall worker requires --recall-socket")
        return
    if not args.recall_worker_key:
        logger.error("Recall worker requires --recall-worker-key")
        return

    remind_dir = Path(args.remind_dir) if args.remind_dir else None
    project_dir = remind_dir.parent if remind_dir is not None else None
    lock_path = get_recall_lock_path(args.db, args.recall_worker_key, remind_dir=remind_dir)
    lock = FileLock(str(lock_path), timeout=0)

    try:
        lock.acquire(blocking=False)
    except Timeout:
        logger.info(f"Recall worker already running for {args.db} ({args.recall_worker_key})")
        return

    socket_path = Path(args.recall_socket)
    socket_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from remind.interface import create_memory

        memory = create_memory(
            embedding_provider=args.embedding,
            db_url=args.db,
            project_dir=project_dir,
        )
    except Exception as e:
        logger.exception(f"Failed to initialize recall worker memory for {args.db}: {e}")
        lock.release()
        return

    idle_seconds = max(5, int(args.recall_idle_seconds or DEFAULT_RECALL_WORKER_IDLE_SECONDS))
    logger.info(
        f"Recall worker started for {args.db} ({args.recall_worker_key}, idle={idle_seconds}s)"
    )

    async def _serve():
        last_activity = time.monotonic()
        stop_event = asyncio.Event()

        if socket_path.exists():
            try:
                socket_path.unlink()
            except OSError:
                pass

        async def _send(writer: asyncio.StreamWriter, payload: dict[str, Any]) -> None:
            writer.write((json.dumps(payload) + "\n").encode("utf-8"))
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        async def _handle_client(
            reader: asyncio.StreamReader, writer: asyncio.StreamWriter
        ) -> None:
            nonlocal last_activity
            try:
                line = await reader.readline()
                if not line:
                    await _send(writer, {"ok": False, "error": "empty request"})
                    return
                req = json.loads(line.decode("utf-8"))
            except Exception:
                await _send(writer, {"ok": False, "error": "invalid request"})
                return

            action = req.get("action")
            if action == "ping":
                last_activity = time.monotonic()
                await _send(writer, {"ok": True, "pong": True})
                return
            if action != "recall":
                await _send(writer, {"ok": False, "error": "unknown action"})
                return

            try:
                query = req.get("query")
                entity = req.get("entity")
                raw = bool(req.get("raw"))
                k = int(req.get("k", 3))
                episode_k = int(req.get("episode_k", 5))
                context = req.get("context")
                topic = req.get("topic")

                result = await memory.recall(
                    query=query,
                    k=k,
                    context=context,
                    entity=entity,
                    raw=raw,
                    episode_k=episode_k,
                    topic=topic,
                )
                last_activity = time.monotonic()
                if raw:
                    raw_payload = _serialize_recall_raw_result(result, entity)
                    await _send(writer, {"ok": True, **raw_payload})
                else:
                    await _send(writer, {"ok": True, "result_type": "text", "result": result})
            except Exception as e:
                logger.exception(f"Recall worker request failed: {e}")
                await _send(writer, {"ok": False, "error": str(e)})

        server = await asyncio.start_unix_server(_handle_client, path=str(socket_path))
        try:
            async with server:
                while not stop_event.is_set():
                    await asyncio.sleep(1.0)
                    if (time.monotonic() - last_activity) >= idle_seconds:
                        logger.info(
                            f"Recall worker idle timeout reached ({idle_seconds}s), shutting down"
                        )
                        stop_event.set()
        finally:
            server.close()
            await server.wait_closed()

    try:
        asyncio.run(_serve())
        logger.info(f"Recall worker stopped for {args.db} ({args.recall_worker_key})")
    except Exception as e:
        logger.exception(f"Recall worker failed for {args.db}: {e}")
    finally:
        try:
            socket_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            lock.release()
        except Exception:
            pass
        try:
            asyncio.run(memory.aclose())
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Background recall worker")
    parser.add_argument("--db", required=True, help="Database URL or path")
    parser.add_argument("--embedding", required=True, help="Embedding provider")
    parser.add_argument("--remind-dir", help="Project-local .remind directory for logs/locks")
    parser.add_argument("--recall-worker", action="store_true", help="Run as persistent recall worker")
    parser.add_argument("--recall-worker-key", help="Recall worker identity key")
    parser.add_argument("--recall-socket", help="Unix socket path for recall worker IPC")
    parser.add_argument(
        "--recall-idle-seconds",
        type=int,
        default=DEFAULT_RECALL_WORKER_IDLE_SECONDS,
        help="Idle timeout for recall worker before exit",
    )
    args = parser.parse_args()

    remind_dir = Path(args.remind_dir) if args.remind_dir else None
    logger = setup_logging(args.db, remind_dir=remind_dir)

    if args.recall_worker:
        run_recall_worker(args, logger)
    else:
        logger.error("No worker mode specified. Use --recall-worker")


if __name__ == "__main__":
    main()
