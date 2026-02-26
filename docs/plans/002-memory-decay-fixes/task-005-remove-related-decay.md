# Task 005: Remove Related Concept Decay

## Objective
Remove the related-concept decay logic from `decay_concepts()` to eliminate double-decay and non-determinism.

## Context
- **File**: `src/remind/store.py`
- Issue #1: Related concepts get decayed twice - once in main loop, once as "related"
- Highly-connected concepts decay fastest (opposite of intended behavior)
- Order-dependent: non-deterministic total decay amount

## Steps
1. In `decay_concepts()`, remove the nested loop that decays related concepts:
   ```python
   # REMOVE this block:
   # related = self.get_related(concept.id)
   # related_decay_amount = decay_rate * related_decay_factor
   # for related_concept, relation in related:
   #     ...
   ```
2. Keep only the main decay logic:
   ```python
   for concept in concepts:
       old_decay = max(0.0, min(1.0, concept.decay_factor))
       new_decay = max(0.0, old_decay - decay_rate)
       if new_decay < old_decay:
           concept.decay_factor = new_decay
           concept.updated_at = datetime.now()
           self.update_concept(concept)
   ```
3. Update docstring to remove references to related decay

## Done When
- Related concepts are no longer decayed in `decay_concepts()`
- Each concept decays only once per decay run
- Decay amount is deterministic (no order dependency)
- Docstring reflects the simplified behavior