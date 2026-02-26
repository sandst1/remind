# Task 008: Add Decay Stats

## Objective
Add decay-related statistics to `MemoryStore.get_stats()` method.

## Context
- File: `src/remind/store.py`
- The `get_stats()` method returns a dict with counts and distributions
- Need to expose decay-related metrics for monitoring/debugging

## Steps
1. In `get_stats()`, add decay-related metrics:
   - `concepts_with_decay`: Count of concepts with decay_factor < 1.0
   - `avg_decay_factor`: Average decay_factor across all concepts
   - `min_decay_factor`: Lowest decay_factor (most decayed)
   - `recalls_since_last_decay`: Current recall count mod decay_interval
2. Update `MemoryInterface` to expose these stats
3. Consider adding CLI command or API endpoint to view decay stats

## Done When
- `get_stats()` includes decay metrics
- Stats can be viewed via CLI or API
- Metrics help understand decay system behavior
- No performance impact on stats calculation