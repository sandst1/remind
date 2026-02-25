# Task 1.2: Add Retrieval Access Log Table

**Phase**: 1 - Data Model & Storage (Core Foundation)

## Story

As a system, I can log concept accesses for decay computation.

## Description

Add the `retrieval_access_log` table to the SQLite schema and implement the necessary store methods for recording and querying concept accesses.

## Changes

### File: `src/remind/store.py`

1. Add table schema:

```sql
CREATE TABLE retrieval_access_log (
    id TEXT PRIMARY KEY,
    concept_id TEXT NOT NULL,
    accessed_at TIMESTAMP NOT NULL,
    activation_level REAL NOT NULL,
    query_hash TEXT NOT NULL,
    FOREIGN KEY (concept_id) REFERENCES concepts(id)
);
```

2. Implement methods:
   - `record_concept_access(concept_id, activation, query_hash)` - Record concept access
   - `get_concept_access_stats(concept_id)` - Get access statistics
   - `get_recent_accesses(limit=100)` - Get recent accesses for monitoring

3. Add database migration for existing databases

## Acceptance Criteria

- [ ] `retrieval_access_log` table exists in schema
- [ ] `record_concept_access()` correctly logs accesses
- [ ] `get_concept_access_stats()` returns accurate statistics
- [ ] `get_recent_accesses()` returns recent accesses
- [ ] Migration script handles existing databases
- [ ] Unit tests for all new methods

## Notes

- Query hash enables grouping similar queries for analytics
- Access logs are separate from concept's `access_history` field