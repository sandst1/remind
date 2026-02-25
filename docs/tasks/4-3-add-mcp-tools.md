# Task 4.3: Add MCP Tools

**Phase**: 4 - CLI & API Exposure

## Story

As an LLM agent, I can query decay stats.

## Description

Add MCP (Model Context Protocol) tools for decay inspection and management.

## Changes

### File: `src/remind/mcp_server.py`

Add three new tools using FastMCP decorators:

1. **get_decay_stats(concept_id: str)** - Get decay statistics
   ```python
   @tool
   def get_decay_stats(concept_id: str) -> dict:
       """Get decay score and access statistics for a concept."""
       # Returns: decay_score, access_count, last_accessed, access_history
   ```

2. **reset_decay(concept_id: str)** - Reset decay to maximum
   ```python
   @tool
   def reset_decay(concept_id: str) -> dict:
       """Reset decay score to maximum for a concept."""
       # Returns: success, new_decay_score, access_count
   ```

3. **get_recent_accesses(limit: int = 20)** - View access patterns
   ```python
   @tool
   def get_recent_accesses(limit: int = 20) -> list[dict]:
       """Get recent memory access patterns for analysis."""
       # Returns: list of {concept_id, accessed_at, activation_level}
   ```

## Acceptance Criteria

- [ ] All 3 MCP tools are implemented
- [ ] Tools use correct FastMCP decorators
- [ ] Type hints are correct for MCP
- [ ] Error handling for invalid inputs
- [ ] Tools are registered and available
- [ ] Documentation added to `docs/AGENTS.md`
- [ ] MCP integration tests

## Notes

- MCP tools enable LLM agents to query and manage decay
- Tools should work with the same backend as CLI/API
- Consider adding to MCP server initialization
- Update agent documentation with new capabilities