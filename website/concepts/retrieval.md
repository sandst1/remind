# Retrieval

Remind uses **spreading activation** for retrieval — a biologically-inspired algorithm that goes beyond keyword or vector matching. When you query Remind, it doesn't just find the closest embeddings. It activates a network of related concepts through the knowledge graph.

## How spreading activation works

```
Query: "What authentication approach should we use?"

1. EMBED     → Query is converted to a dense vector

2. MATCH     → Concepts with similar embeddings activate (via native
               vector index when available, or brute-force fallback)
               "JWT auth middleware" (0.89)
               "Auth module architecture" (0.82)
               "Password hashing with bcrypt" (0.75)

2b. FUSE     → Embedding ranking is fused with a lexical (full-text) search
               ranking via weighted Reciprocal Rank Fusion
               (configurable via hybrid_keyword_weight, default 0.3)

3. SPREAD    → Activated concepts propagate through relations
               "JWT auth middleware"
                 → implies: "Need token refresh strategy" (0.71)
                 → part_of: "Auth system architecture" (0.66)
               "Auth module architecture"
                 → implies: "Rate limiting on auth endpoints" (0.58)

4. DECAY     → Activation reduces with each hop
               Hop 1: activation × relation_strength × 0.5
               Hop 2: activation × relation_strength × 0.25

5. RETURN    → Highest-activation concepts are returned
```

This is fundamentally different from RAG. You don't get "the 5 most similar documents." You get a network of related knowledge that spreads from the query through the concept graph.

## Why spreading activation?

Consider how human memory works. You don't search for "that restaurant" by scanning every memory. You think about *food*, which activates *that conversation about cooking*, which activates *that restaurant*, which activates *who you were with*.

Spreading activation retrieves concepts you didn't directly query for but are meaningfully connected. Asking about "auth" might activate "rate limiting" (which is part of the auth system) even though "rate limiting" has no embedding similarity to "auth."

## Lexical recall channel and RRF fusion

Vector similarity alone can miss exact identifiers — specific tool names, config keys, error codes, or other technical terms that an embedding may not represent distinctly. To catch these, Remind runs a second, independent recall channel: a **lexical (full-text) search** over the same concepts and episodes, using whichever full-text backend the database supports:

| Backend | Mechanism |
|---------|-----------|
| SQLite | [FTS5](https://sqlite.org/fts5.html) virtual tables, kept in sync on every write |
| PostgreSQL | Generated `tsvector` columns with a GIN index |
| MySQL | `FULLTEXT` indexes |

The backend is detected automatically at startup (`lexical_enabled`, default `true`); if none is available, retrieval silently falls back to pure vector search.

Vector and lexical results are combined using **weighted Reciprocal Rank Fusion (RRF)** rather than blending raw scores — RRF only needs each channel's *ranking*, so cosine similarity and BM25-style lexical scores don't need to be on comparable scales:

```
fused(id) = (1 - weight) / (rrf_k + vector_rank(id) + 1)
          +      weight  / (rrf_k + lexical_rank(id) + 1)
```

`weight` is `hybrid_keyword_weight` (default `0.3`) — the lexical arm's share of the fusion. `rrf_k` (default `60`) dampens the influence of rank position; higher values flatten the curve so lower-ranked results still contribute. The fused scores are then min-max normalized so the top match is `1.0`, keeping results comparable to the `[0, 1]` similarity range that `activation_threshold`/`min_activation` are calibrated against.

If the lexical channel returns nothing (disabled, no backend, or no matching terms), fusion degrades to the raw vector similarity untouched — pure-embedding recall is unaffected.

Set `hybrid_keyword_weight` to `0.0` to disable the lexical arm and use pure embedding search, or higher to weight exact-term matches more heavily.

Configure via `~/.remind/remind.config.json`:

```json
{
  "hybrid_keyword_weight": 0.3,
  "lexical_enabled": true,
  "rrf_k": 60
}
```

Or environment variables: `REMIND_HYBRID_KEYWORD_WEIGHT=0.3`, `REMIND_LEXICAL_ENABLED=true`, `REMIND_RRF_K=60`

## Reranking

Optionally, retrieval can apply a **cross-encoder reranker** after spreading activation. While embedding similarity and keyword overlap are fast, they can miss nuanced relevance — a cross-encoder reads the query and each candidate together, producing a more accurate relevance score.

When enabled, reranking is applied in two places:

1. **Concept retrieval** — After spreading activation and entity matching produce a candidate set, the reranker scores each concept's title + summary against the query. The final activation is blended: `0.4 × activation + 0.6 × rerank_score`.
2. **Direct episode search** — Episode results are similarly rescored using episode content.

This preserves graph structure signal (spreading activation, entity links) while letting the cross-encoder correct false positives and surface better matches.

### Setup

Install the reranking extra:

```bash
pip install "remind-mcp[rerank]"
```

Enable in config (`~/.remind/remind.config.json`):

```json
{
  "reranking_enabled": true,
  "reranking_model": "cross-encoder/ms-marco-MiniLM-L-6-v2"
}
```

Or via environment variables:

```bash
REMIND_RERANKING_ENABLED=true
REMIND_RERANKING_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
```

The default model (`ms-marco-MiniLM-L-6-v2`) is ~88MB on disk, typically loads in ~0.3-1.0s from cache, and scores 30 candidates in ~20-30ms on CPU. Hardware acceleration (CUDA, MPS) is auto-detected.

### Runtime behavior: CLI vs MCP

- **MCP server** is long-lived, so reranker model load is amortized naturally across many recall calls.
- **CLI (`remind recall`)** is normally one-shot, but when `reranking_enabled=true` it transparently routes requests through a persistent local recall worker so reranker load is reused across calls.
- The CLI worker exits after `cli_recall_worker_idle_seconds` of inactivity (default: 600s).
- If the worker is unavailable, CLI falls back to one-shot recall so commands remain functional.

### Tuning with recall_initial_candidates

The `recall_initial_candidates` setting controls how many concepts are fetched from the vector index before spreading activation and reranking. The default is `10` (which queries the DB for `10 × 2 = 20` raw candidates before filtering).

When reranking is enabled, increasing this value gives the reranker more candidates to evaluate, which can improve recall quality at the cost of slightly higher latency. A value of `15`-`20` is a good starting point:

```json
{
  "reranking_enabled": true,
  "recall_initial_candidates": 15
}
```

Without reranking, the default of `10` is generally sufficient since the spreading activation and entity matching steps already broaden the candidate pool.

## Vector indexes

Remind uses native database vector indexes when available, replacing the default brute-force Python cosine similarity:

| Backend | Extension | How it works |
|---------|-----------|-------------|
| SQLite | [sqlite-vec](https://github.com/asg017/sqlite-vec) | `vec0` virtual tables with cosine distance KNN. The package is installed with Remind; see below for when it can actually load. |
| PostgreSQL | [pgvector](https://github.com/pgvector/pgvector) | `vector(N)` columns with HNSW indexes. Installed with `pip install "remind-mcp[postgres]"`. |
| Fallback | — | NumPy brute-force cosine similarity (O(n) per query). |

Vector tables are created automatically on first embedding write. No manual setup is needed — Remind detects the backend at startup and chooses the best available path.

### SQLite (sqlite-vec) requirements

sqlite-vec loads as a **SQLite extension**. Your Python `sqlite3` connection must support `enable_load_extension`. Some builds (notably macOS interpreters linked against a minimal system SQLite) do not — then Remind skips sqlite-vec and uses brute-force similarity; recall still works.

To **use** native SQLite vector search, run Remind under a Python built with loadable SQLite extensions, typically by linking against Homebrew’s SQLite when installing Python (e.g. pyenv with `PYTHON_CONFIGURE_OPTS=--enable-loadable-sqlite-extensions` and `LDFLAGS`/`CPPFLAGS` pointing at `brew --prefix sqlite`). Verify with:

```bash
python -c "import sqlite3; c=sqlite3.connect(':memory:'); print(hasattr(c, 'enable_load_extension'))"
```

Full step-by-step notes are in [Configuration — Vector search](/guide/configuration#vector-search).

## Entity-based retrieval

Retrieval has two entity-based signals:

### Entity embedding search

Entities are embedded on creation (using their type and display name). During retrieval, the query embedding is compared against entity embeddings in parallel with concept and episode searches. Concepts linked to high-similarity entities receive a boost — this catches concepts that may have low direct embedding similarity to the query but are linked to entities that match well.

For example, querying "session storage" might not match a concept about "Redis configuration" directly, but if `tool:redis` has high embedding similarity to the query, concepts linked to that entity get boosted.

### Entity name matching

Words in your query are matched against entity names and IDs — if the query mentions "redis", concepts linked to the `tool:redis` entity are activated directly. This provides a fast, embedding-free signal that complements the semantic search.

## Direct episode search

In addition to concept-based spreading activation, recall can search **episodes directly** by embedding similarity. When `episode_k` is set (default: 5), the query embedding is compared against episode embeddings to find fine-grained matches that may not yet be consolidated into concepts.

Direct episode results appear first in the recall output under a **RELEVANT EPISODES** heading, followed by the concept-based **RELEVANT MEMORY** section.

Use `--episode-k 0` (CLI) or `episode_k=0` (Python/MCP) to disable direct episode search and use only concept-level retrieval.

## Label-scoped retrieval

When `labels` are provided to recall, they're pushed down as a pre-filter into the vector search itself — not applied afterward to the top-k. Only episodes/concepts carrying a matching `key=value` label are eligible to be returned. See [Labels](/concepts/labels) for how the pre-filter is implemented per backend.

This reduces noise when querying a specific knowledge area, at the cost of excluding unlabeled or differently-labeled results entirely — unlike the old topic filter, there's no cross-label leakage with a penalty.

## Fact clusters in recall output

Fact-cluster concepts render their **active fact rows** with provenance and validity:

```
- Cache TTL is 600 seconds (alice, since 2026-03-01)
- Cache backend is Redis (since 2026-01-10)
```

Superseded values don't appear — a fact that was updated shows only its current value, with history reachable via [as-of recall](#as-of-recall-time-travel) or the concept detail view. Episode lines show the episode's creation date (when it was asserted) and provenance.

## As-of recall (time travel)

Passing `as_of` (ISO date/datetime) makes fact clusters show the facts that were **valid at that point in time** instead of the current ones:

```bash
remind recall --as-of 2026-01-15 "cache configuration"
```

Useful for "what did we believe then" questions — auditing past decisions against the knowledge available at the time. See [Facts & Conflicts](/concepts/facts-and-conflicts#as-of-recall-time-travel).

## Contradiction and supersession display

When a retrieved concept is involved in **open conflicts**, recall output includes an `OPEN CONFLICTS` warning with the conflict IDs and descriptions, so the consumer knows the retrieved knowledge is contested and can triage it (`remind conflicts`) instead of silently picking a side. Resolved and dismissed conflicts don't clutter the output.

Similarly, **supersedes** relations between concepts are surfaced explicitly:
- `→ supersedes [old_id]: <old summary>` — this concept replaces an older one
- `→ SUPERSEDED BY [new_id]: <new summary>` — this concept has been replaced

This acts as a staleness signal: if a retrieved concept has been superseded, the consumer knows to prefer the newer version.

## Parameters

The retrieval algorithm has a few key parameters:

- **k** — Maximum number of concepts to return (default: 3)
- **episode_k** — Number of episodes to retrieve via direct embedding search (default: 5). Set to 0 to disable.
- **recall_initial_candidates** — How many initial embedding candidates to fetch before spreading activation and reranking (default: 10). The database actually queries for `recall_initial_candidates × 2` raw results, then filters by activation threshold. Increase when using reranking to give the cross-encoder more candidates to evaluate.
- **min_activation** — Minimum activation score to include in results (default: 0.15). Concepts below this floor are dropped even if there's budget remaining. This prevents low-relevance noise from reaching the context.
- **Initial activation threshold** — Minimum embedding similarity to activate a concept
- **Spread decay** — How much activation reduces per hop (default: 0.5 per hop)
- **Spread depth** — Number of hops to propagate (default: 2)

## Recall budget controls

`recall()` also accepts three cost/size guardrails, each with a config default (`recall_max_chars`, `recall_min_score`, `recall_timeout_ms`) so they can be set once and left alone:

- **max_chars** — Caps the formatted output length. When the rendered text would exceed this, the lowest-ranked concepts and episodes are dropped *whole* — never truncated mid-item — until it fits. Useful for bounding how much context a single recall call injects into a prompt.
- **min_score** — Floor below which concepts/episodes are dropped even if the `k`/`episode_k` budget has room left. Distinct from `min_activation` in that it also applies to direct episode results, not just concepts.
- **timeout_ms** — Soft deadline for the whole retrieval. If exceeded, remaining phases (spreading activation, reranking) are skipped and results are built from whatever was already gathered — recall returns best-so-far instead of raising.

None of the three are enabled by default (`None`), preserving existing behavior until explicitly configured.

## Query-free bootstrap read

`recall()` and `snapshot(scopes="query:<text>")` both need an embedding call and return different results depending on the query. Sometimes you want the opposite: a stable, deterministic slice of "what does this memory currently know" that doesn't change between calls unless the underlying data changes — cheap enough to run at the start of every session, or to place in a system prompt via an injection layer without busting the KV cache on every turn.

`snapshot(scopes="bootstrap[:<n>]")` (default `n=10`) returns exactly that: the top-n **actionable** concepts ranked by `(confidence, instance_count)` descending, plus the open conflict count and memory stats — no embedding call involved.

```bash
remind snapshot bootstrap        # Top 10 concepts + conflicts + stats
remind snapshot bootstrap:5      # Top 5
```

```json
{
  "bootstrap": {
    "count": 5,
    "concepts": [ /* top concepts, most confident + corroborated first */ ],
    "open_conflicts": 2,
    "stats": { "total_episodes": 143, "total_concepts": 37, "..." : "..." }
  }
}
```

## Decay factor

Each concept has a `decay_factor` (0.0–1.0) that multiplies its activation score during retrieval. This implements [memory decay](/concepts/memory-decay) — concepts that haven't been recalled recently rank lower. Frequently-recalled concepts maintain high decay factors.

## Using recall

::: code-group

```bash [CLI]
remind recall "authentication approach"
remind recall "auth" --entity module:auth    # Entity-scoped
remind recall --entity module:auth           # Entity-only (no query needed)
remind recall "performance" -k 10            # More results
remind recall "auth" --episode-k 10          # More direct episode matches
remind recall "auth" --episode-k 0           # Concepts only, no episodes
remind recall "database design" -l topic=architecture # Label-scoped
remind recall --as-of 2026-01-15 "cache config"       # Time-travel
remind recall "auth" --max-chars 2000                 # Cap output size
remind recall "auth" --min-score 0.3 --timeout-ms 500 # Budget controls
```

```python [Python]
context = await memory.recall("authentication approach")
context = await memory.recall("auth", entity="module:auth")
context = await memory.recall(entity="module:auth")       # Entity-only
context = await memory.recall("auth", episode_k=10)       # More episode matches
context = await memory.recall("auth", episode_k=0)        # Concepts only
context = await memory.recall("database design", labels={"topic": "architecture"})  # Label-scoped
context = await memory.recall("cache config", as_of="2026-01-15")  # Time-travel
context = await memory.recall("auth", max_chars=2000)     # Cap output size
context = await memory.recall("auth", min_score=0.3, timeout_ms=500)  # Budget controls
```

```text [MCP]
recall(query="authentication approach")
recall(query="auth", entity="module:auth")
recall(entity="module:auth")
recall(query="auth", episode_k=10)
recall(query="auth", episode_k=0)
recall(query="auth", max_chars=2000)
recall(query="auth", min_score=0.3, timeout_ms=500)
recall(query="database design", labels="topic=architecture")
recall(query="cache config", as_of="2026-01-15")
```

:::
