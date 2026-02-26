# Task 007: Hook Periodic Decay into Interface

## Objective
Add recall tracking and trigger decay every N recalls in `MemoryInterface`.

## Context
- File: `src/remind/interface.py`
- Need to track total recall count across session
- Decay should run automatically every `decay_interval` recalls (default 20)
- Similar pattern to auto-consolidation threshold

## Steps
1. Add `_recall_count: int = 0` field to `MemoryInterface` class
2. In `recall()` method:
   - Increment `_recall_count` after each recall
   - Check if `_recall_count % config.decay.decay_interval == 0`
   - If yes, call `self.store.decay_concepts()` with config parameters
3. Consider using background consolidation pattern (spawn subprocess) for decay
4. Log when decay is triggered and how many concepts were affected

## Done When
- Recall count is tracked across the lifetime of MemoryInterface
- Decay triggers automatically every N recalls
- Decay uses configured parameters from config
- Logging shows decay events
- No blocking of recall operation (use background if slow)