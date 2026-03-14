# REST API

The MCP server exposes a REST API under `/api/v1/`. Used by the Web UI and available for custom integrations.

Base URL: `http://localhost:8765/api/v1`

All endpoints accept a `db` query parameter to select the database.

## Stats

**`GET /stats`** — Memory statistics.

```bash
curl http://localhost:8765/api/v1/stats?db=my-project
```

## Concepts

**`GET /concepts`** — Paginated concept list. Params: `page`, `limit`.

**`GET /concepts/{id}`** — Concept detail with source episodes.

**`POST /concepts/{id}`** — Update a concept.

**`DELETE /concepts/{id}`** — Soft delete a concept.

**`POST /concepts/{id}/restore`** — Restore a deleted concept.

**`GET /concepts/deleted`** — List soft-deleted concepts.

## Episodes

**`GET /episodes`** — Paginated episodes. Params: `page`, `limit`, `type`.

**`GET /episodes/{id}`** — Episode detail.

**`POST /episodes/{id}`** — Update an episode.

**`DELETE /episodes/{id}`** — Soft delete an episode.

**`POST /episodes/{id}/restore`** — Restore a deleted episode.

**`GET /episodes/deleted`** — List soft-deleted episodes.

## Entities

**`GET /entities`** — All entities with mention counts.

**`GET /entities/{id}`** — Entity detail.

**`GET /entities/{id}/episodes`** — Episodes mentioning this entity.

**`GET /entities/{id}/concepts`** — Concepts derived from this entity's episodes.

## Graph

**`GET /graph`** — Full concept graph for D3 visualization.

**`GET /graph/entities`** — Entity relationship graph.

## Query and Chat

**`POST /query`** — Execute a recall query.

```bash
curl -X POST http://localhost:8765/api/v1/query?db=my-project \
  -H "Content-Type: application/json" \
  -d '{"query": "authentication approach"}'
```

**`POST /chat`** — Streaming chat with memory context (Server-Sent Events).

```bash
curl -X POST http://localhost:8765/api/v1/chat?db=my-project \
  -H "Content-Type: application/json" \
  -d '{"query": "What do we know about auth?"}'
```

## Tasks

**`GET /tasks`** — List tasks. Params: `status`, `entity`.

**`POST /tasks`** — Add a new task.

**`POST /tasks/{id}/status`** — Update task status.

## Specs and Plans

**`GET /specs`** — List spec episodes.

**`GET /plans`** — List plan episodes.

## Databases

**`GET /databases`** — List available databases in `~/.remind/`.

## Bulk Operations

**`POST /purge`** — Permanently delete all soft-deleted items.
