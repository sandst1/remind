"""Read-only diagnosis and explicit derived-state repair."""

from pathlib import Path
from typing import Any

from remind.serialization import validate_records
from remind.provenance import freshness


def diagnose(store: Any, source_root: Path | None = None, embedding=None) -> dict:
    issues = []
    try:
        snapshot = store.export_data()
        validate_records(snapshot["records"])
    except Exception as exc:
        return {"ok": False, "issues": [{"kind": "integrity", "message": str(exc)}]}
    backup = store.export_data(mode="backup")
    for kind in ("episodes", "concepts", "entities", "facts"):
        missing = [row["id"] for row in backup["records"][kind]
                   if not row.get("embedding")]
        if missing:
            issues.append({"kind": "missing_embeddings", "collection": kind, "count": len(missing)})
    for episode in store.get_all_episodes():
        for source in freshness(source_root, episode.metadata.get("source_refs", [])):
            if source["status"] != "unchanged":
                issues.append({"kind": "source_freshness", "episode_id": episode.id, **source})
    fingerprint = store.get_metadata("embedding_fingerprint")
    if embedding is not None and fingerprint:
        import json
        expected = json.dumps({"provider": embedding.name, "dimensions": embedding.dimensions, "input_version": 1}, sort_keys=True)
        if fingerprint != expected:
            issues.append({"kind": "incompatible_embeddings", "action": "re-embed --all"})
    return {"ok": not any(i["kind"] == "integrity" for i in issues), "issues": issues,
            "backend": type(store).__name__, "embedding_fingerprint": store.get_metadata("embedding_fingerprint")}


def diagnose_directory(directory: Path) -> dict:
    """Diagnose invalid canonical data without opening or mutating a projection."""
    issues = []
    if not directory.exists():
        return {"ok": True, "issues": []}
    from remind.file_store import FileMemoryStore
    view = FileMemoryStore.__new__(FileMemoryStore)
    view.directory = directory.resolve()
    try:
        view._read(view._files())
    except Exception as exc:
        issues.append({"kind": "invalid_record", "path": str(directory), "message": str(exc)})
    return {"ok": not issues, "issues": issues}
