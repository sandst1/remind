# RealMem

Generalization-capable memory layer for LLMs. Unlike simple RAG systems that store verbatim text, RealMem extracts and maintains *generalized concepts* from experiences, mimicking how human memory consolidates specific episodes into abstract knowledge.

## Key Features

- **Episodic Buffer**: Raw experiences/interactions are logged as episodes
- **LLM-Powered Consolidation**: Episodes are processed into generalized concepts (like "sleeping" consolidates memory)
- **Semantic Concept Graph**: Concepts have typed relations (implies, contradicts, specializes, etc.)
- **Spreading Activation Retrieval**: Queries activate not just matching concepts but related ones through the graph
- **Multi-Provider Support**: Works with Anthropic, OpenAI, and Ollama (local)

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    LLM Provider (Abstract)                      │
│              (Claude / OpenAI / Ollama / vLLM)                  │
└─────────────────────┬───────────────────────┬───────────────────┘
                      │                       │
                 read/query              write/update
                      │                       │
                      ▼                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                      MEMORY INTERFACE                           │
│              remember() / recall() / reflect()                  │
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

### Required Environment Variables

| Variable | Required For | Description |
|----------|--------------|-------------|
| `ANTHROPIC_API_KEY` | `--llm anthropic` | Claude API key from [Anthropic Console](https://console.anthropic.com/) |
| `OPENAI_API_KEY` | `--llm openai` or `--embedding openai` | OpenAI API key from [OpenAI Platform](https://platform.openai.com/api-keys) |

### Provider Combinations

| Setup | Command | Requirements |
|-------|---------|--------------|
| **Cloud (recommended)** | `--llm anthropic --embedding openai` | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` |
| **Fully Local** | `--llm ollama --embedding ollama` | [Ollama](https://ollama.ai/) with `llama3.2` and `nomic-embed-text` |
| **Hybrid** | `--llm ollama --embedding openai` | `OPENAI_API_KEY`, Ollama running |
| **OpenAI Only** | `--llm openai --embedding openai` | `OPENAI_API_KEY` |

### Using Ollama (Local Models)

```bash
# Install Ollama from https://ollama.ai/
# Then pull the required models:
ollama pull llama3.2           # For LLM operations
ollama pull nomic-embed-text   # For embeddings

# Use with RealMem:
realmem --llm ollama --embedding ollama remember "Some experience"
```

## Quick Start

### Python API

```python
import asyncio
from dotenv import load_dotenv
from realmem import create_memory

load_dotenv()  # Load .env file

async def main():
    # Create memory with default providers (openai for both LLM and embeddings)
    memory = create_memory(
        llm_provider="openai",          # or "anthropic", "ollama"
        embedding_provider="openai",    # or "ollama"
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
    
    # Let the LLM reflect on its memory
    reflection = await memory.reflect("What do I know about this user?")
    print(reflection)

asyncio.run(main())
```

### CLI

```bash
# Add episodes
realmem remember "User likes Python and Rust"
realmem remember "User works on backend systems"

# Run consolidation
realmem consolidate

# Query memory
realmem recall "What languages does the user know?"

# Inspect concepts
realmem inspect
realmem inspect <concept-id>

# Show statistics
realmem stats

# Export/Import
realmem export memory-backup.json
realmem import memory-backup.json

# Reflect
realmem reflect "What are the key themes in my memory?"

# Use different providers
realmem --llm ollama --embedding ollama remember "Local-only experience"
```

### MCP Server (for AI Agents)

RealMem can run as an MCP (Model Context Protocol) server, allowing AI agents in IDEs like Cursor to use it as their memory system.

```bash
# Start the MCP server
realmem-mcp --port 8765

# With custom providers
realmem-mcp --port 8765 --llm anthropic --embedding openai
```

Configure your MCP client (e.g., Cursor's `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "realmem": {
      "url": "http://127.0.0.1:8765/sse?db=my-project"
    }
  }
}
```

#### Database Path Resolution

The `db` parameter supports multiple formats:

| Format | Resolves To | Example |
|--------|-------------|---------|
| Simple name | `~/.realmem/{name}.db` | `my-project` → `~/.realmem/my-project.db` |
| Relative path | Resolved against cwd | `./memory.db` → `/current/dir/memory.db` |
| Absolute path | Used as-is | `/path/to/db.db` → `/path/to/db.db` |
| Home path | Expanded | `~/data/mem.db` → `/home/user/data/mem.db` |

**Recommended**: Use simple names (e.g., `my-project`) for portability. All databases are stored in `~/.realmem/`.

Each project can have its own database. A single MCP server instance (SSE mode) can serve multiple projects with different databases.

**Available MCP Tools:**
- `remember` - Store experiences/observations
- `recall` - Retrieve relevant memories
- `consolidate` - Process episodes into concepts
- `entities` - List/inspect entities
- `decisions` / `questions` - View by episode type
- `inspect` - View concepts or episodes
- `stats` - Memory statistics
- `reflect` - Meta-cognitive analysis

**Agent Instructions**: Copy [docs/AGENTS.md](./docs/AGENTS.md) into your project's documentation to instruct AI agents how to use RealMem as their memory system.

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
from realmem import AnthropicLLM
llm = AnthropicLLM(model="claude-sonnet-4-20250514")
```

### OpenAI
```python
from realmem import OpenAILLM, OpenAIEmbedding
llm = OpenAILLM(model="gpt-4o")
embedding = OpenAIEmbedding(model="text-embedding-3-small")
```

### Ollama (Local)
```python
from realmem import OllamaLLM, OllamaEmbedding
llm = OllamaLLM(model="llama3.2")
embedding = OllamaEmbedding(model="nomic-embed-text")
```

## Database

By default, RealMem uses SQLite for storage (`memory.db`). This is simple and portable.

```python
memory = create_memory(db_path="my-memory.db")
```

## License

MIT
