---
name: oo-learn-patterns
description: >-
  Bootstrap project-specific oo output patterns for a repository. Scans the repo
  to detect its toolchain and creates .oo/patterns/*.toml files that compress
  verbose command output for AI agents. Use when you want to set up oo patterns
  for a project, teach oo about a repo's commands, or create .oo/patterns.
---

# oo-learn-patterns

Create project-specific output patterns so `oo` can compress verbose command
output into terse summaries for AI coding agents.

## Workflow

### 1. Detect project root and toolchain

Find the git root (`git rev-parse --show-toplevel`) and scan for toolchain
markers to determine which commands the project uses:

| Marker file | Commands to pattern |
|-------------|-------------------|
| `Cargo.toml` | `cargo test`, `cargo build`, `cargo clippy`, `cargo fmt --check` |
| `package.json` | `npm test`, `npm run build`, `npx jest`, `npx eslint`, `npx tsc` |
| `pyproject.toml` / `setup.py` / `requirements.txt` | `pytest`, `ruff check`, `mypy`, `pip install` |
| `go.mod` | `go test ./...`, `go build ./...`, `go vet ./...` |
| `Makefile` / `CMakeLists.txt` | `make`, `cmake --build` |
| `Dockerfile` / `docker-compose.yml` | `docker build`, `docker compose up` |
| `terraform/` / `*.tf` | `terraform plan`, `terraform apply` |
| `.github/workflows/` | inspect YAML for additional commands |

Also check for CI config files (`.github/workflows/*.yml`, `.gitlab-ci.yml`,
`Jenkinsfile`) to discover commands actually used in the project.

### 2. Create the patterns directory

```bash
mkdir -p <git-root>/.oo/patterns
```

### 3. Author one `.toml` file per command

For each discovered command, create a pattern file in `.oo/patterns/`.
Name files descriptively: `cargo-test.toml`, `npm-build.toml`, etc.

Use the TOML format reference below. Key principles:

- `command_match` is a regex tested against the full command string
- `[success]` extracts a terse summary from passing output via named captures
- `[failure]` filters noisy failure output to show only actionable lines
- An empty `summary = ""` suppresses output entirely on success (quiet pass)
- Omit `[failure]` to show all output on failure (sensible default)

### 4. Validate patterns

After creating patterns, verify them:

```bash
oo patterns          # lists all loaded patterns (project + user + builtins)
oo <command>         # run a real command to test the pattern
```

### 5. Iterate

If a pattern doesn't match as expected, adjust `command_match` regex or
`[success].pattern` captures. Run the command again with `oo` to verify.

You can also use `oo learn <command>` to have an LLM generate a pattern
(saves to `~/.config/oo/patterns/`, not project-local), then move or
adapt the generated file into `.oo/patterns/`.

---

## Pattern TOML Format Reference

Patterns are `.toml` files — one per command. They are loaded from two locations
in order, with the first regex match winning:

1. **Project:** `<git-root>/.oo/patterns/` — repo-specific, checked in with the project
2. **User:** `~/.config/oo/patterns/` — personal patterns across all projects

Both layers are checked before built-in patterns, so custom patterns always override.

### TOML format

```toml
# Regex matched against the full command string (e.g. "make -j4 all")
command_match = "^make\\b"

[success]
# Regex with named captures run against stdout+stderr
pattern = '(?P<target>\S+) is up to date'
# Template: {name} is replaced with the capture of the same name
summary = "{target} up to date"

[failure]
# Strategy: tail | head | grep | between
strategy = "grep"
# For grep: lines matching this regex are kept
grep = "Error:|error\\["
```

### `[success]` section

| Field | Type | Description |
|-------|------|-------------|
| `pattern` | regex | Named captures become template variables |
| `summary` | string | Template; `{capture_name}` replaced at runtime |

An empty `summary = ""` suppresses output on success (quiet pass).

### `[failure]` section

`strategy` is optional and defaults to `"tail"`.

| `strategy` | Extra fields | Behaviour |
|------------|-------------|-----------|
| `tail` | `lines` (default 30) | Last N lines of output |
| `head` | `lines` (default 20) | First N lines of output |
| `grep` | `grep` (regex, required) | Lines matching regex |
| `between` | `start`, `end` (strings, required) | Lines from first `start` match to first `end` match (inclusive) |

Omit `[failure]` to show all output on failure.

> **Note:** `start` and `end` in the `between` strategy are plain substring
> matches, not regexes.

### Command Categories

oo categorizes commands to determine default behavior when no pattern matches:

| Category | Examples | Default Behavior |
|----------|----------|------------------|
| **Status** | `cargo test`, `pytest`, `eslint`, `cargo build` | Quiet success (empty summary) if output > 4 KB |
| **Content** | `git show`, `git diff`, `cat`, `bat` | Always pass through, never index |
| **Data** | `git log`, `git status`, `gh api`, `ls`, `find` | Index for recall if output > 4 KB and unpatterned |
| **Unknown** | Anything else (curl, docker, etc.) | Pass through (safe default) |

Patterns always take priority over category defaults. If a pattern matches, it
determines the output classification regardless of category.

---

## Example Patterns

### `docker build`

```toml
command_match = "\\bdocker\\s+build\\b"

[success]
pattern = 'Successfully built (?P<id>[0-9a-f]+)'
summary = "built {id}"

[failure]
strategy = "tail"
lines = 20
```

### `terraform plan`

```toml
command_match = "\\bterraform\\s+plan\\b"

[success]
pattern = 'Plan: (?P<add>\d+) to add, (?P<change>\d+) to change, (?P<destroy>\d+) to destroy'
summary = "+{add} ~{change} -{destroy}"

[failure]
strategy = "grep"
grep = "Error:|error:"
```

### `make`

```toml
command_match = "^make\\b"

[success]
pattern = '(?s).*'   # always matches; empty summary = quiet
summary = ""

[failure]
strategy = "between"
start = "make["
end = "Makefile:"
```

---

## Example: Programmatic Pattern Usage (Rust)

This shows how patterns work at the library level, useful for understanding
the internal structure when authoring TOML patterns.

```rust
use double_o::pattern::parse_pattern_str;
use double_o::{CommandOutput, classify};

fn main() {
    let toml_pattern = r#"
command_match = "^myapp test"

[success]
pattern = '(?P<passed>\d+) tests passed, (?P<failed>\d+) failed'
summary = "{passed} passed, {failed} failed"

[failure]
strategy = "tail"
lines = 20
"#;

    let custom_pattern = parse_pattern_str(toml_pattern).unwrap();

    let success_output = CommandOutput {
        stdout: br"Running test suite...
Test 1... OK
Test 2... OK
Test 3... OK
Result: 42 tests passed, 0 failed
Total time: 2.5s"
            .to_vec(),
        stderr: Vec::new(),
        exit_code: 0,
    };

    let patterns = vec![custom_pattern];
    let classification = classify(&success_output, "myapp test --verbose", &patterns);

    match &classification {
        double_o::Classification::Success { label, summary } => {
            println!("  Label: {}", label);   // "myapp"
            println!("  Summary: {}", summary); // "42 passed, 0 failed"
        }
        _ => println!("  Unexpected classification type"),
    }
}
```

A grep-based failure strategy example:

```rust
let grep_pattern = r#"
command_match = "^myapp build"

[success]
pattern = 'Build complete'
summary = "build succeeded"

[failure]
strategy = "grep"
grep = "Error:"
"#;
// Only lines matching "Error:" are kept in the failure output.
```
