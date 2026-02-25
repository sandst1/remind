# Memory Decay Implementation Review

Review of the `qwen3.5-35B-A3B-memory-decay` branch against `docs/plan-memory-decay.md`.

---

## Priority Fixes

### 1. Fix confidence boost weight (Bug)

The confidence boost uses `confidence * 0.5`, but the plan specifies 20% weight. The weights don't sum to 1.0 — they sum to 1.3 at maximum.

**Current (wrong):**
```python
confidence_boost = (concept.confidence or 0.5) * 0.5
```

**Should be:**
```python
confidence_boost = concept.confidence * 0.2
```

**Affected files:**
- `src/remind/retrieval.py` — `_compute_decay_score()`
- `src/remind/cli.py` — `decay inspect` command (lines 1037-1040)
- `src/remind/api/routes.py` — `get_concept_decay()` (lines 669-670)
- `src/remind/mcp_server.py` — `tool_get_decay_stats()` (lines 465-466)

**Also fix the formula display in CLI:**
```
# cli.py line 1170 — currently shows:
decay_score = (recency × 0.4) + (frequency × 0.4) + (confidence × 0.5)
# Should be:
decay_score = (recency × 0.4) + (frequency × 0.4) + (confidence × 0.2)
```

### 2. Fix `confidence or 0.5` masking zero confidence (Bug)

Python's `or` treats `0.0` as falsy, so `confidence=0.0` silently becomes `0.5`.

**Current (wrong):**
```python
confidence_boost = (concept.confidence or 0.5) * 0.5
```

**Should be:**
```python
confidence_boost = concept.confidence * 0.2
```

Using the value directly is fine since `Concept.confidence` defaults to `0.5`.

### 3. Cap `_compute_decay_score` at 1.0

The MCP tool adds `min(decay_score, 1.0)` but the canonical `_compute_decay_score()` in `retrieval.py` does not. After fixing the weights to sum to 1.0 this becomes less critical, but a cap is still good defensive practice.

**In `retrieval.py` `_compute_decay_score()`:**
```python
return max(min(decay_score, 1.0), self.config.decay.min_decay_score)
```

### 4. Extract decay computation to eliminate 4x duplication (DRY)

The decay score formula is duplicated in 4 places:
1. `src/remind/retrieval.py` — `MemoryRetriever._compute_decay_score()`
2. `src/remind/cli.py` — `decay inspect` command
3. `src/remind/api/routes.py` — `get_concept_decay()`
4. `src/remind/mcp_server.py` — `tool_get_decay_stats()`

**Fix:** Extract into a standalone function (e.g., in `retrieval.py` or a new `decay.py` module) and have all 4 call sites use it. The function should take a `Concept` and `DecayConfig` and return a dict with `decay_score`, `recency_factor`, `frequency_factor`.

---

## Minor Issues

### 5. Missing config fields from plan

The plan specifies two `DecayConfig` fields that were not implemented:
- `access_weighting: str = "exponential"` — allows choosing between exponential and linear decay
- `max_access_history: int = 100` — configurable history truncation limit (currently hardcoded)

### 6. Performance: per-concept DB writes on every retrieval

In `retrieval.py`, after retrieval, `store.update_concept()` is called for every retrieved concept (full JSON serialization + SQLite UPDATE). For 5 results, that's 5 DB writes + 5 access log inserts per query. The plan mentions batch logging as a mitigation but it wasn't implemented.

Consider:
- Batching concept updates into a single transaction
- Making access tracking async/deferred
- Only updating access metadata without full concept re-serialization

### 7. `reset_decay` doesn't achieve decay_score=1.0

The plan says reset should set `decay_score = 1.0`. The implementation resets `access_count = 0` but the resulting score depends on recency (`last_accessed`) and confidence. A concept accessed 60 days ago with `access_count=0` would get a score well below 1.0 after reset.

To match the plan, reset should also set `last_accessed = datetime.now()`.

### 8. Commit message hygiene

- `799cc3d` — "Plans for memory decau" (typo, truncated "decay")
- `db3145d` — "update interface layer, 3-2" (casual, not conventional commit format)
- Inconsistent use of `feat:` prefix across commits

---

## Plan Coverage

| Task | Status | Notes |
|------|--------|-------|
| 1.1 Update Concept model | ✅ Done | Clean |
| 1.2 Add retrieval access log | ✅ Done | Table + methods + indexes |
| 1.3 Add DecayConfig | ⚠️ Mostly done | Missing `access_weighting`, `max_access_history` |
| 2.1 Decay score computation | ⚠️ Has bugs | Weight sum > 1.0, confidence=0 bug |
| 2.2 Integrate access tracking | ✅ Done | Performance concern noted |
| 3.1 Update retrieval ranking | ✅ Done | 70/30 split matches plan |
| 3.2 Update interface layer | ✅ Done | Good docstrings |
| 4.1 CLI commands | ✅ Done | All 4 commands |
| 4.2 REST API endpoints | ✅ Done | All endpoints |
| 4.3 MCP tools | ✅ Done | All 3 tools + docs |
| 5.1 Unit tests | ✅ Done | 23 tests passing |
| 5.2 Integration tests | ✅ Done | 12 tests passing |

All 35 tests pass. The implementation covers the full plan scope across all 5 phases.
