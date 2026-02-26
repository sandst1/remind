# Task 001: Add Metadata Table

## Objective
Create a `metadata` table in the SQLite database to store persistent key-value pairs, starting with recall count.

## Context
- **File**: `src/remind/store.py`
- The `_recall_count` in `MemoryInterface` is ephemeral and resets on each process restart
- Need a database-backed storage for persistent state like recall count
- The `metadata` table will support future persistent settings beyond just recall count

## Steps
1. Add `metadata` table schema in `_init_db()`:
   ```sql
   CREATE TABLE IF NOT EXISTS metadata (
       key TEXT PRIMARY KEY,
       value TEXT
   )
   ```
2. Add abstract methods to `MemoryStore` interface:
   - `get_metadata(key: str) -> Optional[str]`
   - `set_metadata(key: str, value: str) -> None`
3. Implement methods in `SQLiteMemoryStore`:
   - Use simple SELECT/INSERT OR REPLACE queries
   - Values are stored as strings (JSON-encoded if complex)

## Done When
- `metadata` table exists in database schema
- `MemoryStore` interface defines `get_metadata()` and `set_metadata()` methods
- `SQLiteMemoryStore` implements both methods correctly
- Can store and retrieve a test value through the new methods