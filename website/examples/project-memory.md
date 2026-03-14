# Project Memory

The foundational use case: persistent, project-scoped memory for AI coding agents. Your agent remembers preferences, decisions, architecture, and context across sessions — and consolidates them into generalized understanding.

## The problem

Every coding session, your agent starts fresh. You tell it your conventions, explain the architecture, re-state your preferences. It's like onboarding a new developer every morning.

## Setup

Install Remind and the base skill in your project:

```bash
pip install remind-mcp
cd your-project
remind skill-install
```

This creates `.claude/skills/remind/SKILL.md` and sets up the project-local database at `.remind/remind.db`.

## Walkthrough

### Session 1: Initial context

```bash
# Agent stores what it learns
remind remember "Project uses React 19 with TypeScript, Vite for bundling"
remind remember "API is FastAPI with SQLAlchemy ORM" -t observation \
  -e tool:fastapi -e tool:sqlalchemy
remind remember "Chose PostgreSQL over MySQL: better JSON support, team familiarity" \
  -t decision -e tool:postgres
remind remember "All API endpoints must validate input with Pydantic" \
  -t spec -e tool:pydantic -e module:api
remind remember "User prefers explicit error handling over exceptions" \
  -t preference

# End of session
remind end-session
```

### After consolidation

Remind consolidates these into concepts like:

> **"Project tech stack centers on Python (FastAPI + SQLAlchemy) backend with React/TypeScript frontend"**
> - Confidence: 0.9
> - Relations: implies → "Team has Python backend expertise"
> - Conditions: "Current project architecture"

> **"User values explicitness and type safety across the stack"**
> - Confidence: 0.8
> - Source: preference for explicit error handling + TypeScript usage + Pydantic validation
> - Relations: correlates → "Prefers statically typed languages"

### Session 2: Context carries forward

```bash
# Agent recalls at session start
remind recall "project architecture and tech stack"
remind recall "user preferences and conventions"
remind decisions
```

The agent immediately knows the stack, the conventions, and *why* decisions were made — without re-explaining anything.

### Session 5: Knowledge deepens

After several sessions, consolidation has produced a rich concept graph. New episodes get integrated with existing knowledge:

```bash
remind remember "Added Redis caching layer for expensive DB queries" \
  -t decision -e tool:redis -e module:caching
```

This consolidates into the existing tech stack knowledge, possibly creating:

> **"Project follows a pattern of adding infrastructure tools (Postgres, Redis) based on specific performance needs rather than speculative scaling"**
> - Relations: specializes → "Team pragmatic about infrastructure choices"

## What you get

After a few weeks of use:

- **No more re-onboarding** — The agent knows the project cold
- **Decision audit trail** — Every architectural choice is remembered with rationale
- **Growing understanding** — Not just facts, but patterns and preferences
- **Entity graph** — Navigate from a file to its specs, from a tool to the decisions that chose it
