# Memory Decay Feature

## Goal
Add a usage-based memory decay system that gradually reduces concept confidence over time, with reinforcement on access. Decay runs in batches after N recall operations (configurable threshold), applies relative decay to all concepts equally, and uses spreading activation to reinforce accessed concepts and their neighbors. Includes a config option to disable decay entirely.

## Approach
1. **Track access metadata**: Add `last_accessed_at` and `access_count` fields to `Concept` model to track when/how often concepts are accessed
2. **Access tracking in retrieval**: Modify `MemoryRetriever.retrieve()` to record access events (concept ID + activation level) for activated concepts
3. **Decay engine**: Create `decay.py` with `MemoryDecayer` class that:
   - Applies relative decay multiplier (e.g., 0.95) to all concept confidences
   - Uses stored access events to reinforce concepts (higher activation = stronger reinforcement)
   - Spreads reinforcement to neighbors via relations
   - Updates `last_accessed_at` on reinforced concepts
4. **Batch trigger**: Track recall count in `MemoryInterface`, trigger decay when threshold reached (similar to consolidation)
5. **Config**: Add `decay_enabled` (bool, default True), `decay_threshold` (int, default 10), and `decay_rate` (float, default 0.95) to `RemindConfig`
6. **Store updates**: Add methods to track/access recall counts and access events
7. **Separate decay method**: Decay runs only via explicit `decay()` method call, not during consolidation

## Open Questions
None