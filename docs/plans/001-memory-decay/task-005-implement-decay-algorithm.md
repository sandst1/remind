# Task 005: Implement Decay Algorithm

## Objective
Add a `decay_concepts()` method to `MemoryStore` that performs linear decay on all concepts.

## Context
- File: `src/remind/store.py`
- Need to add method to `MemoryStore` abstract class and `SQLiteMemoryStore` implementation
- Decay algorithm: `new_decay_factor = max(0.0, old_decay_factor - decay_rate)`
- Should also decay related concepts by `decay_rate * related_decay_factor`

## Steps
1. Add `decay_concepts(decay_interval: int, decay_rate: float, related_decay_factor: float) -> int` to `MemoryStore` abstract class
2. Implement in `SQLiteMemoryStore`:
   - Get all concepts
   - For each concept: `decay_factor = max(0.0, decay_factor - decay_rate)`
   - For related concepts: `decay_factor = max(0.0, decay_factor - decay_rate * related_decay_factor)`
   - Update concepts in database
   - Return count of concepts decayed
3. Handle concepts with missing decay_factor (backwards compatibility)
4. Use batch updates for performance if many concepts

## Done When
- `decay_concepts()` method exists in store interface
- Linear decay formula is correctly implemented
- Related concepts decay at reduced rate
- Method returns count of decayed concepts
- Backwards compatible with old concepts