# REST API

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

Scopes: `pending`, `conflicts`, `entity:<id>`, `topic:<id>`, `concept:<id>`, `recent:<n>`, `stats`, `query:<text>`.

## Apply

**`POST /apply`** — Transactional batch write.

```bash
curl -X POST http://localhost:8765/api/v1/apply?db=my-project \
  -H "Content-Type: application/json" \
  -d '{"changeset": "remember t=fact e=tool:redis \"Cache TTL is 600s\""}'
```

See [MCP Tools — apply](/reference/mcp-tools#apply) for the full op vocabulary.

## Concepts

**`GET /concepts`** — Paginated concept list. Params: `page`, `limit`.

**`GET /concepts/{id}`** — Concept detail with source episodes. For fact clusters, includes a `facts` array (active facts plus superseded history).

**`GET /concepts/deleted`** — List soft-deleted concepts.

## Episodes

**`GET /episodes`** — Paginated episodes. Params: `page`, `limit`, `type`.

**`GET /episodes/{id}`** — Episode detail.

**`GET /episodes/deleted`** — List soft-deleted episodes.

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
  -d '{"query": "authentication approach"}'
```

## Databases

**`GET /databases`** — List available databases in `~/.remind/`.
