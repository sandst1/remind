# Task 006: Add Rejuvenation on Recall

## Objective
Update the recall process to reset decay when a concept is accessed (rejuvenation).

## Context
- File: `src/remind/interface.py`
- The `recall()` method (line ~184) retrieves concepts for LLM context
- When a concept is recalled, it should be "refreshed" - decay reset to 1.0

## Steps
1. In `MemoryInterface.recall()`, after retrieving concepts, update each concept's:
   - `decay_factor = 1.0` (reset decay)
   - `access_count += 1` (increment counter)
   - `last_accessed = datetime.now()` (update timestamp)
2. Save updated concepts back to store
3. Consider batching updates for performance if many concepts retrieved
4. Log rejuvenation events at debug level

## Done When
- Recalled concepts have decay_factor reset to 1.0
- access_count increments on each recall
- last_accessed timestamp updates
- Rejuvenated concepts rank higher in subsequent recalls
- No significant performance impact