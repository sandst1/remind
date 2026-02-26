# Task 002: Implement Recall Count Persistence

## Objective
Replace ephemeral `_recall_count` in `MemoryInterface` with persistent storage using the new metadata table.

## Context
- **File**: `src/remind/interface.py`
- Current `_recall_count` starts at 0 on every `MemoryInterface` instantiation
- CLI spawns new processes per command, so decay never triggers (interval=20)
- Need to load recall count on init and save after each increment

## Steps
1. In `MemoryInterface.__init__()`:
   - Remove `self._recall_count: int = 0`
   - Add: `self._recall_count = self._load_recall_count()`
2. Add `_load_recall_count()` method:
   - Query `store.get_metadata("recall_count")`
   - Parse as int, default to 0 if not found
3. Add `_save_recall_count()` method:
   - Call `store.set_metadata("recall_count", str(self._recall_count))`
4. In `recall()` method:
   - After `self._recall_count += 1`, call `self._save_recall_count()`

## Done When
- `MemoryInterface` loads recall count from metadata on init
- Each call to `recall()` persists the updated count
- New `MemoryInterface` instance sees the previous recall count
- Decay triggers correctly after 20 recalls across multiple CLI invocations