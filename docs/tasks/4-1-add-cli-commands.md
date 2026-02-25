# Task 4.1: Add CLI Commands

**Phase**: 4 - CLI & API Exposure

## Story

As a user, I can inspect and manage decay.

## Description

Add CLI commands for decay inspection, reset, and configuration viewing.

## Changes

### File: `src/remind/cli.py`

Add new command group `decay` with subcommands:

1. **inspect** - Show decay stats for a concept:
   ```bash
   remind decay inspect <concept_id>
   ```
   Output: decay score, access count, last accessed, recency, frequency factors

2. **reset** - Reset decay to maximum:
   ```bash
   remind decay reset <concept_id>
   ```
   Behavior: sets decay_score = 1.0, resets access_count = 0, keeps last_accessed

3. **recent** - Show recent accesses:
   ```bash
   remind decay recent --limit 20
   ```
   Output: concept IDs, timestamps, activation levels

4. **config** - Show current decay configuration:
   ```bash
   remind decay config
   ```
   Output: all decay config values

## Acceptance Criteria

- [ ] `remind decay inspect <concept_id>` works
- [ ] `remind decay reset <concept_id>` works
- [ ] `remind decay recent --limit N` works
- [ ] `remind decay config` works
- [ ] All commands show human-readable output
- [ ] Error handling for invalid concept IDs
- [ ] CLI integration tests

## Notes

- Use `click` decorators for command structure
- Reset should persist changes to database
- Recent accesses should show from retrieval_access_log table