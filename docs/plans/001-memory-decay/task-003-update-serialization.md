# Task 003: Update Concept Serialization

## Objective
Update `Concept.to_dict()` and `Concept.from_dict()` methods to handle the new decay fields with backwards compatibility.

## Context
- File: `src/remind/models.py`
- The `Concept` class has `to_dict()` (line ~230) and `from_dict()` (line ~250) methods
- Existing databases will have concepts without these fields - need graceful handling

## Steps
1. Update `to_dict()` to include `last_accessed`, `access_count`, and `decay_factor`
2. Update `from_dict()` to:
   - Read the new fields if present
   - Use defaults if fields are missing (backwards compatibility)
   - Handle `last_accessed` being None or a valid ISO timestamp string
3. Ensure datetime serialization uses ISO format (consistent with other datetime fields)

## Done When
- New concepts serialize all decay fields
- Old concepts (without decay fields) deserialize with defaults
- No errors when loading existing databases
- Serialization format is consistent with existing patterns