# Task 2.2: Integrate Access Tracking into Retrieval

**Phase**: 2 - Decay Computation Engine

## Story

As a retrieval system, I track concept accesses automatically.

## Description

Modify the `retrieve()` method to record concept accesses and update concept tracking data after retrieval.

## Changes

### File: `src/remind/retrieval.py`

1. Modify `MemoryRetriever.retrieve()` to:
   - Record accesses for all concepts reaching activation threshold
   - Update concept's `last_accessed`, `access_count`, and `access_history`
   - Truncate `access_history` to max 100 entries
   - Persist changes to store

2. Integration points:
   ```python
   # After computing activations:
   for activated_concept in computed_results:
       concept = activated_concept.concept
       
       # Record access
       self.store.record_concept_access(
           concept_id=concept.id,
           activation=activated_concept.activation,
           query_hash=self._compute_query_hash(query)
       )
       
       # Update concept tracking
       concept.access_count += 1
       concept.last_accessed = datetime.now()
       concept.access_history.append((datetime.now(), activated_concept.activation))
       concept.access_history = concept.access_history[-100:]  # Truncate
       
       # Persist changes
       self.store.update_concept(concept)
   ```

## Acceptance Criteria

- [ ] `retrieve()` records accesses for threshold concepts
- [ ] `access_count` is incremented on each retrieval
- [ ] `last_accessed` is updated to current timestamp
- [ ] `access_history` is appended with activation level
- [ ] `access_history` is truncated to 100 entries
- [ ] Changes are persisted to store
- [ ] Access tracking works with decay disabled
- [ ] Integration tests verify end-to-end tracking

## Notes

- Track both final retrieved concepts AND threshold concepts
- Final concepts are logged to access log table for analytics
- Threshold concepts count for decay computation but not persisted to query history