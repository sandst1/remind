# Task 001: Add Concept Access Tracking

## Objective
Add `last_accessed_at` and `access_count` fields to the `Concept` model to track when concepts are accessed and how many times.

## Context
- File: `src/remind/models.py`
- The `Concept` dataclass already has `created_at` and `updated_at` fields
- These new fields will be used by the decay system to determine which concepts to reinforce

## Steps
1. Add `last_accessed_at: Optional[datetime] = None` field to `Concept` dataclass
2. Add `access_count: int = 0` field to `Concept` dataclass
3. Update `Concept.to_dict()` to include both fields
4. Update `Concept.from_dict()` to deserialize both fields with backwards compatibility (default to None/0 if missing)

## Done When
- `Concept` model has both fields with appropriate defaults
- Serialization/deserialization works correctly
- Old concepts without these fields load without errors