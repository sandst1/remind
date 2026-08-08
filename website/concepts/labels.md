# Labels

Labels are freeform `key=value` tags on episodes and concepts. They replace the old rigid "topic" concept with a general-purpose primitive: there's no label registry to manage, no CRUD, no default label to fall back to — you just apply the key/value pairs that make sense for your use case, and a subject can carry more than one value per key.

```python
memory.remember("Use event sourcing for audit trail", labels={"topic": "architecture"})
memory.remember("Retry-with-backoff fixed flaky deploys", labels={"topic": ["infra", "reliability"]})
```

## Why labels instead of topics

Remind is a building block, not an opinionated app. A single, hardcoded grouping dimension (`topic_id`) forces every consumer into one taxonomy. Labels let you encode whatever dimensions matter to you — `topic`, `env`, `team`, `priority`, `customer` — and combine them:

```bash
remind remember "Staging DB uses smaller instance" -t fact -l env=staging -l topic=infra
```

Nothing stops you from using the key `topic` to reconstruct the old behavior; labels are a superset, not a replacement requiring migration of intent — only of storage.

## Labels are a pre-filter, not a post-filter

The old topic filter narrowed results *after* vector search already ran, which could silently under-return matches that existed but didn't make the top-k before filtering. Labels are pushed down into the query itself:

- **Brute-force backend** — rows are filtered before scoring.
- **pgvector** — an `EXISTS` subquery against the `labels` table runs inside the same `ORDER BY embedding_vec <=> :query` statement, so the database only ranks eligible rows.
- **sqlite-vec** — the matching subject ID set is resolved first; for small sets the `vec0` `MATCH` is constrained directly, otherwise `k` escalates (k → 4k → 16k) until enough post-filter survivors are found.

This makes label-scoped recall exact rather than approximate, regardless of backend.

## Applying and removing labels

::: code-group

```bash [CLI]
remind remember "Use event sourcing" -t decision -l topic=architecture
remind recall "database design" -l topic=architecture
remind update-concept <id> -l topic=architecture
remind update-episode <id> --clear-labels
```

```bash [apply]
remind apply << 'EOF'
label id=c-123 key=topic value=architecture
unlabel id=c-123 key=topic value=infra
EOF
```

```python [Python]
memory.remember("Use event sourcing", labels={"topic": "architecture"})
memory.recall("database design", labels={"topic": "architecture"})
memory.add_label("concept", "c-123", "topic", "architecture")
memory.remove_label("concept", "c-123", "topic", "infra")
```

:::

## Discovering labels in use

```bash
remind snapshot labels                    # every distinct key=value pair, with counts
remind snapshot label:topic=architecture  # everything tagged with that pair
```

The REST API exposes the same data at `GET /api/v1/labels`, optionally filtered by `subject_type`.

## Migrating from topics

Existing databases created before labels were introduced are migrated automatically the first time they're opened: each `topics` row and every `topic_id` on episodes/concepts is backfilled into a `topic=<name>` label, then the legacy `topics` table and `topic_id` columns are dropped. This runs once, guarded by a metadata flag, and requires no manual steps.
