# Memory Decay Branch — Review

## Issues to Fix

### 1. Double/non-deterministic decay on related concepts

**File**: `src/remind/store.py` — `decay_concepts()`

Every concept gets `-decay_rate` in the main loop. Then, when a concept has relations, its related concepts get an *additional* `-decay_rate * related_decay_factor`. Since those related concepts also get their own `-decay_rate` during their own turn in the main loop, they effectively decay more than intended.

Worse: if concept B is a target of relations from A and C, it gets decayed three times: once for itself, once as A's related concept, once as C's related concept. Highly-connected concepts decay fastest — likely the opposite of what's desired.

The order also matters: whether a related concept has already been processed in the main loop when it gets read for related-decay depends on iteration order, making the total decay amount **non-deterministic**.

**Fix**: Compute all decay deltas upfront from a snapshot of current values, then apply them in a single pass. Or remove the related-concept decay from `decay_concepts()` entirely, since every concept already gets its own decay in the main loop.

### 2. `create_memory()` doesn't pass `decay_config` to `MemoryInterface`

**File**: `src/remind/interface.py` — `create_memory()`

The factory function loads `config.decay` from the config file but never passes it through to `MemoryInterface`. Users configuring decay via `~/.remind/remind.config.json` will always get the defaults.

**Fix**: Add to `create_memory()`:
```python
if "decay_config" not in kwargs:
    kwargs["decay_config"] = config.decay
```

### 3. `_recall_count` is ephemeral — decay never triggers in CLI

**File**: `src/remind/interface.py`

`_recall_count` is an instance variable that starts at 0 every time `MemoryInterface` is created. The CLI spawns a new process per command, so each `remind recall` invocation starts at count=1 and decay never triggers (default interval is 20).

Even in the MCP server, a restart resets the counter. The decay mechanism is effectively dead code for any non-long-running usage.

**Fix**: Either persist the recall count in the database (e.g., a metadata table) or switch to time-based decay (compare last decay timestamp to now), which is naturally persistent.

### 4. Entity-based recalls skip rejuvenation and decay triggering

**File**: `src/remind/interface.py` — `recall()`

When `entity` is provided, the method returns early before the rejuvenation and decay-trigger blocks. But `_recall_count` is still incremented. This means:
- Entity recalls count toward the decay interval but don't rejuvenate any concepts
- Inconsistent behavior between the two recall paths

**Fix**: Move the decay trigger check to run for both paths. For entity recalls, decide whether related concepts should be rejuvenated or not.

### 5. Rejuvenation is too aggressive — full reset to 1.0

**File**: `src/remind/interface.py` — `_rejuvenate_concepts()`

Any concept in the recall results gets `decay_factor` fully reset to `1.0`, regardless of activation score. A concept that barely scraped above the activation threshold gets the same rejuvenation as the top result. A nearly-dead concept (`decay_factor=0.01`) that sneaks into results gets fully restored.

**Fix**: Consider proportional rejuvenation (e.g., `min(1.0, decay_factor + 0.3)`), or only rejuvenate concepts above a certain activation threshold, or scale rejuvenation by activation score.

### 6. Performance: `decay_concepts()` loads all concepts including embeddings

**File**: `src/remind/store.py` — `decay_concepts()`

The method calls `self.get_all_concepts()` which deserializes every concept from JSON including full embedding vectors. Then for each concept it calls `self.get_related()` (another query + deserialization) and `self.update_concept()` (individual write). With many concepts this is very expensive.

**Fix**: Use a SQL-level update: `UPDATE concepts SET data = json_set(data, '$.decay_factor', max(0, json_extract(data, '$.decay_factor') - ?))`. Or at minimum, batch the writes in a single transaction.

### 7. `get_stats()` also loads all concepts just for decay stats

**File**: `src/remind/store.py` — `get_stats()`

Decay stats are computed by loading and deserializing every concept (including embeddings) just to read `decay_factor`. This adds overhead to a frequently-called method.

**Fix**: Use SQL queries on the JSON field:
```sql
SELECT COUNT(*) FROM concepts WHERE json_extract(data, '$.decay_factor') < 1.0;
SELECT AVG(json_extract(data, '$.decay_factor')) FROM concepts;
SELECT MIN(json_extract(data, '$.decay_factor')) FROM concepts;
```

### 8. No way to disable decay

**File**: `src/remind/config.py` — `DecayConfig`

There's no `enabled` flag. Even if someone sets `decay_interval` very high to prevent the decay pass, rejuvenation writes (resetting `decay_factor` to 1.0 + updating `last_accessed` + incrementing `access_count`) still happen on every recall, adding unnecessary DB writes.

**Fix**: Add `enabled: bool = True` to `DecayConfig` and check it before rejuvenation/decay operations.

### 9. Unused `conn` in `decay_concepts()`

**File**: `src/remind/store.py` — `decay_concepts()`

The method opens a connection with `self._get_conn()` but never uses `conn` directly — all operations go through `self.get_all_concepts()`, `self.get_related()`, `self.update_concept()` which each open their own connections.

**Fix**: Remove the unused `conn = self._get_conn()` / `conn.close()` wrapper.

### 10. Unused `decay_interval` parameter in `decay_concepts()`

**File**: `src/remind/store.py` — `decay_concepts()`

The `decay_interval` parameter is accepted and documented as "for tracking" but never used inside the method.

**Fix**: Remove it from the method signature, or actually use it.

### 11. Redundant/split imports

**File**: `src/remind/interface.py`

`from remind.config import load_config` is added at the top-level, but `DecayConfig` is imported again inside `__init__` with `from remind.config import DecayConfig`.

**Fix**: Import both at the top level together.

### 12. Tests don't test through `MemoryInterface`

**File**: `tests/test_decay.py`

Rejuvenation and periodic decay tests manually simulate the behavior (manually managing a `recall_count`, manually setting fields) rather than calling `MemoryInterface.recall()`. The actual integration path where rejuvenation and decay triggering happen together isn't tested end-to-end.

**Fix**: Add integration tests that create a `MemoryInterface` with mock providers and actually call `recall()` to verify the full flow.

### 13. Misleading test name

**File**: `tests/test_decay.py`

`test_decay_only_applies_once_per_interval` actually tests that calling decay twice applies it twice (0.8 = 1.0 - 0.1 - 0.1). The name suggests the opposite.

**Fix**: Rename to something like `test_decay_accumulates_across_multiple_calls`.
