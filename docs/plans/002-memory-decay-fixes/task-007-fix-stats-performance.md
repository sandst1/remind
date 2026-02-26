# Task 007: Fix get_stats() Performance

## Objective
Rewrite decay statistics calculation in `get_stats()` to use SQL queries instead of loading all concepts.

## Context
- **File**: `src/remind/store.py`
- Issue #7: `get_stats()` loads and deserializes every concept (including embeddings) just to read `decay_factor`
- `get_stats()` is called frequently, adding unnecessary overhead

## Steps
1. Replace the Python loop in `get_stats()` with SQL queries:
   ```sql
   SELECT COUNT(*) FROM concepts WHERE json_extract(data, '$.decay_factor') < 1.0
   SELECT AVG(json_extract(data, '$.decay_factor')) FROM concepts
   SELECT MIN(json_extract(data, '$.decay_factor')) FROM concepts
   ```
2. Handle NULL/missing decay_factor (old concepts) by using COALESCE:
   ```sql
   SELECT COALESCE(AVG(json_extract(data, '$.decay_factor')), 1.0) FROM concepts
   ```
3. Remove the `concepts = self.get_all_concepts()` call and Python loop
4. Use the SQL results directly for `concepts_with_decay`, `avg_decay_factor`, `min_decay_factor`

## Done When
- `get_stats()` uses SQL queries for decay statistics
- No concepts are loaded into Python memory for stats calculation
- Results match previous implementation (verify with test)
- Performance is O(1) regardless of concept count