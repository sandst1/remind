# Task 005: Implement Memory Decayer Class

## Objective
Create `MemoryDecayer` class in `decay.py` that applies decay and reinforcement to concepts.

## Context
- New file: `src/remind/decay.py`
- Uses `MemoryStore` to read/write concepts and access events
- Decay rate is configurable (default 0.95 = 5% decay)
- Reinforcement uses spreading activation from accessed concepts

## Steps
1. Create `src/remind/decay.py` with `MemoryDecayer` class
2. Implement `decay()` method that:
   - Gets all concepts from store
   - Applies relative decay: `new_confidence = old_confidence * decay_rate`
   - Gets access events from store
   - For each accessed concept, reinforces: `confidence = max(confidence, activation)`
   - Spreads reinforcement to neighbors via relations (with decay per hop)
   - Updates `last_accessed_at` and `access_count` on reinforced concepts
   - Saves updated concepts back to store
   - Clears access events and resets recall counter
3. Return `DecayResult` dataclass with stats (concepts decayed, reinforced, etc.)

## Done When
- `MemoryDecayer` class exists with `decay()` method
- Decay is applied to all concepts
- Reinforcement uses access events and spreads to neighbors
- Access tracking fields are updated correctly
- `DecayResult` returns useful statistics