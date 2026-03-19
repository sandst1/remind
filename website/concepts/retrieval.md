# Retrieval

Remind uses **spreading activation** for retrieval — a biologically-inspired algorithm that goes beyond keyword or vector matching. When you query Remind, it doesn't just find the closest embeddings. It activates a network of related concepts through the knowledge graph.

## How spreading activation works

```
Query: "What authentication approach should we use?"

1. EMBED     → Query is converted to a dense vector

2. MATCH     → Concepts with similar embeddings activate
               "JWT auth middleware" (0.89)
               "Auth module architecture" (0.82)
               "Password hashing with bcrypt" (0.75)

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

## Entity name matching

In addition to embedding similarity, retrieval performs **entity name matching** on the query. Words in your query are matched against entity names and IDs — if the query mentions "redis", concepts linked to the `tool:redis` entity are activated directly. This provides a fast, embedding-free signal that complements the semantic search.

## Parameters

The retrieval algorithm has a few key parameters:

- **k** — Maximum number of concepts to return (default: 3)
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
```

```python [Python]
context = await memory.recall("authentication approach")
context = await memory.recall("auth", entity="module:auth")
context = await memory.recall(entity="module:auth")       # Entity-only
```

```text [MCP]
recall(query="authentication approach")
recall(query="auth", entity="module:auth")
recall(entity="module:auth")
```

:::
