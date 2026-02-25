# Task 2.1: Implement Decay Score Computation

**Phase**: 2 - Decay Computation Engine

## Story

As a retriever, I can compute decay scores for concepts.

## Description

Implement the decay score computation algorithm in `src/remind/retrieval.py`.

## Changes

### File: `src/remind/retrieval.py`

1. Add `_compute_decay_score()` method to `MemoryRetriever`:

```python
def _compute_decay_score(self, concept: Concept) -> float:
    """Compute decay score based on access patterns."""
    
    # Recency factor (40% weight)
    recency_factor = self._compute_recency_factor(concept)
    
    # Frequency factor (40% weight)
    frequency_factor = self._compute_frequency_factor(concept)
    
    # Confidence boost (20% weight)
    confidence_boost = (concept.confidence or 0.5) * 0.5
    
    decay_score = (recency_factor * 0.4) + (frequency_factor * 0.4) + confidence_boost
    
    # Apply minimum threshold
    return max(decay_score, self.config.decay.min_decay_score)
```

2. Add helper methods:
   - `_compute_recency_factor(concept)` - exponential decay based on days since last access
   - `_compute_frequency_factor(concept)` - capped at 1.0 based on access count

3. Implement formula:
   - `recency_factor = 1 / (1 + days_since_access / decay_half_life)`
   - `frequency_factor = min(access_count / frequency_threshold, 1.0)`

## Acceptance Criteria

- [ ] `_compute_decay_score()` method exists in `MemoryRetriever`
- [ ] Recency factor uses exponential decay curve
- [ ] Frequency factor caps at 1.0
- [ ] Confidence contributes 20% to final score
- [ ] Minimum decay score is enforced
- [ ] Unit tests for edge cases (new concepts, old concepts, no accesses)
- [ ] Tests verify formula produces expected values

## Notes

- New concepts should start with decay_score = 1.0
- Confidence and decay are independent factors
- Use `self.config.decay` for configuration values