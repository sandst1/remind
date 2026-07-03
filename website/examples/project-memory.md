# Project Memory

The foundational use case: persistent, project-scoped memory for AI coding agents. Your agent remembers preferences, decisions, architecture, and context across sessions — and curates them into organized knowledge.

## The problem

Every coding session, your agent starts fresh. You tell it your conventions, explain the architecture, re-state your preferences. It's like onboarding a new developer every morning.

## Setup

Install Remind and the bundled skills in your project:

```bash
pip install remind-mcp
cd your-project
remind skill-install
```

This creates the `remind-capture`, `remind-context`, and `remind-curate` skills under `.claude/skills/` and sets up the project-local database at `.remind/remind.db`.

## Walkthrough

Episode types for `-t` / `--type`: `observation` (default), `decision`, `question`, `meta`, `preference`, `outcome`, `fact`.

### Session 1: Initial context

```bash
# Agent stores what it learns
remind remember "Project uses React 19 with TypeScript, Vite for bundling"
remind remember "API is FastAPI with SQLAlchemy ORM" -t observation \
  -e tool:fastapi -e tool:sqlalchemy
remind remember "Chose PostgreSQL over MySQL: better JSON support, team familiarity" \
  -t decision -e tool:postgres
remind remember "All API endpoints must validate input with Pydantic" \
  -t fact -e tool:pydantic -e module:api
remind remember "User prefers explicit error handling over exceptions" \
  -t preference
```

### Session 1: Agent curates knowledge

At session end (or when prompted), the agent reviews pending episodes:

```bash
# See what needs review
remind snapshot pending

# Create concepts from related episodes
remind apply << 'EOF'
concept from=ep:1,ep:2,ep:3 title="Tech stack" "FastAPI + SQLAlchemy backend, React/TypeScript frontend"
concept from=ep:4,ep:5 title="Code style" "Explicit error handling, Pydantic validation on all endpoints"
processed ids=ep:1,ep:2,ep:3,ep:4,ep:5
EOF
```

### Session 2: Context carries forward

```bash
# Agent recalls at session start
remind recall "project architecture and tech stack"
remind recall "user preferences and conventions"
```

The agent immediately knows the stack, the conventions, and *why* decisions were made — without re-explaining anything.

### Session 5: Knowledge deepens

After several sessions, the agent has built a rich concept graph. New episodes get integrated with existing knowledge:

```bash
remind remember "Added Redis caching layer for expensive DB queries" \
  -t decision -e tool:redis -e module:caching

remind remember "Redis TTL is 300s for auth tokens" \
  -t fact -e tool:redis --asserted-by alice
```

The agent can link new concepts to existing ones:

```bash
remind apply << 'EOF'
concept from=ep:20 title="Caching strategy" "Redis for expensive queries"
link source=$c1 type=extends target=concept:tech-stack
processed ids=ep:20
EOF
```

### Handling facts and conflicts

When facts change, Remind detects collisions:

```bash
# Later, the TTL is updated
remind remember "Redis TTL is 600s for auth tokens" -t fact -e tool:redis
# Output: collision detected with fact:abc123 ("Redis TTL is 300s")
```

The agent decides what to do:

```bash
remind apply << 'EOF'
supersede old=fact:abc123 new=fact:def456
EOF
```

## What you get

After a few weeks of use:

- **No more re-onboarding** — The agent knows the project cold
- **Decision audit trail** — Every architectural choice is remembered with rationale
- **Growing understanding** — Curated concepts with provenance and history
- **Entity graph** — Navigate from a file or module to related concepts
- **Time travel** — `remind recall --as-of 2024-06-01 "cache config"` shows what was true then
