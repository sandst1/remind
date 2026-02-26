# Memory Decay Fixes

## Goal
Fix critical bugs and performance issues in the memory decay system: resolve double/non-deterministic decay, ensure config is passed through, make decay actually trigger in CLI usage, fix inconsistent entity-based recall behavior, and optimize performance by using SQL-level updates instead of loading all concepts with embeddings.

## Approach

### Critical Bugs
1. **Remove related-concept decay** - Each concept decays independently, eliminating double-decay and non-determinism
2. **Pass `decay_config`** through `create_memory()` factory function
3. **Persist recall count** in a `metadata` table - survives process restarts
4. **Fix entity-based recall** to trigger decay check

### Performance
5. **SQL-level decay update** - Use `UPDATE concepts SET data = json_set(...)` instead of loading all concepts
6. **SQL-level stats query** - Use `json_extract()` in SELECT for decay stats in `get_stats()`

### Code Quality
7. Remove unused `conn` and `decay_interval` parameter from `decay_concepts()`
8. Consolidate imports in `interface.py`

### Testing
9. Create `tests/test_interface_decay.py` with end-to-end integration tests through `MemoryInterface.recall()`
10. Rename misleading test in `test_decay.py`

### Rejuvenation Approach
Proportional rejuvenation with activation scaling:
```python
activation_boost = 0.3 * activated_concept.activation  # 0.0-0.3 based on activation
concept.decay_factor = min(1.0, concept.decay_factor + activation_boost)
```
This way top results get nearly full boost (~0.3), while barely-above-threshold results get small boost (~0.03).

## Open Questions
None