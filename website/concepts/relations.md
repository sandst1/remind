# Relations

Relations are typed, directional edges between concepts in Remind's knowledge graph. They're what make retrieval smarter than keyword search — when you query for one concept, related concepts activate through the graph.

## Relation types

| Type | Meaning | Example |
|------|---------|---------|
| `implies` | If A then likely B | "Prefers typed languages" → implies → "Values compile-time safety" |
| `contradicts` | A and B are in tension | "Prefers simplicity" → contradicts → "Wants maximum configurability" |
| `specializes` | A is a more specific version of B | "Uses PostgreSQL for user store" → specializes → "Prefers SQL databases" |
| `generalizes` | A is more general than B | "Prefers SQL databases" → generalizes → "Uses PostgreSQL for user store" |
| `causes` | A leads to B | "Chose microservices" → causes → "Needs service discovery" |
| `correlates` | A and B tend to co-occur | "Uses TypeScript" → correlates → "Uses React" |
| `part_of` | A is a component of B | "JWT middleware" → part_of → "Auth system architecture" |
| `context_of` | A provides context for B | "Team is 3 engineers" → context_of → "Architecture decisions" |

## How relations are created

Relations emerge during [consolidation](/concepts/consolidation). The LLM analyzes episodes and existing concepts to identify connections:

- **Cross-episode patterns** — If episodes about caching and performance always appear together, a `correlates` relation might be created.
- **Contradiction detection** — If a new episode contradicts an existing concept, a `contradicts` relation is established.
- **Hierarchical structure** — The LLM identifies when one concept is a specialization or generalization of another.

## Relations and retrieval

Relations are the backbone of [spreading activation retrieval](/concepts/retrieval). When a concept is activated by a query, its relations propagate activation to connected concepts with strength-based decay.

Each relation has a `strength` field (0.0–1.0) that controls how much activation propagates. Strong relations (0.8+) spread activation aggressively; weak ones (0.2) barely ripple.

## Viewing relations

```bash
# See a concept's relations
remind inspect <concept-id>

# See entity relationships
remind entity-relations <entity-id>
```

In the Web UI, the **Graph** view shows relations as edges in an interactive D3 visualization.
