# Research Ingestion

Feed research papers into Remind and use consolidation to find commonalities, contradictions, and themes across sources. Instead of reading each paper in isolation, Remind builds a connected knowledge graph across all of them.

## The problem

You read 10 papers on a topic. Each one has insights, but finding the threads that connect them — the agreements, the contradictions, the gaps — requires holding all of them in your head simultaneously. That's exactly what consolidation is for.

## Setup

Create a project for the research topic:

```bash
mkdir ~/research/llm-memory
cd ~/research/llm-memory
remind skill-install
```

## Walkthrough

### Ingesting papers

For each paper, have the agent read it and store key findings as episodes:

```bash
# Paper 1: "Generative Agents" (Park et al.)
remind remember "Generative Agents uses a retrieval-based memory with recency, \
  importance, and relevance scoring. Agents reflect on memories to form \
  higher-level abstractions." \
  -t observation -e person:park -e concept:memory-architecture

remind remember "Generative Agents reflection mechanism: periodically ask \
  'what are the most salient high-level questions?' and generate insights" \
  -t observation -e concept:reflection -e concept:generative-agents

# Paper 2: "MemGPT" (Packer et al.)
remind remember "MemGPT treats context window as 'working memory' and uses \
  explicit read/write to a larger 'archival memory'. Inspired by OS virtual \
  memory paging." \
  -t observation -e person:packer -e concept:memory-architecture

remind remember "MemGPT key insight: LLMs can manage their own memory if given \
  tools to page information in and out of context" \
  -t observation -e concept:memgpt -e concept:self-managed-memory

# Paper 3: "Voyager" (Wang et al.)
remind remember "Voyager stores learned skills as code in a 'skill library'. \
  Retrieval is by task description similarity. Skills compose and build on \
  each other." \
  -t observation -e person:wang -e concept:skill-library -e concept:voyager

remind remember "Voyager demonstrates that executable code can serve as a \
  memory representation — more precise than natural language for procedural \
  knowledge" \
  -t observation -e concept:memory-representation -e concept:voyager
```

### Consolidation surfaces themes

```bash
remind consolidate --force
```

After ingesting several papers, consolidation might produce:

> **"Current LLM memory systems share a two-tier architecture: fast working memory (context window) + slower persistent storage, differing mainly in how they manage the boundary"**
> - Confidence: 0.85
> - Source: Generative Agents, MemGPT, Voyager
> - Relations: generalizes → specific observations about each system

> **"There is a spectrum of memory representations from natural language (Generative Agents) to structured code (Voyager), with a tradeoff between expressiveness and precision"**
> - Relations: contradicts → "Natural language is the universal memory format"

> **"All surveyed systems lack true generalization — they store and retrieve specific memories rather than consolidating into abstract knowledge"**
> - Confidence: 0.7
> - Relations: implies → "Gap in the literature for consolidation-based memory"

### Querying across papers

```bash
remind recall "how do different systems handle memory retrieval?"
remind recall "memory representation tradeoffs"
remind recall "limitations" --entity concept:memory-architecture
remind entities  # See all papers, concepts, and their connections
```

## The result

Here's what the entity graph looks like after ingesting several ML papers — concepts, models, techniques, and their relationships, all extracted and linked automatically:

![Entity graph from research paper ingestion](/ui-entity-graph.png)

And the concepts view showing generalized knowledge with confidence, conditions, exceptions, and relations:

![Concepts extracted from papers](/ui-concepts.png)

## What you get

- **Cross-paper synthesis** — Themes and patterns that span multiple sources
- **Contradiction detection** — Where papers disagree, flagged automatically
- **Gap identification** — What the literature doesn't address
- **Entity graph** — Navigate from an author to their contributions, from a concept to all papers that discuss it
- **Persistent knowledge base** — Come back months later and recall the synthesis, not just individual paper notes
