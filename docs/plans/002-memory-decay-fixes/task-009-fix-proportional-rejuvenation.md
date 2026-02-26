# Task 009: Fix Proportional Rejuvenation

## Objective
Replace aggressive full-reset rejuvenation with proportional, activation-scaled rejuvenation.

## Context
- **File**: `src/remind/interface.py`
- Issue #5: Current `_rejuvenate_concepts()` resets ALL recalled concepts to `decay_factor=1.0`
- A concept that barely scraped above threshold gets same boost as top result
- Nearly-dead concepts (`decay_factor=0.01`) get fully restored

## Steps
1. Update `_rejuvenate_concepts()` to use proportional boost:
   ```python
   def _rejuvenate_concepts(self, activated: list[ActivatedConcept]) -> None:
       for ac in activated:
           concept = ac.concept
           # Scale boost by activation score (0.0-1.0)
           # Max boost is 0.3, scaled by how strongly the concept was activated
           activation_boost = 0.3 * ac.activation
           concept.decay_factor = min(1.0, concept.decay_factor + activation_boost)
           concept.access_count += 1
           concept.last_accessed = datetime.now()
           concept.updated_at = datetime.now()
           self.store.update_concept(concept)
   ```
2. This ensures:
   - Top results (activation ~1.0) get ~0.3 boost
   - Barely-above-threshold (activation ~0.1) get ~0.03 boost
   - Nearly-dead concepts don't get fully restored unless strongly activated

## Done When
- Rejuvenation scales with activation score
- High-activation concepts get larger boosts
- Low-activation concepts get smaller boosts
- No concept exceeds `decay_factor=1.0`