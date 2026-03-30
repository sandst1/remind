# Remind + PostgreSQL (Docker)

Run Remind CLI backed by a PostgreSQL database in Docker.

## Prerequisites

- Docker & Docker Compose
- Python 3.11+
- Remind installed with the `postgres` extra:

```bash
pip install "remind-mcp[postgres]"
```

## Quickstart

### 1. Start PostgreSQL

```bash
docker compose up -d
```

Wait for the health check to pass:

```bash
docker compose ps
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — fill in your API keys and adjust any settings
source .env   # or use direnv, dotenv, etc.
```

> **Note:** Remind reads environment variables only — it does not load `.env` files automatically.

### 3. Use Remind normally

Everything works exactly as with SQLite — Remind creates the schema on first use.

```bash
# Store a memory
remind remember "First memory stored in PostgreSQL"

# Recall memories
remind recall "memory"

# Check stats
remind stats

# Run consolidation
remind consolidate
```

### 4. Inspect the database directly

```bash
docker compose exec postgres psql -U remind remind
```

```sql
SELECT COUNT(*) FROM episodes;
SELECT id, title FROM concepts;
\dt  -- list all tables
```

### 5. Tear down

```bash
docker compose down       # stop containers (data persists in volume)
docker compose down -v    # stop containers AND delete data
```

## Alternative ways to pass the database URL

**Environment variable** (recommended for production):

```bash
export REMIND_DB_URL="postgresql+psycopg://remind:remind@localhost:5432/remind"
remind remember "something"
```

**CLI flag** (ad-hoc usage):

```bash
remind --db "postgresql+psycopg://remind:remind@localhost:5432/remind" remember "something"
```

**Config file** (`~/.remind/remind.config.json`):

```json
{
  "db_url": "postgresql+psycopg://remind:remind@localhost:5432/remind"
}
```

## Connection string format

```
postgresql+psycopg://USER:PASSWORD@HOST:PORT/DATABASE
```

- `postgresql+psycopg` — PostgreSQL with the psycopg v3 driver
- `postgresql+psycopg2` — PostgreSQL with the older psycopg2 driver
- `mysql+pymysql` — MySQL with the PyMySQL driver

See the [SQLAlchemy docs](https://docs.sqlalchemy.org/en/20/core/engines.html) for all supported backends.
