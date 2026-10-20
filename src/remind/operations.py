"""Shared concurrency and idempotency contracts."""

from __future__ import annotations

import json
from functools import wraps
from typing import Any, Optional

from sqlalchemy import select

from remind.serialization import revision, portable_row


class RevisionConflict(ValueError):
    def __init__(self, subject_id: str, current_revision: Optional[str]):
        self.subject_id = subject_id
        self.current_revision = current_revision
        super().__init__(f"Revision conflict for {subject_id}; current revision: {current_revision}")


def record_revision(store: Any, subject_id: str) -> Optional[str]:
    from remind.store import metadata_obj, _parse_json
    with store._connect() as conn:
        for name in ("episodes", "concepts", "facts", "conflicts", "entities", "evidence"):
            table = metadata_obj.tables[name]
            row = conn.execute(select(table).where(table.c.id == subject_id).with_for_update()).mappings().first()
            if row:
                return row_revision(name, dict(row))
    return None


def row_revision(name: str, value: dict) -> str:
    from remind.store import _parse_json
    value = dict(value)
    if "data" in value:
        value["data"] = _parse_json(value["data"])
    return revision(json.loads(json.dumps(portable_row(name, value), default=str)))


def check_revisions(store: Any, expected: dict[str, str]) -> None:
    for identifier, wanted in expected.items():
        current = record_revision(store, identifier)
        if current != wanted:
            raise RevisionConflict(identifier, current)


def resolve_id(store: Any, identifier: str) -> str:
    """Resolve exact IDs first, then an unambiguous opaque-ID prefix."""
    from remind.store import metadata_obj
    names = ("episodes", "concepts", "facts", "conflicts", "entities", "evidence")
    with store._connect() as conn:
        for name in names:
            table = metadata_obj.tables[name]
            if conn.execute(select(table.c.id).where(table.c.id == identifier)).first():
                return identifier
        prefix = identifier
        if identifier.startswith(("ep:", "fact:", "conflict:", "concept:")):
            prefix = identifier.split(":", 1)[1]
        if len(prefix) < 4:
            return identifier
        matches = set()
        for name in names:
            table = metadata_obj.tables[name]
            matches.update(conn.execute(select(table.c.id).where(table.c.id.startswith(prefix, autoescape=True))).scalars())
        if len(matches) > 1:
            raise ValueError(f"Ambiguous record ID prefix: {identifier}")
        return next(iter(matches)) if matches else identifier


def receipt(store: Any, key: Optional[str], request: Any) -> Optional[dict]:
    if key is None:
        return None
    raw = store.get_metadata("receipt:" + revision(key))
    if raw:
        saved = json.loads(raw)
        if saved["request_hash"] != revision(request):
            raise ValueError("Idempotency key was already used for a different request")
        return saved["result"]
    return None


def save_receipt(store: Any, key: Optional[str], request: Any, result: dict) -> None:
    if key is not None:
        store.set_metadata("receipt:" + revision(key), json.dumps({
            "request_hash": revision(request), "result": result,
        }))


def revision_edit(kind: str):
    """Require a caller's revision, then commit an edit and event together."""
    def decorate(method):
        @wraps(method)
        def wrapped(self, identifier, *args, expected_revision=None, **kwargs):
            with self.store.transaction():
                identifier = resolve_id(self.store, identifier)
                current = record_revision(self.store, identifier)
                if current is None:
                    return None
                if expected_revision is None or current != expected_revision:
                    raise RevisionConflict(identifier, current)
                result = method(self, identifier, *args, **kwargs)
                if result is not None and result is not False:
                    self.store.emit_event(kind, "conflict" if "conflict" in method.__name__ else "concept" if "concept" in method.__name__ else "episode", identifier)
                    if hasattr(result, "to_dict"):
                        result._revision = record_revision(self.store, identifier)
                return result
        return wrapped
    return decorate
