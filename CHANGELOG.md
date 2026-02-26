# Changelog

All notable changes to this project will be documented in this file.

## [0.4.0] - 2026-02-26

### Added
- Memory decay system: concepts gradually lose retrieval priority based on how rarely they are recalled, mimicking human forgetting
  - `decay_factor` (0.0–1.0) multiplies each concept's retrieval activation score
  - Decay runs every N recalls (`decay_interval`, default 20), reducing `decay_factor` by `decay_rate` (default 0.1) using a single SQL update for O(1) performance
  - Rejuvenation: recalled concepts receive an activation-proportional boost to their `decay_factor`; recently-accessed concepts are protected by a 60-second grace window so they are not penalised immediately after being recalled
  - Recall count is persisted in the database across process restarts, so decay works correctly with the CLI
  - Decay stats visible in `remind stats` (enabled state, recall count, next decay, avg/min decay factor)
- `DecayConfig` in `~/.remind/remind.config.json` under the `"decay"` key with `enabled`, `decay_interval`, and `decay_rate` options
- Metadata table in SQLite for persistent key-value storage (currently used for recall count)
- Memory status panel in web UI and recall count shown in concepts view

## [0.3.1] - 2026-02-25

### Fixed
- Bump numpy requirement to `>=2.0.0` to prevent segfault on macOS in sandboxed environments (e.g. Cursor agent terminal) caused by numpy 1.26.x `_mac_os_check` startup self-test

## [0.3.0] - 2026-02-25

### Added
- Global config file support (`~/.remind/remind.config.json`) for centralized configuration
- `--version` CLI argument to display current version
- Collapsible sidebar in web UI
- Agent skills support for Claude Code integration
- UI can now be run from any directory

### Fixed
- Entity relationship extraction
- Consolidation with explicit entities

## [0.2.0] - 2026-01-09

### Added
- Web UI with interactive concept graph visualization (D3-based)
- Docker support for containerized deployment
- Entity inspection UI and MCP tools
- LLM-powered query answering with source episodes
- Dark mode support
- Batch consolidation and reconsolidation
- Concept and entity filtering in UI
- Entity relationship inference
- Concept titles for better readability
- Episode titles in UI

### Changed
- Improved concept list ordering (alphabetical)
- Enhanced graph visualization

## [0.1.0] - 2026-01-04

### Added
- Core memory system with episodes and concepts
- Spreading activation retrieval algorithm
- LLM-powered consolidation (episode to concept transformation)
- Entity extraction from episodes
- Provider support: Anthropic, OpenAI, Azure OpenAI, Ollama
- MCP server (SSE mode)
- CLI tool (`remind` command)
- SQLite persistence layer
- Background consolidation
- Project-aware database paths
