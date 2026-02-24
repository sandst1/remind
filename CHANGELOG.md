# Changelog

All notable changes to this project will be documented in this file.

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
