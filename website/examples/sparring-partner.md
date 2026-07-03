# Sparring Partner

Use Remind to have an ongoing, multi-session conversation on any topic. The agent remembers prior arguments, positions, open threads, and contradictions — so each session picks up where the last left off.

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
  -t observation -e subject:monolith -e subject:microservices

remind remember "Counterargument: team of 3 doesn't have bandwidth for \
  distributed systems operational overhead" \
  -t observation -e subject:team-size -e subject:microservices

remind remember "Open question: at what team size does the coordination cost \
  of a monolith exceed the operational cost of microservices?" \
  -t question -e subject:team-size -e subject:architecture

remind remember "Tentative position: start monolith, extract services at \
  domain boundaries when team hits 8-10 engineers" \
  -t decision -e subject:architecture -e subject:team-size
```

### Session 1: Agent curates positions

At session end, the agent reviews and organizes:

```bash
remind snapshot pending

remind apply << 'EOF'
concept from=ep:1,ep:2,ep:4 title="Monolith-first strategy" "Pragmatic architecture: start monolith, extract services at domain boundaries when team hits 8-10 engineers. Driven by operational simplicity."
processed ids=ep:1,ep:2,ep:3,ep:4
EOF
```

### Session 2: Deepening the debate

```bash
# Recall where we left off
remind recall "microservices vs monolith"
remind recall "open questions"

# New observations
remind remember "Discussed Conway's Law: team structure should mirror system \
  architecture. 3 engineers → monolith. 3 teams → 3 services." \
  -t observation -e subject:conways-law -e subject:team-size

remind remember "User refined position: the extraction trigger isn't team size \
  alone, it's team size × deployment frequency. High deploy frequency with \
  shared codebase = merge conflicts = pain point" \
  -t observation -e subject:architecture -e subject:deployment
```

### Session 5: Contradictions emerge

By session 5, the agent has curated several sessions. When reviewing pending episodes, it notices a tension:

```bash
remind remember "User enthusiastic about event-driven architecture for the \
  notification system despite complexity" \
  -t observation -e subject:event-driven -e subject:architecture

# Agent creates a conflict to track the tension
remind apply << 'EOF'
concept from=ep:20 title="Event-driven preference" "Enthusiasm for event-driven patterns in notification system"
conflict fact_a=concept:monolith-first fact_b=$c1 severity=low
EOF
```

The agent can now surface this contradiction: "You've said you prefer simplicity, but you keep gravitating toward event-driven patterns. Which is it, or is there a condition where each applies?"

## What you get

- **Continuity** — Every session builds on the last
- **Contradiction tracking** — Tensions in your thinking are explicitly flagged
- **Position evolution** — Watch how your views change over time
- **Open threads** — Questions from session 1 can be revisited in session 10
- **Curated understanding** — Not a transcript, but organized positions and arguments
