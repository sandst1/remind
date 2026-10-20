"""Versioned, complete snapshots shared by SQL and file stores."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, LargeBinary, select

FORMAT_VERSION = 4
TABLE_NAMES = (
    "entities", "concepts", "episodes", "facts", "conflicts", "evidence",
    "relations", "mentions", "entity_relations", "labels", "events", "metadata",
)
RUNTIME_KEYS = {"recall_count", "embedding_dimensions", "embedding_fingerprint", "event_generation", "cache_digest"}
USAGE_KEYS = {"last_accessed", "access_count", "decay_factor"}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"


def revision(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def portable_row(name: str, row: dict) -> dict:
    row = dict(row)
    row.pop("embedding", None)
    if name == "mentions":
        row.pop("created_at", None)  # Derived from episode entity references.
    if isinstance(row.get("data"), dict):
        row["data"] = {k: v for k, v in row["data"].items()
                       if k != "embedding" and k not in USAGE_KEYS}
    return row


def export_store(store: Any, mode: str = "portable") -> dict:
    from remind.store import metadata_obj

    if mode not in {"portable", "backup"}:
        raise ValueError("mode must be portable or backup")
    records = {}
    with store._connect() as conn:
        for name in TABLE_NAMES:
            rows = []
            for result in conn.execute(select(metadata_obj.tables[name])).mappings():
                row = dict(result)
                if isinstance(row.get("data"), str):
                    row["data"] = json.loads(row["data"])
                if name == "metadata" and mode == "portable" and not row["key"].startswith("receipt:"):
                    continue
                for key, value in row.items():
                    if isinstance(value, datetime):
                        row[key] = value.isoformat()
                    elif isinstance(value, bytes):
                        row[key] = {"base64": base64.b64encode(value).decode()}
                rows.append(portable_row(name, row) if mode == "portable" else row)
            records[name] = sorted(rows, key=canonical_json)
    # Keep familiar top-level views for callers of previous export versions.
    return {"version": FORMAT_VERSION, "mode": mode, "records": records,
            "concepts": [r["data"] for r in records["concepts"]],
            "episodes": [r["data"] for r in records["episodes"]],
            "entities": [r["data"] for r in records["entities"]]}


def _record_identities(records: dict) -> dict:
    from remind.store import metadata_obj

    if not isinstance(records, dict) or set(records) - set(TABLE_NAMES):
        raise ValueError("Unknown snapshot record collection")
    identities = {}
    for name, rows in records.items():
        if not isinstance(rows, list):
            raise ValueError(f"{name} must be an array")
        table = metadata_obj.tables[name]
        keys = [c.name for c in table.primary_key]
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) - set(table.c.keys()):
                raise ValueError(f"Invalid {name} record")
            identity = tuple(row.get(k) for k in keys)
            if None in identity or identity in seen:
                raise ValueError(f"Missing or duplicate {name} identity: {identity}")
            seen.add(identity)
            canonical_json(row)
        identities[name] = seen
    return identities


def validate_records(records: dict) -> None:
    identities = _record_identities(records)
    def require(name: str, identifier: Any) -> None:
        if identifier is not None and (identifier,) not in identities.get(name, set()):
            raise ValueError(f"Dangling reference to {name}: {identifier}")
    for row in records.get("concepts", []):
        model = row.get("data") or {}
        if isinstance(model, str):
            model = json.loads(model)
        for episode_id in model.get("source_episodes", []):
            require("episodes", episode_id)
        for relation in model.get("relations", []):
            require("concepts", relation["target_id"])
    for row in records.get("conflicts", []):
        identifiers = row.get("concept_ids") or []
        if isinstance(identifiers, str):
            identifiers = json.loads(identifiers)
        for identifier in identifiers:
            require("concepts", identifier)
    for row in records.get("labels", []):
        target = {"episode": "episodes", "concept": "concepts", "fact": "facts"}.get(row["subject_type"])
        if target is None:
            raise ValueError("Invalid label subject type")
        require(target, row["subject_id"])
    for name, fields in {
        "facts": {"cluster_id": "concepts", "source_episode_id": "episodes", "superseded_by": "facts"},
        "evidence": {"episode_id": "episodes", "concept_id": "concepts"},
        "mentions": {"episode_id": "episodes", "entity_id": "entities"},
        "relations": {"source_id": "concepts", "target_id": "concepts"},
        "entity_relations": {"source_id": "entities", "target_id": "entities", "source_episode_id": "episodes"},
        "conflicts": {"fact_a_id": "facts", "fact_b_id": "facts", "winning_fact_id": "facts"},
    }.items():
        for row in records.get(name, []):
            for field, target in fields.items():
                require(target, row.get(field))
    facts = {row["id"]: row for row in records.get("facts", [])}
    for fact in facts.values():
        if fact.get("valid_to") and fact["valid_to"] < fact["valid_from"]:
            raise ValueError("Fact validity window ends before it starts")
        seen = set()
        current = fact
        while current.get("superseded_by"):
            if current["id"] in seen:
                raise ValueError("Cycle in fact supersession")
            seen.add(current["id"])
            current = facts[current["superseded_by"]]


def import_store(store: Any, data: dict, replace: bool = False) -> dict:
    # Validate against the same locked state that will receive the writes.
    if getattr(store._local, "tx_conn", None) is not None:
        return _import_store(store, data, replace)
    with store.transaction():
        return _import_store(store, data, replace)


def _import_store(store: Any, data: dict, replace: bool = False) -> dict:
    from remind.store import metadata_obj

    if data.get("version") != FORMAT_VERSION or "records" not in data:
        raise ValueError("Expected a version 4 snapshot")
    import copy
    records = copy.deepcopy(data["records"])
    # Do not silently collapse duplicate identities while assembling a merge.
    _record_identities(records)
    # Merge is validated as a complete prospective state, including existing references.
    existing = export_store(store, data.get("mode", "portable"))["records"]
    if not replace and records.get("events") and existing["events"]:
        prior = {row["event_id"]: row for row in existing["events"]}
        next_seq = max((row["seq"] for row in existing["events"]), default=0)
        for event in sorted(records["events"], key=lambda row: row["seq"]):
            previous = prior.get(event["event_id"])
            if previous is not None:
                if {k: v for k, v in previous.items() if k != "seq"} != {k: v for k, v in event.items() if k != "seq"}:
                    raise ValueError("Conflicting durable event identity")
                event["seq"] = previous["seq"]
            else:
                next_seq += 1
                event["seq"] = next_seq
    merged = {} if replace else dict(existing)
    for name, incoming in records.items():
        table = metadata_obj.tables.get(name)
        if table is None:
            raise ValueError(f"Unknown collection: {name}")
        keys = [c.name for c in table.primary_key]
        by_id = {tuple(r[k] for k in keys): r for r in merged.get(name, [])}
        for row in incoming:
            identity = tuple(row[k] for k in keys)
            if identity in by_id and by_id[identity] != row:
                raise ValueError(f"Import conflict in {name}: {identity}")
            by_id[identity] = row
        merged[name] = list(by_id.values())
    validate_records(merged)
    def write() -> None:
        with store._connect() as conn:
            if replace:
                for name in reversed(TABLE_NAMES):
                    conn.execute(metadata_obj.tables[name].delete())
            for name in TABLE_NAMES:
                table = metadata_obj.tables[name]
                keys = [c.name for c in table.primary_key]
                present = set() if replace else {tuple(r[k] for k in keys) for r in existing.get(name, [])}
                for source in records.get(name, []):
                    if tuple(source[k] for k in keys) in present:
                        continue
                    row = dict(source)
                    for col in table.c:
                        value = row.get(col.name)
                        if value is not None and isinstance(col.type, DateTime):
                            row[col.name] = datetime.fromisoformat(value)
                        elif value is not None and isinstance(col.type, LargeBinary):
                            row[col.name] = base64.b64decode(value["base64"], validate=True)
                    conn.execute(table.insert().values(**row))
    if getattr(store._local, "tx_conn", None) is not None:
        write()
    else:
        with store.transaction():
            write()
    return {f"{name}_imported": len(records.get(name, [])) for name in TABLE_NAMES}


def synchronize_projection(store: Any, records: dict) -> None:
    """Apply only externally changed rows to a disposable SQL projection."""
    from sqlalchemy import and_
    from remind.store import metadata_obj, _bytes_to_embedding
    old = export_store(store, "backup")["records"]
    removed, added = {}, {}
    for name in TABLE_NAMES:
        table = metadata_obj.tables[name]
        keys = [c.name for c in table.primary_key]
        previous = {tuple(r[k] for k in keys): r for r in old[name]}
        desired = {tuple(r[k] for k in keys): r for r in records[name]}
        removed[name] = {key: row for key, row in previous.items() if desired.get(key) != row}
        added[name] = {key: row for key, row in desired.items() if previous.get(key) != row}
    with store.transaction():
        with store._connect() as conn:
            for name in reversed(TABLE_NAMES):
                table = metadata_obj.tables[name]
                for key in removed[name]:
                    conn.execute(table.delete().where(and_(*(col == value for col, value in zip(table.primary_key, key)))))
            for name in TABLE_NAMES:
                table = metadata_obj.tables[name]
                for key, source in added[name].items():
                    row = dict(source)
                    for column in table.c:
                        value = row.get(column.name)
                        if value is not None and isinstance(column.type, DateTime):
                            row[column.name] = datetime.fromisoformat(value)
                        elif value is not None and isinstance(column.type, LargeBinary):
                            row[column.name] = base64.b64decode(value["base64"], validate=True)
                    conn.execute(table.insert().values(**row))
            for name, singular in (("concepts", "concept"), ("episodes", "episode"), ("facts", "fact")):
                for key in removed[name]:
                    getattr(store, "_delete_vec_" + singular)(conn, key[0])
                    if name != "facts":
                        getattr(store, "_delete_fts_" + singular)(conn, key[0])
                for key, source in added[name].items():
                    blob = source.get("embedding")
                    vector = _bytes_to_embedding(base64.b64decode(blob["base64"])) if blob else None
                    getattr(store, "_upsert_vec_" + singular)(conn, key[0], vector)
                    if name != "facts":
                        getattr(store, "_upsert_fts_" + singular)(conn, key[0], source.get("title"),
                                                               source.get("summary" if name == "concepts" else "content"))
