# Consolidation

Consolidation is Remind's "sleep" process — the mechanism that transforms raw episodes into generalized concepts. This is where the LLM does its work, and it's what separates Remind from a simple vector store.

## The brain analogy

During human sleep, the hippocampus replays episodic memories and transfers patterns to the neocortex, compressing specific events into abstract knowledge. You don't remember every meal you've ever had — you have a generalized understanding of "restaurants I like" and "foods I prefer."

Remind does the same thing. Raw episodes are replayed through an LLM, which identifies patterns, extracts entities, creates generalized concepts, and establishes relations.

## Two phases

### Phase 1: Extraction

Episodes are grouped into batches (default 5 per batch) and sent to the LLM in a single call per batch, rather than one call per episode. For each episode in a batch:
- **Type classification** — Is this an observation, decision, question, meta, preference, outcome, or fact?
- **Entity extraction** — What files, people, tools, and concepts are mentioned?
- **Relationship extraction** — When multiple entities appear in the same episode, their relationships are inferred (e.g., "Alice manages Bob" → `person:alice → manages → person:bob`)

### Phase 2: Generalization

Episodes are grouped by **topic** and each group is consolidated independently. This prevents cross-domain noise (e.g., product discussions polluting architecture concepts).

Within each topic group:
- **Pattern identification** — What recurs across episodes?
- **Concept creation** — New generalized concepts with confidence scores, inheriting the topic from their source episodes
- **Concept update** — Existing concepts are strengthened, refined, or given exceptions
- **Relation establishment** — Typed edges between concepts (implies, contradicts, specializes, supersedes, etc.)
- **Contradiction detection** — Flagging when new episodes conflict with existing knowledge
- **Supersession detection** — When a concept is replaced by a newer understanding, a `supersedes` relation is created (distinct from `contradicts` — supersession is temporal replacement, contradiction is simultaneous tension)
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

Consolidation prioritizes specificity and falsifiability — concepts should be concrete enough to be validated against reality. For `fact` episodes, consolidation preserves details verbatim in concept summaries rather than abstracting them away.

## Performance tuning

Consolidation performance can be tuned with four settings:

| Option | Default | Description |
|--------|---------|-------------|
| `extraction_batch_size` | `50` | Number of episodes fetched per extraction loop pass. This is independent from `consolidation_batch_size`. |
| `extraction_llm_batch_size` | `10` | Number of episodes grouped into each extraction LLM call. Higher values mean fewer LLM calls but larger prompts and slower individual calls. |
| `consolidation_batch_size` | `25` | Number of episodes fetched and generalized per consolidation pass. Controls how much episode context each consolidation batch sees. |
| `llm_concurrency` | `3` | Maximum concurrent LLM calls within a consolidation run. This shared cap applies to extraction sub-batches, topic-group work, and concept-chunk sub-passes. |

With the defaults, 30 episodes split across 3 topics can process up to 3 LLM calls in parallel. Increase `llm_concurrency` to parallelize more aggressively.

Legacy aliases remain supported: `entity_extraction_batch_size` and `consolidation_llm_concurrency`.

Only LLM calls are parallelized — all store writes (entity deduplication, concept creation, relation storage) remain sequential to avoid conflicts.

## Immediate consolidation from auto-ingest

Episodes created via `ingest()` are immediately consolidated with `force=True`, bypassing the normal episode threshold. The triage step already filtered for quality, so there's no reason to wait. This does not affect `remember()`-created episodes, which still follow normal threshold-based consolidation.
