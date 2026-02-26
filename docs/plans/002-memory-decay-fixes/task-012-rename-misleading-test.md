# Task 012: Rename Misleading Test

## Objective
Rename the misleading test name in `tests/test_decay.py`.

## Context
- **File**: `tests/test_decay.py`
- Issue #13: Test name `test_decay_only_applies_once_per_interval` suggests decay applies once
- But the test actually verifies that calling decay twice applies it twice (0.8 = 1.0 - 0.1 - 0.1)

## Steps
1. Rename the test function:
   ```python
   # From:
   def test_decay_only_applies_once_per_interval(self, store):
   
   # To:
   def test_decay_accumulates_across_multiple_calls(self, store):
   ```

## Done When
- Test name accurately describes what it tests
- Test still passes after renaming