# Task 008: Add CLI Decay Command

## Objective
Add `remind decay` CLI command for manual decay execution.

## Context
- File: `src/remind/cli.py`
- Follow existing CLI command patterns (e.g., `consolidate`, `recall`)
- Should show decay results to user

## Steps
1. Add `decay` subcommand to CLI using `@cli.command()`
2. Command should:
   - Create `MemoryInterface` for the database
   - Call `memory.decay()`
   - Print results (concepts decayed, reinforced, etc.)
3. Add optional `--force` flag to run decay even if threshold not reached

## Done When
- `remind decay` command exists and runs
- Shows meaningful output about what was decayed/reinforced
- `--force` flag works correctly