# REST API

## Version 0.14 contract

The default store is Git-friendly JSON under the nearest project root's `.remind/memory/`; embeddings and indexes are disposable ignored caches. Use `--store file:///absolute/path` for another directory. Explicit SQL URLs continue to select SQL backends. See [Storage and migration](/concepts/storage).

Reads return full opaque IDs and revision tokens. Existing-record writes require the inspected revision: `--expected-revision` for individual CLI edits, `--revisions '{"full-id":"revision"}'` for CLI apply, `expected_revision`/`expected_revisions` in MCP and Python, and `If-Match` on individual REST edits. Stale edits fail instead of overwriting newer memory. `snapshot deleted` supplies revisions for restore or bulk purge; bulk purge takes an `expected_revisions` map.

Recall is read-only by default. Explicit label filters constrain candidates, graph traversal, facts, and rendered context. Labels are generic tags; separate stores provide isolation. Structured recall includes `text`, `concepts`, `episodes`, `warnings`, and optional `explanation`. Source freshness warnings annotate changed/missing files without changing the remembered claim.

New workflow tools include `remember_batch`, generation-aware `poll_events`, and `doctor`. CLI equivalents are `remember-batch`, `events --cursor`, and `doctor`. REST exposes `POST /api/v1/workflow/{operation}` for `remember`, `remember_batch`, `recall`, `apply`, `snapshot`, `events`, and `doctor`. Use idempotency keys for capture/apply retries. Portable export includes facts, conflicts, evidence, labels, events, and retry receipts; `--mode backup` also includes derived vectors.


The MCP server exposes a REST API under `/api/v1/`. Used by the Web UI and available for custom integrations.

Base URL: `http://localhost:8765/api/v1`

All endpoints accept a `db` query parameter to select the database.

## Stats

**`GET /stats`** — Memory statistics.

```bash
curl http://localhost:8765/api/v1/stats?db=my-project
```

## Snapshot

**`POST /snapshot`** — Batch read of current memory state.

```bash
curl -X POST http://localhost:8765/api/v1/snapshot?db=my-project \
  -H "Content-Type: application/json" \
  -d '{"scopes": ["pending", "conflicts"]}'
```

Scopes: `pending`, `conflicts`, `entity:<id>`, `labels`, `label:<key>=<value>`, `concept:<id>`, `recent:<n>`, `stats`, `query:<text>`.

## Apply

**`POST /apply`** — Transactional batch write.

```bash
curl -X POST http://localhost:8765/api/v1/apply?db=my-project \
  -H "Content-Type: application/json" \
  -d '{"changeset": "remember t=fact e=tool:redis \"Cache TTL is 600s\""}'
```

See [MCP Tools — apply](/reference/mcp-tools#apply) for the full op vocabulary.

## Concepts

**`GET /concepts`** — Paginated concept list. Params: `page`, `limit`, `label` (repeatable `key:value`, filters to concepts carrying all given labels).

**`GET /concepts/{id}`** — Concept detail with source episodes. For fact clusters, includes a `facts` array (active facts plus superseded history).

**`GET /concepts/deleted`** — List soft-deleted concepts.

## Episodes

**`GET /episodes`** — Paginated episodes. Params: `page`, `limit`, `type`, `label` (repeatable `key:value`, filters to episodes carrying all given labels).

**`GET /episodes/{id}`** — Episode detail.

**`GET /episodes/deleted`** — List soft-deleted episodes.

## Labels

**`GET /labels`** — List distinct `key=value` labels in use, with counts. Params: `subject_type` (`episode` or `concept`, optional).

```bash
curl "http://localhost:8765/api/v1/labels?db=my-project&subject_type=concept"
```

## Entities

**`GET /entities`** — All entities with mention counts.

**`GET /entities/{id}`** — Entity detail.

**`GET /entities/{id}/episodes`** — Episodes mentioning this entity.

**`GET /entities/{id}/concepts`** — Concepts derived from this entity's episodes.

## Conflicts

**`GET /conflicts`** — List conflicts. Params: `status` (`open` default, `resolved`, `dismissed`, `all`), `kind` (`fact`, `concept`).

```bash
curl "http://localhost:8765/api/v1/conflicts?db=my-project&status=open"
```

## Graph

**`GET /graph`** — Full concept graph for D3 visualization.

**`GET /graph/entities`** — Entity relationship graph.

## Query

**`POST /query`** — Execute a recall query.

```bash
curl -X POST http://localhost:8765/api/v1/query?db=my-project \
  -H "Content-Type: application/json" \
  -d '{"query": "authentication approach", "labels": {"topic": "architecture"}}'
```

## Databases

**`GET /databases`** — List available databases in `~/.remind/`.
