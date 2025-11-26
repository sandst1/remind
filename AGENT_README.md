# RealMem - Instructions for AI Agents

This document explains how AI agents and LLMs should use RealMem as an external memory system.

## What is RealMem?

RealMem is your external memory layer. Unlike your context window (which resets each conversation), RealMem persists knowledge across sessions and **generalizes** from specific experiences into abstract concepts.

Think of it as:
- **Episodic memory**: Raw experiences you log with `remember()`
- **Semantic memory**: Generalized concepts extracted via `consolidate()`
- **Associative retrieval**: Related concepts activate together via `recall()`

## Core Operations

### 1. Remember - Log Experiences

When something important happens in a conversation, log it:

```python
await memory.remember("User prefers functional programming over OOP")
await memory.remember("User is working on a real-time data pipeline")
await memory.remember("User expressed frustration with Python's GIL")
```

**When to remember:**
- User preferences, opinions, or values
- Technical context about their project/work
- Corrections or clarifications they make
- Patterns in how they communicate or think
- Important decisions or constraints they mention

**What NOT to remember:**
- Trivial, one-off information
- Things already captured in existing concepts
- Raw conversation logs (summarize first)

### 2. Consolidate - Generalize Knowledge

Consolidation extracts generalized concepts from raw episodes. Think of it as "sleeping" - processing experiences into knowledge.

**Two modes of operation:**

#### Automatic (Threshold-based) - Default
```python
memory = create_memory(
    auto_consolidate=True,       # Default: enabled
    consolidation_threshold=10,  # After 10 episodes
)

# Just remember things - consolidation happens automatically
await memory.remember("...")  # After 10th episode, auto-consolidates
```

#### Manual/Hook-based
```python
memory = create_memory(auto_consolidate=False)

# Use hooks at natural boundaries
await memory.end_session()  # Call at end of conversation/task

# Or check and consolidate manually
if memory.should_consolidate:
    await memory.consolidate()

# Or force consolidation anytime
await memory.consolidate(force=True)
```

#### Hybrid (Recommended)
```python
memory = create_memory(
    auto_consolidate=True,      # Safety net
    consolidation_threshold=10,
)

# Auto-consolidation handles long sessions
# But also call end_session() at natural boundaries
await memory.end_session()  # At end of conversation
```

### When to Trigger Consolidation

| Trigger | Method | Use Case |
|---------|--------|----------|
| **Automatic** | Threshold reached | Fire-and-forget, general use |
| **End of conversation** | `end_session()` | Conversational agents |
| **Task completion** | `end_session()` | Task-based agents |
| **Scheduled job** | `consolidate(force=True)` | Background maintenance |
| **Manual command** | `consolidate()` | Development, testing |
| **Context manager exit** | Automatic | `async with memory:` usage |

### Useful Properties

```python
# Check if consolidation would be useful
if memory.should_consolidate:
    await memory.consolidate()

# See how many episodes are pending
count = memory.pending_episodes_count

# Preview what will be consolidated
episodes = memory.get_pending_episodes()
```

### 3. Recall - Retrieve Relevant Context

Before responding to a user, recall relevant memory:

```python
context = await memory.recall("What do I know about their programming preferences?")
# Returns formatted memory block to include in your prompt
```

**How to use recall:**
```python
# Get relevant memory
memory_context = await memory.recall(user_message)

# Include in your response generation
response = await llm.complete(f"""
{memory_context}

User: {user_message}
""")
```

### 4. Reflect - Meta-cognitive Analysis

Ask questions about your own memory:

```python
reflection = await memory.reflect("What gaps exist in my understanding of this user?")
reflection = await memory.reflect("What are the main themes across all my memories?")
reflection = await memory.reflect("Are there any contradictions in what I know?")
```

## Integration Pattern

Here's the recommended pattern for integrating RealMem into your agent loop:

```python
from realmem import create_memory
from dotenv import load_dotenv

load_dotenv()

memory = create_memory()

async def agent_loop(user_message: str) -> str:
    # 1. Recall relevant context
    context = await memory.recall(user_message)
    
    # 2. Generate response with memory context
    response = await generate_response(context, user_message)
    
    # 3. Decide what to remember from this interaction
    if should_remember(user_message, response):
        await memory.remember(f"User: {summarize(user_message)}")
        await memory.remember(f"Learned: {extract_learnings(response)}")
    
    return response
```

## Concept Structure

Each concept in memory has:

```
[concept_id] (confidence: 0.85)
  Summary: "User prefers statically-typed languages for production code"
  → Applies when: building production systems
  → Exceptions: prototyping, one-off scripts
  → implies: [values_type_safety]
  → contradicts: [prefers_dynamic_typing]
```

Use this structure to understand:
- **Confidence**: How certain (more episodes = higher confidence)
- **Conditions**: When this applies
- **Exceptions**: When it doesn't apply
- **Relations**: How concepts connect

## Relation Types

Understand how concepts relate:

| Relation | Meaning | Example |
|----------|---------|---------|
| `implies` | A suggests B | "likes Rust" implies "values memory safety" |
| `contradicts` | A conflicts with B | "prefers brevity" contradicts "wants verbose docs" |
| `specializes` | A is a specific case of B | "likes Python" specializes "likes scripting languages" |
| `generalizes` | A is broader than B | "likes typed languages" generalizes "likes TypeScript" |
| `causes` | A leads to B | "tight deadline" causes "prefers familiar tools" |
| `part_of` | A is component of B | "API design" part_of "system architecture work" |

## CLI Commands (for manual testing)

```bash
# Log an episode
realmem remember "User mentioned they use Vim"

# Run consolidation manually
realmem consolidate
realmem consolidate --force  # Even with few episodes

# End session (consolidate all pending)
realmem end-session

# Query memory
realmem recall "What editor does the user prefer?"

# Inspect all concepts
realmem inspect

# Inspect specific concept
realmem inspect abc123

# View episodes
realmem inspect --episodes

# Memory statistics (shows consolidation state)
realmem stats

# Reflect on memory
realmem reflect "What do I know about the user's workflow?"

# Export for backup
realmem export backup.json

# Search by keyword
realmem search "programming"
```

## Best Practices

### 1. Be Selective About What to Remember
Don't log everything. Focus on:
- Information that generalizes (preferences, patterns)
- Context you'll need in future sessions
- Corrections to existing knowledge

### 2. Use Natural Language
Write episodes as clear, standalone statements:
```python
# Good
await memory.remember("User prefers tabs over spaces for indentation")

# Bad
await memory.remember("tabs")
```

### 3. Include Context When Recalling
```python
# Better retrieval with context
context = await memory.recall(
    query="programming language choice",
    context="User is starting a new web project"
)
```

### 4. Handle Contradictions
When you notice conflicting information:
```python
await memory.remember("User now prefers spaces over tabs (changed from previous preference)")
await memory.consolidate()  # Consolidation will flag the contradiction
```

### 5. Periodic Reflection
Occasionally reflect on your memory state:
```python
gaps = await memory.reflect("What important aspects of this user might I be missing?")
contradictions = await memory.reflect("Are there any inconsistencies in my knowledge?")
```

## Environment Variables

Ensure these are set (via `.env` file or environment):

```bash
# For cloud providers
ANTHROPIC_API_KEY=sk-ant-...  # If using --llm anthropic
OPENAI_API_KEY=sk-...         # If using --llm openai or --embedding openai

# For local (Ollama) - no keys needed, just have Ollama running
```

## Error Handling

```python
try:
    await memory.remember(content)
except Exception as e:
    # Log but don't crash - memory is enhancement, not critical path
    logger.warning(f"Failed to remember: {e}")

try:
    context = await memory.recall(query)
except Exception as e:
    context = ""  # Gracefully degrade
    logger.warning(f"Failed to recall: {e}")
```

## Performance Considerations

- **Recall is fast**: Embedding lookup + graph traversal is quick
- **Consolidation is slow**: Involves LLM calls, run periodically not on every interaction
- **Database is local**: SQLite file, no network latency for storage operations

## Example: Full Agent Integration

```python
import asyncio
from dotenv import load_dotenv
from realmem import create_memory

load_dotenv()

class MemoryAgent:
    def __init__(self):
        self.memory = create_memory(
            llm_provider="anthropic",
            embedding_provider="openai",
            db_path="agent_memory.db",
            auto_consolidate=True,       # Safety net
            consolidation_threshold=10,  # Auto after 10 episodes
        )
    
    async def respond(self, user_input: str) -> str:
        # Recall relevant context
        context = await self.memory.recall(user_input)
        
        # Your LLM call here with context
        response = await self._generate(context, user_input)
        
        # Remember important information
        if self._is_memorable(user_input):
            await self.memory.remember(f"User said: {user_input}")
        
        return response
    
    async def on_conversation_end(self):
        """Hook: Call this when conversation ends."""
        await self.memory.end_session()
    
    async def on_task_complete(self, task_summary: str):
        """Hook: Call this when a task is completed."""
        await self.memory.remember(f"Completed: {task_summary}")
        await self.memory.end_session()
    
    def _is_memorable(self, text: str) -> bool:
        # Your logic to decide what's worth remembering
        memorable_signals = ["I prefer", "I always", "I never", "I work on", "I'm building"]
        return any(signal.lower() in text.lower() for signal in memorable_signals)
    
    async def _generate(self, context: str, user_input: str) -> str:
        # Your LLM integration here
        pass

# Usage
agent = MemoryAgent()
response = await agent.respond("I prefer using TypeScript for all my projects")

# At end of conversation
await agent.on_conversation_end()
```

## Context Manager Pattern

For automatic cleanup, use the context manager:

```python
async with create_memory() as memory:
    await memory.remember("First experience")
    await memory.remember("Second experience")
    # ... more operations ...
# Automatically calls end_session() on exit
```

