# Task 009: Test Decay Behavior

## Objective
Write tests to verify decay and rejuvenation work correctly.

## Context
- File: `tests/test_decay.py` (new file)
- Need to test: decay reduces activation, rejuvenation resets decay, periodic decay triggers
- Use temporary database fixtures like other tests

## Steps
1. Create test file `tests/test_decay.py`
2. Write tests:
   - `test_concept_decay_fields`: Verify new fields exist and serialize correctly
   - `test_decay_reduces_activation`: Verify decayed concepts have lower activation
   - `test_rejuvenation_resets_decay`: Verify recalled concepts reset to decay_factor=1.0
   - `test_periodic_decay_triggers`: Verify decay runs every N recalls
   - `test_related_concepts_decay`: Verify related concepts decay at reduced rate
   - `test_backwards_compatibility`: Verify old concepts load with default decay_factor=1.0
3. Run tests with `pytest tests/test_decay.py`
4. Verify all tests pass

## Done When
- All decay-related tests pass
- Tests cover decay, rejuvenation, and periodic triggering
- Backwards compatibility verified
- No regressions in existing tests