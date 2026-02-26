# Task 004: Modify Retrieval to Incorporate Decay

## Objective
Update `MemoryRetriever.retrieve()` to multiply activation scores by concept decay factors.

## Context
- File: `src/remind/retrieval.py`
- The `retrieve()` method (line ~78) calculates activation scores for concepts
- Current flow: embedding similarity → weighted by confidence → spreading activation
- Need to multiply final activation by `concept.decay_factor`

## Steps
1. In `retrieve()` method, after calculating initial activation from embedding similarity, multiply by `concept.decay_factor`
2. Also apply decay factor when spreading activation to related concepts
3. Ensure decay factor is clamped to 0.0-1.0 range (should already be, but verify)
4. Log decay factors for concepts with low activation (debugging aid)

## Done When
- Retrieved concepts have activation modified by their decay_factor
- Concepts with low decay_factor rank lower in results
- Decay affects both initial matches and spreading activation
- No performance regression in retrieval