# Task 002: Add Decay Configuration

## Objective
Create a `DecayConfig` dataclass in `config.py` to hold decay parameters.

## Context
- File: `src/remind/config.py`
- Need to add a new dataclass alongside existing config classes (`AnthropicConfig`, `OpenAIConfig`, etc.)
- The config will be part of the main `RemindConfig` dataclass

## Steps
1. Create `DecayConfig` dataclass with fields:
   - `decay_interval: int = 20` - Number of recalls between decay runs
   - `decay_rate: float = 0.1` - How much decay_factor decreases per interval (0.0-1.0)
   - `related_decay_factor: float = 0.5` - Multiplier for related concept decay
2. Add `decay: DecayConfig` field to `RemindConfig` dataclass
3. Update `load_config()` to merge decay config from config file if present
4. Ensure defaults are used when config file doesn't specify decay settings

## Done When
- `DecayConfig` dataclass exists with three parameters
- `RemindConfig` includes `decay` field
- Config loading handles decay settings gracefully
- Defaults match plan specifications (interval=20, rate=0.1, related=0.5)