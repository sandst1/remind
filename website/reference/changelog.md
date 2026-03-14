# Changelog

All notable changes to Remind.

## [0.6.0] - 2026-03-09

### Added
- Task management system: task episodes with status tracking (todo, in_progress, done, blocked), dependency chains, plan/spec linking, and priority levels
- Agent workflow skills for the plan-to-implementation lifecycle:
  - `remind` -- base memory operations reference
  - `remind-plan` -- interactive planning with sparring and crystallization
  - `remind-spec` -- spec-driven development with lifecycle management
  - `remind-implement` -- systematic task execution loop
- Active tasks are excluded from consolidation; completed tasks become eligible

### Changed
- Updated web UI

### Fixed
- `run_async` helper function

## [0.5.3] - 2026-03-03

### Fixed
- When updating episodes, reset entity associations so they are rebuilt on next consolidation

## [0.5.2] - 2026-03-02

### Fixed
- Actually include web UI static files in wheel builds

## [0.5.1] - 2026-03-02

### Fixed
- Include built web UI assets in package

## [0.5.0] - 2026-03-02

### Added
- Support for updating and deleting concepts and episodes
- Built-in memories about Remind itself for self-aware assistance

### Changed
- Consolidation is now non-blocking, improving CLI responsiveness

### Fixed
- Explicit consolidation command now works correctly
- Build issues resolved

## [0.4.0] - 2026-02-26

### Added
- Memory decay system: concepts gradually lose retrieval priority based on recall frequency
  - `decay_factor` (0.0--1.0) multiplies retrieval activation score
  - Decay runs every N recalls with configurable rate
  - Rejuvenation: recalled concepts receive activation-proportional boost
  - 60-second grace window protects recently-accessed concepts
- `DecayConfig` in config file under `"decay"` key
- Metadata table in SQLite for persistent key-value storage
- Memory status panel in web UI

## [0.3.1] - 2026-02-25

### Fixed
- Bump numpy requirement to `>=2.0.0` to prevent segfault on macOS in sandboxed environments

## [0.3.0] - 2026-02-25

### Added
- Global config file support (`~/.remind/remind.config.json`)
- `--version` CLI argument
- Collapsible sidebar in web UI
- Agent skills support for Claude Code integration

### Fixed
- Entity relationship extraction
- Consolidation with explicit entities

## [0.2.0] - 2026-01-09

### Added
- Web UI with interactive concept graph visualization (D3-based)
- Docker support
- Entity inspection UI and MCP tools
- LLM-powered query answering with source episodes
- Dark mode support
- Batch consolidation and reconsolidation

## [0.1.0] - 2026-01-04

### Added
- Core memory system with episodes and concepts
- Spreading activation retrieval algorithm
- LLM-powered consolidation
- Entity extraction from episodes
- Provider support: Anthropic, OpenAI, Azure OpenAI, Ollama
- MCP server (SSE mode)
- CLI tool
- SQLite persistence layer
- Background consolidation
- Project-aware database paths
