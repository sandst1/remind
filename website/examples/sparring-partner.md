# Sparring Partner

Use Remind to have an ongoing, multi-session conversation on any topic. The agent remembers prior arguments, positions, open threads, and contradictions — so each session picks up where the last left off, with consolidated understanding of the debate.

## The problem

AI conversations are stateless. A great debate about system design, philosophy, or strategy evaporates when the session ends. You can't build on yesterday's arguments.

## Setup

Create a project directory for the conversation and install Remind:

```bash
mkdir ~/sparring/distributed-systems
cd ~/sparring/distributed-systems
remind skill-install
```

The database lives at `.remind/remind.db` in this directory — dedicated to this topic.

## Walkthrough

### Session 1: Opening positions

You and the agent debate microservices vs. monolith for a new project.

```bash
# The agent captures key positions and arguments
remind remember "User argues monolith-first: easier to refactor a monolith \
  into services than to merge services into a monolith" \
  -t observation -e concept:monolith -e concept:microservices

remind remember "Counterargument: team of 3 doesn't have bandwidth for \
  distributed systems operational overhead" \
  -t observation -e concept:team-size -e concept:microservices

remind remember "Open question: at what team size does the coordination cost \
  of a monolith exceed the operational cost of microservices?" \
  -t question -e concept:team-size -e concept:architecture

remind remember "Tentative position: start monolith, extract services at \
  domain boundaries when team hits 8-10 engineers" \
  -t decision -e concept:architecture -e concept:team-size

remind end-session
```

### After consolidation

> **"User favors pragmatic architecture decisions driven by team size, preferring monolith-first with planned extraction points"**
> - Confidence: 0.75
> - Relations: implies → "Values operational simplicity over theoretical scalability"
> - Open question: "Where exactly is the team-size tipping point?"

### Session 2: Deepening the debate

```bash
# Recall where we left off
remind recall "microservices vs monolith"
remind questions

# The agent sees the open question about team size and pushes on it
remind remember "Discussed Conway's Law: team structure should mirror system \
  architecture. 3 engineers → monolith. 3 teams → 3 services." \
  -t observation -e concept:conways-law -e concept:team-size

remind remember "User refined position: the extraction trigger isn't team size \
  alone, it's team size × deployment frequency. High deploy frequency with \
  shared codebase = merge conflicts = pain point" \
  -t observation -e concept:architecture -e concept:deployment

remind end-session
```

### Session 5: Contradictions emerge

By session 5, the agent has consolidated several sessions. It notices:

> **"User's stated preference for simplicity contradicts their enthusiasm for event-driven architecture (which adds complexity)"**
> - Relation: contradicts → "Values operational simplicity"
> - Confidence: 0.6

The agent can now surface this contradiction: "You've said you prefer simplicity, but you keep gravitating toward event-driven patterns. Which is it, or is there a condition where each applies?"

## What you get

- **Continuity** — Every session builds on the last
- **Contradiction detection** — Consolidation surfaces tensions in your thinking
- **Position evolution** — Watch how your views change over time through the concept graph
- **Open threads** — Questions from session 1 can be revisited in session 10
- **Generalized understanding** — Not a transcript, but a distilled model of the debate
