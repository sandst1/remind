# Concepts

Concepts are curated knowledge — generalized understanding that the agent creates from episodes. They're the persistent, meaningful output of Remind's memory system.

## Structure

Each concept has:

| Field | Description |
|-------|-------------|
| `id` | Unique identifier |
| `title` | Short descriptive title |
| `summary` | Natural language description of the knowledge |
| `concept_type` | Type: `pattern` (generalizations), `fact_cluster` (grouped facts) |
| `confidence` | How certain (0.0–1.0) |
| `instance_count` | How many episodes support this concept |
| `relations` | Typed edges to other concepts |
| `conditions` | When/where this concept applies |
| `exceptions` | Known cases where it doesn't hold |
| `source_episodes` | Episode IDs this was derived from |
| `specifics` | For fact_clusters: list of verbatim facts |
| `entity_ids` | Entities linked to this concept |
| `embedding` | Dense vector for similarity retrieval |
| `tags` | Searchable tags |
| `topic` | Knowledge area (e.g., `"architecture"`, `"product"`) |
| `decay_factor` | Retrieval priority weight (affected by [memory decay](/concepts/memory-decay)) |

## How concepts differ from episodes

| | Episodes | Concepts |
|---|---|---|
| Nature | Specific, raw | Curated, structured |
| Created by | `remember()` | Agent via `apply` |
| Lifespan | Pending → processed | Persistent |
| Structure | Plain text + type | Text + confidence + relations |
| Retrieval | Direct search | Primary retrieval target |

## Concept types

### Pattern concepts

Generalizations the agent creates from observations, decisions, and outcomes:

> **Pattern**: "The team favors statically typed languages for backend services"
> - Created from multiple language preference observations
> - Generalizes across specific instances

```
concept from=ep:11,ep:12,ep:13 title="Language preferences" "Team favors statically typed languages"
```

### Fact clusters

Groups of related concrete facts, created automatically when fact episodes are stored:

> **Fact Cluster**: "Redis Configuration"
> - Redis TTL: 300s (alice, 2024-06-01)
> - Redis connection pool: 10 (bob, 2024-06-05)

Fact clusters preserve exact values. When facts conflict, both are kept and a [conflict](/concepts/facts-and-conflicts) is opened.

### Standalone facts

Single fact episodes that don't share entities with other facts are **not** clustered. They remain as first-class retrieval targets via direct episode search.

## Creating concepts with apply

Agents create concepts via the `apply` tool:

```
concept as=c1 from=ep:11,ep:12 title="Auth pattern" "JWT with refresh tokens"
link source=$c1 type=implies target=concept:security
processed ids=ep:11,ep:12
```

This:
1. Creates a concept from episodes 11 and 12
2. Links it to an existing security concept
3. Marks the source episodes as processed

## Concept quality

Good concepts are:

- **Specific and falsifiable** — Making concrete claims, not abstract platitudes
- **Generalized** (for patterns) — Not just restating a single episode
- **Verbatim** (for facts) — Preserving exact values
- **Conditional** — Stating when they apply
- **Connected** — Linked to related concepts via typed relations
- **Grounded** — Traceable back to source episodes

## Topics

Concepts can belong to a **topic** — a knowledge area like `"architecture"` or `"product"`. Topics scope retrieval (queries can be filtered to a specific topic).

Concepts without a topic are treated as general knowledge accessible from any topic context.

## Managing concepts

```bash
# View a concept
remind snapshot concept:<id>

# Create a concept (via apply)
remind apply << 'EOF'
concept from=ep:11,ep:12 title="New pattern" "Description of the pattern"
EOF

# Update a concept's summary
remind update-concept <id> -s "Refined understanding"

# Update confidence
remind update-concept <id> --confidence 0.9

# Reassign or clear topic
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
