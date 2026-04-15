# Web UI

Remind includes a web interface for exploring and managing your memory database.

## Quick start

```bash
remind ui
```

This starts the server and opens your browser with the project-local database selected. For a specific port:

```bash
remind ui --port 9000
remind ui --no-open    # Start server without opening browser
```

You can also access the UI when the MCP server is running:

```
http://localhost:8765/ui/?db=my-project
```

## Views

### Dashboard

Overview of memory statistics: episode count, concept count, entity count, consolidation status, and episode type distribution.

### Episodes

Timeline view of raw experiences. Filter by episode type (observation, decision, question, meta, preference, outcome, fact). Inline delete for cleanup.

![Episodes view](/ui-episodes.png)

### Concepts

Browse generalized concepts with confidence scores, instance counts, and relations. Search by keyword. Click a concept to see its full summary, conditions, exceptions, relations, and source episodes.

![Concepts view](/ui-concepts.png)

### Entities

Explore entities (files, people, tools, concepts) and their mention counts. Click through to see related episodes and concepts.

### Graph

Interactive D3 visualization of the entity network. Zoom, pan, and click nodes to see details. Relations are shown as directed edges with typed labels. Nodes are color-coded by entity type.

![Entity graph](/ui-entity-graph.png)

### Memory Status

Memory health dashboard showing decay statistics, consolidation state, and database metrics.

## Features

- **Database selector** — Switch between multiple databases from the sidebar
- **Dark mode** — Toggle between light, dark, and system theme
- **Collapsible sidebar** — More space when you need it
