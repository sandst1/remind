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

    # Run consolidation — this is where the LLM does its work
    result = await memory.consolidate(force=True)
    print(f"Created {result.concepts_created} concepts")

    # Retrieve relevant concepts
    context = await memory.recall("What programming preferences?")
    print(context)

asyncio.run(main())
```

## Key design decisions

- **`remember()` is synchronous and fast** — No LLM calls, just stores the episode. This keeps the write path non-blocking.
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
