# Task 003: Fix MemoryInterface Recall Count

## Objective
Fix `MemoryInterface` to use persistent recall count instead of ephemeral instance variable.

## Context
- **File**: `src/remind/interface.py`
- Depends on Task 001 (metadata table) and Task 002 (persistence methods)
- This is the actual implementation task that ties it together

## Steps
1. Modify `MemoryInterface.__init__()`:
   ```python
   # Remove: self._recall_count: int = 0
   # Add:
   self._recall_count = self._load_recall_count()
   ```
2. Add helper methods after `_trigger_decay()`:
   ```python
   def _load_recall_count(self) -> int:
       """Load recall count from persistent storage."""
       value = self.store.get_metadata("recall_count")
       return int(value) if value else 0
   
   def _save_recall_count(self) -> None:
       """Save recall count to persistent storage."""
       self.store.set_metadata("recall_count", str(self._recall_count))
   ```
3. Update `recall()` method:
   - After `self._recall_count += 1`, add `self._save_recall_count()`

## Done When
- `MemoryInterface` loads recall count from metadata on init
- Each call to `recall()` persists the updated count
- New `MemoryInterface` instance sees the previous recall count
- Decay triggers correctly after 20 recalls across multiple CLI invocations