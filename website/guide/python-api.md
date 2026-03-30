# Python API

Use Remind as a library in your own Python applications.

## Basic usage

```python
import asyncio
from dotenv import load_dotenv
from remind import create_memory, EpisodeType

load_dotenv()

async def main():
    memory = create_memory(
        llm_provider="openai",          # or "anthropic", "azure_openai", "ollama"
        embedding_provider="openai",    # or "azure_openai", "ollama"
    )

    # Log experiences — fast, no LLM calls
    memory.remember("User mentioned they prefer Python for backend work")
    memory.remember("User is building a distributed system")
    memory.remember("User values type safety")

    # Typed episodes
    memory.remember("API must return JSON", episode_type=EpisodeType.SPEC)
    memory.remember("Build auth first, then billing", episode_type=EpisodeType.PLAN)

    # Topic-scoped episodes
    memory.remember("Use event sourcing for audit trail", topic="architecture")
    memory.remember("Users want offline mode", topic="product", source_type="slack")

    # Run consolidation — this is where the LLM does its work
    result = await memory.consolidate(force=True)
    print(f"Created {result.concepts_created} concepts")

    # Retrieve relevant concepts
    context = await memory.recall("What programming preferences?")
    print(context)

    # Topic-scoped retrieval
    context = await memory.recall("database design", topic="architecture")

    # Explore topics
    topics = memory.list_topics()
    overview = await memory.get_topic_overview("architecture")

asyncio.run(main())
```

## Auto-ingest

Stream raw text and let Remind decide what's worth remembering:

```python
# Stream conversation fragments — buffer accumulates internally
await memory.ingest("User: How should we handle rate limiting?")
await memory.ingest("Assistant: I'd suggest a token bucket at the gateway...")

# At session end, flush remaining buffer
await memory.flush_ingest()
```

`ingest()` buffers text until a threshold (~4000 chars) is reached, then scores information density and extracts episodes automatically. Use `remember()` when you already know what's important; use `ingest()` when you want Remind to decide.

## Fact and outcome episodes

```python
# Facts: concrete values preserved verbatim through consolidation
memory.remember("Redis TTL is 300s for auth tokens", episode_type=EpisodeType.FACT)

# Outcomes: action-result pairs for causal pattern learning
memory.remember(
    "Grep search for 'auth' missed verify_credentials",
    episode_type=EpisodeType.OUTCOME,
    metadata={"strategy": "grep search", "result": "partial", "prediction_error": "high"},
)
```

## Key design decisions

- **`remember()` is synchronous and fast** — No LLM calls, just stores the episode. This keeps the write path non-blocking.
- **`ingest()` is async with LLM triage** — Buffers raw text, scores density, extracts episodes, and consolidates automatically.
- **`consolidate()` is async** — This is where all LLM work happens (extraction, generalization). Call it explicitly or let auto-consolidation handle it.
- **`recall()` is async** — Uses embeddings and spreading activation.

## Task management

```python
# Create a task
task_id = memory.remember(
    "Implement JWT auth",
    episode_type=EpisodeType.TASK,
    metadata={"status": "todo", "priority": "p0"},
    entities=["module:auth"],
)

# Update status
memory.update_task_status(task_id, "in_progress")
memory.update_task_status(task_id, "done")

# Query tasks
active_tasks = memory.get_tasks(status="in_progress")
specs = memory.get_episodes_by_type(EpisodeType.SPEC)
```

## Database path

```python
# Default: ~/.remind/memory.db
memory = create_memory()

# Named database: ~/.remind/my-project.db
memory = create_memory(db_path="my-project")
```

## Provider selection

Providers can be set via `create_memory()`, config file, or environment variables:

```python
# Explicit
memory = create_memory(llm_provider="anthropic", embedding_provider="openai")

# From config file / env vars
memory = create_memory()  # Uses ~/.remind/remind.config.json or env vars
```

See [Configuration](/guide/configuration) and [Providers](/reference/providers) for all options.
