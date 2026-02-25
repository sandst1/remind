# Task 3.2: Update Interface Layer

**Phase**: 3 - Ranking & Integration

## Story

As an API consumer, I get decay-aware retrieval results.

## Description

Update `MemoryInterface.recall()` to return updated `ActivatedConcept` objects with decay information and document the new fields.

## Changes

### File: `src/remind/interface.py`

1. Update `recall()` method signature and documentation:

```python
async def recall(self, query: str, **kwargs) -> list[ActivatedConcept]:
    """
    Recall relevant concepts.
    
    Args:
        query: Search query
        k: Number of results to return (default: 10)
        entity: Optional entity filter
        
    Returns:
        List of ActivatedConcept objects with:
        - concept: The Concept object
        - activation: Final ranked score (combines retrieval + decay)
        - decay_score: Separate decay component (0.0-1.0)
        - source: "embedding" or "spread"
        - hops: Number of hops from initial match
    """
```

2. Ensure `ActivatedConcept` is exported from module

3. Verify all callers of `recall()` handle new fields

## Acceptance Criteria

- [ ] `recall()` returns `ActivatedConcept` objects with decay info
- [ ] Documentation describes all new fields
- [ ] Type hints are correct
- [ ] Existing API consumers still work
- [ ] No breaking changes to public API
- [ ] Tests verify return values

## Notes

- This is the main public API for retrieval
- Maintain backward compatibility
- Documentation should explain decay vs. confidence distinction