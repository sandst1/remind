# Task 010: Test Concept Access Tracking

## Objective
Test that concept access tracking works correctly during retrieval.

## Context
- File: `tests/test_decay.py` or `tests/test_retrieval.py`
- Verify access events are recorded when concepts are retrieved

## Steps
1. Create test concepts in store
2. Run retrieval that activates those concepts
3. Verify `store.get_access_events()` returns correct events with activation levels
4. Verify `store.increment_recall_count()` increments correctly
5. Verify `Concept.last_accessed_at` and `access_count` update after decay runs

## Done When
- Access events are recorded correctly during retrieval
- Recall counter increments properly
- Concept access fields update after decay