# Task 003: Add Access Event Tracking to Store

## Objective
Add methods to `MemoryStore` protocol and `SQLiteMemoryStore` for tracking concept access events.

## Context
- Files: `src/remind/store.py`
- Access events store concept IDs with their activation levels during retrieval
- These events are used by the decayer to reinforce concepts
- Events should be cleared after decay runs

## Steps
1. Add `AccessEvent` dataclass with fields: `concept_id: str`, `activation: float`, `timestamp: datetime`
2. Add to `MemoryStore` protocol:
   - `record_access(concept_id: str, activation: float) -> None`
   - `get_access_events() -> list[AccessEvent]`
   - `clear_access_events() -> None`
3. Implement in `SQLiteMemoryStore`:
   - Create `access_events` table (concept_id, activation, timestamp)
   - Implement the three methods

## Done When
- `AccessEvent` dataclass exists with serialization
- Store protocol has the three new methods
- SQLite implementation persists and retrieves access events correctly