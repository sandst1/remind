---
layout: home

hero:
  name: Remind
  text: Make AI dream about your tokens.
  tagline: A memory layer that consolidates raw experiences into generalized knowledge. Episodes in, concepts out — like how your brain works overnight.
  actions:
    - theme: brand
      text: Get Started
      link: /guide/getting-started
    - theme: alt
      text: View on GitHub
      link: https://github.com/sandst1/remind

features:
  - icon: 🧠
    title: Generalization, not storage
    details: Episodes are consolidated into generalized concepts with confidence, conditions, and exceptions. Not another vector store.
  - icon: 🔧
    title: Composable via Skills
    details: Build any workflow on top of Remind. The plan/spec/implement cycle is just one example — write your own skills for any use case.
  - icon: 📂
    title: Project-scoped or centralized
    details: Skills use project-local databases (.remind/ in your repo). MCP uses a centralized server. Pick what fits.
  - icon: 🌐
    title: Spreading activation retrieval
    details: Queries activate matching concepts, which activate related concepts through the graph. Like how human memory works.
  - icon: 🤖
    title: Multi-provider
    details: Works with Anthropic, OpenAI, Azure OpenAI, and Ollama. Use cloud or run fully local.
  - icon: 🖥️
    title: Web UI included
    details: Dashboard, concept graph, entity explorer, task board, and memory health — all built in.
---

<style>
.showcase {
  max-width: 900px;
  margin: 3rem auto 0;
  padding: 0 24px;
  text-align: center;
}

.showcase img {
  width: 100%;
  border-radius: 12px;
  border: 1px solid var(--vp-c-divider);
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.08);
}

.showcase .caption {
  color: var(--vp-c-text-3);
  font-size: 0.85rem;
  margin-top: 0.75rem;
}

.how-it-works {
  max-width: 688px;
  margin: 4rem auto;
  padding: 0 24px;
}

.how-it-works h2 {
  text-align: center;
  font-size: 1.6rem;
  margin-bottom: 0.5rem;
}

.how-it-works .subtitle {
  text-align: center;
  color: var(--vp-c-text-2);
  margin-bottom: 2rem;
}

.flow {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.flow-step {
  border: 1px solid var(--vp-c-divider);
  border-radius: 12px;
  padding: 1.25rem;
  background: var(--vp-c-bg-soft);
}

.flow-step h3 {
  margin: 0 0 0.5rem 0;
  font-size: 1rem;
}

.flow-step p {
  margin: 0;
  color: var(--vp-c-text-2);
  font-size: 0.9rem;
  line-height: 1.5;
}

.flow-step code {
  font-size: 0.85rem;
}

.flow-arrow {
  text-align: center;
  color: var(--vp-c-text-3);
  font-size: 1.2rem;
}

.examples-section {
  max-width: 900px;
  margin: 2rem auto 4rem;
  padding: 0 24px;
}

.examples-section h2 {
  text-align: center;
  font-size: 1.6rem;
  margin-bottom: 2rem;
}

.example-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 1rem;
}

.example-card {
  border: 1px solid var(--vp-c-divider);
  border-radius: 12px;
  padding: 1.25rem;
  background: var(--vp-c-bg-soft);
  text-decoration: none;
  color: inherit;
  transition: border-color 0.2s;
}

.example-card:hover {
  border-color: var(--vp-c-brand-1);
}

.example-card h3 {
  margin: 0 0 0.5rem 0;
  font-size: 1rem;
}

.example-card p {
  margin: 0;
  color: var(--vp-c-text-2);
  font-size: 0.9rem;
  line-height: 1.5;
}
</style>

<div class="showcase">
  <img src="/ui-entity-graph.png" alt="Remind entity graph showing concepts and relationships extracted from research papers" />
  <p class="caption">Entity graph built from ingesting research papers — concepts, tools, and their relationships, all extracted automatically.</p>
</div>

<div class="how-it-works">

## How it works

<p class="subtitle">The same consolidation loop your brain runs during sleep, applied to AI memory.</p>

<div class="flow">

<div class="flow-step">

### 1. Remember

Your agent stores raw experiences as episodes. Fast — no LLM calls.

```
remind remember "User prefers Rust for systems work"
remind remember "Chose PostgreSQL over MySQL for the user store" -t decision
```

</div>

<div class="flow-arrow">↓</div>

<div class="flow-step">

### 2. Consolidate

Remind's "sleep" process. The LLM reviews episodes, finds patterns, extracts entities, and creates generalized concepts with relations.

```
remind consolidate
```

</div>

<div class="flow-arrow">↓</div>

<div class="flow-step">

### 3. Recall

Spreading activation retrieval — not just keyword matching. Queries activate matching concepts, which activate related concepts through the graph.

```
remind recall "What tech stack decisions have we made?"
```

Returns generalized concepts like *"User gravitates toward statically typed, performance-oriented languages"* — not a list of raw transcripts.

</div>

</div>

</div>

<div class="examples-section">

## See it in practice

<div class="example-cards">

<a class="example-card" href="/examples/project-memory">
<h3>Project Memory</h3>
<p>Persistent context across coding sessions. Your agent remembers preferences, decisions, and project architecture.</p>
</a>

<a class="example-card" href="/examples/sparring-partner">
<h3>Sparring Partner</h3>
<p>Ongoing debates across sessions. Remind tracks arguments, positions, and open threads.</p>
</a>

<a class="example-card" href="/examples/research-ingestion">
<h3>Research Ingestion</h3>
<p>Feed in papers, find commonalities and contradictions. Consolidation surfaces themes across sources.</p>
</a>

</div>

</div>
