"""Git-friendly JSON source of truth with a disposable SQL projection."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4
from typing import Optional

from filelock import FileLock
from sqlalchemy import event

from remind.serialization import TABLE_NAMES, canonical_json, export_store, import_store, revision, validate_records
from remind.store import SQLAlchemyMemoryStore


def _atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


class FileMemoryStore(SQLAlchemyMemoryStore):
    """All API mutations journal canonical files; SQLite is only a cache.

    A committed journal is rolled forward on restart. Recovery refuses to
    overwrite files that match neither the before nor the committed image.
    """

    def __init__(self, directory: str | Path, legacy_db: Optional[Path] = None):
        self.directory = Path(directory).expanduser().resolve()
        token = hashlib.sha256(str(self.directory).encode()).hexdigest()[:16]
        self.runtime = self.directory.parent / "runtime" / token
        self.cache = self.directory.parent / "cache" / token
        self.runtime.mkdir(parents=True, exist_ok=True)
        self.cache.mkdir(parents=True, exist_ok=True)
        self._file_lock = FileLock(str(self.runtime / "store.lock"), timeout=30)
        self._ready = False
        self._digest = None
        self._observed = None
        with self._file_lock:
            super().__init__(f"sqlite:///{self.cache / 'index.db'}")
            with self.engine.connect() as connection:
                connection.exec_driver_sql("PRAGMA journal_mode=WAL")
                connection.commit()
        @event.listens_for(self.engine, "before_execute")
        def track_write(conn, clause, multiparams, params, execution_options):
            if getattr(clause, "is_dml", False) and getattr(getattr(clause, "table", None), "name", None) != "metadata":
                self._local.dirty = True
        self._digest = self.get_metadata("cache_digest")
        self._observed = json.loads(self.get_metadata("cache_stats") or "null")
        self._ready = True
        with self._file_lock:
            self._recover()
            if not self.directory.exists() and legacy_db and legacy_db.exists():
                self._migrate(legacy_db)
            self.directory.mkdir(parents=True, exist_ok=True)
            schema = self.directory / "schema.json"
            if not schema.exists():
                _atomic(schema, canonical_json({"version": 4}))
            self._synchronize()
            if self.directory.parent.name == ".remind":
                ignore = self.directory.parent / ".gitignore"
                content = ignore.read_text() if ignore.exists() else ""
                for rule in ("/cache/", "/runtime/", "*.log", "*.db", "*.db-wal", "*.db-shm"):
                    if rule not in content.splitlines():
                        content += ("\n" if content and not content.endswith("\n") else "") + rule + "\n"
                _atomic(ignore, content)

    def _init_db(self):
        # Rebuilding a cache must never curate or backfill durable knowledge.
        from remind.store import metadata_obj
        metadata_obj.create_all(self.engine)
        self._run_migrations()
        self._init_vector_tables()
        self._init_lexical_index()

    def _files(self) -> dict[str, str]:
        result = {}
        for path in sorted(self.directory.glob("*/*.json")):
            if not path.resolve().is_relative_to(self.directory):
                raise ValueError(f"Memory records cannot escape their directory: {path.name}")
            if path.parent.name not in TABLE_NAMES:
                raise ValueError(f"Unknown memory collection: {path.parent.name}")
            result[path.relative_to(self.directory).as_posix()] = path.read_text(encoding="utf-8")
        return result

    def _file_stats(self) -> dict:
        result = {}
        for folder in os.scandir(self.directory):
            if not folder.is_dir():
                continue
            for entry in os.scandir(folder.path):
                if entry.name.endswith(".json"):
                    stat = entry.stat(follow_symlinks=False)
                    result[f"{folder.name}/{entry.name}"] = [stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
        return result

    def get_metadata(self, key):
        if getattr(self, "_ready", False) and key in {"embedding_dimensions", "embedding_fingerprint", "recall_count", "cache_digest", "cache_stats"}:
            from remind.store import metadata_table
            from sqlalchemy import select
            with super()._connect() as connection:
                return connection.execute(select(metadata_table.c.value).where(metadata_table.c.key == key)).scalar()
        return super().get_metadata(key)

    def set_metadata(self, key, value):
        if getattr(self, "_ready", False) and key.startswith("receipt:"):
            if getattr(self._local, "tx_conn", None) is None:
                with self.transaction():
                    self._local.dirty = True
                    return super().set_metadata(key, value)
            self._local.dirty = True
        if (getattr(self, "_ready", False) and not getattr(self._local, "synchronizing", False)
                and getattr(self._local, "tx_conn", None) is None and not key.startswith("receipt:")):
            with self._file_lock:
                with super().transaction():
                    return super().set_metadata(key, value)
        return super().set_metadata(key, value)

    def _read(self, files: dict[str, str]) -> dict:
        schema = json.loads((self.directory / "schema.json").read_text())
        if schema != {"version": 4}:
            raise ValueError("Unsupported memory schema")
        records = {name: [] for name in TABLE_NAMES}
        for name, content in files.items():
            document = json.loads(content)
            kind = name.split("/", 1)[0]
            if document.get("version") != 4 or document.get("kind") != kind:
                raise ValueError(f"Invalid memory record envelope: {name}")
            records[kind].append(document["record"])
        # Human-facing records contain model data once, without SQL mirrors.
        for kind, text_column in (("concepts", "summary"), ("episodes", "content"), ("entities", "display_name")):
            expanded = []
            for model in records[kind]:
                if "data" in model:  # Read early v4 snapshots as well.
                    expanded.append(model)
                    continue
                row = {"id": model["id"], text_column: model.get(text_column), "data": model}
                if kind == "entities":
                    row.update(type=model["type"], created_at=model["created_at"])
                else:
                    row["title"] = model.get("title")
                    row["deleted_at"] = model.get("deleted_at")
                    if kind == "episodes":
                        row.update(consolidated=model.get("consolidated", False),
                                   episode_type=model.get("episode_type", "observation"),
                                   timestamp=model.get("updated_at") or model["created_at"])
                        records["mentions"].extend({"episode_id": model["id"], "entity_id": entity}
                                                   for entity in model.get("entity_ids", []))
                    else:
                        row.update(created_at=model["created_at"], updated_at=model["updated_at"])
                        row["search_text"] = " ".join([model.get("title") or "", model.get("summary") or "", *model.get("tags", [])])
                        records["relations"].extend({"source_id": model["id"], "target_id": rel["target_id"],
                            "type": rel["type"], "strength": rel.get("strength", .5), "context": rel.get("context")}
                            for rel in model.get("relations", []))
                    records["labels"].extend({"subject_type": kind[:-1], "subject_id": model["id"], "key": key, "value": value}
                        for key, values in model.get("labels", {}).items() for value in values)
                expanded.append(row)
            records[kind] = expanded
        records["events"].sort(key=lambda row: (row["ts"], row["event_id"]))
        for seq, row in enumerate(records["events"], 1):
            row["seq"] = seq
        validate_records(records)
        return {"version": 4, "mode": "portable", "records": records}

    def _synchronize(self) -> None:
        if json.loads((self.directory / "schema.json").read_text()) != {"version": 4}:
            raise ValueError("Unsupported memory schema")
        observed = self._file_stats()
        if self._digest is not None and observed == self._observed:
            return
        files = self._files()
        digest = revision(files)
        if digest == self._digest:
            self._observed = observed
            self.set_metadata("cache_stats", json.dumps(observed))
            return
        snapshot = self._read(files)
        self._local.synchronizing = True
        try:
            cached = export_store(self, "backup")["records"]
            for kind in ("concepts", "episodes", "entities", "facts"):
                old = {row["id"]: row for row in cached[kind]}
                from remind.serialization import portable_row
                for index, row in enumerate(snapshot["records"][kind]):
                    previous = old.get(row["id"])
                    if previous is not None and portable_row(kind, previous) == row:
                        snapshot["records"][kind][index] = previous
            snapshot["mode"] = "backup"
            snapshot["records"]["metadata"].extend(row for row in cached["metadata"]
                if not row["key"].startswith("receipt:"))
            from remind.serialization import synchronize_projection
            synchronize_projection(self, snapshot["records"])
            self._digest = digest
            self._observed = observed
            self.set_metadata("cache_digest", digest)
            self.set_metadata("cache_stats", json.dumps(observed))
            self.set_metadata("event_generation", uuid4().hex)
        finally:
            self._local.synchronizing = False

    def _images(self, records=None) -> dict[str, str]:
        records = export_store(self)["records"] if records is None else records
        mentions, relations, subject_labels = {}, {}, {}
        for mention in records["mentions"]:
            mentions.setdefault(mention["episode_id"], []).append(mention["entity_id"])
        for relation in records["relations"]:
            relations.setdefault(relation["source_id"], []).append(relation)
        for label in records["labels"]:
            subject_labels.setdefault((label["subject_type"], label["subject_id"]), {}).setdefault(label["key"], []).append(label["value"])
        result = {}
        for kind, rows in records.items():
            if kind in {"mentions", "relations"}:
                continue
            for source in rows:
                if kind == "labels" and source["subject_type"] in {"episode", "concept"}:
                    continue
                row = dict(source)
                if kind == "metadata" and (row["key"] == "event_generation" or not row["key"].startswith("receipt:")):
                    continue
                if kind == "events":
                    row.pop("seq", None)
                    identity = row["event_id"]
                else:
                    from remind.store import metadata_obj
                    identity = [row[c.name] for c in metadata_obj.tables[kind].primary_key]
                if kind in {"episodes", "concepts", "entities"}:
                    row = dict(row["data"])
                    if kind == "episodes":
                        row["entity_ids"] = sorted(set(mentions.get(row["id"], [])))
                    if kind == "concepts":
                        row["relations"] = [{key: relation[key] for key in ("target_id", "type", "strength", "context")}
                            for relation in relations.get(row["id"], [])]
                    if kind != "entities":
                        labels = subject_labels.get((kind[:-1], row["id"]), {})
                        row["labels"] = {key: sorted(set(values)) for key, values in sorted(labels.items())}
                filename = identity if isinstance(identity, str) else (
                    str(identity[0]) if len(identity) == 1 and all(c.isalnum() or c == '-' for c in str(identity[0]))
                    else revision(identity))
                result[f"{kind}/{filename}.json"] = canonical_json({
                    "version": 4, "kind": kind, "record": row,
                })
        return result

    def _persist(self) -> None:
        records = export_store(self)["records"]
        validate_records(records)
        before, after = self._files(), self._images(records)
        changes = {name: {"before": revision(before.get(name)), "after": after.get(name)}
                   for name in before.keys() | after.keys() if before.get(name) != after.get(name)}
        if changes:
            _atomic(self.runtime / "journal.json", canonical_json({"committed": True, "changes": changes}))
            self._recover()
        self._digest = revision(after)
        self._observed = self._file_stats()
        self.set_metadata("cache_digest", self._digest)
        self.set_metadata("cache_stats", json.dumps(self._observed))

    def _recover(self) -> None:
        journal = self.runtime / "journal.json"
        if not journal.exists():
            return
        state = json.loads(journal.read_text())
        if state.get("committed") is not True:
            raise ValueError("Invalid recovery journal")
        for name, change in state["changes"].items():
            path = self.directory / name
            if path.resolve().parent.parent != self.directory or path.suffix != ".json":
                raise ValueError("Unsafe recovery path")
            current = path.read_text() if path.exists() else None
            if revision(current) not in {change["before"], revision(change["after"])}:
                raise ValueError(f"Recovery blocked by external edit: {name}")
        for name, change in state["changes"].items():
            path = self.directory / name
            if change["after"] is None:
                path.unlink(missing_ok=True)
            else:
                _atomic(path, change["after"])
        journal.unlink()

    @contextmanager
    def read_snapshot(self):
        """Reconcile once, then pin a WAL snapshot for the whole request."""
        from remind.read_snapshot import ReadSnapshotStore
        with self._file_lock:
            self._recover()
            self._synchronize()
            connection = self.engine.connect()
            connection.exec_driver_sql("BEGIN")
            connection.exec_driver_sql("SELECT COUNT(*) FROM episodes").scalar()
        try:
            yield ReadSnapshotStore(self, connection)
        finally:
            connection.rollback()
            connection.close()

    @contextmanager
    def _connect(self):
        if (not getattr(self, "_ready", False) or getattr(self._local, "synchronizing", False)
                or getattr(self._local, "tx_conn", None) is not None):
            with super()._connect() as conn:
                yield conn
        else:
            with self.transaction():
                yield self._local.tx_conn

    @contextmanager
    def transaction(self):
        if not self._ready or getattr(self._local, "synchronizing", False):
            with super().transaction():
                yield
            return
        with self._file_lock:
            self._recover()
            self._synchronize()
            self._local.dirty = False
            persist_started = False
            try:
                with super().transaction():
                    yield
                    if self._local.dirty:
                        persist_started = True
                        self._persist()
            except BaseException:
                # A durable decision may already exist. Reconcile before use.
                # A rejected edit before persistence only rolls back SQL; its
                # unchanged files must not cause event resequencing/cursor reset.
                if persist_started:
                    self._digest = None
                raise

    def _migrate(self, legacy: Path) -> None:
        backup = self.runtime / "legacy-backup.db"
        if not backup.exists():
            with sqlite3.connect(legacy) as source, sqlite3.connect(backup) as target:
                source.backup(target)
        old = SQLAlchemyMemoryStore(f"sqlite:///{backup}")
        try:
            data = old.export_data()
        finally:
            old.engine.dispose()
        self._local.synchronizing = True
        try:
            import_store(self, data, replace=True)
            self.directory.mkdir(parents=True, exist_ok=True)
            _atomic(self.directory / "schema.json", canonical_json({"version": 4}))
            self._persist()
            actual = self._read(self._files())["records"]
            if self._images(actual) != self._images(data["records"]):
                raise ValueError("Migration verification failed: canonical content differs")
            for kind in TABLE_NAMES:
                if kind not in {"metadata", "events"} and len(actual[kind]) != len(data["records"][kind]):
                    raise ValueError(f"Migration verification failed: {kind}")
        finally:
            self._local.synchronizing = False
