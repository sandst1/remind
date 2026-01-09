# Release Notes

## v0.2.0 (2026-01-09)

### Web UI
- Complete Svelte-based single-page application with dashboard, concept browser, entity explorer, and episode timeline
- Interactive concept graph visualization with D3.js
- Database selector for managing multiple memory stores
- Dark mode support

### Consolidation
- Batch consolidation for processing multiple episodes at once
- Reconsolidation support to update existing concepts with new episodes

### Retrieval Enhancements
- LLM-powered query answering for more contextual recall results
- Entity relationship inference automatically detects connections between entities
- Source episode tracking returns the episodes that generated each concept
- Concept titles for improved readability

### MCP & API
- REST API (`/api/v1/*`) powering the web UI
- Entity inspection MCP tool for viewing entity details

### Infrastructure
- Docker support with Dockerfile and docker-compose.yml

### UI/UX
- Episode title display
- Filtering for concepts and entities
- Related concepts and episodes shown for entities
- Alphabetical ordering in concept list
