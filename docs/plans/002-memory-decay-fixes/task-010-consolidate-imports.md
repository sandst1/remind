# Task 010: Consolidate Imports

## Objective
Fix redundant/split imports in `interface.py` by consolidating `DecayConfig` import to top-level.

## Context
- **File**: `src/remind/interface.py`
- Issue #11: `load_config` imported at top-level, but `DecayConfig` imported inside `__init__`
- Split imports are confusing and non-standard

## Steps
1. Update top-level imports:
   ```python
   from remind.config import load_config, DecayConfig
   ```
2. Remove the inline import from `__init__`:
   ```python
   # Remove: from remind.config import DecayConfig
   ```

## Done When
- All config imports are at top-level together
- No inline imports in `__init__`
- Code follows standard Python import conventions