# Task 012: Test Batch Trigger

## Objective
Test that decay triggers correctly after N recall operations.

## Context
- File: `tests/test_decay.py`
- Test the batch threshold mechanism

## Steps
1. Set decay_threshold to a low number (e.g., 3)
2. Perform recall operations below threshold
3. Verify decay does NOT run automatically
4. Perform recall to reach threshold
5. Verify decay runs when threshold reached
6. Verify recall counter resets after decay

## Done When
- Decay doesn't run below threshold
- Decay triggers at threshold
- Counter resets properly