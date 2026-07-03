# What is Remind?

Remind is a memory layer for LLM agents. It stores facts, episodes, and concepts with first-class support for temporal validity, provenance tracking, and conflict detection. Unlike simple RAG systems, Remind maintains *structured knowledge* that agents can query and curate.

## The problem with current AI memory

Most approaches to giving AI persistent memory are some variation of "store text, search text":

- **RAG**: Embed documents, retrieve similar chunks
- **Conversation buffers**: Keep recent messages around
- **Vector stores**: Log everything, search by similarity

These approaches treat memory as passive storage. Remind treats memory as *structured knowledge* that agents actively curate.

## Agent-driven memory

Remind v1.0 takes a different approach: **the calling agent is the only intelligence**. Remind provides:

1. **Deterministic fact handling** — Facts are clustered by entity overlap, stored with validity windows, and collisions are reported for agent triage
2. **Batch read/write tools** — `snapshot` returns current memory state; `apply` executes transactional changesets
3. **Local embeddings by default** — No API keys needed; uses `all-MiniLM-L6-v2` via fastembed

The agent decides what to remember, how to organize concepts, and how to resolve conflicts. Remind is the substrate.

## How Remind works

```
┌─────────────────────────────────────────────────────────────────┐
│                      CALLING AGENT                              │
│         (Your agent that uses Remind for memory)                │
└─────────────────────┬───────────────────────┬───────────────────┘
                      │                       │
              snapshot (read)           apply (write)
                      │                       │
                      ▼                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                      MEMORY INTERFACE                           │
│              remember() / recall() / snapshot() / apply()       │
└─────────────────────┬───────────────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
   ┌─────────┐  ┌──────────┐  ┌──────────────┐
   │EPISODES │  │ CONCEPTS │  │    FACTS     │
   │ (raw)   │  │(curated) │  │ (clustered)  │
   └─────────┘  └──────────┘  └──────────────┘
        │             │              │
        └──────┬──────┴──────────────┘
               ▼
      ┌─────────────────┐      ┌─────────────────┐
      │  FACT PIPELINE  │      │    RETRIEVER    │
      │ (deterministic) │      │ (Spreading Act) │
      └─────────────────┘      └─────────────────┘
```

### Core components

1. **Episodes** — Raw experiences logged via `remember()`. Fast (no LLM calls), just storage + embedding.

2. **Facts** — Specific factual assertions (`type=fact`). Automatically clustered by entity overlap, stored with validity windows. Collisions are reported back so the agent can decide what to do.

3. **Concepts** — Curated knowledge created by the agent via `apply`. These are patterns, summaries, or grouped facts that the agent has reviewed and organized.

4. **Spreading activation retrieval** — When you query, matching concepts activate related concepts through the graph, with activation decaying over hops.

5. **Memory decay** — Concepts that are rarely recalled gradually lose retrieval priority. Concepts that are frequently accessed get reinforced.

## Two batch tools

The core workflow uses two batch tools:

### `snapshot` — Batch read

Returns current memory state as JSON. Combine scopes in a single call:

```
snapshot(scopes="pending,conflicts")  # Unreviewed episodes + open conflicts
snapshot(scopes="entity:tool:redis")  # All data for an entity
snapshot(scopes="concept:abc123")     # Concept detail with fact history
```

### `apply` — Batch write

Executes a transactional changeset. All-or-nothing with per-op results:

```
remember as=f1 t=fact e=tool:redis "Cache TTL is 600 seconds"
supersede old=fact:a91c2 new=$f1
concept from=ep:11,ep:12 title="Retry pattern" "Transient failures resolve with backoff"
resolve id=conflict:7 winner=fact:b3d01 "confirmed by ops"
processed ids=ep:11,ep:12
```

## Two ways to integrate

### Skills + CLI (project-local)

Your agent calls the `remind` CLI from skills — markdown files with instructions. The database lives in your project repo at `.remind/remind.db`. Each project has its own isolated memory.

[Learn more about Skills →](/guide/skills)

### MCP Server (centralized)

Remind runs as an MCP server. Agents connect to it over HTTP. The database is centralized at `~/.remind/`. Good for cross-project memory and shared knowledge bases.

[Learn more about MCP →](/guide/mcp)
