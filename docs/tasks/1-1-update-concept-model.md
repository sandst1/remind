# Task 1.1: Update Concept Model

**Phase**: 1 - Data Model & Storage (Core Foundation)

## Story

As a developer, I can store and retrieve concept access tracking data.

## Description

Add access tracking fields to the `Concept` dataclass in `src/remind/models.py`.

## Changes

### File: `src/remind/models.py`

Add the following fields to the `Concept` dataclass:

```python
last_accessed: Optional[datetime] = None
access_count: int = 0
access_history: list[tuple[datetime, float]] = field(default_factory=list)
```

Also update `to_dict()` and `from_dict()` methods to serialize/deserialize these new fields.

## Acceptance Criteria

- [ ] Concept model includes `last_accessed`, `access_count`, and `access_history` fields
- [ ] `to_dict()` correctly serializes new fields
- [ ] `from_dict()` correctly deserializes new fields
- [ ] Existing concepts can be loaded without errors
- [ ] Unit tests pass for serialization/deserialization

## Notes

- `decay_score` is NOT stored - computed dynamically during retrieval
- `access_history` will be truncated to last 100 entries when persisted