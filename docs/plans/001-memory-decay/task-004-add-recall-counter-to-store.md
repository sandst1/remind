# Task 004: Add Recall Counter to Store

## Objective
Add methods to `MemoryStore` for tracking recall operation count to trigger batch decay.

## Context
- Files: `src/remind/store.py`
- Similar to how consolidation tracks episodes, decay tracks recalls
- Counter increments on each recall, reset after decay runs

## Steps
1. Add to `MemoryStore` protocol:
   - `increment_recall_count() -> int` (increments and returns new count)
   - `get_recall_count() -> int` (returns current count)
   - `reset_recall_count() -> None` (resets to 0)
2. Implement in `SQLiteMemoryStore`:
   - Store counter in a simple key-value table or metadata table
   - Implement the three methods

## Done When
- Store protocol has the three recall counter methods
- SQLite implementation persists counter across sessions
- Counter increments and resets correctly