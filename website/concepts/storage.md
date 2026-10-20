# Storage and migration

Remind's default local store is a directory of deterministic JSON records. The store has no built-in project or personal category: choose its location and labels to suit the application.

```text
.remind/
  remind.config.json
  memory/                 # authoritative, version-controlled records
  cache/                  # ignored SQLite, vectors, and lexical indexes
  runtime/                # ignored locks, recovery journals, backups
```

Commit `memory/` with the code. Checking out a branch selects its memory; merging brings both code and memories together. Distinct record files merge normally. Concurrent edits to the same record, including a newly introduced shared entity, may require ordinary Git conflict resolution. Remind neither commits nor selects a semantic winner.

## Selecting a store

```bash
remind remember "Use PostgreSQL for concurrent writers"
remind --store ./personal-memory remember "User prefers concise answers"
remind --store file:///absolute/path/to/memory snapshot stats
remind --store sqlite:////absolute/path/to/explicit.db snapshot stats
remind --store postgresql+psycopg://user:password@localhost/database snapshot stats
```

The implicit location uses the nearest Remind directory, otherwise the Git root, otherwise the working directory. Names and legacy local `.db` paths resolve to text stores; explicit SQL URLs retain SQL storage. `--db` remains an alias selector; conflicting `--store` and `--db` values are rejected. Configuration accepts `store_url` or legacy `db_url`; `REMIND_STORE` and `REMIND_DB_URL` are supported. Keep credentials out of committed configuration.

## Integrity and recovery

Each logical capture, batch, or apply commits its records, events, and retry receipt together. A process lock protects file transactions. A durable journal records the commit decision before installation; interrupted committed writes roll forward before normal operations resume. Unexpected external edits block recovery rather than being overwritten.

SQLite is a projection. Content changes after checkout, merge, or manual editing are validated and reconciled into that projection. Warm recall uses a pinned, read-only database snapshot; external changes update only affected projection rows. Invalid JSON, unresolved conflict markers, invalid references, or supersession cycles are actionable errors.

```bash
remind doctor
remind doctor --repair-indexes
```

Doctor diagnoses first. Repair rebuilds derived indexes; it does not invent facts or resolve semantic conflicts. Embedding fingerprints include provider/model identity, dimensions, and input version. Incompatible or unavailable embeddings degrade retrieval to lexical search until `remind re-embed --all` succeeds.

## Migration and backups

An existing local database migrates automatically on first selection. Remind locks migration, takes a consistent SQLite backup including WAL changes, stages all durable records, and verifies decoding and references before activating the text store. The original database and an ignored backup remain available. Explicit SQL URLs do not trigger migration.

```bash
remind export portable.json
remind export backup.json --mode backup
remind import portable.json
remind import backup.json --replace
```

Portable exports include all knowledge, soft-deleted records, relationships, evidence, provenance, and durable events. There is no episode-count truncation. Backups additionally include cached embeddings and operational statistics; indexes are reconstructed. Import adds new records, accepts identical records, and rejects differing records with the same identity. `--replace` explicitly restores the whole store.

To roll back the software, use a preserved database backup with an explicit `sqlite:///...` URL. Retain newer JSON records for deliberate reconciliation; an older binary backup cannot include later writes.

## Public workflow changes in 0.14

- New opaque IDs are full UUIDs. Existing IDs remain valid; abbreviated IDs must be unambiguous.
- Snapshots expose opaque revisions. Individual edits require `expected_revision`; apply requires an `expected_revisions` map for existing records it modifies. CLI equivalents are `--expected-revision` and `--revisions '{"id":"revision"}'`.
- `label` and `unlabel` accept a fact ID as an alias for its source episode. Include that episode's revision in `expected_revisions`; a fact revision does not authorize changing episode labels. Records created within the same changeset need no prior revision.
- Capture and apply accept stable idempotency keys. Retrying the same key/input returns the previous result; reusing a key for different input fails.
- Python recall returns `RecallResult`; use `.text` for prompt context or `.to_dict()` for structured results. Batch capture returns `BatchRememberResult.results`.
- Ordinary recall is read-only. `track_usage=True` / `--track-usage` updates operational usage state outside version-controlled records.
- Explicit label filters constrain retrieval and rendered content, including fact-cluster members. They do not partition clustering or entity identity; use separate stores for isolation.
- Explicit file entities capture relative paths, commit and content hashes. Changed or missing sources remain visible with annotations.
- Use `poll_events(cursor=...)`. A `reset_required` result means restart polling after checkout, merge, or a cache rebuild. Legacy numeric sequences are local to one projection.

MCP tools return JSON representations of structured results. REST provides the shared operations under `/api/v1/workflow/{remember,remember-batch,recall,apply,snapshot,events,doctor}` and structured recall at `/api/v1/query`. Record-editing REST requests use the revision in `If-Match`; conflicts return HTTP 409.
