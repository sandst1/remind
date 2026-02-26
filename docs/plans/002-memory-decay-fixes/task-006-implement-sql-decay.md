# Task 006: Implement SQL-Level Decay Update

## Objective
Rewrite `decay_concepts()` to use SQL-level updates instead of loading all concepts with embeddings.

## Context
- **File**: `src/remind/store.py`
- Issue #6: Current implementation loads ALL concepts including full embedding vectors
- Then calls `get_related()` and `update_concept()` for each concept (N+1 queries)
- Very expensive with many concepts

## Steps
1. Replace the Python loop with a single SQL UPDATE:
   ```sql
   UPDATE concepts 
   SET data = json_set(
       data, 
       '$.decay_factor', 
       max(0, json_extract(data, '$.decay_factor') - ?)
   ),
   updated_at = CURRENT_TIMESTAMP
   WHERE json_extract(data, '$.decay_factor') > 0
   ```
2. Bind `decay_rate` as the parameter
3. Count affected rows with `cursor.rowcount`
4. Remove the `get_all_concepts()`, `get_related()`, and per-concept `update_concept()` calls
5. Update method signature: remove unused `decay_interval` and `related_decay_factor` params

## Done When
- `decay_concepts()` uses a single SQL UPDATE statement
- No concepts are loaded into Python memory during decay
- Performance is O(1) regardless of concept count
- Returns the count of affected concepts via `rowcount`