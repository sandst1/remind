"""Memory storage backends."""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Optional
import json
import logging
import numpy as np
from pathlib import Path

from sqlalchemy import (
    create_engine,
    MetaData,
    Table,
    Column,
    String,
    Text,
    Float,
    Boolean,
    LargeBinary,
    DateTime,
    Integer,
    JSON,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    func,
    select,
    insert,
    update,
    delete,
    text,
    inspect,
    event,
)
from sqlalchemy.exc import IntegrityError, OperationalError

from remind.models import (
    Concept, Conflict, Episode, Evidence, Fact, Relation, RelationType,
    Entity, EntityType, EntityRelation, EpisodeType,
    canonicalize_entity_name,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Vector backend detection
# ---------------------------------------------------------------------------

_SQLITE_VEC_AVAILABLE: Optional[bool] = None
_SQLITE_LOAD_EXT_AVAILABLE: Optional[bool] = None
_PGVECTOR_AVAILABLE: Optional[bool] = None


def _sqlite_load_extension_supported() -> bool:
    """True if Python's sqlite3 can load extensions (sqlite-vec needs this).

    macOS and some other builds omit SQLITE_ENABLE_LOAD_EXTENSION; then
    Connection has no enable_load_extension and sqlite-vec cannot be used.
    """
    global _SQLITE_LOAD_EXT_AVAILABLE
    if _SQLITE_LOAD_EXT_AVAILABLE is not None:
        return _SQLITE_LOAD_EXT_AVAILABLE
    import sqlite3

    conn = sqlite3.connect(":memory:")
    try:
        _SQLITE_LOAD_EXT_AVAILABLE = hasattr(conn, "enable_load_extension")
    finally:
        conn.close()
    return _SQLITE_LOAD_EXT_AVAILABLE


def _check_sqlite_vec() -> bool:
    """Check if sqlite-vec is installable and can be loaded at runtime."""
    global _SQLITE_VEC_AVAILABLE
    if _SQLITE_VEC_AVAILABLE is not None:
        return _SQLITE_VEC_AVAILABLE
    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        _SQLITE_VEC_AVAILABLE = False
        return _SQLITE_VEC_AVAILABLE
    if not _sqlite_load_extension_supported():
        logger.info(
            "sqlite-vec is installed but SQLite was built without extension loading; "
            "using brute-force vector similarity instead"
        )
        _SQLITE_VEC_AVAILABLE = False
        return _SQLITE_VEC_AVAILABLE
    _SQLITE_VEC_AVAILABLE = True
    return _SQLITE_VEC_AVAILABLE


def _check_pgvector() -> bool:
    """Check if pgvector is importable."""
    global _PGVECTOR_AVAILABLE
    if _PGVECTOR_AVAILABLE is not None:
        return _PGVECTOR_AVAILABLE
    try:
        import pgvector.sqlalchemy  # noqa: F401
        _PGVECTOR_AVAILABLE = True
    except ImportError:
        _PGVECTOR_AVAILABLE = False
    return _PGVECTOR_AVAILABLE


# ---------------------------------------------------------------------------
# Lexical (keyword) backend detection
# ---------------------------------------------------------------------------

_SQLITE_FTS5_AVAILABLE: Optional[bool] = None


def _check_sqlite_fts5() -> bool:
    """Check if this Python's SQLite build has the FTS5 extension compiled in."""
    global _SQLITE_FTS5_AVAILABLE
    if _SQLITE_FTS5_AVAILABLE is not None:
        return _SQLITE_FTS5_AVAILABLE
    import sqlite3

    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE VIRTUAL TABLE _fts5_probe USING fts5(x)")
        _SQLITE_FTS5_AVAILABLE = True
    except sqlite3.OperationalError:
        _SQLITE_FTS5_AVAILABLE = False
    finally:
        conn.close()
    return _SQLITE_FTS5_AVAILABLE


def _fts5_match_query(raw_query: str) -> Optional[str]:
    """Turn free text into a safe FTS5 MATCH expression: each word becomes a
    quoted phrase token, ORed together so any matching term contributes to
    the bm25 rank. Returns None if there are no usable terms."""
    import re

    terms = re.findall(r"\w+", raw_query or "", re.UNICODE)
    if not terms:
        return None
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in terms)


def _lexical_label_where(
    table: str, labels: Optional[dict[str, str]], params: dict
) -> list[str]:
    """Build EXISTS clauses ANDing a label filter into a lexical query
    against *table* (main table name, e.g. "concepts"), mutating *params*
    in place with the bind values."""
    clauses = []
    if not labels:
        return clauses
    subject_type = _LABEL_SUBJECT_TYPE_BY_TABLE.get(table, table.rstrip("s"))
    params["subject_type"] = subject_type
    for i, (key, value) in enumerate(labels.items()):
        alias = f"ll{i}"
        clauses.append(
            f"EXISTS (SELECT 1 FROM labels {alias} WHERE {alias}.subject_type = :subject_type "
            f"AND {alias}.subject_id = {table}.id AND {alias}.key = :lex_label_key_{i} "
            f"AND {alias}.value = :lex_label_value_{i})"
        )
        params[f"lex_label_key_{i}"] = key
        params[f"lex_label_value_{i}"] = value
    return clauses


class MemoryStore(ABC):
    """
    Abstract base class for memory storage.

    Defines the interface for storing and retrieving concepts, episodes,
    and their relationships. Implementations can use SQLite, PostgreSQL, etc.
    """

    # Concept operations
    @abstractmethod
    def add_concept(self, concept: Concept) -> str:
        """Add a concept and return its ID."""
        ...

    @abstractmethod
    def get_concept(self, id: str) -> Optional[Concept]:
        """Get a concept by ID."""
        ...

    @abstractmethod
    def update_concept(self, concept: Concept) -> None:
        """Update an existing concept."""
        ...

    @abstractmethod
    def delete_concept(self, id: str) -> bool:
        """Soft delete a concept (set deleted_at timestamp).

        Returns True if concept was found and deleted.
        """
        ...

    @abstractmethod
    def restore_concept(self, id: str) -> bool:
        """Restore a soft-deleted concept (clear deleted_at timestamp).

        Returns True if concept was found and restored.
        """
        ...

    @abstractmethod
    def purge_concept(self, id: str) -> bool:
        """Permanently delete a concept.

        Returns True if concept was found and purged.
        """
        ...

    @abstractmethod
    def get_deleted_concepts(self, limit: Optional[int] = None) -> list[Concept]:
        """Get soft-deleted concepts."""
        ...

    @abstractmethod
    def get_all_concepts(self) -> list[Concept]:
        """Get all concepts."""
        ...

    @abstractmethod
    def get_concepts_summary(self) -> list[dict]:
        """Get a lightweight summary of all concepts (for consolidation prompts)."""
        ...

    @abstractmethod
    def get_fact_clusters_for_entity(self, entity_id: str) -> list[Concept]:
        """Get all fact_cluster concepts that reference episodes mentioning this entity."""
        ...

    @abstractmethod
    def get_concepts_for_entity(self, entity_id: str) -> list[Concept]:
        """Get all concepts (any type) that have this entity in their entity_ids."""
        ...

    @abstractmethod
    def get_concepts_by_type(self, concept_type: str) -> list[Concept]:
        """Get all concepts of a specific type (pattern, fact_cluster, legacy)."""
        ...

    # Fact operations
    @abstractmethod
    def add_fact(self, fact: Fact) -> str:
        """Add a fact row and return its ID."""
        ...

    @abstractmethod
    def add_facts_batch(self, facts: list[Fact]) -> list[str]:
        """Add multiple facts in a single transaction. Returns fact IDs."""
        ...

    @abstractmethod
    def get_fact(self, id: str) -> Optional[Fact]:
        """Get a fact by ID."""
        ...

    @abstractmethod
    def get_facts(
        self,
        cluster_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        active_only: bool = False,
        as_of: Optional[datetime] = None,
        limit: int = 500,
    ) -> list[Fact]:
        """Get facts, optionally filtered.

        Args:
            cluster_id: Only facts belonging to this fact_cluster concept.
            entity_id: Only facts referencing this entity.
            active_only: Only facts with an open validity window (valid_to IS NULL).
            as_of: Only facts valid at this point in time
                   (valid_from <= as_of < valid_to). Overrides active_only.
            limit: Maximum number of facts returned (newest valid_from first).
        """
        ...

    @abstractmethod
    def update_fact(self, fact: Fact) -> None:
        """Update an existing fact row."""
        ...

    @abstractmethod
    def supersede_fact(
        self,
        old_fact_id: str,
        new_fact_id: str,
        at: Optional[datetime] = None,
    ) -> bool:
        """Structurally supersede a fact: close the old fact's validity
        window (valid_to = *at*) and point it at its replacement.

        Returns True if the old fact was found and superseded.
        """
        ...

    @abstractmethod
    def delete_facts_for_cluster(self, cluster_id: str) -> int:
        """Delete all facts belonging to a cluster. Returns count deleted."""
        ...

    # Conflict operations
    @abstractmethod
    def add_conflict(self, conflict: Conflict) -> str:
        """Add a conflict row and return its ID."""
        ...

    @abstractmethod
    def get_conflict(self, id: str) -> Optional[Conflict]:
        """Get a conflict by ID."""
        ...

    @abstractmethod
    def get_conflicts(
        self,
        status: Optional[str] = None,
        kind: Optional[str] = None,
        concept_id: Optional[str] = None,
        limit: int = 200,
    ) -> list[Conflict]:
        """Get conflicts, optionally filtered by status, kind, or involved concept."""
        ...

    @abstractmethod
    def update_conflict(self, conflict: Conflict) -> None:
        """Update an existing conflict row."""
        ...

    @abstractmethod
    def count_conflicts(self, status: str = "open") -> int:
        """Count conflicts with the given status."""
        ...

    @abstractmethod
    def find_open_conflict_for_facts(self, fact_a_id: str, fact_b_id: str) -> Optional[Conflict]:
        """Find an open fact conflict involving this pair (order-insensitive)."""
        ...

    # Evidence operations
    @abstractmethod
    def add_evidence(self, evidence: Evidence) -> str:
        """Add an evidence link and return its ID."""
        ...

    @abstractmethod
    def get_evidence(self, id: str) -> Optional[Evidence]:
        """Get an evidence link by ID."""
        ...

    @abstractmethod
    def get_evidence_for_concept(self, concept_id: str) -> list[Evidence]:
        """Get all evidence links for a concept."""
        ...

    @abstractmethod
    def get_evidence_for_episode(self, episode_id: str) -> list[Evidence]:
        """Get all evidence links for an episode."""
        ...

    @abstractmethod
    def delete_evidence(self, id: str) -> bool:
        """Delete an evidence link. Returns True if found and deleted."""
        ...

    @abstractmethod
    def delete_evidence_for_concept(self, concept_id: str) -> int:
        """Delete all evidence links for a concept. Returns count deleted."""
        ...

    # Embedding-based retrieval
    @abstractmethod
    def find_by_embedding(
        self, embedding: list[float], k: int = 5, labels: Optional[dict[str, str]] = None
    ) -> list[tuple[Concept, float]]:
        """Find concepts by embedding similarity. Returns (concept, similarity) pairs.

        Args:
            labels: If set, only concepts matching ALL given key=value label
                filters are considered. Applied as a pre-filter, not a
                post-filter, so top-k results are not under-returned.
        """
        ...

    @abstractmethod
    def find_episodes_by_embedding(
        self, embedding: list[float], k: int = 5, labels: Optional[dict[str, str]] = None
    ) -> list[tuple["Episode", float]]:
        """Find episodes by embedding similarity. Returns (episode, similarity) pairs.

        Args:
            labels: If set, only episodes matching ALL given key=value label
                filters are considered.
        """
        ...

    @abstractmethod
    def find_entities_by_embedding(
        self, embedding: list[float], k: int = 5, labels: Optional[dict[str, str]] = None
    ) -> list[tuple[Entity, float]]:
        """Find entities by embedding similarity. Returns (entity, similarity) pairs.

        Args:
            labels: If set, only entities matching ALL given key=value label
                filters are considered.
        """
        ...

    @abstractmethod
    def find_facts_by_embedding(
        self,
        embedding: list[float],
        k: int = 10,
        cluster_id: Optional[str] = None,
        active_only: bool = True,
    ) -> list[tuple[Fact, float]]:
        """Find facts by embedding similarity. Returns (fact, similarity) pairs.
        
        Args:
            embedding: Query embedding vector.
            k: Maximum number of facts to return.
            cluster_id: If set, only search within this fact cluster.
            active_only: If True (default), only return facts with valid_to IS NULL.
        """
        ...

    # Lexical (keyword) retrieval — fused with embedding results via RRF
    def search_concepts_lexical(
        self, query: str, k: int = 10, labels: Optional[dict[str, str]] = None
    ) -> list[tuple[Concept, float]]:
        """Keyword search over concept title+summary. Returns (concept, score)
        pairs ranked best-first. Empty list if no lexical backend is active
        or the query has no searchable terms. Default: unsupported (base
        class); overridden by backends that detect a lexical index."""
        return []

    def search_episodes_lexical(
        self, query: str, k: int = 10, labels: Optional[dict[str, str]] = None
    ) -> list[tuple["Episode", float]]:
        """Keyword search over episode title+content. Returns (episode, score)
        pairs ranked best-first. See :meth:`search_concepts_lexical`."""
        return []

    @abstractmethod
    def find_facts_by_entity_name(
        self,
        bare_name: str,
        active_only: bool = True,
        exclude_cluster_id: Optional[str] = None,
        limit: int = 20,
    ) -> list[Fact]:
        """Find active facts whose entity_ids contain a bare entity name.

        Matches any entity ID of the form ``<type>:<bare_name>`` regardless of
        type prefix, so ``person:alice``, ``concept:alice``, and
        ``project:alice`` are all returned when *bare_name* is ``alice``.

        Args:
            bare_name: Name without type prefix (e.g. ``"alice"``).
            active_only: Only facts with an open validity window (valid_to IS NULL).
            exclude_cluster_id: Skip facts belonging to this cluster.
            limit: Maximum number of facts to return.
        """
        ...

    # Graph traversal
    @abstractmethod
    def get_related(
        self,
        concept_id: str,
        relation_types: Optional[list[RelationType]] = None,
        depth: int = 1
    ) -> list[tuple[Concept, Relation]]:
        """Get related concepts with their relations."""
        ...

    @abstractmethod
    def get_incoming_relations(
        self,
        concept_id: str,
        relation_type: RelationType,
    ) -> list[tuple[Concept, Relation]]:
        """Get concepts that have a relation pointing *to* this concept.

        Returns (source_concept, relation) pairs where relation.target_id
        equals *concept_id* and relation.type equals *relation_type*.
        Soft-deleted source concepts are excluded.
        """
        ...

    # Episode operations
    @abstractmethod
    def add_episode(self, episode: Episode) -> str:
        """Add an episode and return its ID."""
        ...

    @abstractmethod
    def add_episodes_batch(self, episodes: list[Episode]) -> list[str]:
        """Add multiple episodes in a single transaction.

        Returns list of episode IDs. More efficient than calling add_episode()
        in a loop because it uses a single connection and transaction.
        """
        ...

    @abstractmethod
    def get_episode(self, id: str, include_deleted: bool = False) -> Optional[Episode]:
        """Get an episode by ID."""
        ...

    @abstractmethod
    def get_episodes_batch(self, ids: list[str]) -> list[Episode]:
        """Get multiple episodes by ID in a single query.

        Returns episodes in no guaranteed order. Missing or soft-deleted
        IDs are silently skipped.
        """
        ...

    @abstractmethod
    def update_episode(self, episode: Episode) -> None:
        """Update an existing episode."""
        ...

    @abstractmethod
    def delete_episode(self, id: str) -> bool:
        """Soft delete an episode (set deleted_at timestamp).

        Also cleans up:
        - Mention records (episode <-> entity links)
        - Entity relations derived from this episode

        Returns True if episode was found and deleted.
        """
        ...

    @abstractmethod
    def restore_episode(self, id: str) -> bool:
        """Restore a soft-deleted episode (clear deleted_at timestamp).

        Returns True if episode was found and restored.
        """
        ...

    @abstractmethod
    def purge_episode(self, id: str) -> bool:
        """Permanently delete an episode.

        Also cleans up:
        - Mention records (episode <-> entity links)
        - Entity relations derived from this episode

        Returns True if episode was found and purged.
        """
        ...

    @abstractmethod
    def get_deleted_episodes(self, limit: int = 50) -> list[Episode]:
        """Get soft-deleted episodes."""
        ...

    @abstractmethod
    def get_unconsolidated_episodes(self, limit: int = 10) -> list[Episode]:
        """Get episodes that haven't been consolidated yet."""
        ...

    @abstractmethod
    def count_unconsolidated_episodes(self) -> int:
        """Count episodes that haven't been consolidated yet."""
        ...

    @abstractmethod
    def get_recent_episodes(self, limit: int = 10) -> list[Episode]:
        """Get most recent episodes."""
        ...

    @abstractmethod
    def get_all_episodes(self) -> list[Episode]:
        """Get all non-deleted episodes."""
        ...

    @abstractmethod
    def get_episodes_by_date_range(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100
    ) -> list[Episode]:
        """Get episodes within a date range."""
        ...

    # Entity operations
    @abstractmethod
    def add_entity(self, entity: Entity) -> str:
        """Add an entity and return its ID. Updates if exists."""
        ...

    @abstractmethod
    def update_entity(self, entity: Entity) -> None:
        """Update an existing entity (including embedding)."""
        ...

    @abstractmethod
    def get_entity(self, id: str) -> Optional[Entity]:
        """Get an entity by ID."""
        ...

    @abstractmethod
    def get_entities_by_type(self, entity_type: EntityType) -> list[Entity]:
        """Get all entities of a given type."""
        ...

    @abstractmethod
    def get_all_entities(self) -> list[Entity]:
        """Get all entities."""
        ...

    @abstractmethod
    def find_entity_by_name(self, name: str) -> Optional[Entity]:
        """Find an entity by display name, case-insensitive.

        Searches for entities whose display_name matches the given name
        after normalization (lowercase, trimmed). Returns the first match
        if multiple exist.

        Args:
            name: The entity name to search for

        Returns:
            Entity if found, None otherwise
        """
        ...

    @abstractmethod
    def search_entities_by_words(
        self, words: list[str], limit: int = 10
    ) -> list[tuple[Entity, int]]:
        """Find entities whose display_name or ID contains any of the given words.

        Performs case-insensitive substring matching. Returns entities sorted by
        the number of distinct query words that matched (descending), then by
        mention count as a tiebreaker.

        Args:
            words: Query words to match (should be pre-filtered, e.g. 3+ chars).
            limit: Maximum entities to return.

        Returns:
            List of (entity, match_count) tuples where match_count is the number
            of query words found in the entity's name or ID.
        """
        ...

    @abstractmethod
    def merge_duplicate_entities(self) -> dict[str, int]:
        """Merge duplicate entities that canonicalize to the same name.

        Returns:
            Stats including number of merged groups and rows reassigned/deleted.
        """
        ...

    # Mention operations (episode <-> entity)
    @abstractmethod
    def add_mention(self, episode_id: str, entity_id: str) -> None:
        """Create a mention link between episode and entity."""
        ...

    @abstractmethod
    def get_episodes_mentioning(self, entity_id: str, limit: int = 50) -> list[Episode]:
        """Get all episodes that mention an entity."""
        ...

    @abstractmethod
    def find_episodes_by_entities(
        self,
        entity_ids: list[str],
        exclude_episode_ids: Optional[set[str]] = None,
        limit: int = 20,
    ) -> list[Episode]:
        """Find episodes that share any of the given entities.

        Args:
            entity_ids: Entity IDs to search for.
            exclude_episode_ids: Episode IDs to exclude from results.
            limit: Maximum episodes to return.

        Returns:
            Episodes ordered by number of matching entities (descending).
        """
        ...

    @abstractmethod
    def get_entities_mentioned_in(self, episode_id: str) -> list[Entity]:
        """Get all entities mentioned in an episode."""
        ...

    @abstractmethod
    def delete_mentions_for_episode(self, episode_id: str) -> int:
        """Delete all mention records for an episode. Returns count deleted."""
        ...

    @abstractmethod
    def get_unextracted_episodes(self, limit: int = 100) -> list[Episode]:
        """Get episodes that haven't had entity extraction performed."""
        ...

    @abstractmethod
    def get_episodes_by_type(self, episode_type: str, limit: int = 50) -> list[Episode]:
        """Get episodes of a specific type."""
        ...

    # Entity relation operations
    @abstractmethod
    def add_entity_relation(self, relation: EntityRelation) -> None:
        """Add an entity relation. Updates if same source/target/type exists."""
        ...

    @abstractmethod
    def get_entity_relations(self, entity_id: str) -> list[EntityRelation]:
        """Get all relations involving an entity (as source or target)."""
        ...

    @abstractmethod
    def get_entity_relations_from(self, entity_id: str) -> list[EntityRelation]:
        """Get relations where entity is the source (outgoing relations)."""
        ...

    @abstractmethod
    def delete_entity_relations_from_episode(self, episode_id: str) -> int:
        """Delete all entity relations derived from an episode. Returns count deleted."""
        ...

    @abstractmethod
    def get_existing_relation_pairs(self, entity_ids: list[str]) -> set[tuple[str, str]]:
        """Get pairs of entities that already have relations between them.

        Returns set of (source_id, target_id) tuples for pairs that have any relation.
        Both directions are included (if A->B exists, returns (A,B)).
        """
        ...

    @abstractmethod
    def get_unextracted_relation_episodes(self, limit: int = 100) -> list[Episode]:
        """Get episodes that have entities but haven't had relation extraction performed."""
        ...

    # Bulk operations for reconsolidation
    @abstractmethod
    def delete_all_concepts(self) -> int:
        """Delete all concepts and their relations. Returns count deleted."""
        ...

    @abstractmethod
    def delete_all_entities(self) -> int:
        """Delete all entities, mentions, and entity relations. Returns count deleted."""
        ...

    @abstractmethod
    def reset_episode_flags(self) -> int:
        """Reset consolidated, entities_extracted, and relations_extracted flags on all episodes.

        Also clears entity_ids and concepts_activated lists.
        Returns count of episodes reset.
        """
        ...

    @abstractmethod
    def clear_embeddings(
        self,
        include_episodes: bool = True,
        include_concepts: bool = True,
        include_entities: bool = True,
    ) -> dict[str, int]:
        """Clear stored embeddings for selected record types.

        Returns counts for cleared concept, episode, and entity rows.
        """
        ...

    # Decay operations
    @abstractmethod
    def decay_concepts(
        self,
        decay_rate: float,
        skip_recently_accessed_seconds: int = 60,
    ) -> int:
        """Apply linear decay to all concepts.

        Concepts accessed within skip_recently_accessed_seconds are exempt from
        this decay pass so that just-recalled concepts are not immediately penalised.

        Args:
            decay_rate: How much decay_factor decreases per interval
            skip_recently_accessed_seconds: Grace period in seconds; concepts whose
                last_accessed timestamp is within this window are not decayed.

        Returns:
            Count of concepts that were decayed
        """
        ...

    # Metadata operations
    @abstractmethod
    def get_metadata(self, key: str) -> Optional[str]:
        """Get a metadata value by key. Returns None if not found."""
        ...

    @abstractmethod
    def set_metadata(self, key: str, value: str) -> None:
        """Set a metadata value. Updates if key exists."""
        ...

    # Change feed
    def emit_event(
        self,
        kind: str,
        subject_type: str,
        subject_id: str,
        payload: Optional[dict] = None,
    ) -> None:
        """Append a row to the change feed. When called inside
        ``store.transaction()``, the event commits atomically with whatever
        write it describes. Default: no-op (base class); overridden by
        backends that maintain the ``events`` table."""
        return None

    def get_events(
        self,
        since_seq: int = 0,
        limit: int = 100,
        kind: Optional[str] = None,
    ) -> list[dict]:
        """Read change-feed events with ``seq > since_seq``, oldest first.
        Default: empty (base class); overridden by backends that maintain
        the ``events`` table."""
        return []

    # Statistics
    @abstractmethod
    def get_stats(self) -> dict:
        """Get storage statistics."""
        ...

    # Transaction support
    @abstractmethod
    def transaction(self):
        """Context manager for transaction scope.
        
        All operations within the context are executed in a single transaction.
        Commits on successful exit, rolls back on exception.
        
        Usage:
            with store.transaction():
                store.add_episode(ep1)
                store.add_episode(ep2)
                # Both commit together, or neither does
        """
        ...


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a_arr = np.array(a)
    b_arr = np.array(b)

    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))


def _label_escalation_steps(k: int, allowed_ids: Optional[set]) -> list[int]:
    """Fetch-size steps for a sqlite-vec KNN search that is post-filtered by
    a resolved label ID set. Without a filter, a single 2k pass matches
    prior (unfiltered) behavior. With a filter, escalate the candidate pool
    (k, 4k, 16k relative to the initial 2k) since matches may be sparse
    among the label-filtered subset.
    """
    if allowed_ids is None:
        return [k * 2]
    return [k * 2, k * 8, k * 32]


_LABEL_SUBJECT_TYPE_BY_TABLE = {"concepts": "concept", "episodes": "episode", "entities": "entity"}


def _pgvector_label_query(
    table: str,
    select_cols: str,
    vec_param: str,
    k: int,
    labels: Optional[dict[str, str]],
    order_by: str,
) -> tuple[str, dict]:
    """Build a pgvector query string + params with an optional labels
    EXISTS pre-filter, ANDed across all given key=value pairs. Runs inside
    the main ORDER BY ... LIMIT query, so it is index-assisted and exact
    (no post-filter under-return like the sqlite-vec path needs)."""
    params: dict = {"query": vec_param, "k": k * 2}
    where_clauses = [f"{table}.embedding_vec IS NOT NULL"]
    if labels:
        subject_type = _LABEL_SUBJECT_TYPE_BY_TABLE[table]
        params["subject_type"] = subject_type
        for i, (key, value) in enumerate(labels.items()):
            alias = f"l{i}"
            where_clauses.append(
                f"EXISTS (SELECT 1 FROM labels {alias} WHERE {alias}.subject_type = :subject_type "
                f"AND {alias}.subject_id = {table}.id AND {alias}.key = :label_key_{i} "
                f"AND {alias}.value = :label_value_{i})"
            )
            params[f"label_key_{i}"] = key
            params[f"label_value_{i}"] = value
    query = (
        f"SELECT {select_cols} FROM {table} WHERE " + " AND ".join(where_clauses)
        + f" ORDER BY {order_by} LIMIT :k"
    )
    return query, params


# ---------------------------------------------------------------------------
# Table definitions
# ---------------------------------------------------------------------------

metadata_obj = MetaData()

concepts_table = Table(
    "concepts", metadata_obj,
    Column("id", String, primary_key=True),
    Column("title", Text, nullable=True),
    Column("summary", Text, nullable=True),
    Column("data", JSON, nullable=False),
    Column("embedding", LargeBinary, nullable=True),
    Column("created_at", DateTime, server_default=func.now()),
    Column("updated_at", DateTime, server_default=func.now()),
)

episodes_table = Table(
    "episodes", metadata_obj,
    Column("id", String, primary_key=True),
    Column("title", Text, nullable=True),
    Column("content", Text, nullable=True),
    Column("data", JSON, nullable=False),
    Column("consolidated", Boolean, default=False),
    Column("timestamp", DateTime, server_default=func.now()),
    Column("embedding", LargeBinary, nullable=True),
)

relations_table = Table(
    "relations", metadata_obj,
    Column("source_id", String, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False),
    Column("target_id", String, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False),
    Column("type", String, nullable=False),
    Column("strength", Float, default=0.5),
    Column("context", Text, nullable=True),
    PrimaryKeyConstraint("source_id", "target_id", "type"),
)

entities_table = Table(
    "entities", metadata_obj,
    Column("id", String, primary_key=True),
    Column("type", String, nullable=False),
    Column("display_name", Text, nullable=True),
    Column("data", JSON, nullable=True),
    Column("created_at", DateTime, server_default=func.now()),
    Column("embedding", LargeBinary, nullable=True),
)

mentions_table = Table(
    "mentions", metadata_obj,
    Column("episode_id", String, ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False),
    Column("entity_id", String, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
    Column("created_at", DateTime, server_default=func.now()),
    PrimaryKeyConstraint("episode_id", "entity_id"),
)

entity_relations_table = Table(
    "entity_relations", metadata_obj,
    Column("source_id", String, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
    Column("target_id", String, ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
    Column("relation_type", String, nullable=False),
    Column("strength", Float, default=0.5),
    Column("context", Text, nullable=True),
    Column("source_episode_id", String, ForeignKey("episodes.id", ondelete="SET NULL"), nullable=True),
    Column("created_at", DateTime, server_default=func.now()),
    Column("episode_count", Integer, default=1),
    Column("source_episode_ids", Text, default="[]"),
    PrimaryKeyConstraint("source_id", "target_id", "relation_type"),
)

facts_table = Table(
    "facts", metadata_obj,
    Column("id", String, primary_key=True),
    Column("cluster_id", String, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=True),
    Column("statement", Text, nullable=False),
    Column("attribute", Text, nullable=True),
    Column("entity_ids", Text, default="[]"),
    Column("valid_from", DateTime, nullable=False),
    Column("valid_to", DateTime, nullable=True),
    Column("superseded_by", String, nullable=True),
    Column("asserted_by", Text, nullable=True),
    Column("source_ref", Text, nullable=True),
    Column("source_episode_id", String, nullable=True),
    Column("created_at", DateTime, server_default=func.now()),
    Column("embedding", LargeBinary, nullable=True),
)

conflicts_table = Table(
    "conflicts", metadata_obj,
    Column("id", String, primary_key=True),
    Column("kind", String, nullable=False, server_default="fact"),
    Column("fact_a_id", String, nullable=True),
    Column("fact_b_id", String, nullable=True),
    Column("concept_ids", Text, default="[]"),
    Column("description", Text, nullable=False, server_default=""),
    Column("severity", String, nullable=False, server_default="medium"),
    Column("status", String, nullable=False, server_default="open"),
    Column("created_at", DateTime, server_default=func.now()),
    Column("resolved_at", DateTime, nullable=True),
    Column("resolution_note", Text, nullable=True),
    Column("resolved_by", Text, nullable=True),
    Column("winning_fact_id", String, nullable=True),
)

evidence_table = Table(
    "evidence", metadata_obj,
    Column("id", String, primary_key=True),
    Column("episode_id", String, ForeignKey("episodes.id", ondelete="CASCADE"), nullable=False),
    Column("concept_id", String, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=False),
    Column("link_type", String, nullable=False, server_default="supports"),
    Column("strength", Float, default=0.5),
    Column("note", Text, nullable=True),
    Column("created_at", DateTime, server_default=func.now()),
)

Index("idx_evidence_episode", evidence_table.c.episode_id)
Index("idx_evidence_concept", evidence_table.c.concept_id)

metadata_table = Table(
    "metadata", metadata_obj,
    Column("key", String, primary_key=True),
    Column("value", Text, nullable=True),
)

# Generic key/value labels on any subject (episode | concept | fact). This is
# the substrate's only grouping primitive — deliberately more general than
# the "topic" concept it replaced, and designed to be pushed down as a
# pre-filter into vector search rather than applied as a post-filter.
labels_table = Table(
    "labels", metadata_obj,
    Column("subject_type", String, nullable=False),
    Column("subject_id", String, nullable=False),
    Column("key", String, nullable=False),
    Column("value", String, nullable=False),
    PrimaryKeyConstraint("subject_type", "subject_id", "key", "value"),
)
Index("idx_labels_kv", labels_table.c.key, labels_table.c.value)
Index("idx_labels_subject", labels_table.c.subject_type, labels_table.c.subject_id)

# Append-only change feed. Written inside the same transaction as the write
# it describes, so consolidation daemons and sync layers can poll
# "since seq N" instead of re-scanning `snapshot pending` on every tick.
events_table = Table(
    "events", metadata_obj,
    Column("seq", Integer, primary_key=True, autoincrement=True),
    Column("ts", DateTime, server_default=func.now()),
    Column("kind", String, nullable=False),  # remembered | superseded | conflict_opened | conflict_resolved | conflict_dismissed | concept_created | concept_updated | labeled | unlabeled | deleted | restored | processed
    Column("subject_type", String, nullable=False),  # episode | concept | fact | conflict
    Column("subject_id", String, nullable=False),
    Column("payload", JSON, nullable=True),
)
Index("idx_events_kind", events_table.c.kind)
Index("idx_events_subject", events_table.c.subject_type, events_table.c.subject_id)

# Indexes defined separately to keep Table definitions clean
Index("idx_episodes_consolidated", episodes_table.c.consolidated)
Index("idx_episodes_timestamp", episodes_table.c.timestamp)
Index("idx_relations_source", relations_table.c.source_id)
Index("idx_relations_target", relations_table.c.target_id)
Index("idx_relations_type", relations_table.c.type)
Index("idx_entities_type", entities_table.c.type)
Index("idx_mentions_episode", mentions_table.c.episode_id)
Index("idx_mentions_entity", mentions_table.c.entity_id)
Index("idx_entity_relations_source", entity_relations_table.c.source_id)
Index("idx_entity_relations_target", entity_relations_table.c.target_id)
Index("idx_entity_relations_episode", entity_relations_table.c.source_episode_id)
Index("idx_facts_cluster", facts_table.c.cluster_id)
Index("idx_facts_valid_to", facts_table.c.valid_to)
Index("idx_facts_valid_from", facts_table.c.valid_from)
Index("idx_conflicts_status", conflicts_table.c.status)


def _is_sqlite(engine) -> bool:
    return engine.dialect.name == "sqlite"


def _has_column_in_list(columns: list[dict], col_name: str) -> bool:
    """Check if a column exists in an inspector column list."""
    return any(c["name"] == col_name for c in columns)


def _embedding_to_bytes(embedding: Optional[list[float]]) -> Optional[bytes]:
    if not embedding:
        return None
    return np.array(embedding, dtype=np.float32).tobytes()


def _bytes_to_embedding(blob: Optional[bytes]) -> Optional[list[float]]:
    if not blob:
        return None
    return np.frombuffer(blob, dtype=np.float32).tolist()


def _parse_json(value) -> dict:
    """Parse a JSON column value. SQLAlchemy returns dicts for native JSON
    backends (PG, MySQL) but strings for SQLite."""
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return value
    return json.loads(value)


def _dump_json(value) -> str:
    """Always serialize to a string. SQLAlchemy JSON columns accept both
    dicts and strings depending on the dialect, but strings work everywhere."""
    if isinstance(value, str):
        return value
    return json.dumps(value)


class SQLAlchemyMemoryStore(MemoryStore):
    """
    SQLAlchemy-based memory store.

    Supports SQLite (default), PostgreSQL, MySQL, and any database
    backend supported by SQLAlchemy.

    When sqlite-vec or pgvector is available, embedding search uses native
    vector indexes instead of brute-force Python cosine similarity.
    """

    def __init__(self, db_url: str = "sqlite:///memory.db"):
        import threading
        
        if db_url.endswith(".db") and "://" not in db_url:
            db_url = f"sqlite:///{db_url}"

        self.db_url = db_url
        self.engine = create_engine(db_url)

        # Vector backend state
        self._vec_backend: Optional[str] = None  # "sqlite-vec", "pgvector", or None
        self._vec_dimensions: Optional[int] = None

        # Lexical backend state
        self._fts_backend: Optional[str] = None  # "fts5", "tsvector", "fulltext", or None

        # Transaction state (thread-local for safety)
        self._local = threading.local()

        self._setup_vector_backend()
        self._setup_lexical_backend()
        self._init_db()

    def _setup_vector_backend(self) -> None:
        """Detect and configure the appropriate vector search backend."""
        if _is_sqlite(self.engine) and _check_sqlite_vec():
            import sqlite_vec

            @event.listens_for(self.engine, "connect")
            def _load_sqlite_vec(dbapi_conn, connection_record):
                dbapi_conn.enable_load_extension(True)
                sqlite_vec.load(dbapi_conn)
                dbapi_conn.enable_load_extension(False)

            self._vec_backend = "sqlite-vec"
            logger.info("Vector backend: sqlite-vec")

        elif not _is_sqlite(self.engine) and _check_pgvector():
            self._vec_backend = "pgvector"
            logger.info("Vector backend: pgvector")

        else:
            backend = "SQLite" if _is_sqlite(self.engine) else self.engine.dialect.name
            logger.info(f"Vector backend: brute-force (no native vector extension for {backend})")

    def _setup_lexical_backend(self) -> None:
        """Detect the appropriate lexical (keyword/BM25) search backend."""
        if _is_sqlite(self.engine) and _check_sqlite_fts5():
            self._fts_backend = "fts5"
            logger.info("Lexical backend: SQLite FTS5")
        elif self.engine.dialect.name == "postgresql":
            self._fts_backend = "tsvector"
            logger.info("Lexical backend: PostgreSQL tsvector")
        elif self.engine.dialect.name == "mysql":
            self._fts_backend = "fulltext"
            logger.info("Lexical backend: MySQL FULLTEXT")
        else:
            logger.info(f"Lexical backend: none available for {self.engine.dialect.name}")

    @contextmanager
    def _connect(self):
        """Context manager that yields a connection and auto-commits on success.
        
        When inside a transaction() block, reuses the transaction connection
        and defers commit until the transaction exits.
        """
        # Check if we're inside a transaction
        tx_conn = getattr(self._local, 'tx_conn', None)
        if tx_conn is not None:
            # Reuse transaction connection, don't commit
            yield tx_conn
            return
        
        # Normal mode: create new connection and auto-commit
        with self.engine.connect() as conn:
            yield conn
            conn.commit()
    
    @contextmanager
    def transaction(self):
        """Context manager for transaction scope.
        
        All operations within the context are executed in a single transaction.
        Commits on successful exit, rolls back on exception.
        
        Usage:
            with store.transaction():
                store.add_episode(ep1)
                store.add_episode(ep2)
                # Both commit together, or neither does
        """
        # Prevent nested transactions
        if getattr(self._local, 'tx_conn', None) is not None:
            raise RuntimeError("Nested transactions are not supported")
        
        with self.engine.begin() as conn:
            self._local.tx_conn = conn
            try:
                yield
                # engine.begin() auto-commits on successful context exit
            finally:
                self._local.tx_conn = None

    def _init_db(self):
        """Create tables and run additive migrations."""
        metadata_obj.create_all(self.engine)
        self._run_migrations()
        self._init_vector_tables()
        self._init_lexical_index()
        self._backfill_facts_from_specifics()
        self._backfill_conflicts_from_concepts()
        self._backfill_evidence_from_source_episodes()
        self._backfill_labels_from_topics()

    def _backfill_facts_from_specifics(self) -> None:
        """One-time backfill: turn legacy fact_cluster `specifics` strings
        into first-class fact rows.

        Legacy facts get valid_from = cluster.created_at (best available
        approximation) and inherit the cluster's entity_ids. Guarded by a
        metadata flag so it runs once per database.
        """
        if self.get_metadata("facts_backfill_v1"):
            return

        facts: list[Fact] = []
        for concept in self.get_all_concepts():
            if concept.concept_type not in ("fact_cluster", "fact") or not concept.specifics:
                continue
            if self.get_facts(cluster_id=concept.id, limit=1):
                continue  # already has fact rows
            for statement in concept.specifics:
                facts.append(Fact(
                    cluster_id=concept.id,
                    statement=statement,
                    entity_ids=list(concept.entity_ids),
                    valid_from=concept.created_at,
                    created_at=concept.created_at,
                ))

        if facts:
            self.add_facts_batch(facts)
            logger.info(f"Backfilled {len(facts)} facts from legacy fact_cluster specifics")

        self.set_metadata("facts_backfill_v1", "done")

    def _backfill_conflicts_from_concepts(self) -> None:
        """One-time backfill: turn legacy `Concept.conflicts` dicts into
        open conflict rows. Fact statements are matched to fact rows by
        exact statement when possible. Guarded by a metadata flag.
        """
        if self.get_metadata("conflicts_backfill_v1"):
            return

        migrated = 0
        for concept in self.get_all_concepts():
            if not concept.conflicts:
                continue
            cluster_facts = self.get_facts(cluster_id=concept.id, limit=1000)
            by_statement = {f.statement: f for f in cluster_facts}
            for entry in concept.conflicts:
                fact_a = entry.get("fact_a", "")
                fact_b = entry.get("fact_b", "")
                reason = entry.get("reason", "")
                description = f'"{fact_a}" vs "{fact_b}"'
                if reason:
                    description += f": {reason}"
                fact_a_id = entry.get("fact_a_id") or (by_statement[fact_a].id if fact_a in by_statement else None)
                fact_b_id = entry.get("fact_b_id") or (by_statement[fact_b].id if fact_b in by_statement else None)
                created_at = datetime.now()
                if entry.get("detected_at"):
                    try:
                        created_at = datetime.fromisoformat(entry["detected_at"])
                    except ValueError:
                        pass
                self.add_conflict(Conflict(
                    kind="fact",
                    fact_a_id=fact_a_id,
                    fact_b_id=fact_b_id,
                    concept_ids=[concept.id],
                    description=description,
                    created_at=created_at,
                ))
                migrated += 1

        if migrated:
            logger.info(f"Backfilled {migrated} conflicts from legacy concept conflict dicts")

        self.set_metadata("conflicts_backfill_v1", "done")

    def _backfill_evidence_from_source_episodes(self) -> None:
        """One-time backfill: convert legacy Concept.source_episodes lists
        to Evidence links with type='supports' and default strength.
        Guarded by a metadata flag so it runs once per database.
        """
        if self.get_metadata("evidence_backfill_v1"):
            return

        migrated = 0
        for concept in self.get_all_concepts():
            if not concept.source_episodes:
                continue
            # Check if evidence already exists for this concept
            existing_evidence = self.get_evidence_for_concept(concept.id)
            existing_episode_ids = {e.episode_id for e in existing_evidence}
            
            for episode_id in concept.source_episodes:
                if episode_id in existing_episode_ids:
                    continue
                evidence = Evidence(
                    episode_id=episode_id,
                    concept_id=concept.id,
                    link_type="supports",
                    strength=0.5,
                )
                self.add_evidence(evidence)
                migrated += 1

        if migrated:
            logger.info(f"Backfilled {migrated} evidence links from legacy source_episodes")

        self.set_metadata("evidence_backfill_v1", "done")

    def _backfill_labels_from_topics(self) -> None:
        """One-time backfill: convert legacy topic assignments into labels
        (key="topic", value=<topic name or id>), mirror them into the JSON
        `data` blob, then drop the now-unused `topics` table and the
        `topic_id` columns on episodes/concepts. Guarded by a metadata flag
        so it runs once per database.

        Uses raw schema inspection rather than the SQLAlchemy metadata
        (which no longer declares these objects) so it still finds them on
        pre-0.13 databases.
        """
        if self.get_metadata("labels_backfill_v1"):
            return

        insp = inspect(self.engine)
        has_topics_table = insp.has_table("topics")
        has_ep_topic_col = insp.has_table("episodes") and any(
            c["name"] == "topic_id" for c in insp.get_columns("episodes")
        )
        has_concept_topic_col = insp.has_table("concepts") and any(
            c["name"] == "topic_id" for c in insp.get_columns("concepts")
        )

        if has_topics_table or has_ep_topic_col or has_concept_topic_col:
            topic_names: dict[str, str] = {}
            if has_topics_table:
                with self.engine.connect() as conn:
                    rows = conn.execute(text("SELECT id, name FROM topics")).fetchall()
                topic_names = {r[0]: r[1] for r in rows if r[1]}

            migrated = 0
            if has_ep_topic_col:
                migrated += self._migrate_topic_column_to_labels(
                    "episode", episodes_table, topic_names
                )
            if has_concept_topic_col:
                migrated += self._migrate_topic_column_to_labels(
                    "concept", concepts_table, topic_names
                )

            if migrated:
                logger.info(f"Backfilled {migrated} topic assignments into labels")

            self._drop_legacy_topic_schema(has_topics_table, has_ep_topic_col, has_concept_topic_col)

        self.set_metadata("labels_backfill_v1", "done")

    def _migrate_topic_column_to_labels(
        self, subject_type: str, table: Table, topic_names: dict[str, str]
    ) -> int:
        """Copy a legacy topic_id column's values into the labels table and
        the JSON data blob for one subject type. Returns rows migrated."""
        migrated = 0
        with self._connect() as conn:
            rows = conn.execute(text(
                f"SELECT id, data, topic_id FROM {table.name} "
                f"WHERE topic_id IS NOT NULL AND topic_id != ''"
            )).fetchall()
            for row_id, data_raw, topic_id in rows:
                value = topic_names.get(topic_id, topic_id)
                if not value:
                    continue
                data = _parse_json(data_raw)
                labels = data.get("labels") or {}
                topic_values = labels.setdefault("topic", [])
                if value not in topic_values:
                    topic_values.append(value)
                data["labels"] = labels
                conn.execute(
                    table.update().where(table.c.id == row_id).values(data=_dump_json(data))
                )
                self._sync_labels(conn, subject_type, row_id, labels)
                migrated += 1
        return migrated

    def _drop_legacy_topic_schema(
        self, has_topics_table: bool, has_ep_topic_col: bool, has_concept_topic_col: bool
    ) -> None:
        """Best-effort removal of the pre-0.13 topics table/columns.

        Wrapped so failures (e.g. SQLite < 3.35 lacking DROP COLUMN) are
        tolerated: the column becomes a harmless orphan since it is no
        longer part of the SQLAlchemy metadata either way.
        """
        dialect = self.engine.dialect.name
        with self.engine.connect() as conn:
            for stmt in (
                "DROP INDEX IF EXISTS idx_episodes_topic_id",
                "DROP INDEX IF EXISTS idx_concepts_topic_id",
            ):
                try:
                    conn.execute(text(stmt))
                    conn.commit()
                except Exception:
                    conn.rollback()

            if has_ep_topic_col:
                try:
                    conn.execute(text("ALTER TABLE episodes DROP COLUMN topic_id"))
                    conn.commit()
                    logger.info("Migration: Dropped topic_id column from episodes table")
                except Exception:
                    conn.rollback()
                    logger.warning(
                        "Migration: Could not drop episodes.topic_id (unsupported by this "
                        "database version); leaving it as an unused column"
                    )

            if has_concept_topic_col:
                try:
                    conn.execute(text("ALTER TABLE concepts DROP COLUMN topic_id"))
                    conn.commit()
                    logger.info("Migration: Dropped topic_id column from concepts table")
                except Exception:
                    conn.rollback()
                    logger.warning(
                        "Migration: Could not drop concepts.topic_id (unsupported by this "
                        "database version); leaving it as an unused column"
                    )

            if has_topics_table:
                try:
                    conn.execute(text("DROP TABLE IF EXISTS topics"))
                    conn.commit()
                    logger.info("Migration: Dropped topics table")
                except Exception:
                    conn.rollback()
                    logger.warning("Migration: Could not drop topics table")

    def _run_migrations(self):
        """Run additive schema migrations for backwards compatibility."""
        insp = inspect(self.engine)

        def _has_column(table_name: str, col_name: str) -> bool:
            cols = {c["name"] for c in insp.get_columns(table_name)}
            return col_name in cols

        with self.engine.connect() as conn:
            if not _has_column("concepts", "title"):
                conn.execute(text("ALTER TABLE concepts ADD COLUMN title TEXT"))
                conn.commit()
                logger.info("Migration: Added title column to concepts table")

            if not _has_column("episodes", "title"):
                conn.execute(text("ALTER TABLE episodes ADD COLUMN title TEXT"))
                conn.commit()
                logger.info("Migration: Added title column to episodes table")

            if not _has_column("entity_relations", "episode_count"):
                conn.execute(text("ALTER TABLE entity_relations ADD COLUMN episode_count INTEGER DEFAULT 1"))
                conn.commit()
                logger.info("Migration: Added episode_count column to entity_relations table")

            if not _has_column("entity_relations", "source_episode_ids"):
                conn.execute(text("ALTER TABLE entity_relations ADD COLUMN source_episode_ids TEXT DEFAULT '[]'"))
                conn.commit()
                logger.info("Migration: Added source_episode_ids column to entity_relations table")

            if not _has_column("episodes", "embedding"):
                conn.execute(text("ALTER TABLE episodes ADD COLUMN embedding BYTEA" if not _is_sqlite(self.engine) else "ALTER TABLE episodes ADD COLUMN embedding BLOB"))
                conn.commit()
                logger.info("Migration: Added embedding column to episodes table")

            try:
                entity_count = conn.execute(text("SELECT COUNT(*) FROM entities")).scalar()
                mention_count = conn.execute(text("SELECT COUNT(*) FROM mentions")).scalar()
                logger.debug(f"Schema v2: {entity_count} entities, {mention_count} mentions")
            except OperationalError:
                logger.warning("Entity tables not found, will be created on next init")

    def _init_vector_tables(self) -> None:
        """Create vector index tables/extensions if a vector backend is active."""
        if self._vec_backend is None:
            return

        stored_dims = self.get_metadata("embedding_dimensions")
        if stored_dims:
            self._vec_dimensions = int(stored_dims)

        if self._vec_backend == "sqlite-vec":
            self._init_sqlite_vec_tables()
        elif self._vec_backend == "pgvector":
            self._init_pgvector()

    def _init_sqlite_vec_tables(self) -> None:
        """Create sqlite-vec vec0 virtual tables if they don't exist."""
        if not self._vec_dimensions:
            return

        dims = self._vec_dimensions
        with self.engine.connect() as conn:
            existing = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='vec_concepts'")
            ).fetchone()
            if not existing:
                conn.execute(text(
                    f"CREATE VIRTUAL TABLE vec_concepts USING vec0("
                    f"concept_id TEXT PRIMARY KEY, "
                    f"embedding float[{dims}] distance_metric=cosine)"
                ))
                self._backfill_sqlite_vec(conn, "concepts")
                conn.commit()
                logger.info(f"Created vec_concepts table ({dims} dims)")

            existing = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='vec_episodes'")
            ).fetchone()
            if not existing:
                conn.execute(text(
                    f"CREATE VIRTUAL TABLE vec_episodes USING vec0("
                    f"episode_id TEXT PRIMARY KEY, "
                    f"embedding float[{dims}] distance_metric=cosine)"
                ))
                self._backfill_sqlite_vec(conn, "episodes")
                conn.commit()
                logger.info(f"Created vec_episodes table ({dims} dims)")

            existing = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='vec_facts'")
            ).fetchone()
            if not existing:
                conn.execute(text(
                    f"CREATE VIRTUAL TABLE vec_facts USING vec0("
                    f"fact_id TEXT PRIMARY KEY, "
                    f"embedding float[{dims}] distance_metric=cosine)"
                ))
                self._backfill_sqlite_vec(conn, "facts")
                conn.commit()
                logger.info(f"Created vec_facts table ({dims} dims)")

    def _backfill_sqlite_vec(self, conn, table: str) -> None:
        """Populate a vec0 table from existing embeddings in the main table."""
        if table == "concepts":
            rows = conn.execute(
                select(concepts_table.c.id, concepts_table.c.embedding)
                .where(concepts_table.c.embedding.isnot(None))
            ).fetchall()
            for row in rows:
                if row.embedding:
                    vec = np.frombuffer(row.embedding, dtype=np.float32)
                    conn.execute(text(
                        "INSERT INTO vec_concepts(concept_id, embedding) VALUES (:id, :emb)"
                    ), {"id": row.id, "emb": vec.tobytes()})
        elif table == "episodes":
            rows = conn.execute(
                select(episodes_table.c.id, episodes_table.c.embedding)
                .where(episodes_table.c.embedding.isnot(None))
            ).fetchall()
            for row in rows:
                if row.embedding:
                    vec = np.frombuffer(row.embedding, dtype=np.float32)
                    conn.execute(text(
                        "INSERT INTO vec_episodes(episode_id, embedding) VALUES (:id, :emb)"
                    ), {"id": row.id, "emb": vec.tobytes()})
        elif table == "facts":
            rows = conn.execute(
                select(facts_table.c.id, facts_table.c.embedding)
                .where(facts_table.c.embedding.isnot(None))
            ).fetchall()
            for row in rows:
                if row.embedding:
                    vec = np.frombuffer(row.embedding, dtype=np.float32)
                    conn.execute(text(
                        "INSERT INTO vec_facts(fact_id, embedding) VALUES (:id, :emb)"
                    ), {"id": row.id, "emb": vec.tobytes()})

    # pgvector HNSW indexes support at most 2000 dimensions.
    _PGVECTOR_HNSW_MAX_DIMS = 2000

    def _init_pgvector(self) -> None:
        """Enable pgvector extension and create vector columns/indexes if needed."""
        with self.engine.connect() as conn:
            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.commit()
            except Exception as e:
                logger.warning(f"Could not create pgvector extension: {e}")
                self._vec_backend = None
                return

            insp = inspect(self.engine)
            dims = self._vec_dimensions

            for table_name in ("concepts", "episodes", "facts"):
                if _has_column_in_list(insp.get_columns(table_name), "embedding_vec"):
                    continue
                if not dims:
                    continue

                conn.execute(text(
                    f"ALTER TABLE {table_name} ADD COLUMN embedding_vec vector({dims})"
                ))
                self._backfill_pgvector(conn, table_name)
                conn.commit()

                if dims <= self._PGVECTOR_HNSW_MAX_DIMS:
                    conn.execute(text(
                        f"CREATE INDEX IF NOT EXISTS idx_{table_name}_embedding_vec "
                        f"ON {table_name} USING hnsw (embedding_vec vector_cosine_ops)"
                    ))
                    conn.commit()
                else:
                    logger.warning(
                        f"Skipping HNSW index on {table_name}.embedding_vec: "
                        f"{dims} dims exceeds pgvector limit of {self._PGVECTOR_HNSW_MAX_DIMS}. "
                        f"Vector search will use exact (sequential) scan."
                    )

                logger.info(f"Created {table_name}.embedding_vec column ({dims} dims)")

    def _backfill_pgvector(self, conn, table: str) -> None:
        """Convert existing LargeBinary embeddings to pgvector format."""
        if table == "concepts":
            main_table = concepts_table
        elif table == "episodes":
            main_table = episodes_table
        else:
            main_table = facts_table
        rows = conn.execute(
            select(main_table.c.id, main_table.c.embedding)
            .where(main_table.c.embedding.isnot(None))
        ).fetchall()
        for row in rows:
            if row.embedding:
                vec = _bytes_to_embedding(row.embedding)
                vec_str = "[" + ",".join(str(v) for v in vec) + "]"
                conn.execute(text(
                    f"UPDATE {table} SET embedding_vec = :vec WHERE id = :id"
                ), {"vec": vec_str, "id": row.id})

    # ------------------------------------------------------------------
    # Lexical (keyword/BM25) index setup
    # ------------------------------------------------------------------

    def _init_lexical_index(self) -> None:
        """Create the lexical search index if a backend was detected."""
        if self._fts_backend == "fts5":
            self._init_sqlite_fts_tables()
        elif self._fts_backend == "tsvector":
            self._init_postgres_tsvector()
        elif self._fts_backend == "fulltext":
            self._init_mysql_fulltext()

    def _init_sqlite_fts_tables(self) -> None:
        """Create standalone FTS5 virtual tables, manually kept in sync on
        write (mirrors the vec0 sync pattern used for embeddings)."""
        with self.engine.connect() as conn:
            existing = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='fts_concepts'")
            ).fetchone()
            if not existing:
                conn.execute(text(
                    "CREATE VIRTUAL TABLE fts_concepts USING fts5(concept_id UNINDEXED, text)"
                ))
                self._backfill_sqlite_fts(conn, "concepts")
                conn.commit()
                logger.info("Created fts_concepts table (FTS5)")

            existing = conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name='fts_episodes'")
            ).fetchone()
            if not existing:
                conn.execute(text(
                    "CREATE VIRTUAL TABLE fts_episodes USING fts5(episode_id UNINDEXED, text)"
                ))
                self._backfill_sqlite_fts(conn, "episodes")
                conn.commit()
                logger.info("Created fts_episodes table (FTS5)")

    def _backfill_sqlite_fts(self, conn, table: str) -> None:
        """Populate a fts5 table from existing rows in the main table."""
        if table == "concepts":
            rows = conn.execute(
                select(concepts_table.c.id, concepts_table.c.title, concepts_table.c.summary)
            ).fetchall()
            for row in rows:
                text_val = " ".join(filter(None, [row.title, row.summary])).strip()
                if text_val:
                    conn.execute(text(
                        "INSERT INTO fts_concepts(concept_id, text) VALUES (:id, :text)"
                    ), {"id": row.id, "text": text_val})
        elif table == "episodes":
            rows = conn.execute(
                select(episodes_table.c.id, episodes_table.c.title, episodes_table.c.content)
            ).fetchall()
            for row in rows:
                text_val = " ".join(filter(None, [row.title, row.content])).strip()
                if text_val:
                    conn.execute(text(
                        "INSERT INTO fts_episodes(episode_id, text) VALUES (:id, :text)"
                    ), {"id": row.id, "text": text_val})

    def _init_postgres_tsvector(self) -> None:
        """Add a generated, auto-maintained tsvector column + GIN index.

        Being a STORED generated column, Postgres keeps it in sync on every
        write with no application-level hook needed.
        """
        insp = inspect(self.engine)
        with self.engine.connect() as conn:
            for table_name, cols in (
                ("concepts", ("title", "summary")),
                ("episodes", ("title", "content")),
            ):
                if _has_column_in_list(insp.get_columns(table_name), "text_search"):
                    continue
                col_expr = " || ' ' || ".join(f"coalesce({c}, '')" for c in cols)
                try:
                    conn.execute(text(
                        f"ALTER TABLE {table_name} ADD COLUMN text_search tsvector "
                        f"GENERATED ALWAYS AS (to_tsvector('english', {col_expr})) STORED"
                    ))
                    conn.execute(text(
                        f"CREATE INDEX IF NOT EXISTS idx_{table_name}_text_search "
                        f"ON {table_name} USING GIN (text_search)"
                    ))
                    conn.commit()
                    logger.info(f"Created {table_name}.text_search tsvector column + GIN index")
                except Exception as e:
                    logger.warning(f"Could not create tsvector index on {table_name}: {e}")
                    conn.rollback()

    def _init_mysql_fulltext(self) -> None:
        """Add FULLTEXT indexes on existing text columns. MySQL maintains
        these automatically on write, same as any other index."""
        with self.engine.connect() as conn:
            for table_name, idx_name, cols in (
                ("concepts", "ft_concepts", "title, summary"),
                ("episodes", "ft_episodes", "title, content"),
            ):
                try:
                    existing = conn.execute(text(
                        "SELECT COUNT(*) FROM information_schema.statistics "
                        "WHERE table_schema = DATABASE() AND table_name = :t AND index_name = :i"
                    ), {"t": table_name, "i": idx_name}).scalar()
                    if not existing:
                        conn.execute(text(
                            f"ALTER TABLE {table_name} ADD FULLTEXT INDEX {idx_name} ({cols})"
                        ))
                        conn.commit()
                        logger.info(f"Created FULLTEXT index {idx_name} on {table_name}")
                except Exception as e:
                    logger.warning(f"Could not create FULLTEXT index on {table_name}: {e}")
                    conn.rollback()

    def _upsert_fts_concept(self, conn, concept_id: str, title: Optional[str], summary: Optional[str]) -> None:
        """Sync a concept's searchable text into the FTS5 index (SQLite only;
        Postgres/MySQL maintain their indexes automatically on write)."""
        if self._fts_backend != "fts5":
            return
        text_val = " ".join(filter(None, [title, summary])).strip()
        conn.execute(text("DELETE FROM fts_concepts WHERE concept_id = :id"), {"id": concept_id})
        if text_val:
            conn.execute(text(
                "INSERT INTO fts_concepts(concept_id, text) VALUES (:id, :text)"
            ), {"id": concept_id, "text": text_val})

    def _upsert_fts_episode(self, conn, episode_id: str, title: Optional[str], content: Optional[str]) -> None:
        """Sync an episode's searchable text into the FTS5 index (SQLite only)."""
        if self._fts_backend != "fts5":
            return
        text_val = " ".join(filter(None, [title, content])).strip()
        conn.execute(text("DELETE FROM fts_episodes WHERE episode_id = :id"), {"id": episode_id})
        if text_val:
            conn.execute(text(
                "INSERT INTO fts_episodes(episode_id, text) VALUES (:id, :text)"
            ), {"id": episode_id, "text": text_val})

    def _delete_fts_concept(self, conn, concept_id: str) -> None:
        if self._fts_backend == "fts5":
            conn.execute(text("DELETE FROM fts_concepts WHERE concept_id = :id"), {"id": concept_id})

    def _delete_fts_episode(self, conn, episode_id: str) -> None:
        if self._fts_backend == "fts5":
            conn.execute(text("DELETE FROM fts_episodes WHERE episode_id = :id"), {"id": episode_id})

    def search_concepts_lexical(
        self, query: str, k: int = 10, labels: Optional[dict[str, str]] = None
    ) -> list[tuple[Concept, float]]:
        if not query or not query.strip():
            return []
        if self._fts_backend == "fts5":
            return self._search_concepts_fts5(query, k, labels)
        elif self._fts_backend == "tsvector":
            return self._search_concepts_tsvector(query, k, labels)
        elif self._fts_backend == "fulltext":
            return self._search_concepts_mysql_fulltext(query, k, labels)
        return []

    def _search_concepts_fts5(
        self, query: str, k: int, labels: Optional[dict[str, str]]
    ) -> list[tuple[Concept, float]]:
        match = _fts5_match_query(query)
        if not match:
            return []
        allowed_ids = self._resolve_label_ids("concept", labels)
        if allowed_ids is not None and not allowed_ids:
            return []
        with self._connect() as conn:
            results: list[tuple[Concept, float]] = []
            for fetch_k in _label_escalation_steps(k, allowed_ids):
                try:
                    rows = conn.execute(text(
                        "SELECT concept_id, rank FROM fts_concepts WHERE fts_concepts MATCH :q "
                        "ORDER BY rank LIMIT :k"
                    ), {"q": match, "k": fetch_k}).fetchall()
                except Exception:
                    logger.warning("FTS5 concept search failed", exc_info=True)
                    return []

                results = []
                for i, row in enumerate(rows):
                    if allowed_ids is not None and row.concept_id not in allowed_ids:
                        continue
                    concept = self._get_concept_from_conn(conn, row.concept_id)
                    if concept is None:
                        continue
                    results.append((concept, 1.0 / (1.0 + i)))

                if len(results) >= k or len(rows) < fetch_k:
                    break

            return results[:k]

    def _search_concepts_tsvector(
        self, query: str, k: int, labels: Optional[dict[str, str]]
    ) -> list[tuple[Concept, float]]:
        with self._connect() as conn:
            params: dict = {"q": query, "k": k}
            where_clauses = ["text_search @@ plainto_tsquery('english', :q)"]
            where_clauses.extend(_lexical_label_where("concepts", labels, params))
            query_sql = (
                "SELECT id, data, embedding, "
                "ts_rank_cd(text_search, plainto_tsquery('english', :q)) AS score "
                "FROM concepts WHERE " + " AND ".join(where_clauses)
                + " ORDER BY score DESC LIMIT :k"
            )
            try:
                rows = conn.execute(text(query_sql), params).fetchall()
            except Exception:
                logger.warning("tsvector concept search failed", exc_info=True)
                return []

            results = []
            for row in rows:
                data = _parse_json(row.data)
                if data.get("deleted_at"):
                    continue
                if row.embedding:
                    data["embedding"] = _bytes_to_embedding(row.embedding)
                results.append((Concept.from_dict(data), float(row.score)))
            return results[:k]

    def _search_concepts_mysql_fulltext(
        self, query: str, k: int, labels: Optional[dict[str, str]]
    ) -> list[tuple[Concept, float]]:
        with self._connect() as conn:
            params: dict = {"q": query, "k": k}
            where_clauses = ["MATCH(title, summary) AGAINST (:q IN NATURAL LANGUAGE MODE)"]
            where_clauses.extend(_lexical_label_where("concepts", labels, params))
            query_sql = (
                "SELECT id, data, embedding, "
                "MATCH(title, summary) AGAINST (:q IN NATURAL LANGUAGE MODE) AS score "
                "FROM concepts WHERE " + " AND ".join(where_clauses)
                + " ORDER BY score DESC LIMIT :k"
            )
            try:
                rows = conn.execute(text(query_sql), params).fetchall()
            except Exception:
                logger.warning("MySQL FULLTEXT concept search failed", exc_info=True)
                return []

            results = []
            for row in rows:
                data = _parse_json(row.data)
                if data.get("deleted_at"):
                    continue
                if row.embedding:
                    data["embedding"] = _bytes_to_embedding(row.embedding)
                results.append((Concept.from_dict(data), float(row.score)))
            return results[:k]

    def search_episodes_lexical(
        self, query: str, k: int = 10, labels: Optional[dict[str, str]] = None
    ) -> list[tuple[Episode, float]]:
        if not query or not query.strip():
            return []
        if self._fts_backend == "fts5":
            return self._search_episodes_fts5(query, k, labels)
        elif self._fts_backend == "tsvector":
            return self._search_episodes_tsvector(query, k, labels)
        elif self._fts_backend == "fulltext":
            return self._search_episodes_mysql_fulltext(query, k, labels)
        return []

    def _search_episodes_fts5(
        self, query: str, k: int, labels: Optional[dict[str, str]]
    ) -> list[tuple[Episode, float]]:
        match = _fts5_match_query(query)
        if not match:
            return []
        allowed_ids = self._resolve_label_ids("episode", labels)
        if allowed_ids is not None and not allowed_ids:
            return []
        with self._connect() as conn:
            results: list[tuple[Episode, float]] = []
            for fetch_k in _label_escalation_steps(k, allowed_ids):
                try:
                    rows = conn.execute(text(
                        "SELECT episode_id, rank FROM fts_episodes WHERE fts_episodes MATCH :q "
                        "ORDER BY rank LIMIT :k"
                    ), {"q": match, "k": fetch_k}).fetchall()
                except Exception:
                    logger.warning("FTS5 episode search failed", exc_info=True)
                    return []

                results = []
                for i, row in enumerate(rows):
                    if allowed_ids is not None and row.episode_id not in allowed_ids:
                        continue
                    ep = self._get_episode_from_conn(conn, row.episode_id)
                    if ep is None:
                        continue
                    results.append((ep, 1.0 / (1.0 + i)))

                if len(results) >= k or len(rows) < fetch_k:
                    break

            return results[:k]

    def _search_episodes_tsvector(
        self, query: str, k: int, labels: Optional[dict[str, str]]
    ) -> list[tuple[Episode, float]]:
        with self._connect() as conn:
            params: dict = {"q": query, "k": k}
            where_clauses = ["text_search @@ plainto_tsquery('english', :q)"]
            where_clauses.extend(_lexical_label_where("episodes", labels, params))
            query_sql = (
                "SELECT id, data, embedding, "
                "ts_rank_cd(text_search, plainto_tsquery('english', :q)) AS score "
                "FROM episodes WHERE " + " AND ".join(where_clauses)
                + " ORDER BY score DESC LIMIT :k"
            )
            try:
                rows = conn.execute(text(query_sql), params).fetchall()
            except Exception:
                logger.warning("tsvector episode search failed", exc_info=True)
                return []

            results = []
            for row in rows:
                data = _parse_json(row.data)
                if data.get("deleted_at"):
                    continue
                ep = Episode.from_dict(data)
                if row.embedding:
                    ep.embedding = _bytes_to_embedding(row.embedding)
                results.append((ep, float(row.score)))
            return results[:k]

    def _search_episodes_mysql_fulltext(
        self, query: str, k: int, labels: Optional[dict[str, str]]
    ) -> list[tuple[Episode, float]]:
        with self._connect() as conn:
            params: dict = {"q": query, "k": k}
            where_clauses = ["MATCH(title, content) AGAINST (:q IN NATURAL LANGUAGE MODE)"]
            where_clauses.extend(_lexical_label_where("episodes", labels, params))
            query_sql = (
                "SELECT id, data, embedding, "
                "MATCH(title, content) AGAINST (:q IN NATURAL LANGUAGE MODE) AS score "
                "FROM episodes WHERE " + " AND ".join(where_clauses)
                + " ORDER BY score DESC LIMIT :k"
            )
            try:
                rows = conn.execute(text(query_sql), params).fetchall()
            except Exception:
                logger.warning("MySQL FULLTEXT episode search failed", exc_info=True)
                return []

            results = []
            for row in rows:
                data = _parse_json(row.data)
                if data.get("deleted_at"):
                    continue
                ep = Episode.from_dict(data)
                if row.embedding:
                    ep.embedding = _bytes_to_embedding(row.embedding)
                results.append((ep, float(row.score)))
            return results[:k]

    def _ensure_vec_dimensions(self, embedding: list[float], conn=None) -> None:
        """Record embedding dimensions on first use and create vector tables.

        When called from within an existing connection context, pass *conn* to
        avoid opening a nested connection (which deadlocks on SQLite).

        When *conn* is the active transaction connection (inside
        ``store.transaction()``), this method persists dims to metadata but
        intentionally skips ``_init_vector_tables()`` and never calls
        ``conn.commit()``.  Calling ``commit()`` inside a SQLAlchemy
        ``engine.begin()`` context manager closes the transaction and causes
        all subsequent operations to raise "Can't operate on closed
        transaction inside context manager".  The caller (``apply()``) must
        pre-initialise vector tables *before* opening the transaction via
        ``_ensure_vec_dimensions(emb, conn=None)``.
        """
        dims = len(embedding)
        if self._vec_dimensions == dims:
            return

        if self._vec_dimensions is not None and self._vec_dimensions != dims:
            logger.warning(
                f"Embedding dimensions changed ({self._vec_dimensions} -> {dims}), "
                f"recreating vector tables"
            )
            self._drop_vector_tables(conn=conn)

        self._vec_dimensions = dims

        # Detect whether conn is the outer transaction connection.
        # Regular _connect() connections must still commit; only the
        # engine.begin() transaction connection must not.
        inside_transaction = (conn is not None and
                              getattr(self._local, 'tx_conn', None) is conn)

        if conn is not None:
            # Use SELECT-first to avoid IntegrityError, which would deactivate
            # the transaction in SQLAlchemy 2.x (same problem as conn.rollback()).
            existing = conn.execute(
                select(metadata_table.c.value)
                .where(metadata_table.c.key == "embedding_dimensions")
            ).fetchone()
            if existing:
                conn.execute(
                    metadata_table.update()
                    .where(metadata_table.c.key == "embedding_dimensions")
                    .values(value=str(dims))
                )
            else:
                conn.execute(
                    metadata_table.insert().values(key="embedding_dimensions", value=str(dims))
                )
            if not inside_transaction:
                conn.commit()
        else:
            self.set_metadata("embedding_dimensions", str(dims))

        if not inside_transaction:
            self._init_vector_tables()

    def _drop_vector_tables(self, conn=None) -> None:
        """Drop vector index tables for recreation."""
        if conn is not None:
            if self._vec_backend == "sqlite-vec":
                conn.execute(text("DROP TABLE IF EXISTS vec_concepts"))
                conn.execute(text("DROP TABLE IF EXISTS vec_episodes"))
            elif self._vec_backend == "pgvector":
                conn.execute(text("ALTER TABLE concepts DROP COLUMN IF EXISTS embedding_vec"))
                conn.execute(text("ALTER TABLE episodes DROP COLUMN IF EXISTS embedding_vec"))
            # Only commit if we're not inside the outer transaction.
            inside_transaction = (getattr(self._local, 'tx_conn', None) is conn)
            if not inside_transaction:
                conn.commit()
            return

        with self.engine.connect() as fresh_conn:
            if self._vec_backend == "sqlite-vec":
                fresh_conn.execute(text("DROP TABLE IF EXISTS vec_concepts"))
                fresh_conn.execute(text("DROP TABLE IF EXISTS vec_episodes"))
            elif self._vec_backend == "pgvector":
                fresh_conn.execute(text("ALTER TABLE concepts DROP COLUMN IF EXISTS embedding_vec"))
                fresh_conn.execute(text("ALTER TABLE episodes DROP COLUMN IF EXISTS embedding_vec"))
            fresh_conn.commit()

    def _upsert_vec_concept(self, conn, concept_id: str, embedding: Optional[list[float]]) -> None:
        """Sync a concept embedding to the vector index."""
        if self._vec_backend is None or embedding is None:
            return
        self._ensure_vec_dimensions(embedding, conn=conn)

        if self._vec_backend == "sqlite-vec":
            vec = np.array(embedding, dtype=np.float32)
            conn.execute(text(
                "DELETE FROM vec_concepts WHERE concept_id = :id"
            ), {"id": concept_id})
            conn.execute(text(
                "INSERT INTO vec_concepts(concept_id, embedding) VALUES (:id, :emb)"
            ), {"id": concept_id, "emb": vec.tobytes()})
        elif self._vec_backend == "pgvector":
            vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
            conn.execute(text(
                "UPDATE concepts SET embedding_vec = :vec WHERE id = :id"
            ), {"vec": vec_str, "id": concept_id})

    def _upsert_vec_episode(self, conn, episode_id: str, embedding: Optional[list[float]]) -> None:
        """Sync an episode embedding to the vector index."""
        if self._vec_backend is None or embedding is None:
            return
        self._ensure_vec_dimensions(embedding, conn=conn)

        if self._vec_backend == "sqlite-vec":
            vec = np.array(embedding, dtype=np.float32)
            conn.execute(text(
                "DELETE FROM vec_episodes WHERE episode_id = :id"
            ), {"id": episode_id})
            conn.execute(text(
                "INSERT INTO vec_episodes(episode_id, embedding) VALUES (:id, :emb)"
            ), {"id": episode_id, "emb": vec.tobytes()})
        elif self._vec_backend == "pgvector":
            vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
            conn.execute(text(
                "UPDATE episodes SET embedding_vec = :vec WHERE id = :id"
            ), {"vec": vec_str, "id": episode_id})

    def _delete_vec_concept(self, conn, concept_id: str) -> None:
        """Remove a concept from the vector index."""
        if self._vec_backend == "sqlite-vec" and self._vec_dimensions:
            conn.execute(text(
                "DELETE FROM vec_concepts WHERE concept_id = :id"
            ), {"id": concept_id})

    def _delete_vec_episode(self, conn, episode_id: str) -> None:
        """Remove an episode from the vector index."""
        if self._vec_backend == "sqlite-vec" and self._vec_dimensions:
            conn.execute(text(
                "DELETE FROM vec_episodes WHERE episode_id = :id"
            ), {"id": episode_id})

    # ------------------------------------------------------------------
    # Concept operations
    # ------------------------------------------------------------------

    def add_concept(self, concept: Concept) -> str:
        with self._connect() as conn:
            data = concept.to_dict()
            conn.execute(
                concepts_table.insert().values(
                    id=concept.id,
                    title=concept.title,
                    summary=concept.summary,
                    data=_dump_json(data),
                    embedding=_embedding_to_bytes(concept.embedding),
                    created_at=concept.created_at,
                    updated_at=concept.updated_at,
                )
            )
            self._sync_relations(conn, concept)
            self._sync_labels(conn, "concept", concept.id, concept.labels)
            self._upsert_vec_concept(conn, concept.id, concept.embedding)
            self._upsert_fts_concept(conn, concept.id, concept.title, concept.summary)
        return concept.id

    def _sync_relations(self, conn, concept: Concept):
        conn.execute(
            relations_table.delete().where(relations_table.c.source_id == concept.id)
        )
        for rel in concept.relations:
            conn.execute(
                relations_table.insert().values(
                    source_id=concept.id,
                    target_id=rel.target_id,
                    type=rel.type.value,
                    strength=rel.strength,
                    context=rel.context,
                )
            )

    def add_relation(self, concept_id: str, relation: Relation) -> None:
        """Add a single relation from a concept to another concept."""
        with self._connect() as conn:
            conn.execute(
                relations_table.insert().values(
                    source_id=concept_id,
                    target_id=relation.target_id,
                    type=relation.type.value,
                    strength=relation.strength,
                    context=relation.context,
                )
            )
            # Also update the concept's in-memory relations list
            row = conn.execute(
                select(concepts_table.c.data).where(concepts_table.c.id == concept_id)
            ).fetchone()
            if row:
                data = _parse_json(row.data)
                relations_list = data.get("relations", [])
                relations_list.append(relation.to_dict())
                data["relations"] = relations_list
                conn.execute(
                    concepts_table.update()
                    .where(concepts_table.c.id == concept_id)
                    .values(data=_dump_json(data))
                )

    def get_concept(self, id: str, include_deleted: bool = False) -> Optional[Concept]:
        with self._connect() as conn:
            row = conn.execute(
                select(concepts_table.c.data, concepts_table.c.embedding)
                .where(concepts_table.c.id == id)
            ).fetchone()
            if not row:
                return None
            data = _parse_json(row.data)
            if data.get("deleted_at") and not include_deleted:
                return None
            if row.embedding:
                data["embedding"] = _bytes_to_embedding(row.embedding)
            return Concept.from_dict(data)

    def update_concept(self, concept: Concept) -> None:
        with self._connect() as conn:
            data = concept.to_dict()
            conn.execute(
                concepts_table.update()
                .where(concepts_table.c.id == concept.id)
                .values(
                    title=concept.title,
                    summary=concept.summary,
                    data=_dump_json(data),
                    embedding=_embedding_to_bytes(concept.embedding),
                    updated_at=concept.updated_at,
                )
            )
            self._sync_relations(conn, concept)
            self._sync_labels(conn, "concept", concept.id, concept.labels)
            self._upsert_vec_concept(conn, concept.id, concept.embedding)
            self._upsert_fts_concept(conn, concept.id, concept.title, concept.summary)

    def delete_concept(self, id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                select(concepts_table.c.data).where(concepts_table.c.id == id)
            ).fetchone()
            if not row:
                return False
            data = _parse_json(row.data)
            if data.get("deleted_at"):
                return False
            data["deleted_at"] = datetime.now().isoformat()
            conn.execute(
                concepts_table.update()
                .where(concepts_table.c.id == id)
                .values(data=_dump_json(data))
            )
            return True

    def restore_concept(self, id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                select(concepts_table.c.data).where(concepts_table.c.id == id)
            ).fetchone()
            if not row:
                return False
            data = _parse_json(row.data)
            if not data.get("deleted_at"):
                return False
            data.pop("deleted_at", None)
            conn.execute(
                concepts_table.update()
                .where(concepts_table.c.id == id)
                .values(data=_dump_json(data))
            )
            return True

    def purge_concept(self, id: str) -> bool:
        with self._connect() as conn:
            self._delete_vec_concept(conn, id)
            self._delete_fts_concept(conn, id)
            # SQLite doesn't enforce FK cascades by default; clean up fact rows explicitly
            conn.execute(facts_table.delete().where(facts_table.c.cluster_id == id))
            conn.execute(
                labels_table.delete().where(
                    (labels_table.c.subject_type == "concept") & (labels_table.c.subject_id == id)
                )
            )
            result = conn.execute(
                concepts_table.delete().where(concepts_table.c.id == id)
            )
            return result.rowcount > 0

    def get_deleted_concepts(self, limit: Optional[int] = None) -> list[Concept]:
        with self._connect() as conn:
            rows = conn.execute(
                select(concepts_table.c.data, concepts_table.c.embedding)
            ).fetchall()
            concepts = []
            for row in rows:
                data = _parse_json(row.data)
                if not data.get("deleted_at"):
                    continue
                if row.embedding:
                    data["embedding"] = _bytes_to_embedding(row.embedding)
                concepts.append(Concept.from_dict(data))
            concepts.sort(key=lambda c: c.deleted_at or "", reverse=True)
            return concepts[:limit] if limit is not None else concepts

    def get_all_concepts(self) -> list[Concept]:
        with self._connect() as conn:
            rows = conn.execute(
                select(concepts_table.c.data, concepts_table.c.embedding)
            ).fetchall()
            concepts = []
            for row in rows:
                data = _parse_json(row.data)
                if data.get("deleted_at"):
                    continue
                if row.embedding:
                    data["embedding"] = _bytes_to_embedding(row.embedding)
                concepts.append(Concept.from_dict(data))
            return concepts

    def get_concepts_summary(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                select(
                    concepts_table.c.id,
                    concepts_table.c.title,
                    concepts_table.c.summary,
                    concepts_table.c.data,
                )
            ).fetchall()
            results = []
            for row in rows:
                data = _parse_json(row.data)
                if data.get("deleted_at"):
                    continue
                results.append({
                    "id": row.id,
                    "title": row.title,
                    "summary": row.summary,
                    "labels": data.get("labels") or {},
                    "confidence": data.get("confidence"),
                    "instance_count": data.get("instance_count"),
                    "tags": data.get("tags", []),
                })
            return results

    # ------------------------------------------------------------------
    # Embedding-based retrieval
    # ------------------------------------------------------------------

    def _resolve_label_ids(
        self, subject_type: str, labels: Optional[dict[str, str]]
    ) -> Optional[set[str]]:
        """Resolve a label filter to a subject ID set, or None if unfiltered."""
        if not labels:
            return None
        return self.find_subject_ids_by_labels(subject_type, labels)

    def find_by_embedding(
        self, embedding: list[float], k: int = 5, labels: Optional[dict[str, str]] = None
    ) -> list[tuple[Concept, float]]:
        if self._vec_backend == "sqlite-vec" and self._vec_dimensions:
            return self._find_concepts_sqlite_vec(embedding, k, labels)
        elif self._vec_backend == "pgvector" and self._vec_dimensions:
            return self._find_concepts_pgvector(embedding, k, labels)
        return self._find_concepts_brute_force(embedding, k, labels)

    def _find_concepts_sqlite_vec(
        self, embedding: list[float], k: int, labels: Optional[dict[str, str]] = None
    ) -> list[tuple[Concept, float]]:
        allowed_ids = self._resolve_label_ids("concept", labels)
        if allowed_ids is not None and not allowed_ids:
            return []
        query_vec = np.array(embedding, dtype=np.float32)
        with self._connect() as conn:
            results: list[tuple[Concept, float]] = []
            for fetch_k in _label_escalation_steps(k, allowed_ids):
                rows = conn.execute(text(
                    "SELECT concept_id, distance FROM vec_concepts "
                    "WHERE embedding MATCH :query AND k = :k"
                ), {"query": query_vec.tobytes(), "k": fetch_k}).fetchall()

                results = []
                for row in rows:
                    if allowed_ids is not None and row.concept_id not in allowed_ids:
                        continue
                    concept = self._get_concept_from_conn(conn, row.concept_id)
                    if concept is None:
                        continue
                    distance = row.distance if row.distance is not None else 1.0
                    results.append((concept, 1.0 - distance))

                if len(results) >= k or len(rows) < fetch_k:
                    break

            return results[:k]

    def _find_concepts_pgvector(
        self, embedding: list[float], k: int, labels: Optional[dict[str, str]] = None
    ) -> list[tuple[Concept, float]]:
        vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
        with self._connect() as conn:
            query, params = _pgvector_label_query(
                "concepts", "id, data, embedding, embedding_vec <=> :query AS distance",
                vec_str, k, labels, order_by="embedding_vec <=> :query",
            )
            rows = conn.execute(text(query), params).fetchall()

            results = []
            for row in rows:
                data = _parse_json(row.data)
                if data.get("deleted_at"):
                    continue
                if row.embedding:
                    data["embedding"] = _bytes_to_embedding(row.embedding)
                similarity = 1.0 - row.distance
                results.append((Concept.from_dict(data), similarity))

            return results[:k]

    def _find_concepts_brute_force(
        self, embedding: list[float], k: int, labels: Optional[dict[str, str]] = None
    ) -> list[tuple[Concept, float]]:
        allowed_ids = self._resolve_label_ids("concept", labels)
        if allowed_ids is not None and not allowed_ids:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                select(concepts_table.c.data, concepts_table.c.embedding)
                .where(concepts_table.c.embedding.isnot(None))
            ).fetchall()

            results = []
            for row in rows:
                data = _parse_json(row.data)
                if data.get("deleted_at"):
                    continue
                if allowed_ids is not None and data.get("id") not in allowed_ids:
                    continue
                if not row.embedding:
                    continue
                stored = _bytes_to_embedding(row.embedding)
                sim = cosine_similarity(embedding, stored)
                data["embedding"] = stored
                results.append((Concept.from_dict(data), sim))

            results.sort(key=lambda x: x[1], reverse=True)
            return results[:k]

    def _get_concept_from_conn(self, conn, concept_id: str) -> Optional[Concept]:
        """Load a concept by ID within an existing connection."""
        row = conn.execute(
            select(concepts_table.c.data, concepts_table.c.embedding)
            .where(concepts_table.c.id == concept_id)
        ).fetchone()
        if not row:
            return None
        data = _parse_json(row.data)
        if data.get("deleted_at"):
            return None
        if row.embedding:
            data["embedding"] = _bytes_to_embedding(row.embedding)
        return Concept.from_dict(data)

    def find_episodes_by_embedding(
        self, embedding: list[float], k: int = 5, labels: Optional[dict[str, str]] = None
    ) -> list[tuple[Episode, float]]:
        if self._vec_backend == "sqlite-vec" and self._vec_dimensions:
            return self._find_episodes_sqlite_vec(embedding, k, labels)
        elif self._vec_backend == "pgvector" and self._vec_dimensions:
            return self._find_episodes_pgvector(embedding, k, labels)
        return self._find_episodes_brute_force(embedding, k, labels)

    def _find_episodes_sqlite_vec(
        self, embedding: list[float], k: int, labels: Optional[dict[str, str]] = None
    ) -> list[tuple[Episode, float]]:
        allowed_ids = self._resolve_label_ids("episode", labels)
        if allowed_ids is not None and not allowed_ids:
            return []
        query_vec = np.array(embedding, dtype=np.float32)
        with self._connect() as conn:
            results: list[tuple[Episode, float]] = []
            for fetch_k in _label_escalation_steps(k, allowed_ids):
                rows = conn.execute(text(
                    "SELECT episode_id, distance FROM vec_episodes "
                    "WHERE embedding MATCH :query AND k = :k"
                ), {"query": query_vec.tobytes(), "k": fetch_k}).fetchall()

                results = []
                for row in rows:
                    if allowed_ids is not None and row.episode_id not in allowed_ids:
                        continue
                    ep = self._get_episode_from_conn(conn, row.episode_id)
                    if ep is None:
                        continue
                    distance = row.distance if row.distance is not None else 1.0
                    results.append((ep, 1.0 - distance))

                if len(results) >= k or len(rows) < fetch_k:
                    break

            return results[:k]

    def _find_episodes_pgvector(
        self, embedding: list[float], k: int, labels: Optional[dict[str, str]] = None
    ) -> list[tuple[Episode, float]]:
        vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
        with self._connect() as conn:
            query, params = _pgvector_label_query(
                "episodes", "id, data, embedding, embedding_vec <=> :query AS distance",
                vec_str, k, labels, order_by="embedding_vec <=> :query",
            )
            rows = conn.execute(text(query), params).fetchall()

            results = []
            for row in rows:
                data = _parse_json(row.data)
                if data.get("deleted_at"):
                    continue
                ep = Episode.from_dict(data)
                if row.embedding:
                    ep.embedding = _bytes_to_embedding(row.embedding)
                similarity = 1.0 - row.distance
                results.append((ep, similarity))

            return results[:k]

    def _find_episodes_brute_force(
        self, embedding: list[float], k: int, labels: Optional[dict[str, str]] = None
    ) -> list[tuple[Episode, float]]:
        allowed_ids = self._resolve_label_ids("episode", labels)
        if allowed_ids is not None and not allowed_ids:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                select(episodes_table.c.data, episodes_table.c.embedding)
                .where(episodes_table.c.embedding.isnot(None))
            ).fetchall()

            results = []
            for row in rows:
                data = _parse_json(row.data)
                if data.get("deleted_at"):
                    continue
                if allowed_ids is not None and data.get("id") not in allowed_ids:
                    continue
                if not row.embedding:
                    continue
                stored = _bytes_to_embedding(row.embedding)
                sim = cosine_similarity(embedding, stored)
                ep = Episode.from_dict(data)
                ep.embedding = stored
                results.append((ep, sim))

            results.sort(key=lambda x: x[1], reverse=True)
            return results[:k]

    def _get_episode_from_conn(self, conn, episode_id: str) -> Optional[Episode]:
        """Load an episode by ID within an existing connection."""
        row = conn.execute(
            select(episodes_table.c.data, episodes_table.c.embedding)
            .where(episodes_table.c.id == episode_id)
        ).fetchone()
        if not row:
            return None
        data = _parse_json(row.data)
        if data.get("deleted_at"):
            return None
        ep = Episode.from_dict(data)
        if row.embedding:
            ep.embedding = _bytes_to_embedding(row.embedding)
        return ep

    # ------------------------------------------------------------------
    # Entity embedding-based retrieval
    # ------------------------------------------------------------------

    def find_entities_by_embedding(
        self, embedding: list[float], k: int = 5, labels: Optional[dict[str, str]] = None
    ) -> list[tuple[Entity, float]]:
        if self._vec_backend == "sqlite-vec" and self._vec_dimensions:
            return self._find_entities_sqlite_vec(embedding, k, labels)
        elif self._vec_backend == "pgvector" and self._vec_dimensions:
            return self._find_entities_pgvector(embedding, k, labels)
        return self._find_entities_brute_force(embedding, k, labels)

    def _find_entities_sqlite_vec(
        self, embedding: list[float], k: int, labels: Optional[dict[str, str]] = None
    ) -> list[tuple[Entity, float]]:
        allowed_ids = self._resolve_label_ids("entity", labels)
        if allowed_ids is not None and not allowed_ids:
            return []
        query_vec = np.array(embedding, dtype=np.float32)
        with self._connect() as conn:
            results: list[tuple[Entity, float]] = []
            for fetch_k in _label_escalation_steps(k, allowed_ids):
                try:
                    rows = conn.execute(text(
                        "SELECT entity_id, distance FROM vec_entities "
                        "WHERE embedding MATCH :vec ORDER BY distance LIMIT :k"
                    ), {"vec": query_vec.tobytes(), "k": fetch_k}).fetchall()
                except Exception:
                    # Fall back to brute force if vec table doesn't exist
                    return self._find_entities_brute_force(embedding, k, labels)

                results = []
                for row in rows:
                    if allowed_ids is not None and row.entity_id not in allowed_ids:
                        continue
                    entity = self.get_entity(row.entity_id)
                    if entity:
                        results.append((entity, 1.0 - row.distance))

                if len(results) >= k or len(rows) < fetch_k:
                    break

            return results[:k]

    def _find_entities_pgvector(
        self, embedding: list[float], k: int, labels: Optional[dict[str, str]] = None
    ) -> list[tuple[Entity, float]]:
        vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
        with self._connect() as conn:
            try:
                query, params = _pgvector_label_query(
                    "entities", "id, data, embedding_vec <=> :query AS distance",
                    vec_str, k, labels, order_by="embedding_vec <=> :query",
                )
                rows = conn.execute(text(query), params).fetchall()
            except Exception:
                # Fall back to brute force if vector column doesn't exist
                return self._find_entities_brute_force(embedding, k, labels)

            results = []
            for row in rows:
                data = _parse_json(row.data)
                entity = Entity.from_dict(data)
                similarity = 1.0 - row.distance
                results.append((entity, similarity))

            return results[:k]

    def _find_entities_brute_force(
        self, embedding: list[float], k: int, labels: Optional[dict[str, str]] = None
    ) -> list[tuple[Entity, float]]:
        allowed_ids = self._resolve_label_ids("entity", labels)
        if allowed_ids is not None and not allowed_ids:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                select(entities_table.c.data, entities_table.c.embedding)
                .where(entities_table.c.embedding.isnot(None))
            ).fetchall()

            results = []
            for row in rows:
                data = _parse_json(row.data)
                if allowed_ids is not None and data.get("id") not in allowed_ids:
                    continue
                if not row.embedding:
                    continue
                stored = _bytes_to_embedding(row.embedding)
                sim = cosine_similarity(embedding, stored)
                data["embedding"] = stored
                entity = Entity.from_dict(data)
                results.append((entity, sim))

            results.sort(key=lambda x: x[1], reverse=True)
            return results[:k]

    # ------------------------------------------------------------------
    # Fact embedding-based retrieval
    # ------------------------------------------------------------------

    def find_facts_by_embedding(
        self,
        embedding: list[float],
        k: int = 10,
        cluster_id: Optional[str] = None,
        active_only: bool = True,
    ) -> list[tuple[Fact, float]]:
        if self._vec_backend == "sqlite-vec" and self._vec_dimensions:
            return self._find_facts_sqlite_vec(embedding, k, cluster_id, active_only)
        elif self._vec_backend == "pgvector" and self._vec_dimensions:
            return self._find_facts_pgvector(embedding, k, cluster_id, active_only)
        return self._find_facts_brute_force(embedding, k, cluster_id, active_only)

    def _find_facts_sqlite_vec(
        self,
        embedding: list[float],
        k: int,
        cluster_id: Optional[str],
        active_only: bool,
    ) -> list[tuple[Fact, float]]:
        query_vec = np.array(embedding, dtype=np.float32)
        with self._connect() as conn:
            try:
                rows = conn.execute(text(
                    "SELECT fact_id, distance FROM vec_facts "
                    "WHERE embedding MATCH :vec ORDER BY distance LIMIT :limit"
                ), {"vec": query_vec.tobytes(), "limit": k * 3}).fetchall()
            except Exception:
                return self._find_facts_brute_force(embedding, k, cluster_id, active_only)

            results = []
            for row in rows:
                fact = self.get_fact(row.fact_id)
                if not fact:
                    continue
                if cluster_id and fact.cluster_id != cluster_id:
                    continue
                if active_only and not fact.is_active:
                    continue
                similarity = 1.0 - row.distance
                results.append((fact, similarity))
                if len(results) >= k:
                    break

            return results

    def _find_facts_pgvector(
        self,
        embedding: list[float],
        k: int,
        cluster_id: Optional[str],
        active_only: bool,
    ) -> list[tuple[Fact, float]]:
        vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
        with self._connect() as conn:
            try:
                base_query = (
                    "SELECT id, cluster_id, statement, attribute, entity_ids, "
                    "valid_from, valid_to, superseded_by, asserted_by, source_ref, "
                    "source_episode_id, created_at, embedding, "
                    "embedding_vec <=> :vec AS distance "
                    "FROM facts WHERE embedding_vec IS NOT NULL "
                )
                conditions = []
                params = {"vec": vec_str, "limit": k * 3}

                if cluster_id:
                    conditions.append("cluster_id = :cluster_id")
                    params["cluster_id"] = cluster_id
                if active_only:
                    conditions.append("valid_to IS NULL")

                if conditions:
                    base_query += "AND " + " AND ".join(conditions) + " "

                base_query += "ORDER BY embedding_vec <=> :vec LIMIT :limit"

                rows = conn.execute(text(base_query), params).fetchall()
            except Exception:
                return self._find_facts_brute_force(embedding, k, cluster_id, active_only)

            results = []
            for row in rows:
                fact = Fact(
                    id=row.id,
                    cluster_id=row.cluster_id,
                    statement=row.statement,
                    attribute=row.attribute,
                    entity_ids=json.loads(row.entity_ids) if row.entity_ids else [],
                    valid_from=row.valid_from,
                    valid_to=row.valid_to,
                    superseded_by=row.superseded_by,
                    asserted_by=row.asserted_by,
                    source_ref=row.source_ref,
                    source_episode_id=row.source_episode_id,
                    created_at=row.created_at,
                    embedding=_bytes_to_embedding(row.embedding) if row.embedding else None,
                )
                similarity = 1.0 - row.distance
                results.append((fact, similarity))

            return results[:k]

    def _find_facts_brute_force(
        self,
        embedding: list[float],
        k: int,
        cluster_id: Optional[str],
        active_only: bool,
    ) -> list[tuple[Fact, float]]:
        with self._connect() as conn:
            stmt = select(facts_table).where(facts_table.c.embedding.isnot(None))

            if cluster_id:
                stmt = stmt.where(facts_table.c.cluster_id == cluster_id)
            if active_only:
                stmt = stmt.where(facts_table.c.valid_to.is_(None))

            rows = conn.execute(stmt).fetchall()

            results = []
            for row in rows:
                if not row.embedding:
                    continue
                stored = _bytes_to_embedding(row.embedding)
                sim = cosine_similarity(embedding, stored)
                fact = Fact(
                    id=row.id,
                    cluster_id=row.cluster_id,
                    statement=row.statement,
                    attribute=row.attribute,
                    entity_ids=json.loads(row.entity_ids) if row.entity_ids else [],
                    valid_from=row.valid_from,
                    valid_to=row.valid_to,
                    superseded_by=row.superseded_by,
                    asserted_by=row.asserted_by,
                    source_ref=row.source_ref,
                    source_episode_id=row.source_episode_id,
                    created_at=row.created_at,
                    embedding=stored,
                )
                results.append((fact, sim))

            results.sort(key=lambda x: x[1], reverse=True)
            return results[:k]

    def _upsert_vec_fact(self, conn, fact_id: str, embedding: Optional[list[float]]) -> None:
        """Sync a fact embedding to the vector index."""
        if self._vec_backend is None or embedding is None:
            return
        self._ensure_vec_dimensions(embedding, conn=conn)

        if self._vec_backend == "sqlite-vec":
            vec = np.array(embedding, dtype=np.float32)
            conn.execute(text(
                "DELETE FROM vec_facts WHERE fact_id = :id"
            ), {"id": fact_id})
            conn.execute(text(
                "INSERT INTO vec_facts(fact_id, embedding) VALUES (:id, :emb)"
            ), {"id": fact_id, "emb": vec.tobytes()})
        elif self._vec_backend == "pgvector":
            vec_str = "[" + ",".join(str(v) for v in embedding) + "]"
            conn.execute(text(
                "UPDATE facts SET embedding_vec = :vec WHERE id = :id"
            ), {"vec": vec_str, "id": fact_id})

    def _delete_vec_fact(self, conn, fact_id: str) -> None:
        """Remove a fact from the vector index."""
        if self._vec_backend == "sqlite-vec":
            conn.execute(text(
                "DELETE FROM vec_facts WHERE fact_id = :id"
            ), {"id": fact_id})
        elif self._vec_backend == "pgvector":
            conn.execute(text(
                "UPDATE facts SET embedding_vec = NULL WHERE id = :id"
            ), {"id": fact_id})

    # ------------------------------------------------------------------
    # Graph traversal
    # ------------------------------------------------------------------

    def get_related(
        self,
        concept_id: str,
        relation_types: Optional[list[RelationType]] = None,
        depth: int = 1
    ) -> list[tuple[Concept, Relation]]:
        with self._connect() as conn:
            visited: set[str] = set()
            results: list[tuple[Concept, Relation]] = []
            self._traverse_relations(conn, concept_id, relation_types, depth, visited, results)
            return results

    def _traverse_relations(self, conn, concept_id, relation_types, remaining_depth, visited, results):
        if remaining_depth <= 0 or concept_id in visited:
            return
        visited.add(concept_id)

        stmt = select(
            relations_table.c.target_id,
            relations_table.c.type,
            relations_table.c.strength,
            relations_table.c.context,
        ).where(relations_table.c.source_id == concept_id)

        if relation_types:
            stmt = stmt.where(relations_table.c.type.in_([rt.value for rt in relation_types]))

        rows = conn.execute(stmt).fetchall()

        for row in rows:
            target_id = row.target_id
            if target_id in visited:
                continue

            concept_row = conn.execute(
                select(concepts_table.c.data, concepts_table.c.embedding)
                .where(concepts_table.c.id == target_id)
            ).fetchone()
            if not concept_row:
                continue

            data = _parse_json(concept_row.data)
            if concept_row.embedding:
                data["embedding"] = _bytes_to_embedding(concept_row.embedding)

            concept = Concept.from_dict(data)
            relation = Relation(
                type=RelationType(row.type),
                target_id=target_id,
                strength=row.strength,
                context=row.context,
            )
            results.append((concept, relation))

            if remaining_depth > 1:
                self._traverse_relations(conn, target_id, relation_types, remaining_depth - 1, visited, results)

    def get_incoming_relations(
        self,
        concept_id: str,
        relation_type: RelationType,
    ) -> list[tuple[Concept, Relation]]:
        with self._connect() as conn:
            rows = conn.execute(
                select(
                    relations_table.c.source_id,
                    relations_table.c.type,
                    relations_table.c.strength,
                    relations_table.c.context,
                )
                .where(relations_table.c.target_id == concept_id)
                .where(relations_table.c.type == relation_type.value)
            ).fetchall()

            results: list[tuple[Concept, Relation]] = []
            for row in rows:
                concept_row = conn.execute(
                    select(concepts_table.c.data, concepts_table.c.embedding)
                    .where(concepts_table.c.id == row.source_id)
                ).fetchone()
                if not concept_row:
                    continue

                data = _parse_json(concept_row.data)
                if data.get("deleted_at"):
                    continue
                if concept_row.embedding:
                    data["embedding"] = _bytes_to_embedding(concept_row.embedding)

                concept = Concept.from_dict(data)
                relation = Relation(
                    type=RelationType(row.type),
                    target_id=concept_id,
                    strength=row.strength,
                    context=row.context,
                )
                results.append((concept, relation))

            return results

    # ------------------------------------------------------------------
    # Episode operations
    # ------------------------------------------------------------------

    def add_episode(self, episode: Episode) -> str:
        with self._connect() as conn:
            data = episode.to_dict()
            conn.execute(
                episodes_table.insert().values(
                    id=episode.id,
                    title=episode.title,
                    content=episode.content,
                    data=_dump_json(data),
                    consolidated=episode.consolidated,
                    timestamp=episode.timestamp,
                    embedding=_embedding_to_bytes(episode.embedding),
                )
            )
            self._sync_labels(conn, "episode", episode.id, episode.labels)
            self._upsert_vec_episode(conn, episode.id, episode.embedding)
            self._upsert_fts_episode(conn, episode.id, episode.title, episode.content)
        return episode.id

    def add_episodes_batch(self, episodes: list[Episode]) -> list[str]:
        if not episodes:
            return []
        with self._connect() as conn:
            ids = []
            for episode in episodes:
                data = episode.to_dict()
                conn.execute(
                    episodes_table.insert().values(
                        id=episode.id,
                        title=episode.title,
                        content=episode.content,
                        data=_dump_json(data),
                        consolidated=episode.consolidated,
                        timestamp=episode.timestamp,
                        embedding=_embedding_to_bytes(episode.embedding),
                    )
                )
                self._sync_labels(conn, "episode", episode.id, episode.labels)
                self._upsert_vec_episode(conn, episode.id, episode.embedding)
                self._upsert_fts_episode(conn, episode.id, episode.title, episode.content)
                ids.append(episode.id)
            return ids

    def get_episode(self, id: str, include_deleted: bool = False) -> Optional[Episode]:
        with self._connect() as conn:
            row = conn.execute(
                select(episodes_table.c.data, episodes_table.c.embedding)
                .where(episodes_table.c.id == id)
            ).fetchone()
            if not row:
                return None
            data = _parse_json(row.data)
            if data.get("deleted_at") and not include_deleted:
                return None
            ep = Episode.from_dict(data)
            if row.embedding:
                ep.embedding = _bytes_to_embedding(row.embedding)
            return ep

    def get_episodes_batch(self, ids: list[str]) -> list[Episode]:
        if not ids:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                select(episodes_table.c.data, episodes_table.c.embedding)
                .where(episodes_table.c.id.in_(ids))
            ).fetchall()

            episodes = []
            for row in rows:
                data = _parse_json(row.data)
                if data.get("deleted_at"):
                    continue
                ep = Episode.from_dict(data)
                if row.embedding:
                    ep.embedding = _bytes_to_embedding(row.embedding)
                episodes.append(ep)
            return episodes

    def update_episode(self, episode: Episode) -> None:
        with self._connect() as conn:
            data = episode.to_dict()
            conn.execute(
                episodes_table.update()
                .where(episodes_table.c.id == episode.id)
                .values(
                    title=episode.title,
                    content=episode.content,
                    data=_dump_json(data),
                    consolidated=episode.consolidated,
                    timestamp=episode.timestamp,
                    embedding=_embedding_to_bytes(episode.embedding),
                )
            )
            self._sync_labels(conn, "episode", episode.id, episode.labels)
            self._upsert_vec_episode(conn, episode.id, episode.embedding)
            self._upsert_fts_episode(conn, episode.id, episode.title, episode.content)

    def delete_episode(self, id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                select(episodes_table.c.data).where(episodes_table.c.id == id)
            ).fetchone()
            if not row:
                return False
            data = _parse_json(row.data)
            if data.get("deleted_at"):
                return False
            data["deleted_at"] = datetime.now().isoformat()
            conn.execute(
                episodes_table.update()
                .where(episodes_table.c.id == id)
                .values(data=_dump_json(data))
            )
            conn.execute(
                entity_relations_table.delete()
                .where(entity_relations_table.c.source_episode_id == id)
            )
            conn.execute(
                mentions_table.delete()
                .where(mentions_table.c.episode_id == id)
            )
            return True

    def restore_episode(self, id: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                select(episodes_table.c.data).where(episodes_table.c.id == id)
            ).fetchone()
            if not row:
                return False
            data = _parse_json(row.data)
            if not data.get("deleted_at"):
                return False
            data.pop("deleted_at", None)
            conn.execute(
                episodes_table.update()
                .where(episodes_table.c.id == id)
                .values(data=_dump_json(data))
            )
            return True

    def purge_episode(self, id: str) -> bool:
        with self._connect() as conn:
            self._delete_vec_episode(conn, id)
            self._delete_fts_episode(conn, id)
            conn.execute(
                entity_relations_table.delete()
                .where(entity_relations_table.c.source_episode_id == id)
            )
            conn.execute(
                mentions_table.delete()
                .where(mentions_table.c.episode_id == id)
            )
            conn.execute(
                labels_table.delete().where(
                    (labels_table.c.subject_type == "episode") & (labels_table.c.subject_id == id)
                )
            )
            result = conn.execute(
                episodes_table.delete().where(episodes_table.c.id == id)
            )
            return result.rowcount > 0

    def get_deleted_episodes(self, limit: int = 50) -> list[Episode]:
        with self._connect() as conn:
            rows = conn.execute(
                select(episodes_table.c.data)
                .order_by(episodes_table.c.timestamp.desc())
            ).fetchall()
            episodes = []
            for row in rows:
                data = _parse_json(row.data)
                if not data.get("deleted_at"):
                    continue
                episodes.append(Episode.from_dict(data))
                if len(episodes) >= limit:
                    break
            return episodes

    def get_unconsolidated_episodes(self, limit: int = 10) -> list[Episode]:
        with self._connect() as conn:
            rows = conn.execute(
                select(episodes_table.c.data)
                .where(episodes_table.c.consolidated == False)  # noqa: E712
                .order_by(episodes_table.c.timestamp.asc())
                .limit(limit)
            ).fetchall()
            results = []
            for row in rows:
                data = _parse_json(row.data)
                if data.get("deleted_at"):
                    continue
                results.append(Episode.from_dict(data))
            return results

    def count_unconsolidated_episodes(self) -> int:
        with self._connect() as conn:
            rows = conn.execute(
                select(episodes_table.c.data)
                .where(episodes_table.c.consolidated == False)  # noqa: E712
            ).fetchall()
            count = 0
            for row in rows:
                data = _parse_json(row.data)
                if not data.get("deleted_at"):
                    count += 1
            return count

    def get_recent_episodes(self, limit: int = 10) -> list[Episode]:
        with self._connect() as conn:
            rows = conn.execute(
                select(episodes_table.c.data)
                .order_by(episodes_table.c.timestamp.desc())
            ).fetchall()
            results = []
            for row in rows:
                data = _parse_json(row.data)
                if data.get("deleted_at"):
                    continue
                results.append(Episode.from_dict(data))
                if len(results) >= limit:
                    break
            return results

    def get_all_episodes(self) -> list[Episode]:
        with self._connect() as conn:
            rows = conn.execute(
                select(episodes_table.c.data, episodes_table.c.embedding)
                .order_by(episodes_table.c.timestamp.desc())
            ).fetchall()
            results = []
            for row in rows:
                data = _parse_json(row.data)
                if data.get("deleted_at"):
                    continue
                ep = Episode.from_dict(data)
                if row.embedding:
                    ep.embedding = _bytes_to_embedding(row.embedding)
                results.append(ep)
            return results

    def get_episodes_by_date_range(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100,
    ) -> list[Episode]:
        with self._connect() as conn:
            stmt = select(episodes_table.c.data)

            if start_date:
                stmt = stmt.where(episodes_table.c.timestamp >= start_date)
            if end_date:
                stmt = stmt.where(episodes_table.c.timestamp <= end_date)

            stmt = stmt.order_by(episodes_table.c.timestamp.desc())

            rows = conn.execute(stmt).fetchall()
            results = []
            for row in rows:
                data = _parse_json(row.data)
                if data.get("deleted_at"):
                    continue
                results.append(Episode.from_dict(data))
                if len(results) >= limit:
                    break
            return results

    def get_unextracted_episodes(self, limit: int = 100) -> list[Episode]:
        with self._connect() as conn:
            rows = conn.execute(
                select(episodes_table.c.data)
                .order_by(episodes_table.c.timestamp.asc())
            ).fetchall()
            results = []
            for row in rows:
                data = _parse_json(row.data)
                if data.get("deleted_at"):
                    continue
                extracted = data.get("entities_extracted")
                if extracted in (True, 1, "true"):
                    continue
                results.append(Episode.from_dict(data))
                if len(results) >= limit:
                    break
            return results

    def get_episodes_by_type(self, episode_type: str, limit: int = 50) -> list[Episode]:
        type_str = episode_type.value if isinstance(episode_type, EpisodeType) else str(episode_type)
        with self._connect() as conn:
            rows = conn.execute(
                select(episodes_table.c.data)
                .order_by(episodes_table.c.timestamp.desc())
            ).fetchall()
            results = []
            for row in rows:
                data = _parse_json(row.data)
                if data.get("deleted_at"):
                    continue
                if data.get("episode_type") != type_str:
                    continue
                results.append(Episode.from_dict(data))
                if len(results) >= limit:
                    break
            return results

    # ------------------------------------------------------------------
    # Entity operations
    # ------------------------------------------------------------------

    def add_entity(self, entity: Entity) -> str:
        embedding_bytes = _embedding_to_bytes(entity.embedding) if entity.embedding else None
        with self._connect() as conn:
            existing = conn.execute(
                select(entities_table.c.id).where(entities_table.c.id == entity.id)
            ).fetchone()
            if existing:
                conn.execute(
                    entities_table.update()
                    .where(entities_table.c.id == entity.id)
                    .values(
                        type=entity.type.value,
                        display_name=entity.display_name,
                        data=_dump_json(entity.to_dict()),
                        embedding=embedding_bytes,
                    )
                )
            else:
                conn.execute(
                    entities_table.insert().values(
                        id=entity.id,
                        type=entity.type.value,
                        display_name=entity.display_name,
                        data=_dump_json(entity.to_dict()),
                        created_at=entity.created_at,
                        embedding=embedding_bytes,
                    )
                )
        return entity.id

    def update_entity(self, entity: Entity) -> None:
        embedding_bytes = _embedding_to_bytes(entity.embedding) if entity.embedding else None
        with self._connect() as conn:
            conn.execute(
                entities_table.update()
                .where(entities_table.c.id == entity.id)
                .values(
                    type=entity.type.value,
                    display_name=entity.display_name,
                    data=_dump_json(entity.to_dict()),
                    embedding=embedding_bytes,
                )
            )

    def get_entity(self, id: str) -> Optional[Entity]:
        with self._connect() as conn:
            row = conn.execute(
                select(entities_table.c.data, entities_table.c.embedding)
                .where(entities_table.c.id == id)
            ).fetchone()
            if not row:
                return None
            data = _parse_json(row.data)
            if row.embedding:
                data["embedding"] = _bytes_to_embedding(row.embedding)
            return Entity.from_dict(data)

    def get_entities_by_type(self, entity_type: EntityType) -> list[Entity]:
        with self._connect() as conn:
            rows = conn.execute(
                select(entities_table.c.data)
                .where(entities_table.c.type == entity_type.value)
                .order_by(entities_table.c.created_at.desc())
            ).fetchall()
            return [Entity.from_dict(_parse_json(row.data)) for row in rows]

    def get_all_entities(self) -> list[Entity]:
        with self._connect() as conn:
            rows = conn.execute(
                select(entities_table.c.data)
                .order_by(entities_table.c.type, entities_table.c.created_at.desc())
            ).fetchall()
            return [Entity.from_dict(_parse_json(row.data)) for row in rows]

    def find_entity_by_name(self, name: str) -> Optional[Entity]:
        if not name:
            return None
        normalized = canonicalize_entity_name(name)
        with self._connect() as conn:
            row = conn.execute(
                select(entities_table.c.data)
                .where(func.lower(func.trim(entities_table.c.display_name)) == normalized)
                .order_by(entities_table.c.created_at.asc())
                .limit(1)
            ).fetchone()
            if row:
                return Entity.from_dict(_parse_json(row.data))

            # Fallback: canonicalized scan catches label-variant duplicates
            # (e.g. "Role: Alice" vs "Alice") without schema changes.
            rows = conn.execute(
                select(entities_table.c.data)
                .order_by(entities_table.c.created_at.asc())
            ).fetchall()
            for fallback_row in rows:
                entity = Entity.from_dict(_parse_json(fallback_row.data))
                display = entity.display_name or Entity.parse_id(entity.id)[1]
                if canonicalize_entity_name(display) == normalized:
                    return entity
            return None

    def search_entities_by_words(
        self, words: list[str], limit: int = 10
    ) -> list[tuple[Entity, int]]:
        if not words:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                select(entities_table.c.id, entities_table.c.data)
            ).fetchall()

            results: list[tuple[Entity, int]] = []
            for row in rows:
                entity = Entity.from_dict(_parse_json(row.data))
                searchable = f"{entity.id} {entity.display_name}".lower()
                match_count = sum(1 for w in words if w in searchable)
                if match_count > 0:
                    results.append((entity, match_count))

            results.sort(key=lambda x: x[1], reverse=True)
            return results[:limit]

    def merge_duplicate_entities(self) -> dict[str, int]:
        with self._connect() as conn:
            entity_rows = conn.execute(
                select(
                    entities_table.c.id,
                    entities_table.c.data,
                    entities_table.c.created_at,
                )
            ).fetchall()

            mention_rows = conn.execute(
                select(
                    mentions_table.c.entity_id,
                    func.count().label("mention_count"),
                )
                .group_by(mentions_table.c.entity_id)
            ).fetchall()
            mention_counts = {row.entity_id: row.mention_count for row in mention_rows}

            groups: dict[str, list[tuple[Entity, Optional[datetime]]]] = {}
            for row in entity_rows:
                entity = Entity.from_dict(_parse_json(row.data))
                display = entity.display_name or Entity.parse_id(entity.id)[1]
                canonical_name = canonicalize_entity_name(display)
                groups.setdefault(canonical_name, []).append((entity, row.created_at))

            groups_merged = 0
            entities_removed = 0
            mentions_reassigned = 0
            relations_reassigned = 0

            for group in groups.values():
                if len(group) <= 1:
                    continue

                # Keep the most established entity: highest mention count, then oldest.
                winner_entity, _ = sorted(
                    group,
                    key=lambda pair: (
                        -mention_counts.get(pair[0].id, 0),
                        pair[1] or datetime.max,
                        pair[0].id,
                    ),
                )[0]
                winner_id = winner_entity.id

                loser_ids = [entity.id for entity, _ in group if entity.id != winner_id]
                if not loser_ids:
                    continue
                groups_merged += 1

                for loser_id in loser_ids:
                    episode_rows = conn.execute(
                        select(mentions_table.c.episode_id).where(mentions_table.c.entity_id == loser_id)
                    ).fetchall()
                    for ep_row in episode_rows:
                        existing_mention = conn.execute(
                            select(mentions_table.c.episode_id)
                            .where(mentions_table.c.episode_id == ep_row.episode_id)
                            .where(mentions_table.c.entity_id == winner_id)
                        ).fetchone()
                        if not existing_mention:
                            conn.execute(
                                mentions_table.insert().values(
                                    episode_id=ep_row.episode_id,
                                    entity_id=winner_id,
                                )
                            )
                    deleted_mentions = conn.execute(
                        mentions_table.delete().where(mentions_table.c.entity_id == loser_id)
                    ).rowcount
                    mentions_reassigned += deleted_mentions

                    relation_rows = conn.execute(
                        select(entity_relations_table).where(
                            (entity_relations_table.c.source_id == loser_id)
                            | (entity_relations_table.c.target_id == loser_id)
                        )
                    ).fetchall()
                    for rel_row in relation_rows:
                        old_source = rel_row.source_id
                        old_target = rel_row.target_id
                        new_source = winner_id if old_source == loser_id else old_source
                        new_target = winner_id if old_target == loser_id else old_target

                        incoming_ids = (
                            json.loads(rel_row.source_episode_ids or "[]")
                            if isinstance(rel_row.source_episode_ids, str)
                            else (rel_row.source_episode_ids or [])
                        )
                        existing_rel = conn.execute(
                            select(
                                entity_relations_table.c.strength,
                                entity_relations_table.c.context,
                                entity_relations_table.c.source_episode_id,
                                entity_relations_table.c.episode_count,
                                entity_relations_table.c.source_episode_ids,
                            )
                            .where(entity_relations_table.c.source_id == new_source)
                            .where(entity_relations_table.c.target_id == new_target)
                            .where(entity_relations_table.c.relation_type == rel_row.relation_type)
                        ).fetchone()
                        if existing_rel:
                            existing_ids = (
                                json.loads(existing_rel.source_episode_ids or "[]")
                                if isinstance(existing_rel.source_episode_ids, str)
                                else (existing_rel.source_episode_ids or [])
                            )
                            merged_ids = list(dict.fromkeys(existing_ids + incoming_ids))
                            incoming_count = rel_row.episode_count or 1
                            if merged_ids:
                                merged_count = len(merged_ids)
                            else:
                                merged_count = (existing_rel.episode_count or 1) + incoming_count
                            conn.execute(
                                entity_relations_table.update()
                                .where(entity_relations_table.c.source_id == new_source)
                                .where(entity_relations_table.c.target_id == new_target)
                                .where(entity_relations_table.c.relation_type == rel_row.relation_type)
                                .values(
                                    strength=max(existing_rel.strength, rel_row.strength),
                                    context=existing_rel.context or rel_row.context,
                                    source_episode_id=existing_rel.source_episode_id or rel_row.source_episode_id,
                                    episode_count=max(1, merged_count),
                                    source_episode_ids=json.dumps(merged_ids),
                                )
                            )
                        else:
                            conn.execute(
                                entity_relations_table.insert().values(
                                    source_id=new_source,
                                    target_id=new_target,
                                    relation_type=rel_row.relation_type,
                                    strength=rel_row.strength,
                                    context=rel_row.context,
                                    source_episode_id=rel_row.source_episode_id,
                                    created_at=(
                                        rel_row.created_at
                                        if isinstance(rel_row.created_at, datetime)
                                        else datetime.now()
                                    ),
                                    episode_count=rel_row.episode_count or 1,
                                    source_episode_ids=json.dumps(incoming_ids),
                                )
                            )
                        conn.execute(
                            entity_relations_table.delete()
                            .where(entity_relations_table.c.source_id == old_source)
                            .where(entity_relations_table.c.target_id == old_target)
                            .where(entity_relations_table.c.relation_type == rel_row.relation_type)
                        )
                        relations_reassigned += 1

                    conn.execute(entities_table.delete().where(entities_table.c.id == loser_id))
                    entities_removed += 1

            return {
                "groups_merged": groups_merged,
                "entities_removed": entities_removed,
                "mentions_reassigned": mentions_reassigned,
                "relations_reassigned": relations_reassigned,
            }

    # ------------------------------------------------------------------
    # Mention operations
    # ------------------------------------------------------------------

    def add_mention(self, episode_id: str, entity_id: str) -> None:
        with self._connect() as conn:
            existing = conn.execute(
                select(mentions_table.c.episode_id)
                .where(mentions_table.c.episode_id == episode_id)
                .where(mentions_table.c.entity_id == entity_id)
            ).fetchone()
            if not existing:
                conn.execute(
                    mentions_table.insert().values(
                        episode_id=episode_id,
                        entity_id=entity_id,
                    )
                )

    def get_episodes_mentioning(self, entity_id: str, limit: int = 50) -> list[Episode]:
        with self._connect() as conn:
            stmt = (
                select(episodes_table.c.data)
                .select_from(
                    episodes_table.join(
                        mentions_table,
                        episodes_table.c.id == mentions_table.c.episode_id,
                    )
                )
                .where(mentions_table.c.entity_id == entity_id)
                .order_by(episodes_table.c.timestamp.desc())
            )
            rows = conn.execute(stmt).fetchall()
            results = []
            for row in rows:
                data = _parse_json(row.data)
                if data.get("deleted_at"):
                    continue
                results.append(Episode.from_dict(data))
                if len(results) >= limit:
                    break
            return results

    def find_episodes_by_entities(
        self,
        entity_ids: list[str],
        exclude_episode_ids: Optional[set[str]] = None,
        limit: int = 20,
    ) -> list[Episode]:
        if not entity_ids:
            return []
        exclude = exclude_episode_ids or set()
        with self._connect() as conn:
            count_subq = (
                select(
                    mentions_table.c.episode_id.label("id"),
                    func.count(func.distinct(mentions_table.c.entity_id)).label("overlap_count"),
                )
                .where(mentions_table.c.entity_id.in_(entity_ids))
                .group_by(mentions_table.c.episode_id)
                .subquery()
            )
            stmt = (
                select(episodes_table.c.data, count_subq.c.overlap_count)
                .select_from(
                    episodes_table.join(count_subq, episodes_table.c.id == count_subq.c.id)
                )
                .order_by(count_subq.c.overlap_count.desc(), episodes_table.c.timestamp.desc())
                .limit(limit + len(exclude))
            )
            rows = conn.execute(stmt).fetchall()
            results = []
            for row in rows:
                data = _parse_json(row.data)
                if data.get("deleted_at"):
                    continue
                ep = Episode.from_dict(data)
                if ep.id not in exclude:
                    results.append(ep)
                    if len(results) >= limit:
                        break
            return results

    def get_entities_mentioned_in(self, episode_id: str) -> list[Entity]:
        with self._connect() as conn:
            stmt = (
                select(entities_table.c.data)
                .select_from(
                    entities_table.join(
                        mentions_table,
                        entities_table.c.id == mentions_table.c.entity_id,
                    )
                )
                .where(mentions_table.c.episode_id == episode_id)
                .order_by(entities_table.c.type, entities_table.c.display_name)
            )
            rows = conn.execute(stmt).fetchall()
            return [Entity.from_dict(_parse_json(row.data)) for row in rows]

    def delete_mentions_for_episode(self, episode_id: str) -> int:
        with self._connect() as conn:
            result = conn.execute(
                mentions_table.delete().where(mentions_table.c.episode_id == episode_id)
            )
            return result.rowcount

    def get_entity_mention_counts(self) -> list[tuple[Entity, int]]:
        with self._connect() as conn:
            count_subq = (
                select(
                    entities_table.c.id,
                    func.count(mentions_table.c.episode_id).label("mention_count"),
                )
                .select_from(
                    entities_table.outerjoin(
                        mentions_table,
                        entities_table.c.id == mentions_table.c.entity_id,
                    )
                )
                .group_by(entities_table.c.id)
                .subquery()
            )
            stmt = (
                select(entities_table.c.data, count_subq.c.mention_count)
                .select_from(
                    entities_table.join(count_subq, entities_table.c.id == count_subq.c.id)
                )
                .order_by(count_subq.c.mention_count.desc(), entities_table.c.type)
            )
            rows = conn.execute(stmt).fetchall()
            return [
                (Entity.from_dict(_parse_json(row.data)), row.mention_count)
                for row in rows
            ]

    def get_concepts_for_entity(self, entity_id: str, limit: int = 50) -> list[Concept]:
        """Get all concepts that have this entity in their entity_ids.
        
        Falls back to episode-based lookup for legacy concepts without entity_ids.
        """
        all_concepts = self.get_all_concepts()
        matching = []
        legacy_check_needed = []
        
        for concept in all_concepts:
            # Direct lookup via entity_ids field
            if entity_id in concept.entity_ids:
                matching.append(concept)
            elif not concept.entity_ids:
                # Legacy concept without entity_ids - check via episodes
                legacy_check_needed.append(concept)
        
        # Fallback for legacy concepts
        if legacy_check_needed:
            with self._connect() as conn:
                episode_rows = conn.execute(
                    select(mentions_table.c.episode_id)
                    .where(mentions_table.c.entity_id == entity_id)
                ).fetchall()
                episode_ids = {row.episode_id for row in episode_rows}
                
                for concept in legacy_check_needed:
                    overlap = set(concept.source_episodes) & episode_ids
                    if overlap:
                        matching.append(concept)
        
        return matching[:limit]

    def get_fact_clusters_for_entity(self, entity_id: str) -> list[Concept]:
        """Get all fact_cluster concepts that have this entity in their entity_ids.
        
        Falls back to episode-based lookup for legacy clusters without entity_ids.
        """
        all_concepts = self.get_all_concepts()
        matching = []
        legacy_check_needed = []
        
        for concept in all_concepts:
            if concept.concept_type not in ("fact_cluster", "fact"):
                continue
            # Direct lookup via entity_ids field
            if entity_id in concept.entity_ids:
                matching.append(concept)
            elif not concept.entity_ids:
                # Legacy cluster without entity_ids - check via episodes
                legacy_check_needed.append(concept)
        
        # Fallback for legacy clusters
        if legacy_check_needed:
            with self._connect() as conn:
                episode_rows = conn.execute(
                    select(mentions_table.c.episode_id)
                    .where(mentions_table.c.entity_id == entity_id)
                ).fetchall()
                episode_ids = {row.episode_id for row in episode_rows}
                
                for concept in legacy_check_needed:
                    overlap = set(concept.source_episodes) & episode_ids
                    if overlap:
                        matching.append(concept)
        
        return matching

    def get_concepts_by_type(self, concept_type: str) -> list[Concept]:
        """Get all concepts of a specific type (pattern, fact_cluster, legacy)."""
        all_concepts = self.get_all_concepts()
        return [c for c in all_concepts if c.concept_type == concept_type]

    # ------------------------------------------------------------------
    # Fact operations
    # ------------------------------------------------------------------

    @staticmethod
    def _fact_insert_values(fact: Fact) -> dict:
        return {
            "id": fact.id,
            "cluster_id": fact.cluster_id,
            "statement": fact.statement,
            "attribute": fact.attribute,
            "entity_ids": json.dumps(fact.entity_ids),
            "valid_from": fact.valid_from,
            "valid_to": fact.valid_to,
            "superseded_by": fact.superseded_by,
            "asserted_by": fact.asserted_by,
            "source_ref": fact.source_ref,
            "source_episode_id": fact.source_episode_id,
            "created_at": fact.created_at,
            "embedding": _embedding_to_bytes(fact.embedding),
        }

    @staticmethod
    def _row_to_fact(row) -> Fact:
        entity_ids_raw = row.entity_ids or "[]"
        try:
            entity_ids = json.loads(entity_ids_raw) if isinstance(entity_ids_raw, str) else (entity_ids_raw or [])
        except (json.JSONDecodeError, TypeError):
            entity_ids = []
        embedding = None
        if hasattr(row, 'embedding') and row.embedding:
            embedding = _bytes_to_embedding(row.embedding)
        return Fact(
            id=row.id,
            cluster_id=row.cluster_id,
            statement=row.statement or "",
            attribute=row.attribute,
            entity_ids=entity_ids,
            valid_from=row.valid_from,
            valid_to=row.valid_to,
            superseded_by=row.superseded_by,
            asserted_by=row.asserted_by,
            source_ref=row.source_ref,
            source_episode_id=row.source_episode_id,
            created_at=row.created_at or datetime.now(),
            embedding=embedding,
        )

    def add_fact(self, fact: Fact) -> str:
        with self._connect() as conn:
            conn.execute(facts_table.insert().values(**self._fact_insert_values(fact)))
            self._upsert_vec_fact(conn, fact.id, fact.embedding)
        return fact.id

    def add_facts_batch(self, facts: list[Fact]) -> list[str]:
        if not facts:
            return []
        with self._connect() as conn:
            conn.execute(
                facts_table.insert(),
                [self._fact_insert_values(f) for f in facts],
            )
            for f in facts:
                self._upsert_vec_fact(conn, f.id, f.embedding)
        return [f.id for f in facts]

    def get_fact(self, id: str) -> Optional[Fact]:
        with self._connect() as conn:
            row = conn.execute(
                select(facts_table).where(facts_table.c.id == id)
            ).fetchone()
            return self._row_to_fact(row) if row else None

    def get_facts(
        self,
        cluster_id: Optional[str] = None,
        entity_id: Optional[str] = None,
        active_only: bool = False,
        as_of: Optional[datetime] = None,
        limit: int = 500,
    ) -> list[Fact]:
        query = select(facts_table)
        if cluster_id is not None:
            query = query.where(facts_table.c.cluster_id == cluster_id)
        if entity_id is not None:
            # entity_ids is a JSON array serialized as text; match the quoted ID
            query = query.where(facts_table.c.entity_ids.like(f'%"{entity_id}"%'))
        if as_of is not None:
            query = query.where(facts_table.c.valid_from <= as_of)
            query = query.where(
                (facts_table.c.valid_to.is_(None)) | (facts_table.c.valid_to > as_of)
            )
        elif active_only:
            query = query.where(facts_table.c.valid_to.is_(None))
        query = query.order_by(facts_table.c.valid_from.desc()).limit(limit)

        with self._connect() as conn:
            rows = conn.execute(query).fetchall()
            return [self._row_to_fact(row) for row in rows]

    def find_facts_by_entity_name(
        self,
        bare_name: str,
        active_only: bool = True,
        exclude_cluster_id: Optional[str] = None,
        limit: int = 20,
    ) -> list[Fact]:
        # Match any entity ID of the form "<type>:<bare_name>" inside the JSON array.
        # The array is stored as text like '["person:alice","concept:alice"]', so
        # matching '%:<bare_name>"%' catches all type prefixes.
        query = select(facts_table).where(
            facts_table.c.entity_ids.like(f'%:{bare_name}"%')
        )
        if active_only:
            query = query.where(facts_table.c.valid_to.is_(None))
        if exclude_cluster_id is not None:
            query = query.where(facts_table.c.cluster_id != exclude_cluster_id)
        query = query.order_by(facts_table.c.valid_from.desc()).limit(limit)

        with self._connect() as conn:
            rows = conn.execute(query).fetchall()
            return [self._row_to_fact(row) for row in rows]

    def update_fact(self, fact: Fact) -> None:
        values = self._fact_insert_values(fact)
        values.pop("id")
        with self._connect() as conn:
            conn.execute(
                facts_table.update().where(facts_table.c.id == fact.id).values(**values)
            )
            self._upsert_vec_fact(conn, fact.id, fact.embedding)

    def supersede_fact(
        self,
        old_fact_id: str,
        new_fact_id: str,
        at: Optional[datetime] = None,
    ) -> bool:
        at = at or datetime.now()
        with self._connect() as conn:
            result = conn.execute(
                facts_table.update()
                .where(facts_table.c.id == old_fact_id)
                .values(valid_to=at, superseded_by=new_fact_id)
            )
            return result.rowcount > 0

    def delete_facts_for_cluster(self, cluster_id: str) -> int:
        with self._connect() as conn:
            result = conn.execute(
                facts_table.delete().where(facts_table.c.cluster_id == cluster_id)
            )
            return result.rowcount

    # ------------------------------------------------------------------
    # Conflict operations
    # ------------------------------------------------------------------

    @staticmethod
    def _conflict_values(conflict: Conflict) -> dict:
        return {
            "kind": conflict.kind,
            "fact_a_id": conflict.fact_a_id,
            "fact_b_id": conflict.fact_b_id,
            "concept_ids": json.dumps(conflict.concept_ids),
            "description": conflict.description,
            "severity": conflict.severity,
            "status": conflict.status,
            "created_at": conflict.created_at,
            "resolved_at": conflict.resolved_at,
            "resolution_note": conflict.resolution_note,
            "resolved_by": conflict.resolved_by,
            "winning_fact_id": conflict.winning_fact_id,
        }

    @staticmethod
    def _row_to_conflict(row) -> Conflict:
        concept_ids_raw = row.concept_ids or "[]"
        try:
            concept_ids = json.loads(concept_ids_raw) if isinstance(concept_ids_raw, str) else (concept_ids_raw or [])
        except (json.JSONDecodeError, TypeError):
            concept_ids = []
        return Conflict(
            id=row.id,
            kind=row.kind or "fact",
            fact_a_id=row.fact_a_id,
            fact_b_id=row.fact_b_id,
            concept_ids=concept_ids,
            description=row.description or "",
            severity=row.severity or "medium",
            status=row.status or "open",
            created_at=row.created_at or datetime.now(),
            resolved_at=row.resolved_at,
            resolution_note=row.resolution_note,
            resolved_by=row.resolved_by,
            winning_fact_id=row.winning_fact_id,
        )

    def add_conflict(self, conflict: Conflict) -> str:
        with self._connect() as conn:
            conn.execute(
                conflicts_table.insert().values(id=conflict.id, **self._conflict_values(conflict))
            )
        return conflict.id

    def get_conflict(self, id: str) -> Optional[Conflict]:
        with self._connect() as conn:
            row = conn.execute(
                select(conflicts_table).where(conflicts_table.c.id == id)
            ).fetchone()
            return self._row_to_conflict(row) if row else None

    def get_conflicts(
        self,
        status: Optional[str] = None,
        kind: Optional[str] = None,
        concept_id: Optional[str] = None,
        limit: int = 200,
    ) -> list[Conflict]:
        query = select(conflicts_table)
        if status is not None:
            query = query.where(conflicts_table.c.status == status)
        if kind is not None:
            query = query.where(conflicts_table.c.kind == kind)
        if concept_id is not None:
            # concept_ids is a JSON array serialized as text; match the quoted ID
            query = query.where(conflicts_table.c.concept_ids.like(f'%"{concept_id}"%'))
        query = query.order_by(conflicts_table.c.created_at.desc()).limit(limit)

        with self._connect() as conn:
            rows = conn.execute(query).fetchall()
            return [self._row_to_conflict(row) for row in rows]

    def update_conflict(self, conflict: Conflict) -> None:
        with self._connect() as conn:
            conn.execute(
                conflicts_table.update()
                .where(conflicts_table.c.id == conflict.id)
                .values(**self._conflict_values(conflict))
            )

    def count_conflicts(self, status: str = "open") -> int:
        with self._connect() as conn:
            return conn.execute(
                select(func.count()).select_from(conflicts_table)
                .where(conflicts_table.c.status == status)
            ).scalar() or 0

    def find_open_conflict_for_facts(self, fact_a_id: str, fact_b_id: str) -> Optional[Conflict]:
        with self._connect() as conn:
            row = conn.execute(
                select(conflicts_table)
                .where(conflicts_table.c.status == "open")
                .where(
                    ((conflicts_table.c.fact_a_id == fact_a_id) & (conflicts_table.c.fact_b_id == fact_b_id))
                    | ((conflicts_table.c.fact_a_id == fact_b_id) & (conflicts_table.c.fact_b_id == fact_a_id))
                )
            ).fetchone()
            return self._row_to_conflict(row) if row else None

    # ------------------------------------------------------------------
    # Evidence operations
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_evidence(row) -> Evidence:
        return Evidence(
            id=row.id,
            episode_id=row.episode_id,
            concept_id=row.concept_id,
            link_type=row.link_type,
            strength=row.strength or 0.5,
            note=row.note,
            created_at=row.created_at or datetime.now(),
        )

    def add_evidence(self, evidence: Evidence) -> str:
        with self._connect() as conn:
            conn.execute(evidence_table.insert().values(
                id=evidence.id,
                episode_id=evidence.episode_id,
                concept_id=evidence.concept_id,
                link_type=evidence.link_type,
                strength=evidence.strength,
                note=evidence.note,
                created_at=evidence.created_at,
            ))
        return evidence.id

    def get_evidence(self, id: str) -> Optional[Evidence]:
        with self._connect() as conn:
            row = conn.execute(
                select(evidence_table).where(evidence_table.c.id == id)
            ).fetchone()
            return self._row_to_evidence(row) if row else None

    def get_evidence_for_concept(self, concept_id: str) -> list[Evidence]:
        with self._connect() as conn:
            rows = conn.execute(
                select(evidence_table)
                .where(evidence_table.c.concept_id == concept_id)
                .order_by(evidence_table.c.created_at.desc())
            ).fetchall()
            return [self._row_to_evidence(row) for row in rows]

    def get_evidence_for_episode(self, episode_id: str) -> list[Evidence]:
        with self._connect() as conn:
            rows = conn.execute(
                select(evidence_table)
                .where(evidence_table.c.episode_id == episode_id)
                .order_by(evidence_table.c.created_at.desc())
            ).fetchall()
            return [self._row_to_evidence(row) for row in rows]

    def delete_evidence(self, id: str) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                evidence_table.delete().where(evidence_table.c.id == id)
            )
            return result.rowcount > 0

    def delete_evidence_for_concept(self, concept_id: str) -> int:
        with self._connect() as conn:
            result = conn.execute(
                evidence_table.delete().where(evidence_table.c.concept_id == concept_id)
            )
            return result.rowcount

    # ------------------------------------------------------------------
    # Entity relation operations
    # ------------------------------------------------------------------

    def add_entity_relation(self, relation: EntityRelation) -> None:
        with self._connect() as conn:
            existing = conn.execute(
                select(
                    entity_relations_table.c.strength,
                    entity_relations_table.c.source_episode_id,
                    entity_relations_table.c.episode_count,
                    entity_relations_table.c.source_episode_ids,
                    entity_relations_table.c.context,
                )
                .where(entity_relations_table.c.source_id == relation.source_id)
                .where(entity_relations_table.c.target_id == relation.target_id)
                .where(entity_relations_table.c.relation_type == relation.relation_type)
            ).fetchone()

            if existing:
                old_count = existing.episode_count or 1
                old_ids_raw = existing.source_episode_ids or "[]"
                try:
                    old_ids = json.loads(old_ids_raw) if isinstance(old_ids_raw, str) else (old_ids_raw or [])
                except (json.JSONDecodeError, TypeError):
                    old_ids = []
                    if existing.source_episode_id:
                        old_ids = [existing.source_episode_id]

                new_ep_id = relation.source_episode_id
                if new_ep_id and new_ep_id not in old_ids:
                    old_ids.append(new_ep_id)
                    new_count = old_count + 1
                    boost = min(0.1, (1.0 - existing.strength) * 0.2)
                    new_strength = min(1.0, existing.strength + boost)
                else:
                    new_count = old_count
                    new_strength = max(existing.strength, relation.strength)

                conn.execute(
                    entity_relations_table.update()
                    .where(entity_relations_table.c.source_id == relation.source_id)
                    .where(entity_relations_table.c.target_id == relation.target_id)
                    .where(entity_relations_table.c.relation_type == relation.relation_type)
                    .values(
                        strength=new_strength,
                        context=relation.context or existing.context,
                        source_episode_id=new_ep_id or existing.source_episode_id,
                        episode_count=new_count,
                        source_episode_ids=json.dumps(old_ids),
                    )
                )
            else:
                ep_ids = [relation.source_episode_id] if relation.source_episode_id else []
                conn.execute(
                    entity_relations_table.insert().values(
                        source_id=relation.source_id,
                        target_id=relation.target_id,
                        relation_type=relation.relation_type,
                        strength=relation.strength,
                        context=relation.context,
                        source_episode_id=relation.source_episode_id,
                        created_at=relation.created_at,
                        episode_count=1,
                        source_episode_ids=json.dumps(ep_ids),
                    )
                )

    def _entity_relation_from_row(self, row) -> EntityRelation:
        ep_ids_raw = getattr(row, "source_episode_ids", "[]") or "[]"
        try:
            ep_ids = json.loads(ep_ids_raw) if isinstance(ep_ids_raw, str) else (ep_ids_raw or [])
        except (json.JSONDecodeError, TypeError):
            ep_ids = []
        ep_count = getattr(row, "episode_count", 1) or 1
        created = row.created_at
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        elif created is None:
            created = datetime.now()
        return EntityRelation(
            source_id=row.source_id,
            target_id=row.target_id,
            relation_type=row.relation_type,
            strength=row.strength,
            context=row.context,
            source_episode_id=row.source_episode_id,
            created_at=created,
            episode_count=ep_count,
            source_episode_ids=ep_ids,
        )

    def get_entity_relations(self, entity_id: str) -> list[EntityRelation]:
        with self._connect() as conn:
            rows = conn.execute(
                select(entity_relations_table)
                .where(
                    (entity_relations_table.c.source_id == entity_id)
                    | (entity_relations_table.c.target_id == entity_id)
                )
                .order_by(entity_relations_table.c.strength.desc(), entity_relations_table.c.created_at.desc())
            ).fetchall()
            return [self._entity_relation_from_row(row) for row in rows]

    def get_entity_relations_from(self, entity_id: str) -> list[EntityRelation]:
        with self._connect() as conn:
            rows = conn.execute(
                select(entity_relations_table)
                .where(entity_relations_table.c.source_id == entity_id)
                .order_by(entity_relations_table.c.strength.desc(), entity_relations_table.c.created_at.desc())
            ).fetchall()
            return [self._entity_relation_from_row(row) for row in rows]

    def delete_entity_relations_from_episode(self, episode_id: str) -> int:
        with self._connect() as conn:
            result = conn.execute(
                entity_relations_table.delete()
                .where(entity_relations_table.c.source_episode_id == episode_id)
            )
            return result.rowcount

    def get_existing_relation_pairs(self, entity_ids: list[str]) -> set[tuple[str, str]]:
        if len(entity_ids) < 2:
            return set()
        with self._connect() as conn:
            rows = conn.execute(
                select(
                    entity_relations_table.c.source_id,
                    entity_relations_table.c.target_id,
                ).distinct()
                .where(entity_relations_table.c.source_id.in_(entity_ids))
                .where(entity_relations_table.c.target_id.in_(entity_ids))
            ).fetchall()
            return {(row.source_id, row.target_id) for row in rows}

    def get_unextracted_relation_episodes(self, limit: int = 100) -> list[Episode]:
        with self._connect() as conn:
            rows = conn.execute(
                select(episodes_table.c.data)
                .order_by(episodes_table.c.timestamp.desc())
            ).fetchall()
            results = []
            for row in rows:
                data = _parse_json(row.data)
                if data.get("deleted_at"):
                    continue
                extracted = data.get("entities_extracted")
                if extracted not in (True, 1, "true"):
                    continue
                rel_extracted = data.get("relations_extracted")
                if rel_extracted in (True, 1, "true"):
                    continue
                entity_ids = data.get("entity_ids", [])
                if len(entity_ids) < 2:
                    continue
                results.append(Episode.from_dict(data))
                if len(results) >= limit:
                    break
            return results

    # ------------------------------------------------------------------
    # Bulk operations for reconsolidation
    # ------------------------------------------------------------------

    def delete_all_concepts(self) -> int:
        with self._connect() as conn:
            if self._vec_backend == "sqlite-vec":
                try:
                    conn.execute(text("DELETE FROM vec_concepts"))
                except OperationalError:
                    pass
            conn.execute(relations_table.delete())
            conn.execute(labels_table.delete().where(labels_table.c.subject_type == "concept"))
            result = conn.execute(concepts_table.delete())
            return result.rowcount

    def delete_all_entities(self) -> int:
        with self._connect() as conn:
            conn.execute(entity_relations_table.delete())
            conn.execute(mentions_table.delete())
            conn.execute(labels_table.delete().where(labels_table.c.subject_type == "entity"))
            result = conn.execute(entities_table.delete())
            return result.rowcount

    def reset_episode_flags(self) -> int:
        with self._connect() as conn:
            rows = conn.execute(
                select(episodes_table.c.id, episodes_table.c.data)
            ).fetchall()

            count = 0
            for row in rows:
                data = _parse_json(row.data)
                data["consolidated"] = False
                data["entities_extracted"] = False
                data["relations_extracted"] = False
                data["entity_ids"] = []
                data["concepts_activated"] = []
                conn.execute(
                    episodes_table.update()
                    .where(episodes_table.c.id == row.id)
                    .values(data=_dump_json(data), consolidated=False)
                )
                count += 1
            return count

    def clear_embeddings(
        self,
        include_episodes: bool = True,
        include_concepts: bool = True,
        include_entities: bool = True,
    ) -> dict[str, int]:
        cleared_concepts = 0
        cleared_episodes = 0
        cleared_entities = 0

        with self._connect() as conn:
            if include_concepts:
                result = conn.execute(
                    concepts_table.update().values(embedding=None)
                )
                cleared_concepts = result.rowcount or 0

                if self._vec_backend == "sqlite-vec":
                    try:
                        conn.execute(text("DELETE FROM vec_concepts"))
                    except OperationalError:
                        pass
                elif self._vec_backend == "pgvector":
                    try:
                        conn.execute(text("UPDATE concepts SET embedding_vec = NULL"))
                    except OperationalError:
                        pass

            if include_episodes:
                result = conn.execute(
                    episodes_table.update().values(embedding=None)
                )
                cleared_episodes = result.rowcount or 0

                if self._vec_backend == "sqlite-vec":
                    try:
                        conn.execute(text("DELETE FROM vec_episodes"))
                    except OperationalError:
                        pass
                elif self._vec_backend == "pgvector":
                    try:
                        conn.execute(text("UPDATE episodes SET embedding_vec = NULL"))
                    except OperationalError:
                        pass

            if include_entities:
                result = conn.execute(
                    entities_table.update().values(embedding=None)
                )
                cleared_entities = result.rowcount or 0

                if self._vec_backend == "sqlite-vec":
                    try:
                        conn.execute(text("DELETE FROM vec_entities"))
                    except OperationalError:
                        pass
                elif self._vec_backend == "pgvector":
                    try:
                        conn.execute(text("UPDATE entities SET embedding_vec = NULL"))
                    except OperationalError:
                        pass

        return {
            "concepts_cleared": cleared_concepts,
            "episodes_cleared": cleared_episodes,
            "entities_cleared": cleared_entities,
        }

    # ------------------------------------------------------------------
    # Decay operations
    # ------------------------------------------------------------------

    def decay_concepts(
        self,
        decay_rate: float,
        skip_recently_accessed_seconds: int = 60,
    ) -> int:
        cutoff = datetime.now() - timedelta(seconds=skip_recently_accessed_seconds)

        with self._connect() as conn:
            rows = conn.execute(
                select(concepts_table.c.id, concepts_table.c.data)
            ).fetchall()

            affected = 0
            for row in rows:
                data = _parse_json(row.data)
                decay_factor = data.get("decay_factor", 1.0)
                if decay_factor is None:
                    decay_factor = 1.0
                if decay_factor <= 0:
                    continue

                last_accessed_str = data.get("last_accessed")
                if last_accessed_str:
                    try:
                        last_accessed = datetime.fromisoformat(last_accessed_str)
                        if last_accessed > cutoff:
                            continue
                    except (ValueError, TypeError):
                        pass

                new_factor = max(0.0, decay_factor - decay_rate)
                data["decay_factor"] = new_factor
                conn.execute(
                    concepts_table.update()
                    .where(concepts_table.c.id == row.id)
                    .values(data=_dump_json(data), updated_at=datetime.now())
                )
                affected += 1

            logger.info(f"Decay complete: {affected} concepts decayed")
            return affected

    # ------------------------------------------------------------------
    # Metadata operations
    # ------------------------------------------------------------------

    def get_metadata(self, key: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                select(metadata_table.c.value).where(metadata_table.c.key == key)
            ).fetchone()
            return row.value if row else None

    def set_metadata(self, key: str, value: str) -> None:
        with self._connect() as conn:
            existing = conn.execute(
                select(metadata_table.c.value).where(metadata_table.c.key == key)
            ).fetchone()
            if existing:
                conn.execute(
                    metadata_table.update()
                    .where(metadata_table.c.key == key)
                    .values(value=value)
                )
            else:
                conn.execute(
                    metadata_table.insert().values(key=key, value=value)
                )

    # ------------------------------------------------------------------
    # Change feed
    # ------------------------------------------------------------------

    def emit_event(
        self,
        kind: str,
        subject_type: str,
        subject_id: str,
        payload: Optional[dict] = None,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                events_table.insert().values(
                    kind=kind,
                    subject_type=subject_type,
                    subject_id=subject_id,
                    payload=_dump_json(payload) if payload is not None else None,
                )
            )

    def get_events(
        self,
        since_seq: int = 0,
        limit: int = 100,
        kind: Optional[str] = None,
    ) -> list[dict]:
        with self._connect() as conn:
            query = select(events_table).where(events_table.c.seq > since_seq)
            if kind:
                query = query.where(events_table.c.kind == kind)
            query = query.order_by(events_table.c.seq.asc()).limit(limit)
            rows = conn.execute(query).fetchall()
            events = []
            for row in rows:
                payload = _parse_json(row.payload) if row.payload else None
                events.append({
                    "seq": row.seq,
                    "ts": row.ts.isoformat() if row.ts else None,
                    "kind": row.kind,
                    "subject_type": row.subject_type,
                    "subject_id": row.subject_id,
                    "payload": payload,
                })
            return events

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        with self._connect() as conn:
            concept_count = conn.execute(select(func.count()).select_from(concepts_table)).scalar()
            episode_count = conn.execute(select(func.count()).select_from(episodes_table)).scalar()
            unconsolidated_count = conn.execute(
                select(func.count()).select_from(episodes_table)
                .where(episodes_table.c.consolidated == False)  # noqa: E712
            ).scalar()
            relation_count = conn.execute(select(func.count()).select_from(relations_table)).scalar()

            relation_types = conn.execute(
                select(relations_table.c.type, func.count().label("count"))
                .group_by(relations_table.c.type)
            ).fetchall()

            entity_count = conn.execute(select(func.count()).select_from(entities_table)).scalar()
            mention_count = conn.execute(select(func.count()).select_from(mentions_table)).scalar()
            entity_relation_count = conn.execute(
                select(func.count()).select_from(entity_relations_table)
            ).scalar()

            fact_count = conn.execute(select(func.count()).select_from(facts_table)).scalar()
            active_fact_count = conn.execute(
                select(func.count()).select_from(facts_table)
                .where(facts_table.c.valid_to.is_(None))
            ).scalar()

            open_conflict_count = conn.execute(
                select(func.count()).select_from(conflicts_table)
                .where(conflicts_table.c.status == "open")
            ).scalar()

            entity_relation_types = conn.execute(
                select(entity_relations_table.c.relation_type, func.count().label("count"))
                .group_by(entity_relations_table.c.relation_type)
            ).fetchall()

            entity_types = conn.execute(
                select(entities_table.c.type, func.count().label("count"))
                .group_by(entities_table.c.type)
            ).fetchall()

        # Episode type and extraction stats require parsing JSON data
        all_ep_data = []
        with self._connect() as conn:
            rows = conn.execute(select(episodes_table.c.data)).fetchall()
            all_ep_data = [_parse_json(row.data) for row in rows]

        all_concept_data = []
        with self._connect() as conn:
            rows = conn.execute(select(concepts_table.c.data)).fetchall()
            all_concept_data = [_parse_json(row.data) for row in rows]

        ep_type_counts: dict[str, int] = {}
        unextracted_count = 0
        for data in all_ep_data:
            ep_type = data.get("episode_type") or "observation"
            ep_type_counts[ep_type] = ep_type_counts.get(ep_type, 0) + 1
            extracted = data.get("entities_extracted")
            if extracted not in (True, 1, "true"):
                unextracted_count += 1

        concepts_with_decay = 0
        total_decay = 0.0
        min_decay = 1.0
        concept_type_counts: dict[str, int] = {}
        for data in all_concept_data:
            df = data.get("decay_factor", 1.0)
            if df is None:
                df = 1.0
            total_decay += df
            if df < 1.0:
                concepts_with_decay += 1
            min_decay = min(min_decay, df)
            # Count concept types
            concept_type = data.get("concept_type", "legacy")
            concept_type_counts[concept_type] = concept_type_counts.get(concept_type, 0) + 1

        avg_decay = round(total_decay / max(len(all_concept_data), 1), 3)

        return {
            "concepts": concept_count,
            "episodes": episode_count,
            "entities": entity_count,
            "mentions": mention_count,
            "relations": relation_count,
            "entity_relations": entity_relation_count,
            "facts": fact_count,
            "active_facts": active_fact_count,
            "open_conflicts": open_conflict_count,
            "unconsolidated_episodes": unconsolidated_count,
            "unextracted_episodes": unextracted_count,
            "relation_types": {row.type: row.count for row in relation_types},
            "entity_relation_types": {row.relation_type: row.count for row in entity_relation_types},
            "entity_types": {row.type: row.count for row in entity_types},
            "episode_types": ep_type_counts,
            "concept_types": concept_type_counts,
            "concepts_with_decay": concepts_with_decay,
            "avg_decay_factor": avg_decay,
            "min_decay_factor": round(min_decay, 3),
        }

    # ------------------------------------------------------------------
    # Extra methods (not on MemoryStore ABC)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Label operations
    # ------------------------------------------------------------------

    def _sync_labels(self, conn, subject_type: str, subject_id: str, labels: dict) -> None:
        """Replace all label rows for a subject with the given key->values map."""
        conn.execute(
            labels_table.delete().where(
                (labels_table.c.subject_type == subject_type)
                & (labels_table.c.subject_id == subject_id)
            )
        )
        for key, values in (labels or {}).items():
            if not key:
                continue
            values_list = values if isinstance(values, list) else [values]
            seen_values = set()
            for value in values_list:
                if not value or value in seen_values:
                    continue
                seen_values.add(value)
                conn.execute(
                    labels_table.insert().values(
                        subject_type=subject_type,
                        subject_id=subject_id,
                        key=key,
                        value=value,
                    )
                )

    def set_labels(self, subject_type: str, subject_id: str, labels: dict[str, list[str]]) -> None:
        """Replace all labels on a subject (episode | concept | fact) with *labels*."""
        with self._connect() as conn:
            self._sync_labels(conn, subject_type, subject_id, labels)

    def add_label(self, subject_type: str, subject_id: str, key: str, value: str) -> None:
        """Add a single key=value label to a subject, leaving existing labels intact."""
        with self._connect() as conn:
            try:
                conn.execute(
                    labels_table.insert().values(
                        subject_type=subject_type,
                        subject_id=subject_id,
                        key=key,
                        value=value,
                    )
                )
            except IntegrityError:
                pass  # already labeled with this exact key=value

    def remove_label(
        self, subject_type: str, subject_id: str, key: str, value: Optional[str] = None
    ) -> int:
        """Remove a label from a subject. If *value* is None, removes all
        values for *key*. Returns the number of rows removed."""
        with self._connect() as conn:
            cond = (
                (labels_table.c.subject_type == subject_type)
                & (labels_table.c.subject_id == subject_id)
                & (labels_table.c.key == key)
            )
            if value is not None:
                cond = cond & (labels_table.c.value == value)
            result = conn.execute(labels_table.delete().where(cond))
            return result.rowcount

    def get_labels(self, subject_type: str, subject_id: str) -> dict[str, list[str]]:
        """Get all labels on a subject as a key -> [values] map."""
        with self._connect() as conn:
            rows = conn.execute(
                select(labels_table.c.key, labels_table.c.value).where(
                    (labels_table.c.subject_type == subject_type)
                    & (labels_table.c.subject_id == subject_id)
                )
            ).fetchall()
        result: dict[str, list[str]] = {}
        for key, value in rows:
            result.setdefault(key, []).append(value)
        return result

    def find_subject_ids_by_labels(
        self, subject_type: str, label_filters: dict[str, str]
    ) -> set[str]:
        """Find subject IDs matching ALL of the given key=value label filters
        (AND across keys). Returns an empty set if *label_filters* is empty
        or no subject matches every filter."""
        if not label_filters:
            return set()
        with self._connect() as conn:
            result_ids: Optional[set[str]] = None
            for key, value in label_filters.items():
                rows = conn.execute(
                    select(labels_table.c.subject_id).where(
                        (labels_table.c.subject_type == subject_type)
                        & (labels_table.c.key == key)
                        & (labels_table.c.value == value)
                    )
                ).fetchall()
                ids = {r[0] for r in rows}
                result_ids = ids if result_ids is None else (result_ids & ids)
                if not result_ids:
                    return set()
        return result_ids or set()

    def get_distinct_labels(self, subject_type: Optional[str] = None) -> list[dict]:
        """List distinct key/value pairs currently in use, with counts.

        Powers label-filter UIs without exposing full subject listings.
        """
        with self._connect() as conn:
            stmt = select(
                labels_table.c.key,
                labels_table.c.value,
                func.count().label("count"),
            )
            if subject_type:
                stmt = stmt.where(labels_table.c.subject_type == subject_type)
            stmt = stmt.group_by(labels_table.c.key, labels_table.c.value).order_by(
                labels_table.c.key, labels_table.c.value
            )
            rows = conn.execute(stmt).fetchall()
        return [{"key": r.key, "value": r.value, "count": r.count} for r in rows]

    def export_data(self) -> dict:
        with self._connect() as conn:
            mention_rows = conn.execute(
                select(mentions_table.c.episode_id, mentions_table.c.entity_id)
            ).fetchall()

            er_rows = conn.execute(
                select(entity_relations_table)
            ).fetchall()

        return {
            "version": 3,
            "concepts": [c.to_dict() for c in self.get_all_concepts()],
            "episodes": [e.to_dict() for e in self.get_recent_episodes(limit=10000)],
            "entities": [e.to_dict() for e in self.get_all_entities()],
            "mentions": [
                {"episode_id": row.episode_id, "entity_id": row.entity_id}
                for row in mention_rows
            ],
            "entity_relations": [
                {
                    "source_id": row.source_id,
                    "target_id": row.target_id,
                    "relation_type": row.relation_type,
                    "strength": row.strength,
                    "context": row.context,
                    "source_episode_id": row.source_episode_id,
                    "created_at": row.created_at.isoformat() if isinstance(row.created_at, datetime) else row.created_at,
                    "episode_count": row.episode_count or 1,
                    "source_episode_ids": json.loads(row.source_episode_ids or "[]") if isinstance(row.source_episode_ids, str) else (row.source_episode_ids or []),
                }
                for row in er_rows
            ],
        }

    def import_data(self, data: dict) -> dict:
        concepts_imported = 0
        episodes_imported = 0
        entities_imported = 0
        mentions_imported = 0

        for concept_data in data.get("concepts", []):
            concept = Concept.from_dict(concept_data)
            try:
                self.add_concept(concept)
                concepts_imported += 1
            except IntegrityError:
                self.update_concept(concept)
                concepts_imported += 1

        for episode_data in data.get("episodes", []):
            episode = Episode.from_dict(episode_data)
            try:
                self.add_episode(episode)
                episodes_imported += 1
            except IntegrityError:
                self.update_episode(episode)
                episodes_imported += 1

        for entity_data in data.get("entities", []):
            entity = Entity.from_dict(entity_data)
            self.add_entity(entity)
            entities_imported += 1

        for mention in data.get("mentions", []):
            self.add_mention(mention["episode_id"], mention["entity_id"])
            mentions_imported += 1

        entity_relations_imported = 0
        for rel_data in data.get("entity_relations", []):
            relation = EntityRelation.from_dict(rel_data)
            self.add_entity_relation(relation)
            entity_relations_imported += 1

        return {
            "concepts_imported": concepts_imported,
            "episodes_imported": episodes_imported,
            "entities_imported": entities_imported,
            "mentions_imported": mentions_imported,
            "entity_relations_imported": entity_relations_imported,
        }


# Backward compatibility alias
SQLiteMemoryStore = SQLAlchemyMemoryStore
