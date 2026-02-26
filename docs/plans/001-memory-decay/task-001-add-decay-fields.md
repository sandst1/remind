# Task 001: Add Decay Fields to Concept Model

## Objective
Add decay tracking fields to the `Concept` dataclass in `models.py` to track usage and decay state.

## Context
- File: `src/remind/models.py`
- The `Concept` dataclass (around line 195) needs three new fields:
  - `last_accessed: Optional[datetime]` - When the concept was last recalled
  - `access_count: int` - Total number of times the concept has been recalled
  - `decay_factor: float` - Current decay level (1.0 = no decay, 0.0 = fully decayed)

## Steps
1. Add the three new fields to the `Concept` dataclass with appropriate defaults
2. Use `field(default_factory=...)` for mutable defaults where needed
3. Ensure `decay_factor` defaults to 1.0 (no initial decay)
4. Ensure `access_count` defaults to 0
5. Ensure `last_accessed` defaults to None

## Done When
- `Concept` model has `last_accessed`, `access_count`, and `decay_factor` fields
- Fields have sensible defaults for new concepts
- Type hints are correct and consistent with existing code style