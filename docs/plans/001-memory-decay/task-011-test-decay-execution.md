# Task 011: Test Decay Execution

## Objective
Test that decay and reinforcement work correctly when decay runs.

## Context
- File: `tests/test_decay.py`
- Test the core decay logic

## Steps
1. Create test concepts with known confidence values
2. Record some access events for subset of concepts
3. Run decay with known decay_rate (e.g., 0.95)
4. Verify unaccessed concepts had confidence reduced by decay_rate
5. Verify accessed concepts were reinforced (confidence >= activation)
6. Verify neighbors of accessed concepts got partial reinforcement
7. Verify access events cleared and recall counter reset

## Done When
- Decay reduces confidence correctly
- Reinforcement works for accessed concepts
- Spreading reinforcement reaches neighbors
- State is cleaned up after decay