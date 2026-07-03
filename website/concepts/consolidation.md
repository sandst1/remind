# Memory Curation

Memory curation is how agents organize raw episodes into structured knowledge. Unlike previous versions where an LLM did this automatically, Remind v1.0 puts the agent in control via `snapshot` and `apply`.

## Agent-driven approach

The agent decides:
- What episodes to group into concepts
- How to resolve fact conflicts
- When to supersede outdated information
- What relations exist between concepts

Remind provides the tools; the agent provides the judgment.

## The curation workflow

### 1. Capture experiences

During work, store raw experiences:

```
remember(content="Rate limiting is at gateway level", topic="architecture")
remember(content="Max connections is 100", episode_type="fact", entities="tool:postgres")
```

### 2. Review pending state

Use `snapshot` to see what needs curation:

```
snapshot(scopes="pending,conflicts")
```

Returns:
- `pending` — Unprocessed episodes with their entities
- `conflicts` — Open contradictions awaiting resolution

### 3. Curate with apply

Send a changeset that organizes the knowledge:

```
concept from=ep:11,ep:12 title="Gateway handles rate limits" "All rate limiting at gateway"
resolve id=conflict:3 winner=fact:abc "newer config value"
processed ids=ep:11,ep:12
```

## Fact handling (automatic)

While concepts require agent curation, **fact episodes** are processed automatically:

1. **Store** — Episode is stored and embedded
2. **Cluster** — Assigned to existing fact cluster by entity overlap (Jaccard similarity ≥ 0.5), or a new cluster is created
3. **Detect collisions** — Active facts in the cluster with overlapping entities are flagged
4. **Return result** — Collision info is returned for agent triage

Collisions are NOT auto-resolved. The agent decides via `apply`:

```
# New fact supersedes old
supersede old=fact:abc new=fact:def

# Or: both are valid in different contexts
dismiss id=conflict:7 "staging vs prod"

# Or: genuine contradiction
conflict fact_a=abc fact_b=def severity=high
```

## What curation produces

Given these episodes:

```
"User mentioned they like Python on Tuesday"
"User mentioned they like Rust on Thursday"  
"User mentioned they like TypeScript last week"
"User values type safety in all their projects"
```

The agent might create:

```
concept from=ep:1,ep:2,ep:3,ep:4 title="Language preferences" "User is a polyglot programmer drawn to statically typed languages"
link source=$c1 type=implies target=concept:compiled-languages
processed ids=ep:1,ep:2,ep:3,ep:4
```

The difference from automatic consolidation: the agent has full context of what these episodes mean in the current project, and can make informed decisions about how to organize them.

## Pending vs processed

Episodes have a `consolidated` flag (semantically: "processed"):

- **Pending** — Not yet reviewed by the agent
- **Processed** — Agent has reviewed and either created a concept or marked as `processed`

Use `snapshot(scopes="pending")` to see what needs attention.

Use `processed ids=ep:1,ep:2` to mark episodes as reviewed without creating a concept.

## Fact clusters

Fact episodes are automatically grouped into fact_cluster concepts:

- **Cluster title** — Generated from shared entities
- **Active facts** — Facts with open validity windows
- **Superseded facts** — Facts that have been replaced (closed validity window, links to replacement)

Use `snapshot(scopes="concept:cluster_id")` to see full cluster detail including supersession history.

## Time-travel

Fact clusters support time-travel queries:

```
recall(query="cache config", as_of="2024-06-01")
```

This shows what facts were valid at that point in time, not the current values. Useful for debugging "what did we believe then".
