# Task 011: Create Integration Tests

## Objective
Create `tests/test_interface_decay.py` with end-to-end integration tests through `MemoryInterface.recall()`.

## Context
- **File**: `tests/test_interface_decay.py` (new)
- Issue #12: Current tests in `test_decay.py` manually simulate behavior instead of calling `recall()`
- Need integration tests that test the full flow through `MemoryInterface`

## Steps
1. Create `tests/test_interface_decay.py` with tests for:
   - **Test rejuvenation happens on recall**: Call `recall()` and verify `decay_factor` increases
   - **Test decay triggers at interval**: Call `recall()` 20 times, verify decay was applied
   - **Test persistent recall count**: Create new `MemoryInterface` instance, verify it sees previous count
   - **Test entity-based recalls trigger decay**: Call `recall(entity=...)` and verify decay triggers
   - **Test proportional rejuvenation**: Verify high-activation concepts get larger boosts than low-activation

2. Use `MockEmbeddingProvider` and `SQLiteMemoryStore` (temp file) for tests
3. Create `MemoryInterface` with mocks to avoid LLM calls

## Done When
- New test file `tests/test_interface_decay.py` exists
- Tests call `MemoryInterface.recall()` directly (not manual simulation)
- Tests verify persistent recall count survives new instances
- Tests verify decay triggers at correct interval
- Tests verify proportional rejuvenation behavior
- All tests pass with `pytest`