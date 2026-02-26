# Task 008: Fix Entity-Based Recall Decay Trigger

## Objective
Fix entity-based recalls to also trigger decay check, ensuring consistent behavior between recall paths.

## Context
- **File**: `src/remind/interface.py`
- Issue #4: Entity-based recalls return early before decay trigger check
- `_recall_count` is incremented but decay never triggers for entity recalls
- Inconsistent: entity recalls count toward interval but don't rejuvenate or trigger decay

## Steps
1. In `recall()` method, restructure the flow:
   ```python
   # Increment recall count (always)
   self._recall_count += 1
   self._save_recall_count()
   
   # Entity-based retrieval
   if entity:
       episodes = await self.retriever.retrieve_by_entity(entity, limit=k * 4)
       # Check decay BEFORE returning
       if self._recall_count % self.decay_config.decay_interval == 0:
           self._trigger_decay()
       if raw:
           return episodes
       return self.retriever.format_entity_context(entity, episodes)
   
   # Concept-based retrieval (existing path)
   activated = await self.retriever.retrieve(...)
   
   # Rejuvenation (only for concept-based)
   if activated:
       self._rejuvenate_concepts(activated)
   
   # Trigger decay (already here, but now both paths hit it)
   if self._recall_count % self.decay_config.decay_interval == 0:
       self._trigger_decay()
   ```
2. Move decay trigger check to run for both paths

## Done When
- Entity-based recalls trigger decay at the same interval as concept-based recalls
- Both paths have consistent decay behavior
- Rejuvenation still only applies to concept-based recalls (as intended)