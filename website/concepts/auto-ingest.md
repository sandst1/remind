# Auto-Ingest

Auto-ingest is Remind's automatic memory curation pipeline. Instead of requiring the agent to decide what's worth remembering (which competes for attention with the actual task), auto-ingest handles input selection as a separate, cheaper subsystem.

## How it works

The pipeline has three stages:

### 1. Buffer

Raw text accumulates in an in-memory buffer via `ingest()`. When the buffer exceeds a character threshold (default ~4000 chars), it flushes and triggers triage.

### 2. Triage and extraction

The flushed chunk is sent to an LLM that decides what's worth remembering. The LLM extracts any memory-worthy information as tight, standalone episode statements -- and returns nothing if the chunk is pure filler. A density score (0.0-1.0) is also produced for diagnostics/logging, but it doesn't gate extraction. The LLM is the sole decision-maker.

Topics are explicit and optional. When `ingest()` is called with a `topic` argument, all extracted episodes from that operation are stamped with that topic. When no topic is specified, episodes get `topic_id=None` (there is no default or inferred topic).

Large chunks are split into sub-chunks and triaged concurrently (bounded by `llm_concurrency`).

Extracted episodes go through `remember()` and then **immediately consolidate**, bypassing the normal auto-consolidation threshold.

## `ingest()` vs `remember()`

| | `remember()` | `ingest()` |
|---|---|---|
| **Input** | Curated, standalone statement | Raw conversation text |
| **LLM calls** | None (fast) | Yes (triage: extract episodes; optional diagnostic density score) |
| **Filtering** | None — everything is stored | LLM-based — only memory-worthy content is extracted |
| **Consolidation** | Normal threshold-based | Immediate (`force=True`) |
| **Use when** | You know what's worth storing | You want Remind to decide |

Both paths are additive. Using `ingest()` doesn't affect existing `remember()` calls.

## Usage

### From an MCP-connected agent

Auto-ingest is available via MCP tools, CLI, and the Python API. The agent streams conversation fragments or tool output into `ingest()`, and Remind handles the rest.

A good place to call `ingest()` is from deterministic hooks -- after each tool call returns, at the end of each turn, or on a timer. This way the agent doesn't have to "decide" when to ingest; it just always does, and the LLM handles the filtering. The buffer threshold is configurable (default 4000 chars), so no LLM calls happen until enough text has accumulated:

```text
# During the conversation, the agent periodically sends chunks (no topic → topic_id=None)
ingest(content="User: Can you fix the auth bug?\nAssistant: Looking at verify_credentials...")
ingest(content="...I see the issue. The token expiry check uses <= instead of <, so tokens are accepted one second past expiry. Fixing now...")
ingest(content="Assistant: Fixed. Changed the comparison operator in verify_credentials from <= to <. All auth tests pass now.")

# With an explicit topic -- all episodes go to "architecture"
ingest(content="Decided to use Redis for session caching", topic="architecture")

# With instructions -- steer what gets extracted
ingest(content="<meeting transcript>", instructions="extract decisions and action items only")

# At session end
flush_ingest()
```

Remind buffers the text internally. When the buffer threshold is reached (default 4000 chars, configurable via `ingest_buffer_size`), the triage LLM extracts distilled episodes like:

> "Auth bug in verify_credentials: token expiry check used `<=` instead of `<`, accepting tokens one second past expiry"

Low-value text (greetings, acknowledgments, routine narration) is dropped automatically.

### From the CLI

Pipe conversation logs or transcripts directly:

```bash
# Pipe a file
cat conversation-log.txt | remind ingest --source transcript

# Pass as argument (episodes get topic_id=None unless --topic is set)
remind ingest "User prefers dark mode and Vim keybindings in all editors"

# With an explicit topic
remind ingest "Rate limiting at gateway level" --topic architecture

# With instructions to steer extraction
cat meeting.txt | remind ingest -i "extract decisions and action items"

# Force-process whatever is in the buffer
remind flush-ingest
```

### From Python

```python
from remind.interface import create_memory

memory = create_memory(db_path="my-project")

# Stream text in -- omit topic so episodes get topic_id=None
await memory.ingest("User: How should we handle rate limiting?")
await memory.ingest("Assistant: I'd suggest a token bucket at the gateway...")

# With explicit topic -- all episodes go to "architecture"
await memory.ingest("Chose Redis for caching", topic="architecture")

# With instructions -- steer what the triage LLM extracts
await memory.ingest(transcript, instructions="extract all config values and version numbers")

# At session end, flush remaining buffer
await memory.flush_ingest()
```

### Practical workflow for an AI agent

The recommended pattern for an agent using auto-ingest:

1. **Session start** — `recall()` to load context as usual
2. **During work** — use `ingest()` to stream raw conversation/tool output. Use `remember()` for things you *know* are important (decisions, corrections, preferences).
3. **Session end** — call `flush_ingest()` (or `end-session` in CLI, which does this automatically)

You don't have to choose one or the other. `ingest()` and `remember()` are complementary -- `remember()` is the explicit "I know this matters" path, `ingest()` is the "let Remind decide" path.

## Outcome detection

Auto-ingest automatically detects action-result pairs in raw conversation data and extracts them as `outcome` episodes with structured metadata:

- **strategy** — what approach was used
- **result** — `success`, `failure`, or `partial`
- **prediction_error** — `low`, `medium`, or `high`

Over time, consolidation produces causal concepts from outcomes — e.g., "grep-based search is unreliable when function names don't match the domain term" — which spreading activation surfaces when the agent faces similar situations.

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `ingest_buffer_size` | `4000` | Character threshold for buffer flush |
| `<provider>.ingest_model` | `null` | Optional cheaper/faster model for triage (e.g., `anthropic.ingest_model`, `openai.ingest_model`) |

See [Configuration](../guide/configuration.md#auto-ingest) for details.
