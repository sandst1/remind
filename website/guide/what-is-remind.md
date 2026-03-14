# What is Remind?

Remind is a generalization-capable memory layer for LLMs. Unlike simple RAG systems that store verbatim text and retrieve it with vector search, Remind extracts and maintains *generalized concepts* from experiences — mimicking how human memory consolidates specific events into abstract knowledge.

## The problem with current AI memory

Most approaches to giving AI persistent memory are some variation of "store text, search text":

- **RAG**: Embed documents, retrieve similar chunks
- **Conversation buffers**: Keep recent messages around
- **Vector stores**: Log everything, search by similarity

These approaches store:

> "User mentioned they like Python on Tuesday"
> "User mentioned they like Rust on Thursday"
> "User mentioned they like TypeScript last week"

Remind derives:

> "User is a polyglot programmer drawn to languages with strong type systems and systems-level capabilities" (confidence: 0.85, 3 supporting episodes)

That's the difference between *storage* and *understanding*.

## How Remind thinks

Remind is modeled after how human memory actually works:

1. **Episodic buffer** — Raw experiences are logged as episodes, just like how your brain encodes specific events throughout the day. This is fast — no LLM calls, just storage.

2. **Consolidation ("sleep")** — Periodically, the LLM reviews accumulated episodes, finds patterns, extracts entities, and creates generalized concepts. This is analogous to what your brain does during sleep — replaying and compressing episodic memories into semantic knowledge.

3. **Semantic concept graph** — Concepts are connected by typed relations (implies, contradicts, specializes, etc.) with confidence scores, conditions, and exceptions. This is structured knowledge, not a bag of vectors.

4. **Spreading activation retrieval** — When you query, matching concepts activate related concepts through the graph, with activation decaying over hops. Like how thinking about "cooking" might activate "that restaurant" which activates "who you were with."

5. **Memory decay** — Concepts that are rarely recalled gradually lose retrieval priority. Concepts that are frequently accessed get reinforced. Just like human memory.

## Two ways to use Remind

Remind offers two integration paths with different database models:

### Skills + CLI (project-local)

Your agent calls the `remind` CLI from skills — markdown files with instructions. The database lives in your project repo at `.remind/remind.db`. Each project has its own isolated memory.

This is the most powerful and flexible path. Skills are composable: the built-in plan/spec/implement workflow is just one example. You can write your own skills for any workflow — code review, onboarding, research, journaling, whatever.

[Learn more about Skills →](/guide/skills)

### MCP Server (centralized)

Remind runs as an MCP server. Agents connect to it over HTTP. The database is centralized at `~/.remind/`. Good for cross-project memory and shared knowledge bases.

[Learn more about MCP →](/guide/mcp)

Both paths use the same underlying Remind system — same consolidation, same retrieval, same concepts. The difference is where the data lives and how the agent talks to Remind.

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
