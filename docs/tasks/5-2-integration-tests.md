# Task 5.2: Integration Tests

**Phase**: 5 - Testing & Validation

## Story

As a tester, I can verify end-to-end decay functionality.

## Description

Create integration tests to verify decay works correctly across all layers.

## Changes

### File: `tests/test_decay_integration.py` (new file)

Create integration test cases for:

1. **test_retrieval_includes_decay**
   - Create concepts with different access patterns
   - Perform retrieval queries
   - Verify ranking incorporates decay scores
   - Concepts with higher decay should rank higher

2. **test_access_logging**
   - Perform multiple retrievals
   - Verify accesses are logged to database
   - Verify access counts increment
   - Verify last_accessed updates

3. **test_cli_commands_end_to_end**
   - Test `remind decay inspect` with real concept
   - Test `remind decay reset` and verify decay score changes
   - Test `remind decay recent` shows logged accesses
   - Test `remind decay config` shows configuration

4. **test_api_endpoints_end_to_end**
   - Test GET `/api/v1/concepts/<id>/decay`
   - Test PUT `/api/v1/concepts/<id>/decay/reset`
   - Test GET `/api/v1/decay/recent`
   - Test GET `/api/v1/decay/config`
   - Verify JSON responses and status codes

5. **test_decay_with_consolidation**
   - Remember episodes
   - Consolidate into concepts
   - Perform retrievals
   - Verify decay updates work with newly created concepts

6. **test_decay_disabled**
   - Configure decay disabled
   - Verify retrieval still works
   - Verify decay scores are not computed
   - Verify access tracking is skipped

## Acceptance Criteria

- [ ] All integration tests pass
- [ ] Tests use real database (temp file)
- [ ] Tests cover full request/response cycles
- [ ] Tests are deterministic
- [ ] Tests clean up after themselves
- [ ] Tests run in CI pipeline

## Notes

- Use test client for API tests
- Use subprocess or CLI runner for CLI tests
- Clean up temp databases after tests
- Follow existing integration test patterns