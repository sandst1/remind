# Task 1.3: Add Decay Configuration

**Phase**: 1 - Data Model & Storage (Core Foundation)

## Story

As a power user, I can configure decay behavior.

## Description

Add `DecayConfig` dataclass to `src/remind/config.py` and integrate it into the main `RemindConfig`.

## Changes

### File: `src/remind/config.py`

1. Add `DecayConfig` dataclass:

```python
@dataclass
class DecayConfig:
    enabled: bool = True
    decay_half_life: float = 30.0  # days
    frequency_threshold: int = 10
    min_decay_score: float = 0.1
```

2. Add `decay` field to `RemindConfig`:

```python
@dataclass
class RemindConfig:
    # ... existing fields ...
    decay: DecayConfig = field(default_factory=DecayConfig)
```

3. Update config file parsing to support:

```json
{
  "decay": {
    "enabled": true,
    "decay_half_life": 30,
    "frequency_threshold": 10,
    "min_decay_score": 0.1
  }
}
```

## Acceptance Criteria

- [ ] `DecayConfig` dataclass exists with all fields
- [ ] `RemindConfig` includes `decay` field
- [ ] Config file parsing works for decay settings
- [ ] Environment variable overrides work
- [ ] Default values are sensible
- [ ] Configuration can be loaded and validated

## Notes

- `decay_half_life`: days for recency to halve
- `frequency_threshold`: accesses needed to reach max frequency score
- `min_decay_score`: floor for decay scores (never go below this)