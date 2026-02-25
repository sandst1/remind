# Task 007: Update Retriever to Record Access Events

## Objective
Modify `MemoryRetriever.retrieve()` to record access events for activated concepts.

## Context
- File: `src/remind/retrieval.py`
- After retrieval completes, record each activated concept with its activation level
- This feeds into the decay system for reinforcement

## Steps
1. Add `store: MemoryStore` parameter to `MemoryRetriever.__init__()` if not already present
2. At the end of `retrieve()`, after building results:
   - For each `ActivatedConcept` in results, call `store.record_access(concept.id, activation)`
3. Also increment recall counter: `store.increment_recall_count()`
4. Check if recall count >= decay_threshold, if so, optionally trigger decay or return flag

## Done When
- Retrieved concepts are recorded as access events
- Recall counter increments on each retrieval
- Access events include activation levels for reinforcement weighting