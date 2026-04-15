# Concepts

Concepts are the generalized knowledge that emerges from consolidation. They're the persistent, meaningful output of Remind's memory system — what episodes become after the LLM "sleeps on" them.

## Structure

Each concept has:

| Field | Description |
|-------|-------------|
| `id` | Unique identifier |
| `title` | Short descriptive title |
| `summary` | Natural language description of the generalized knowledge |
| `concept_type` | Type of concept: `pattern` (generalizations), `fact_cluster` (grouped facts), or `legacy` (pre-existing) |
| `confidence` | How certain (0.0–1.0), based on supporting evidence |
| `instance_count` | How many episodes support this concept |
| `relations` | Typed edges to other concepts |
| `conditions` | When/where this concept applies |
| `exceptions` | Known cases where it doesn't hold |
| `source_episodes` | Episode IDs this was derived from |
| `specifics` | For fact_clusters: list of verbatim facts |
| `evidence` | Key quotes from source episodes |
| `conflicts` | For fact_clusters: detected conflicting facts |
| `embedding` | Dense vector for similarity retrieval |
| `tags` | Searchable tags |
| `topic` | Knowledge area this concept belongs to (e.g., `"architecture"`, `"product"`) |
| `decay_factor` | Retrieval priority weight (affected by [memory decay](/concepts/memory-decay)) |

## How concepts differ from episodes

| | Episodes | Concepts |
|---|---|---|
| Nature | Specific, raw | Generalized, processed |
| Created by | `remember()` | Consolidation (LLM) |
| Lifespan | Temporary (consumed) | Persistent |
| Structure | Plain text + type | Text + confidence + relations + conditions |
| Retrieval | Not directly queried | Primary retrieval target |

## Concept Types

Remind distinguishes between two types of knowledge:

### Pattern Concepts

Generalizations extracted from observations, decisions, and outcomes. These capture abstract understanding:

> **Pattern**: "The team favors statically typed languages for backend services"
> - Derived from multiple language preference observations
> - Generalizes across specific instances

### Fact Clusters

Groups of related concrete facts, preserved verbatim:

> **Fact Cluster**: "Redis Configuration"
> - Redis TTL: 300s
> - Redis connection pool: 10
> - Redis max memory: 2GB

Fact clusters never generalize away specific values. When facts conflict (e.g., different TTL values from different times), both are kept with conflict markers.

### Legacy Concepts

Concepts created before dual-track was introduced. They continue to work normally and don't have a type badge.

### Standalone Facts

Single fact episodes that don't share entities with other facts are **not** clustered. They remain as first-class retrieval targets via direct episode search. This avoids creating single-fact "clusters."

## Concept quality

Good concepts are:

- **Specific and falsifiable** — Making concrete claims, not abstract platitudes
- **Generalized** (for patterns) — Not just restating a single episode, but abstracting across multiple
- **Verbatim** (for facts) — Preserving exact values, configs, and technical details
- **Conditional** — Stating when they apply, not claiming universal truth
- **Connected** — Linked to related concepts via typed relations
- **Grounded** — Traceable back to source episodes

## Topics

Concepts can belong to a **topic** — a knowledge area like `"architecture"`, `"product"`, or `"infra"`. Topics scope consolidation (episodes are grouped by topic before processing) and retrieval (queries can be filtered to a specific topic).

Concepts without a topic are treated as general knowledge accessible from any topic context.

## Managing concepts

```bash
# List all concepts
remind inspect

# View a specific concept with details
remind inspect <concept-id>

# Update a concept's summary
remind update-concept <id> -s "Refined understanding"

# Update confidence
remind update-concept <id> --confidence 0.9

# Reassign or clear topic (ID or name, same as remember)
remind update-concept <id> --topic product
remind update-concept <id> --clear-topic

# Soft delete
remind delete-concept <id>

# Restore
remind restore-concept <id>
```

::: tip
Updating a concept's summary clears its embedding vector. The embedding is regenerated on the next recall query.
:::
