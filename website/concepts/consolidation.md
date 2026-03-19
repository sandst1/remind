# Consolidation

Consolidation is Remind's "sleep" process — the mechanism that transforms raw episodes into generalized concepts. This is where the LLM does its work, and it's what separates Remind from a simple vector store.

## The brain analogy

During human sleep, the hippocampus replays episodic memories and transfers patterns to the neocortex, compressing specific events into abstract knowledge. You don't remember every meal you've ever had — you have a generalized understanding of "restaurants I like" and "foods I prefer."

Remind does the same thing. Raw episodes are replayed through an LLM, which identifies patterns, extracts entities, creates generalized concepts, and establishes relations.

## Two phases

### Phase 1: Extraction

For each unconsolidated episode:
- **Type classification** — Is this an observation, decision, question, spec, plan, task, outcome, or fact?
- **Entity extraction** — What files, people, tools, and concepts are mentioned?
- **Relationship extraction** — When multiple entities appear in the same episode, their relationships are inferred (e.g., "Alice manages Bob" → `person:alice → manages → person:bob`)

### Phase 2: Generalization

Across all pending episodes:
- **Pattern identification** — What recurs across episodes?
- **Concept creation** — New generalized concepts with confidence scores
- **Concept update** — Existing concepts are strengthened, refined, or given exceptions
- **Relation establishment** — Typed edges between concepts (implies, contradicts, specializes, etc.)
- **Contradiction detection** — Flagging when new episodes conflict with existing knowledge
- **Causal pattern detection** — For outcome-typed episodes, identifying strategy-outcome patterns (e.g., "strategy X tends to fail in context Y") and connecting them with `causes` relations

## Triggering consolidation

### Automatic

When `auto_consolidate` is enabled (default), consolidation runs in the background after `remember` once the episode threshold is reached (default: 5 episodes).

```json
{
  "consolidation_threshold": 5,
  "auto_consolidate": true
}
```

### Manual

```bash
remind consolidate          # Threshold-based
remind consolidate --force  # Force even with few episodes
remind end-session          # Consolidate + session cleanup
```

### Background

The CLI runs consolidation in a background subprocess to keep things fast. Lock files at `~/.remind/.consolidate-{hash}.lock` prevent concurrent runs. Logs go to `~/.remind/logs/consolidation.log`.

## What consolidation produces

Given these episodes:

```
"User mentioned they like Python on Tuesday"
"User mentioned they like Rust on Thursday"  
"User mentioned they like TypeScript last week"
"User values type safety in all their projects"
```

Consolidation might produce:

> **Concept**: "User is a polyglot programmer drawn to statically typed, performance-oriented languages"
> - Confidence: 0.85
> - Instance count: 4
> - Conditions: "Applies to language preferences for new projects"
> - Relations: implies → "User likely prefers compiled languages"
> - Source episodes: [ep_1, ep_2, ep_3, ep_4]

This is understanding, not storage.

## Immediate consolidation from auto-ingest

Episodes created via `ingest()` are immediately consolidated with `force=True`, bypassing the normal episode threshold. The triage step already filtered for quality, so there's no reason to wait. This does not affect `remember()`-created episodes, which still follow normal threshold-based consolidation.
