# Task 009: Test Decay Config Loading

## Objective
Test that decay configuration loads correctly from defaults, config file, and environment variables.

## Context
- File: `tests/test_config.py` or new `tests/test_decay.py`
- Test config loading with various combinations

## Steps
1. Test default values: `decay_enabled=True`, `decay_threshold=10`, `decay_rate=0.95`
2. Test config file overrides all three values
3. Test environment variable overrides work
4. Test priority: env vars > config file > defaults

## Done When
- All config loading tests pass
- Defaults are correct
- Overrides work at all levels