# Remind

Generalization-capable memory layer for LLMs. Unlike simple RAG systems that store verbatim text, Remind extracts and maintains *generalized concepts* from experiences, mimicking how human memory consolidates specific episodes into abstract knowledge.

## Key Features

- **Episodic Buffer**: Raw experiences/interactions are logged as episodes
- **LLM-Powered Consolidation**: Episodes are processed into generalized concepts (like "sleeping" consolidates memory)
- **Semantic Concept Graph**: Concepts have typed relations (implies, contradicts, specializes, etc.)
- **Spreading Activation Retrieval**: Queries activate not just matching concepts but related ones through the graph
- **Multi-Provider Support**: Works with Anthropic, OpenAI, Azure OpenAI, and Ollama (local)

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

## Quick Run (No Install)

Using [uv](https://docs.astral.sh/uv/), you can run Remind directly without installing:

```bash
# Run CLI commands
uv run remind remember "Some experience"
uv run remind consolidate
uv run remind recall "What do I know?"

# Run MCP server
uv run remind-mcp --port 8765

# With local Ollama (no API keys needed)
uv run remind --llm ollama --embedding ollama remember "Some experience"
```

## Installation

### Global Install (Recommended for CLI usage)

```bash
# Using pipx (creates isolated env, command available globally)
pipx install .

# Or for development:
pipx install -e .
```

### Development Install (in a virtual environment)

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -e .
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

## Quick Start

### Python API

```python
import asyncio
from dotenv import load_dotenv
from remind import create_memory

load_dotenv()  # Load .env file

async def main():
    # Create memory with default providers (openai for both LLM and embeddings)
    memory = create_memory(
        llm_provider="openai",          # or "anthropic", "azure_openai", "ollama"
        embedding_provider="openai",    # or "azure_openai", "ollama"
    )
    
    # Log experiences (episodes) - fast, no LLM calls
    memory.remember("User mentioned they prefer Python for backend work")
    memory.remember("User is building a distributed system")
    memory.remember("User values type safety")
    
    # Run consolidation - this is where LLM work happens:
    # 1. Extracts entities and classifies episode types
    # 2. Generalizes episodes into concepts
    result = await memory.consolidate(force=True)
    print(f"Created {result.concepts_created} concepts")
    
    # Retrieve relevant concepts
    context = await memory.recall("What programming preferences?")
    print(context)

asyncio.run(main())
```

### CLI

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

### MCP Server (for AI Agents)

Remind can run as an MCP (Model Context Protocol) server, allowing AI agents in IDEs like Cursor to use it as their memory system.

```bash
# Start the MCP server
remind-mcp --port 8765

# With custom providers
remind-mcp --port 8765 --llm anthropic --embedding openai
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

#### Database Names

The `db` parameter accepts a simple name which resolves to `~/.remind/{name}.db`:

```
my-project → ~/.remind/my-project.db
```

Each project can have its own database. A single MCP server instance (SSE mode) can serve multiple projects with different databases.

**Available MCP Tools:**
- `remember` - Store experiences/observations
- `recall` - Retrieve relevant memories
- `consolidate` - Process episodes into concepts
- `inspect` - View concepts or episodes
- `stats` - Memory statistics

**Agent Instructions**: Copy [docs/AGENTS.md](./docs/AGENTS.md) into your project's documentation to instruct AI agents how to use Remind as their memory system.

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

**Phase 2 - Generalization:**
- Identifies patterns across episodes
- Creates new generalized concepts
- Updates existing concepts
- Establishes relations
- Flags contradictions

### Spreading Activation
Retrieval that goes beyond keyword matching:
1. Query is embedded and matched to concepts
2. Matched concepts activate related concepts through the graph
3. Activation spreads with decay over multiple hops
4. Highest-activation concepts are returned

## Provider Configuration

### Anthropic (Claude)
```python
from remind import AnthropicLLM
llm = AnthropicLLM(model="claude-sonnet-4-20250514")
```

### OpenAI
```python
from remind import OpenAILLM, OpenAIEmbedding
llm = OpenAILLM(model="gpt-4o")
embedding = OpenAIEmbedding(model="text-embedding-3-small")
```

### Azure OpenAI
```python
from remind import AzureOpenAILLM, AzureOpenAIEmbedding
llm = AzureOpenAILLM()  # Uses AZURE_OPENAI_* env vars
embedding = AzureOpenAIEmbedding()
```

### Ollama (Local)
```python
from remind import OllamaLLM, OllamaEmbedding
llm = OllamaLLM(model="llama3.2")
embedding = OllamaEmbedding(model="nomic-embed-text")
```

## Database

Remind uses SQLite for storage. All databases are stored in `~/.remind/`. By default, the database is `~/.remind/memory.db`.

```python
# Uses ~/.remind/memory.db
memory = create_memory()

# Uses ~/.remind/my-project.db
memory = create_memory(db_path="my-project")
```

## License

MIT
