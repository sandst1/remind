# Task 4.2: Add REST API Endpoints

**Phase**: 4 - CLI & API Exposure

## Story

As a web client, I can access decay data via REST.

## Description

Add REST API endpoints for decay inspection, reset, and monitoring.

## Changes

### File: `src/remind/api/routes.py`

Add new endpoints:

1. **GET `/api/v1/concepts/<id>/decay`** - Get decay stats
   ```json
   {
     "concept_id": "xxx",
     "decay_score": 0.75,
     "access_count": 12,
     "last_accessed": "2026-02-25T10:30:00",
     "recency_factor": 0.8,
     "frequency_factor": 0.6
   }
   ```

2. **PUT `/api/v1/concepts/<id>/decay/reset`** - Reset decay
   ```json
   {
     "success": true,
     "decay_score": 1.0,
     "access_count": 0
   }
   ```

3. **GET `/api/v1/decay/recent`** - Recent accesses
   ```json
   {
     "accesses": [
       {
         "concept_id": "xxx",
         "accessed_at": "2026-02-25T10:30:00",
         "activation_level": 0.85,
         "query_hash": "abc123"
       }
     ]
   }
   ```

4. **GET `/api/v1/decay/config`** - Current config
   ```json
   {
     "enabled": true,
     "decay_half_life": 30.0,
     "frequency_threshold": 10,
     "min_decay_score": 0.1
   }
   ```

## Acceptance Criteria

- [ ] All 4 endpoints are implemented
- [ ] Endpoints return correct JSON responses
- [ ] Error handling for invalid concept IDs
- [ ] Auth/authorization (if applicable)
- [ ] Integration tests for all endpoints
- [ ] Response schemas documented

## Notes

- Use Starlette `JSONResponse`
- Reuse store methods from `store.py`
- Compute decay scores on-the-fly (don't store)
- Add to `api_routes` list at bottom of file