# Task 004: Fix create_memory() Config Passing

## Objective
Ensure `create_memory()` factory function passes `decay_config` from config to `MemoryInterface`.

## Context
- **File**: `src/remind/interface.py`
- Issue #2: `config.decay` is loaded but never passed to `MemoryInterface`
- Users configuring decay via `~/.remind/remind.config.json` get defaults instead

## Steps
1. In `create_memory()`, after loading config and before creating `MemoryInterface`:
   ```python
   # Add decay_config to kwargs if not explicitly provided
   if "decay_config" not in kwargs:
       kwargs["decay_config"] = config.decay
   ```
2. Place this before the `return MemoryInterface(...)` call

## Done When
- `create_memory()` passes `config.decay` to `MemoryInterface`
- Custom decay settings in config file are respected
- Explicit `decay_config` kwarg still takes priority (not overridden)