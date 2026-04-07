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

2b. FUSE     → Embedding score is blended with keyword overlap
               score = (1 - keyword_weight) × embedding + keyword_weight × keyword
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

## Hybrid keyword scoring

By default, retrieval fuses embedding similarity with keyword overlap (controlled by `hybrid_keyword_weight`, default `0.3`). This helps surface concepts that contain exact query terms which embeddings alone might miss — for instance, specific tool names, config keys, or technical terms.

The formula is:

```
score = (1 - weight) × embedding_similarity + weight × keyword_overlap
```

Where `keyword_overlap` is the fraction of query tokens (2+ chars) found in the concept's title and summary. Set `hybrid_keyword_weight` to `0.0` for pure embedding search or `1.0` for pure keyword matching.

Configure via `~/.remind/remind.config.json`:

```json
{
  "hybrid_keyword_weight": 0.3
}
```

Or environment variable: `REMIND_HYBRID_KEYWORD_WEIGHT=0.3`

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
  "reranking_model": "cross-encoder/ms-marco-MiniLM-L-2-v2"
}
```

Or via environment variables:

```bash
REMIND_RERANKING_ENABLED=true
REMIND_RERANKING_MODEL=cross-encoder/ms-marco-MiniLM-L-2-v2
```

The default model (`ms-marco-MiniLM-L-2-v2`) is ~50MB, loads in under a second, and scores 30 candidates in ~25-50ms on CPU. Hardware acceleration (CUDA, MPS) is auto-detected.

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
| SQLite | [sqlite-vec](https://github.com/asg017/sqlite-vec) | `vec0` virtual tables with cosine distance KNN. Included as a pip dependency. |
| PostgreSQL | [pgvector](https://github.com/pgvector/pgvector) | `vector(N)` columns with HNSW indexes. Installed with `pip install "remind-mcp[postgres]"`. |
| Fallback | — | NumPy brute-force cosine similarity (O(n) per query). |

Vector tables are created automatically on first embedding write. No manual setup is needed — Remind detects the backend at startup and chooses the best available path.

## Entity name matching

In addition to embedding similarity, retrieval performs **entity name matching** on the query. Words in your query are matched against entity names and IDs — if the query mentions "redis", concepts linked to the `tool:redis` entity are activated directly. This provides a fast, embedding-free signal that complements the semantic search.

## Direct episode search

In addition to concept-based spreading activation, recall can search **episodes directly** by embedding similarity. When `episode_k` is set (default: 5), the query embedding is compared against episode embeddings to find fine-grained matches that may not yet be consolidated into concepts.

Direct episode results appear first in the recall output under a **RELEVANT EPISODES** heading, followed by the concept-based **RELEVANT MEMORY** section.

Use `--episode-k 0` (CLI) or `episode_k=0` (Python/MCP) to disable direct episode search and use only concept-level retrieval.

## Topic-scoped retrieval

When a `topic` is provided to recall, initial concept matches are filtered to that topic (plus untopiced general concepts). Cross-topic concepts can still surface through spreading activation, but receive a 0.4x penalty — they need stronger relation evidence to appear in results.

This reduces noise when querying a specific knowledge area while still allowing relevant cross-domain insights to surface.

## Contradiction and supersession display

Each concept in recall output shows **inbound and outbound contradictions** — concepts that have a `contradicts` relation to or from the current concept. This surfaces conflicting knowledge directly in the retrieval context, so the consumer can see tensions without needing to inspect relations manually.

Similarly, **supersedes** relations are surfaced explicitly:
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
remind recall "database design" --topic architecture  # Topic-scoped
```

```python [Python]
context = await memory.recall("authentication approach")
context = await memory.recall("auth", entity="module:auth")
context = await memory.recall(entity="module:auth")       # Entity-only
context = await memory.recall("auth", episode_k=10)       # More episode matches
context = await memory.recall("auth", episode_k=0)        # Concepts only
context = await memory.recall("database design", topic="architecture")  # Topic-scoped
```

```text [MCP]
recall(query="authentication approach")
recall(query="auth", entity="module:auth")
recall(entity="module:auth")
recall(query="auth", episode_k=10)
recall(query="auth", episode_k=0)
recall(query="database design", topic="architecture")
```

:::
