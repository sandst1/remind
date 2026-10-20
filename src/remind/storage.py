"""Backend selection shared by CLI, MCP, and Python."""

from pathlib import Path
from urllib.parse import unquote


def open_store(selector: str):
    from remind.store import SQLAlchemyMemoryStore
    if selector.startswith("file://"):
        from remind.file_store import FileMemoryStore
        path = Path(unquote(selector[7:]))
        legacy = path.with_suffix(".db") if path.suffix == ".memory" else path.parent / "remind.db"
        return FileMemoryStore(path, legacy_db=legacy)
    return SQLAlchemyMemoryStore(selector)


def default_store_url(start: Path) -> str:
    start = start.resolve()
    root = start
    for candidate in (start, *start.parents):
        if (candidate / ".remind").is_dir() or (candidate / ".git").exists():
            root = candidate
            break
    return (root / ".remind" / "memory").as_uri()
