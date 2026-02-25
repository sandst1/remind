# Task 006: Add Decay Method to Interface

## Objective
Add `decay()` method to `MemoryInterface` that orchestrates the decay process.

## Context
- File: `src/remind/interface.py`
- Similar to `consolidate()` method pattern
- Checks config, triggers decayer, returns result

## Steps
1. Import `MemoryDecayer` and `DecayResult` in `interface.py`
2. Add `decay()` method to `MemoryInterface` that:
   - Checks if decay is enabled in config
   - Creates `MemoryDecayer` with store and decay_rate from config
   - Calls decayer's `decay()` method
   - Returns `DecayResult`
3. Store should be passed to `MemoryDecayer` constructor

## Done When
- `MemoryInterface.decay()` method exists
- Respects `decay_enabled` config flag
- Passes correct parameters to `MemoryDecayer`
- Returns decay result to caller