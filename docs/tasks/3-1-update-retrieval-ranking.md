# Task 3.1: Update Retrieval Ranking

**Phase**: 3 - Ranking & Integration

## Story

As a user, I see concepts ranked by both relevance and recency.

## Description

Modify the final ranking to combine retrieval activation with decay scores, and update the `ActivatedConcept` dataclass.

## Changes

### File: `src/remind/retrieval.py`

1. Update `ActivatedConcept` dataclass:

```python
@dataclass
class ActivatedConcept:
    concept: Concept
    activation: float  # Final ranked score (combines retrieval + decay)
    source: str  # "embedding" or "spread"
    hops: int
    decay_score: float  # Separate decay component for transparency
```

2. Modify `retrieve()` to compute final ranking:

```python
# After computing activations and decay scores:
final_score = (activated_concept.activation * 0.7) + (decay_score * 0.3)

results.append(ActivatedConcept(
    concept=concept,
    activation=final_score,  # Reuse activation field for final score
    source=activated_concept.source,
    hops=activated_concept.hops,
    decay_score=decay_score,
))
```

3. Update `ActivatedConcept` import in `interface.py`

## Acceptance Criteria

- [ ] `ActivatedConcept` includes `decay_score` field
- [ ] Final ranking uses formula: `(activation × 0.7) + (decay_score × 0.3)`
- [ ] Results are sorted by final score (descending)
- [ ] Backward compatibility maintained with existing callers
- [ ] Documentation updated for new fields
- [ ] Tests verify ranking order with decay

## Notes

- 70% weight on retrieval relevance, 30% on popularity/recency
- `decay_score` is exposed separately for transparency
- `activation` field is reused for final combined score