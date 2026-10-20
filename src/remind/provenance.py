"""Portable file provenance and read-only freshness checks."""

import hashlib
from pathlib import Path
import subprocess
from typing import Optional


def capture_sources(root: Path, entity_ids: list[str]) -> list[dict]:
    references = []
    if not any(entity.startswith("file:") for entity in entity_ids):
        return references
    commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                            capture_output=True, text=True).stdout.strip() or None
    for entity in entity_ids:
        if not entity.startswith("file:"):
            continue
        path = (root / entity[5:]).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            continue
        references.append({"path": path.relative_to(root.resolve()).as_posix(),
                           "commit": commit, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return references


def freshness(root: Optional[Path], references: list[dict]) -> list[dict]:
    result = []
    for ref in references:
        status = "unverifiable"
        if root is not None:
            path = (root / ref["path"]).resolve()
            if path.is_relative_to(root.resolve()):
                if not path.exists():
                    status = "missing"
                elif path.is_file():
                    status = "unchanged" if hashlib.sha256(path.read_bytes()).hexdigest() == ref["sha256"] else "changed"
        result.append({**ref, "status": status})
    return result
