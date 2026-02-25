# Task 013: Test Decay Disabled Mode

## Objective
Test that decay is properly skipped when `decay_enabled=false`.

## Context
- File: `tests/test_decay.py`
- Verify the config flag works correctly

## Steps
1. Set `decay_enabled=false` in config
2. Run recall operations to exceed threshold
3. Verify decay does NOT run
4. Verify access events accumulate but aren't processed
5. Enable decay, run manually, verify it works

## Done When
- Decay respects `decay_enabled=false`
- Manual decay still works when disabled
- State remains consistent