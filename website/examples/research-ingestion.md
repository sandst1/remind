# Research Ingestion

Feed research papers into Remind and have your agent curate them into a connected knowledge graph. Instead of reading each paper in isolation, the agent surfaces commonalities, contradictions, and themes across sources.

## The problem

You read 10 papers on a topic. Each one has insights, but finding the threads that connect them — the agreements, the contradictions, the gaps — requires holding all of them in your head simultaneously. That's what your agent can do with Remind.

## Setup

Create a project for the research topic:

```bash
mkdir ~/research/llm-memory
cd ~/research/llm-memory
remind skill-install
```

Optionally create a topic to group this survey:

```bash
remind apply << 'EOF'
topic name="LLM memory survey" "Papers on agent memory architectures"
EOF
```

**Episode types**:

- `observation` — factual summaries and findings from a paper
- `decision` — methodological or interpretive choices
- `question` — open research questions or gaps
- `fact` — specific numbers, claims, or definitions that should stay verbatim
- `outcome` — result of an experiment or evaluation

## Walkthrough

### Storing paper findings

For each paper, have the agent read it and store key findings as episodes:

```bash
# Paper 1: "Generative Agents" (Park et al.)
remind remember "Generative Agents uses a retrieval-based memory with recency, \
  importance, and relevance scoring. Agents reflect on memories to form \
  higher-level abstractions." \
  -t observation -e person:park -e subject:memory-architecture \
  --topic "llm-memory-survey"

remind remember "Generative Agents reflection mechanism: periodically ask \
  'what are the most salient high-level questions?' and generate insights" \
  -t observation -e subject:reflection -e subject:generative-agents \
  --topic "llm-memory-survey"

# Paper 2: "MemGPT" (Packer et al.)
remind remember "MemGPT treats context window as 'working memory' and uses \
  explicit read/write to a larger 'archival memory'. Inspired by OS virtual \
  memory paging." \
  -t observation -e person:packer -e subject:memory-architecture \
  --topic "llm-memory-survey"

# Paper 3: "Voyager" (Wang et al.)
remind remember "Voyager stores learned skills as code in a 'skill library'. \
  Retrieval matches skills by description similarity." \
  -t observation -e person:wang -e subject:skill-library -e subject:voyager \
  --topic "llm-memory-survey"
```

### Agent curates themes

After ingesting several papers, the agent reviews pending episodes and creates concepts:

```bash
# See what needs review
remind snapshot pending

# Create cross-paper concepts
remind apply << 'EOF'
concept from=ep:1,ep:3 title="Two-tier memory architecture" "Current LLM memory systems share a two-tier architecture: fast working memory (context window) + slower persistent storage, differing mainly in how they manage the boundary"
concept from=ep:4 title="Code as memory representation" "Executable code can serve as a memory representation — more precise than natural language for procedural knowledge"
link source=$c1 type=implies target=$c2
processed ids=ep:1,ep:2,ep:3,ep:4
EOF
```

### Querying across papers

```bash
remind recall "how do different systems handle memory retrieval?"
remind recall "memory representation tradeoffs"
remind recall "limitations" --entity subject:memory-architecture
remind recall "retrieval tradeoffs" --topic "llm-memory-survey"
```

### Recording contradictions

When papers disagree, the agent can create conflicts:

```bash
remind remember "Paper A claims 64-shot is optimal" -t fact -e subject:few-shot
remind remember "Paper B claims 8-shot performs equally well" -t fact -e subject:few-shot

# If collision is detected, agent can open a conflict
remind apply << 'EOF'
conflict fact_a=fact:abc fact_b=fact:def severity=medium
EOF
```

## The result

Here's what the entity graph looks like after ingesting several ML papers:

![Entity graph from research paper ingestion](/ui-entity-graph.png)

And the concepts view showing curated knowledge:

![Concepts extracted from papers](/ui-concepts.png)

## What you get

- **Cross-paper synthesis** — Themes and patterns that span multiple sources
- **Contradiction tracking** — Where papers disagree, flagged as conflicts
- **Gap identification** — Open questions captured as `question` episodes
- **Entity graph** — Navigate from an author to their contributions, from a concept to all papers that discuss it
- **Persistent knowledge base** — Come back months later and recall the synthesis
