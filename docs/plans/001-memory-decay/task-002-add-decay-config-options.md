# Task 002: Add Decay Config Options

## Objective
Add decay-related configuration options to `RemindConfig` dataclass.

## Context
- File: `src/remind/config.py`
- Follow existing pattern for config options (e.g., `consolidation_threshold`, `auto_consolidate`)
- Defaults: `decay_enabled=True`, `decay_threshold=10`, `decay_rate=0.95`

## Steps
1. Add `decay_enabled: bool = True` field to `RemindConfig`
2. Add `decay_threshold: int = 10` field to `RemindConfig`
3. Add `decay_rate: float = 0.95` field to `RemindConfig`
4. Update `load_config()` to read these from config file if present
5. Add environment variable support: `DECAY_ENABLED`, `DECAY_THRESHOLD`, `DECAY_RATE`

## Done When
- Config fields exist with correct defaults
- Config file loading works for all three options
- Environment variable overrides work