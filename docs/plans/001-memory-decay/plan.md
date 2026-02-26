# Memory Decay

## Goal
Implement a usage-based memory decay system where concepts gradually lose retrieval priority based on how rarely they're recalled, mimicking human memory forgetting. Decay happens periodically (every N recalls), resets when concepts are recalled (rejuvenation), and can spread to related concepts. Configuration is global with sensible defaults.

## Approach
- **Data Model**: Add `last_accessed` (timestamp), `access_count` (int), and `decay_factor` (float 0.0-1.0) fields to Concept model
- **Configuration**: Create `DecayConfig` dataclass with:
  - `decay_interval`: Number of recalls between decay runs (default: 20)
  - `decay_rate`: How much decay_factor decreases per interval (default: 0.1)
  - `related_decay_factor`: How much related concepts decay when parent decays (default: 0.5)
- **Retrieval**: Multiply activation scores by `decay_factor` in `MemoryRetriever.retrieve()`
- **Decay Algorithm**: Linear decay - `new_decay_factor = max(0.0, old_decay_factor - decay_rate)`
- **Rejuvenation**: Reset `decay_factor` to 1.0 and update `last_accessed` when concept is recalled
- **Periodic Execution**: Track global recall count in `MemoryInterface`, trigger decay every N recalls
- **Related Concept Decay**: When decaying, also reduce decay_factor of related concepts by `decay_rate * related_decay_factor`

## Open Questions
None - all decisions finalized.