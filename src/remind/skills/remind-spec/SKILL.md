---
name: remind-spec
description: Spec-driven software development using Remind as the source of truth. Use when building software from specifications, managing requirements, planning implementations, or when the user describes what they want to build and you need to capture, plan, implement, and evolve specs systematically.
---

# Spec-Driven Development with Remind

> **Important**: The `remind` CLI tool is already available in this environment. Use it directly — no MCP server setup required.

> **DO NOT WRITE CODE.** This skill covers spec capture, planning, and task creation — NOT implementation. You must not create, edit, or modify any source code files during spec/planning phases. Your job here is to understand what the user wants, decompose it into clear requirements, and store those in Remind. Implementation is a separate step that happens later, explicitly requested by the user. Do not "get started" on code, do not scaffold files, do not write prototypes. Capture the idea first. Build later.

Use Remind as the **source of truth** for software specifications. Specs are stored as episodes, linked to files and concepts via entities, and consolidated into architectural knowledge.

## Entity Naming Conventions

Use consistent entity prefixes to build a navigable spec graph:

| Prefix | Use for | Examples |
|--------|---------|---------|
| `module:` | Architectural boundaries | `module:auth`, `module:billing` |
| `subject:` | Functional areas / features | `subject:login-flow`, `subject:rate-limiting` |
| `file:` | Implementation files | `file:src/routes/auth.ts` |
| `project:` | Top-level project | `project:backend-api` |
| `tool:` | Technology choices | `tool:redis`, `tool:postgres` |

## Episode Types for Specs

| Type | Use for | Example |
|------|---------|---------|
| `spec` | Requirements, acceptance criteria | "Login must return JWT with 1h expiry" |
| `plan` | Implementation plans, roadmaps | "Auth plan: 1) bcrypt 2) login route 3) JWT middleware" |
| `task` | Discrete work items | "Implement bcrypt password hashing utility" |
| `decision` | Architecture choices with rationale | "Chose bcrypt: team familiarity, sufficient security" |
| `preference` | Constraints, NFRs, coding standards | "All APIs must respond within 200ms" |
| `question` | Open design questions | "Should we support WebSocket fallback?" |
| `meta` | Process notes, retrospectives | "Auth spec was ambiguous about token refresh" |
| `observation` | General observations, noticed patterns | "Auth module has grown complex, may need refactoring" |

## Metadata Schema

Use `-m` to attach structured metadata for spec lifecycle:

```bash
-m '{"status":"draft","priority":"p0","epic":"user-auth"}'
```

| Field | Values | Purpose |
|-------|--------|---------|
| `status` | `draft`, `approved`, `implemented`, `deprecated` | Spec lifecycle |
| `priority` | `p0`, `p1`, `p2` | Implementation order |
| `epic` | free text | Groups specs under a theme |
| `depends_on` | episode ID | Prerequisite spec |

## Workflow

### Phase 1: Spec Capture

When the user describes what to build, decompose into individual spec episodes. Each episode should be a **standalone, clear requirement**.

```bash
# Feature spec
remind remember "POST /api/auth/login: accepts {email, password}, returns JWT with 1h expiry. Rate limit 5 attempts/IP/min." \
  -t spec -e module:auth -e subject:login-flow -e file:src/routes/auth.ts \
  -m '{"status":"approved","priority":"p0","epic":"user-auth"}'

# Architecture decision
remind remember "Chose bcrypt for password hashing: broad library support, team familiarity, sufficient for threat model" \
  -t decision -e module:auth -e subject:password-hashing -e tool:bcrypt

# Non-functional requirement
remind remember "All auth endpoints must respond within 200ms under normal load" \
  -t spec -e module:auth -e subject:performance \
  -m '{"status":"approved","priority":"p1"}'

# Open question
remind remember "Should token refresh be silent (via cookie) or explicit (via refresh endpoint)?" \
  -t question -e module:auth -e subject:token-refresh

# Coding standard
remind remember "Use zod for all request body validation, define schemas adjacent to route handlers" \
  -t preference -e project:backend-api -e tool:zod
```

**Guidelines**:
- One requirement per episode (not a wall of text)
- Use `-t spec` for prescriptive requirements ("X must/shall...")
- Always tag with `module:` and/or `subject:` entities
- Tag with `file:` entities when the target file is known
- Use `decision` type whenever there's a "chose X because Y"
- Capture open questions immediately with `question` type
- Include rationale in decisions, not just the choice

### Phase 2: Planning

Before implementation, recall all relevant specs and build a plan.

```bash
# Recall all specs for a module
remind recall "auth module requirements" -k 15
remind recall "auth" --entity module:auth

# Check for open questions
remind questions

# Check architecture decisions
remind decisions

# Check all specs
remind specs --entity module:auth

# Check all entities to understand scope
remind entities
```

**Planning workflow**:
1. Recall specs for the target module/feature
2. Check `remind questions` for unresolved design issues -- resolve them with the user, then store answers as `decision` episodes
3. Check `remind decisions` for existing architecture choices to follow
4. Build an implementation plan grounded in the recalled specs
5. Store the plan as a `plan` episode:

```bash
remind remember "Auth implementation plan: 1) bcrypt password hashing utility 2) login route with zod validation 3) JWT middleware 4) rate limiting middleware. Order: hashing > login > JWT > rate limit." \
  -t plan -e module:auth -e subject:implementation-plan \
  -m '{"status":"active","priority":"p0"}'
```

### Phase 2.5: Task Creation

Break the plan into discrete tasks. Tasks have status tracking (todo -> in_progress -> done) and can link back to the plan and specs.

```bash
# Create tasks from plan
remind task add "Implement bcrypt password hashing utility" \
  -e module:auth -e file:src/utils/hash.ts --priority p0 --plan <plan-id> --spec <spec-id>

remind task add "Implement login route with zod validation" \
  -e module:auth -e file:src/routes/auth.ts --priority p0 --plan <plan-id> --depends-on <hash-task-id>

remind task add "Implement JWT middleware" \
  -e module:auth -e file:src/middleware/jwt.ts --priority p0 --plan <plan-id> --depends-on <login-task-id>

remind task add "Implement rate limiting middleware" \
  -e module:auth --priority p1 --plan <plan-id> --depends-on <jwt-task-id>

# Link existing tasks to plan/spec after creation
remind task update <id> --plan <plan-id> --spec <spec-id>
remind task update <id> --depends-on <task-id> --priority p0

# View all tasks
remind tasks
remind tasks --entity module:auth
```

**Task lifecycle**:
```bash
remind task start <id>      # Begin work
remind task done <id>       # Mark complete
remind task block <id> "waiting on API key"  # Block with reason
remind task unblock <id>    # Unblock
```

Active tasks (todo/in_progress/blocked) are **excluded from consolidation**. When a task is marked done, it becomes eligible for consolidation, allowing the system to learn from completed work.

### Phase 3: Implementation (use the implement skill, not this one)

> **STOP.** If you were invoked as the spec skill, your job ends at Phase 2.5 (task creation). Do not proceed to implementation. The user will explicitly request implementation when ready, using the implement skill. The information below is reference for how specs connect to implementation — it is NOT a directive to start coding.

During coding, stay connected to specs and tasks.

**Before touching a module**:
```bash
remind recall "requirements" --entity module:auth
remind tasks --entity module:auth
```

**Working through tasks**:
```bash
# Start the current task
remind task start <id>

# Record implementation decisions along the way
remind remember "Implemented JWT with RS256 instead of HS256: enables future microservice token verification without sharing secrets" \
  -t decision -e module:auth -e subject:jwt-signing -e file:src/middleware/jwt.ts

# Complete the task
remind task done <id>

# Update spec status
remind update-episode <spec-episode-id> -c "POST /api/auth/login: accepts {email, password}, returns JWT with 1h expiry. Rate limit 5 attempts/IP/min." \
  -m '{"status":"implemented"}'
```

**When discovering gaps**:
```bash
# Missing requirement found during implementation
remind remember "Need to handle case where user email is not verified -- should login be blocked or allowed with limited permissions?" \
  -t question -e module:auth -e subject:email-verification

# New task discovered during implementation
remind task add "Handle unverified email case in login flow" -e module:auth --priority p1
```

**When the spec is wrong or incomplete**:
```bash
# Update the spec episode
remind update-episode <id> -c "Updated requirement: login must also return user profile (id, email, display_name) alongside JWT"

# Or delete and replace if substantially different
remind delete-episode <id>
remind remember "New requirement..." -t spec -e module:auth
```

### Phase 4: Spec Evolution

When requirements change:

**Minor refinement** (same intent, more detail):
```bash
remind update-episode <id> -c "Refined: POST /api/auth/login returns JWT with 1h expiry AND refresh token with 7d expiry"
```

**Superseded spec** (requirement replaced):
```bash
remind delete-episode <old-id>
remind remember "New requirement replacing old auth flow..." -t observation -e module:auth
```

**New constraint added**:
```bash
remind remember "Auth tokens must include 'aud' claim scoped to requesting client application" \
  -t observation -e module:auth -e subject:jwt-claims
```

**Deprecation**:
```bash
remind update-episode <id> -c "DEPRECATED: Basic auth support removed in favor of OAuth2 only"
```

### Phase 5: Consolidation (Architecture Review)

Run consolidation after capturing a batch of specs or completing an implementation phase. This is where Remind synthesizes individual specs into higher-level architectural understanding.

```bash
remind end-session          # Background consolidation
remind consolidate          # Foreground (see results immediately)
```

**What consolidation produces**:
- Groups related spec episodes into coherent concepts ("Auth module architecture")
- Surfaces `CONTRADICTS` relations between conflicting specs
- Identifies patterns ("this project consistently prioritizes simplicity")
- Builds semantic graph linking modules, features, and files

**After consolidation, inspect results**:
```bash
remind inspect              # List all concepts
remind inspect <concept-id> # See a specific concept and its relations
remind entities             # See all entities and mention counts
```

**Fix consolidation issues**:
```bash
# If a concept misrepresents the spec
remind update-concept <id> -s "Corrected summary..."

# If consolidation created a bad concept
remind delete-concept <id>
```

## Cross-Session Continuity

At the **start of every session** working on a spec-driven project:

```bash
remind recall "project overview and architecture" -k 10
remind tasks                # What's in progress?
remind questions            # Any unresolved items?
remind stats                # How much is captured?
```

At the **end of every session**:

```bash
remind end-session
```

## Best Practices

1. **NO CODE during spec/plan phases** -- this skill captures requirements and creates plans. Implementation is a separate, explicitly-requested step. Do not write, edit, or scaffold any source code files.
2. **One requirement per episode** -- atomic specs consolidate better
3. **Always use entities** -- they are the backbone of navigability
4. **Capture rationale** -- "chose X because Y" is more valuable than "use X"
5. **Resolve questions before implementing** -- store answers as decisions
6. **Update specs when reality diverges** -- remind is the source of truth, keep it accurate
7. **Consolidate after spec batches** -- don't wait for auto-threshold
8. **Use recall before coding** -- ground implementation in stored specs
9. **Delete rather than contradict** -- cleaner than accumulating conflicting episodes
10. **Tag implementation files** -- `file:` entities connect specs to code
11. **Store the plan** -- implementation plans are decisions worth remembering
