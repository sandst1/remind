# Remind

[![PyPI version](https://img.shields.io/pypi/v/remind-mcp.svg)](https://pypi.org/project/remind-mcp/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](LICENSE)

Generalization-capable memory layer for LLMs. Unlike simple RAG systems that store verbatim text, Remind extracts and maintains *generalized concepts* from experiences, mimicking how human memory consolidates specific episodes into abstract knowledge.

## Key Features

- **Episodic Buffer**: Raw experiences/interactions are logged as episodes
- **LLM-Powered Consolidation**: Episodes are processed into generalized concepts (like "sleeping" consolidates memory)
- **Semantic Concept Graph**: Concepts have typed relations (implies, contradicts, specializes, etc.)
- **Spreading Activation Retrieval**: Queries activate not just matching concepts but related ones through the graph
- **Multi-Provider Support**: Works with Anthropic, OpenAI, Azure OpenAI, and Ollama (local)

![Architecture Diagram](docs/architecture.png)


## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    LLM Provider (Abstract)                      │
│         (Claude / OpenAI / Azure OpenAI / Ollama)               │
└─────────────────────┬───────────────────────┬───────────────────┘
                      │                       │
                 read/query              write/update
                      │                       │
                      ▼                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                      MEMORY INTERFACE                           │
│                   remember() / recall()                         │
└─────────────────────┬───────────────────────────────────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
   ┌─────────┐  ┌──────────┐  ┌──────────────┐
   │EPISODIC │  │ SEMANTIC │  │  RELATIONS   │
   │ BUFFER  │  │ CONCEPTS │  │    GRAPH     │
   └─────────┘  └──────────┘  └──────────────┘
        │             │              │
        └──────┬──────┴──────────────┘
               ▼
      ┌─────────────────┐      ┌─────────────────┐
      │  CONSOLIDATION  │◄────►│    RETRIEVER    │
      │   (LLM-based)   │      │ (Spreading Act) │
      └─────────────────┘      └─────────────────┘
```

## Environment Setup

Copy the example environment file and add your API keys:

```bash
cp .env.example .env
# Edit .env with your API keys
```

### Using OpenAI

```bash
# Required
OPENAI_API_KEY=sk-...

# Provider selection
LLM_PROVIDER=openai
EMBEDDING_PROVIDER=openai
```

OpenAI can be used for both LLM and embeddings.

### Using Anthropic (Claude)

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...

# Provider selection
LLM_PROVIDER=anthropic
EMBEDDING_PROVIDER=openai  # Anthropic has no embeddings, use OpenAI or Ollama
```

Anthropic provides LLM only. Pair with OpenAI or Ollama for embeddings.

### Using Azure OpenAI

```bash
# Required
AZURE_OPENAI_API_KEY=...
AZURE_OPENAI_API_BASE_URL=https://your-resource.openai.azure.com
AZURE_OPENAI_API_VERSION=2024-02-15-preview
AZURE_OPENAI_DEPLOYMENT_NAME=gpt-4
AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME=text-embedding-3-small

# Provider selection
LLM_PROVIDER=azure_openai
EMBEDDING_PROVIDER=azure_openai
```

### Using Ollama (Local)

No API keys required. Install [Ollama](https://ollama.ai/) and pull models:

```bash
ollama pull llama3.2           # For LLM
ollama pull nomic-embed-text   # For embeddings
```

Optional configuration:

```bash
OLLAMA_URL=http://localhost:11434
OLLAMA_LLM_MODEL=llama3.2
OLLAMA_EMBEDDING_MODEL=nomic-embed-text

# Provider selection
LLM_PROVIDER=ollama
EMBEDDING_PROVIDER=ollama
```

## Usage

### MCP Server (for AI Agents)

Remind can run as an MCP (Model Context Protocol) server, allowing AI agents in IDEs like Cursor to use it as their memory system.

```bash
# After pip install
remind-mcp --port 8765

# Or with uv (no install needed)
uvx remind-mcp --port 8765
```

Configure your MCP client (e.g., Cursor's `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "remind": {
      "url": "http://127.0.0.1:8765/sse?db=my-project"
    }
  }
}
```

The `db` parameter accepts a simple name which resolves to `~/.remind/{name}.db`. Each project can have its own database.

**Available MCP Tools:**
- `remember` - Store experiences/observations
- `recall` - Retrieve relevant memories
- `consolidate` - Process episodes into concepts (includes entity relationship extraction)
- `inspect` - View concepts or episodes
- `entities` - List entities in memory
- `inspect_entity` - View entity details and relationships
- `stats` - Memory statistics

**Agent Instructions**: Copy [docs/AGENTS.md](./docs/AGENTS.md) into your project's documentation to instruct AI agents how to use Remind as their memory system.

### Web UI

Remind includes a web interface for exploring and managing your memory database.

```bash
# Start the server (includes Web UI)
remind-mcp --port 8765

# Or with Docker
docker compose up -d
```

Access the UI at `http://localhost:8765/ui/?db=my-project`

**Features:**
- **Dashboard** - Overview of memory statistics
- **Concepts** - Browse and search generalized concepts
- **Entities** - Explore entities and their relationships
- **Episodes** - Timeline view of raw experiences
- **Graph** - Interactive visualization of concept relationships
- **Dark mode** - Toggle via UI

You can switch between multiple databases using the database selector in the UI.

### CLI

```bash
# After pip install
remind remember "User likes Python and Rust"
remind consolidate
remind recall "What languages does the user know?"

# Or with uvx (no install needed)
uvx --from remind-mcp remind remember "User likes Python and Rust"
```

Full CLI examples:

```bash
# Add episodes
remind remember "User likes Python and Rust"
remind remember "User works on backend systems"

# Run consolidation
remind consolidate

# Query memory
remind recall "What languages does the user know?"

# Inspect concepts
remind inspect
remind inspect <concept-id>

# Show statistics
remind stats

# Export/Import
remind export memory-backup.json
remind import memory-backup.json

# Entity management
remind entities                  # List all entities
remind entities file:src/auth.ts # Show details for a specific entity
remind mentions file:src/auth.ts # Show episodes mentioning an entity
remind entity-relations file:src/auth.ts # Show relationships for an entity

# Entity relationship extraction (for existing databases)
remind extract-relations         # Extract relationships from unprocessed episodes
remind extract-relations --force # Re-extract for all episodes

# Episode filtering
remind decisions                 # Show decision-type episodes
remind questions                 # Show open questions/uncertainties
remind search "keyword"          # Search concepts by keyword

# Session management
remind end-session               # End session and consolidate pending episodes

# Use different providers
remind --llm openai --embedding openai remember "..."
remind --llm anthropic --embedding openai remember "..."
remind --llm azure_openai --embedding azure_openai remember "..."
remind --llm ollama --embedding ollama remember "..."
```

### Python API

```python
import asyncio
from dotenv import load_dotenv
from remind import create_memory

load_dotenv()  # Load .env file

async def main():
    memory = create_memory(
        llm_provider="openai",          # or "anthropic", "azure_openai", "ollama"
        embedding_provider="openai",    # or "azure_openai", "ollama"
    )

    # Log experiences (episodes) - fast, no LLM calls
    memory.remember("User mentioned they prefer Python for backend work")
    memory.remember("User is building a distributed system")
    memory.remember("User values type safety")

    # Run consolidation - this is where LLM work happens
    result = await memory.consolidate(force=True)
    print(f"Created {result.concepts_created} concepts")

    # Retrieve relevant concepts
    context = await memory.recall("What programming preferences?")
    print(context)

asyncio.run(main())
```

## Core Concepts

### Episodes
Raw experiences - specific interactions or observations. These are temporary and get consolidated.

### Concepts
Generalized knowledge extracted from episodes. Each concept has:
- **Summary**: Natural language description
- **Confidence**: How certain (0.0-1.0)
- **Instance count**: How many episodes support this
- **Relations**: Typed edges to other concepts
- **Conditions**: When this applies
- **Exceptions**: Known cases where it doesn't hold

### Relations
Typed connections between concepts:
- `implies` - If A then likely B
- `contradicts` - A and B are in tension
- `specializes` - A is a more specific version of B
- `generalizes` - A is more general than B
- `causes` - A leads to B
- `correlates` - A and B tend to co-occur
- `part_of` - A is a component of B
- `context_of` - A provides context for B

### Consolidation
The "sleep" process where episodes are processed into concepts. Runs in two phases:

**Phase 1 - Extraction:**
- Classifies episode types (observation, decision, question, etc.)
- Extracts entity mentions (files, people, tools, concepts)
- Identifies relationships between entities mentioned in the same episode

**Phase 2 - Generalization:**
- Identifies patterns across episodes
- Creates new generalized concepts
- Updates existing concepts
- Establishes relations
- Flags contradictions

### Entity Relationships
When multiple entities are mentioned in the same episode, their relationships are automatically extracted. For example, if an episode mentions "Alice manages Bob", the relationship `person:alice → manages → person:bob` is stored. Use `inspect_entity` or the web UI to explore entity relationships.

### Spreading Activation
Retrieval that goes beyond keyword matching:
1. Query is embedded and matched to concepts
2. Matched concepts activate related concepts through the graph
3. Activation spreads with decay over multiple hops
4. Highest-activation concepts are returned

## Database

Remind uses SQLite for storage. All databases are stored in `~/.remind/`. By default, the database is `~/.remind/memory.db`.

```python
# Uses ~/.remind/memory.db
memory = create_memory()

# Uses ~/.remind/my-project.db
memory = create_memory(db_path="my-project")
```

## Installation

```bash
pip install remind-mcp
```

Or with [pipx](https://pipx.pypa.io/) for an isolated install:

```bash
pipx install remind-mcp
```

For development:

```bash
git clone https://github.com/YOUR_USERNAME/remind.git
cd remind
pip install -e ".[dev]"
```

### Using uv (Recommended)

[uv](https://docs.astral.sh/uv/) is a fast Python package manager. For development:

```bash
git clone https://github.com/YOUR_USERNAME/remind.git
cd remind

# Run commands directly (uv handles dependencies automatically)
uv run remind --help
uv run remind-mcp --port 8765

# Run tests
uv run pytest
```

### Using Docker

Run Remind as a persistent background service with Docker:

```bash
# Copy and configure environment
cp .env.example .env
# Edit .env with your API keys

# Start the service (builds on first run)
docker compose up -d

# View logs
docker compose logs -f remind

# Stop the service
docker compose down
```

The container:
- Mounts `~/.remind` from your host for database persistence
- Reads API keys from `.env`
- Exposes port 8765 for MCP SSE, Web UI, and REST API
- Restarts automatically on crash/reboot

Access endpoints:
- MCP SSE: `http://localhost:8765/sse?db=my-project`
- Web UI: `http://localhost:8765/ui/?db=my-project`
- REST API: `http://localhost:8765/api/v1/...`

To rebuild after code changes:

```bash
docker compose build --no-cache
docker compose up -d
```

## Testing

```bash
# With pip install
pytest

# With uv (recommended)
uv run pytest
```

## License

Apache 2.0 ([LICENSE](./LICENSE))

