# Remind + SQLite

The simplest way to get started with Remind. SQLite is the default backend — no database server required.

## Prerequisites

- Python 3.11+
- Remind installed:

```bash
pip install remind-mcp
```

## Quickstart

### 1. Configure Remind

Copy the example config to either the global or project-local location:

```bash
# Global (applies to all projects)
mkdir -p ~/.remind
cp remind.config.json.example ~/.remind/remind.config.json

# Project-local (only this directory, takes precedence over global)
mkdir -p .remind
cp remind.config.json.example .remind/remind.config.json
```

Edit the file and fill in your API keys.

### 2. Use Remind

By default, Remind stores data in `<current-directory>/.remind/remind.db` (project-aware mode) when you run from a project directory, or `~/.remind/memory.db` for a global shared database.

```bash
# Store a memory
remind remember "First memory stored in SQLite"

# Recall memories
remind recall "memory"

# Check stats
remind stats

# Run consolidation
remind consolidate
```

### 3. Inspect the database directly

```bash
sqlite3 .remind/remind.db
```

```sql
SELECT COUNT(*) FROM episodes;
SELECT id, title FROM concepts;
.tables  -- list all tables
.quit
```

## Choosing a database file

**Default (project-aware)** — stores data alongside your project:

```bash
remind remember "something"
# → .remind/remind.db in current directory
```

**Named database** — stores in `~/.remind/<name>.db`:

```bash
remind --db myproject remember "something"
```

**Explicit path or URL** — full control:

```bash
remind --db /path/to/my.db remember "something"
remind --db "sqlite:////path/to/my.db" remember "something"
```

**Environment variable** (recommended for shared scripts):

```bash
export REMIND_DB_URL="sqlite:////path/to/my.db"
remind remember "something"
```

**Config file** (`~/.remind/remind.config.json`):

```json
{
  "db_url": "sqlite:////path/to/my.db"
}
```

## Database URL format

```
sqlite:////absolute/path/to/file.db
sqlite:///relative/path/to/file.db
```

SQLite requires four slashes (`////`) for absolute paths and three (`///`) for relative paths. See the [SQLAlchemy docs](https://docs.sqlalchemy.org/en/20/core/engines.html) for details.

## Vector search (sqlite-vec)

Remind can store embedding vectors in **sqlite-vec** `vec0` tables for fast KNN search. The `sqlite-vec` Python package is installed with `remind-mcp`, but the extension only activates if your **Python** was built so that `sqlite3.Connection` supports `enable_load_extension` (i.e. SQLite was compiled with loadable extensions, and Python was configured accordingly). On some macOS and pyenv setups this is off by default.

**Quick check:**

```bash
python -c "import sqlite3; c=sqlite3.connect(':memory:'); print('sqlite-vec usable:', hasattr(c, 'enable_load_extension'))"
```

If that prints `False`, Remind still runs and recalls correctly using in-Python cosine similarity; only the native index path is skipped. To enable sqlite-vec, reinstall Python linked against Homebrew SQLite with `--enable-loadable-sqlite-extensions` (see [Configuration — Vector search](https://sandst1.github.io/remind/guide/configuration.html#vector-search) on the docs site).

## When to switch to PostgreSQL

SQLite is great for single-user and local development use cases. Consider switching to PostgreSQL when you need:

- Multiple processes or machines writing concurrently
- A shared team database
- Better performance at very large scale

See the [postgres-docker example](../postgres-docker/README.md) to get started with PostgreSQL.
