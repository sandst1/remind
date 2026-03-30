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
)
from sqlalchemy.exc import IntegrityError, OperationalError

from remind.models import (
    Concept, Episode, Relation, RelationType,
    Entity, EntityType, EntityRelation, EpisodeType,
    Topic, DEFAULT_TOPIC_ID,
)

logger = logging.getLogger(__name__)


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
    def get_deleted_concepts(self) -> list[Concept]:
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

    # Embedding-based retrieval
    @abstractmethod
    def find_by_embedding(self, embedding: list[float], k: int = 5) -> list[tuple[Concept, float]]:
        """Find concepts by embedding similarity. Returns (concept, similarity) pairs."""
        ...

    @abstractmethod
    def find_episodes_by_embedding(self, embedding: list[float], k: int = 5) -> list[tuple["Episode", float]]:
        """Find episodes by embedding similarity. Returns (episode, similarity) pairs."""
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
    def get_episode(self, id: str) -> Optional[Episode]:
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

    # Statistics
    @abstractmethod
    def get_stats(self) -> dict:
        """Get storage statistics."""
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


# ---------------------------------------------------------------------------
# Table definitions
# ---------------------------------------------------------------------------

metadata_obj = MetaData()

topics_table = Table(
    "topics", metadata_obj,
    Column("id", String, primary_key=True),
    Column("name", Text, nullable=False),
    Column("description", Text, nullable=False, server_default=""),
    Column("created_at", DateTime, server_default=func.now()),
    Column("updated_at", DateTime, server_default=func.now()),
)

concepts_table = Table(
    "concepts", metadata_obj,
    Column("id", String, primary_key=True),
    Column("title", Text, nullable=True),
    Column("summary", Text, nullable=True),
    Column("data", JSON, nullable=False),
    Column("embedding", LargeBinary, nullable=True),
    Column("created_at", DateTime, server_default=func.now()),
    Column("updated_at", DateTime, server_default=func.now()),
    Column("topic_id", Text, nullable=True),
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
    Column("topic_id", Text, nullable=True),
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

metadata_table = Table(
    "metadata", metadata_obj,
    Column("key", String, primary_key=True),
    Column("value", Text, nullable=True),
)

# Indexes defined separately to keep Table definitions clean
Index("idx_episodes_consolidated", episodes_table.c.consolidated)
Index("idx_episodes_timestamp", episodes_table.c.timestamp)
Index("idx_episodes_topic_id", episodes_table.c.topic_id)
Index("idx_concepts_topic_id", concepts_table.c.topic_id)
Index("idx_relations_source", relations_table.c.source_id)
Index("idx_relations_target", relations_table.c.target_id)
Index("idx_relations_type", relations_table.c.type)
Index("idx_entities_type", entities_table.c.type)
Index("idx_mentions_episode", mentions_table.c.episode_id)
Index("idx_mentions_entity", mentions_table.c.entity_id)
Index("idx_entity_relations_source", entity_relations_table.c.source_id)
Index("idx_entity_relations_target", entity_relations_table.c.target_id)
Index("idx_entity_relations_episode", entity_relations_table.c.source_episode_id)


def _is_sqlite(engine) -> bool:
    return engine.dialect.name == "sqlite"


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
    """

    def __init__(self, db_url: str = "sqlite:///memory.db"):
        if db_url.endswith(".db") and "://" not in db_url:
            db_url = f"sqlite:///{db_url}"

        self.db_url = db_url
        self.engine = create_engine(db_url)
        self._init_db()

    @contextmanager
    def _connect(self):
        """Context manager that yields a connection and auto-commits on success."""
        with self.engine.connect() as conn:
            yield conn
            conn.commit()

    def _init_db(self):
        """Create tables and run additive migrations."""
        metadata_obj.create_all(self.engine)
        self._run_migrations()

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

            if not _has_column("episodes", "topic_id"):
                conn.execute(text("ALTER TABLE episodes ADD COLUMN topic_id TEXT"))
                conn.commit()
                logger.info("Migration: Added topic_id column to episodes table")

            if not _has_column("concepts", "topic_id"):
                conn.execute(text("ALTER TABLE concepts ADD COLUMN topic_id TEXT"))
                conn.commit()
                logger.info("Migration: Added topic_id column to concepts table")

            # Ensure topics table exists (create_all handles new installs;
            # this covers upgrades where tables were already created without it)
            if not insp.has_table("topics"):
                topics_table.create(self.engine)
                conn.commit()
                logger.info("Migration: Created topics table")

            try:
                entity_count = conn.execute(text("SELECT COUNT(*) FROM entities")).scalar()
                mention_count = conn.execute(text("SELECT COUNT(*) FROM mentions")).scalar()
                logger.debug(f"Schema v2: {entity_count} entities, {mention_count} mentions")
            except OperationalError:
                logger.warning("Entity tables not found, will be created on next init")

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
                    topic_id=concept.topic_id,
                )
            )
            self._sync_relations(conn, concept)
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

    def get_concept(self, id: str) -> Optional[Concept]:
        with self._connect() as conn:
            row = conn.execute(
                select(concepts_table.c.data, concepts_table.c.embedding)
                .where(concepts_table.c.id == id)
            ).fetchone()
            if not row:
                return None
            data = _parse_json(row.data)
            if data.get("deleted_at"):
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
                    topic_id=concept.topic_id,
                )
            )
            self._sync_relations(conn, concept)

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
            result = conn.execute(
                concepts_table.delete().where(concepts_table.c.id == id)
            )
            return result.rowcount > 0

    def get_deleted_concepts(self) -> list[Concept]:
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
            return concepts

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
                    concepts_table.c.topic_id,
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
                    "topic_id": row.topic_id,
                    "confidence": data.get("confidence"),
                    "instance_count": data.get("instance_count"),
                    "tags": data.get("tags", []),
                })
            return results

    # ------------------------------------------------------------------
    # Embedding-based retrieval
    # ------------------------------------------------------------------

    def find_by_embedding(self, embedding: list[float], k: int = 5) -> list[tuple[Concept, float]]:
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
                if not row.embedding:
                    continue
                stored = _bytes_to_embedding(row.embedding)
                sim = cosine_similarity(embedding, stored)
                data["embedding"] = stored
                results.append((Concept.from_dict(data), sim))

            results.sort(key=lambda x: x[1], reverse=True)
            return results[:k]

    def find_episodes_by_embedding(self, embedding: list[float], k: int = 5) -> list[tuple[Episode, float]]:
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
                if not row.embedding:
                    continue
                stored = _bytes_to_embedding(row.embedding)
                sim = cosine_similarity(embedding, stored)
                ep = Episode.from_dict(data)
                ep.embedding = stored
                results.append((ep, sim))

            results.sort(key=lambda x: x[1], reverse=True)
            return results[:k]

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
                    topic_id=episode.topic_id,
                )
            )
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
                        topic_id=episode.topic_id,
                    )
                )
                ids.append(episode.id)
            return ids

    def get_episode(self, id: str) -> Optional[Episode]:
        with self._connect() as conn:
            row = conn.execute(
                select(episodes_table.c.data, episodes_table.c.embedding)
                .where(episodes_table.c.id == id)
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
                    topic_id=episode.topic_id,
                )
            )

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
            conn.execute(
                entity_relations_table.delete()
                .where(entity_relations_table.c.source_episode_id == id)
            )
            conn.execute(
                mentions_table.delete()
                .where(mentions_table.c.episode_id == id)
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
        with self._connect() as conn:
            try:
                conn.execute(
                    entities_table.insert().values(
                        id=entity.id,
                        type=entity.type.value,
                        display_name=entity.display_name,
                        data=_dump_json(entity.to_dict()),
                        created_at=entity.created_at,
                    )
                )
            except IntegrityError:
                conn.rollback()
                conn.execute(
                    entities_table.update()
                    .where(entities_table.c.id == entity.id)
                    .values(
                        type=entity.type.value,
                        display_name=entity.display_name,
                        data=_dump_json(entity.to_dict()),
                    )
                )
        return entity.id

    def get_entity(self, id: str) -> Optional[Entity]:
        with self._connect() as conn:
            row = conn.execute(
                select(entities_table.c.data).where(entities_table.c.id == id)
            ).fetchone()
            if not row:
                return None
            return Entity.from_dict(_parse_json(row.data))

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
        normalized = " ".join(name.lower().split())
        with self._connect() as conn:
            row = conn.execute(
                select(entities_table.c.data)
                .where(func.lower(func.trim(entities_table.c.display_name)) == normalized)
                .order_by(entities_table.c.created_at.asc())
                .limit(1)
            ).fetchone()
            if not row:
                return None
            return Entity.from_dict(_parse_json(row.data))

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

    # ------------------------------------------------------------------
    # Mention operations
    # ------------------------------------------------------------------

    def add_mention(self, episode_id: str, entity_id: str) -> None:
        with self._connect() as conn:
            try:
                conn.execute(
                    mentions_table.insert().values(
                        episode_id=episode_id,
                        entity_id=entity_id,
                    )
                )
            except IntegrityError:
                conn.rollback()

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
        with self._connect() as conn:
            episode_rows = conn.execute(
                select(mentions_table.c.episode_id)
                .where(mentions_table.c.entity_id == entity_id)
            ).fetchall()
            episode_ids = {row.episode_id for row in episode_rows}

            if not episode_ids:
                return []

        all_concepts = self.get_all_concepts()
        matching = []
        for concept in all_concepts:
            overlap = set(concept.source_episodes) & episode_ids
            if overlap:
                matching.append((concept, len(overlap)))
        matching.sort(key=lambda x: x[1], reverse=True)
        return [c for c, _ in matching[:limit]]

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
            conn.execute(relations_table.delete())
            result = conn.execute(concepts_table.delete())
            return result.rowcount

    def delete_all_entities(self) -> int:
        with self._connect() as conn:
            conn.execute(entity_relations_table.delete())
            conn.execute(mentions_table.delete())
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
            try:
                conn.execute(
                    metadata_table.insert().values(key=key, value=value)
                )
            except IntegrityError:
                conn.rollback()
                conn.execute(
                    metadata_table.update()
                    .where(metadata_table.c.key == key)
                    .values(value=value)
                )

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
        for data in all_concept_data:
            df = data.get("decay_factor", 1.0)
            if df is None:
                df = 1.0
            total_decay += df
            if df < 1.0:
                concepts_with_decay += 1
            min_decay = min(min_decay, df)

        avg_decay = round(total_decay / max(len(all_concept_data), 1), 3)

        return {
            "concepts": concept_count,
            "episodes": episode_count,
            "entities": entity_count,
            "mentions": mention_count,
            "relations": relation_count,
            "entity_relations": entity_relation_count,
            "unconsolidated_episodes": unconsolidated_count,
            "unextracted_episodes": unextracted_count,
            "relation_types": {row.type: row.count for row in relation_types},
            "entity_relation_types": {row.relation_type: row.count for row in entity_relation_types},
            "entity_types": {row.type: row.count for row in entity_types},
            "episode_types": ep_type_counts,
            "concepts_with_decay": concepts_with_decay,
            "avg_decay_factor": avg_decay,
            "min_decay_factor": round(min_decay, 3),
        }

    # ------------------------------------------------------------------
    # Extra methods (not on MemoryStore ABC)
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Topic operations
    # ------------------------------------------------------------------

    def create_topic(self, topic: Topic) -> Topic:
        with self._connect() as conn:
            conn.execute(
                topics_table.insert().values(
                    id=topic.id,
                    name=topic.name,
                    description=topic.description,
                    created_at=topic.created_at,
                    updated_at=topic.updated_at,
                )
            )
        return topic

    def get_topic(self, topic_id: str) -> Optional[Topic]:
        with self._connect() as conn:
            row = conn.execute(
                select(topics_table).where(topics_table.c.id == topic_id)
            ).fetchone()
            if not row:
                return None
            return Topic(
                id=row.id,
                name=row.name,
                description=row.description or "",
                created_at=row.created_at if isinstance(row.created_at, datetime) else datetime.now(),
                updated_at=row.updated_at if isinstance(row.updated_at, datetime) else datetime.now(),
            )

    def get_all_topics(self) -> list[Topic]:
        with self._connect() as conn:
            rows = conn.execute(
                select(topics_table).order_by(topics_table.c.name)
            ).fetchall()
            return [
                Topic(
                    id=row.id,
                    name=row.name,
                    description=row.description or "",
                    created_at=row.created_at if isinstance(row.created_at, datetime) else datetime.now(),
                    updated_at=row.updated_at if isinstance(row.updated_at, datetime) else datetime.now(),
                )
                for row in rows
            ]

    def update_topic(self, topic: Topic) -> Topic:
        topic.updated_at = datetime.now()
        with self._connect() as conn:
            conn.execute(
                topics_table.update()
                .where(topics_table.c.id == topic.id)
                .values(
                    name=topic.name,
                    description=topic.description,
                    updated_at=topic.updated_at,
                )
            )
        return topic

    def delete_topic(self, topic_id: str) -> bool:
        with self._connect() as conn:
            result = conn.execute(
                topics_table.delete().where(topics_table.c.id == topic_id)
            )
            return result.rowcount > 0

    def get_or_create_default_topic(self) -> Topic:
        existing = self.get_topic(DEFAULT_TOPIC_ID)
        if existing:
            return existing
        topic = Topic(
            id=DEFAULT_TOPIC_ID,
            name="General",
            description="Default topic for uncategorized memories",
        )
        return self.create_topic(topic)

    def get_topic_stats(self) -> list[dict]:
        """Get all topics with episode/concept counts and latest activity."""
        topics = self.get_all_topics()
        if not topics:
            return []

        with self._connect() as conn:
            ep_rows = conn.execute(
                select(
                    episodes_table.c.topic_id,
                    func.count().label("cnt"),
                    func.max(episodes_table.c.timestamp).label("latest"),
                )
                .where(episodes_table.c.topic_id.isnot(None))
                .group_by(episodes_table.c.topic_id)
            ).fetchall()
            ep_map = {row.topic_id: {"count": row.cnt, "latest": row.latest} for row in ep_rows}

            concept_rows = conn.execute(
                select(
                    concepts_table.c.topic_id,
                    func.count().label("cnt"),
                )
                .where(concepts_table.c.topic_id.isnot(None))
                .group_by(concepts_table.c.topic_id)
            ).fetchall()
            concept_map = {row.topic_id: row.cnt for row in concept_rows}

        results = []
        for t in topics:
            ep_info = ep_map.get(t.id, {"count": 0, "latest": None})
            latest = ep_info["latest"]
            if isinstance(latest, datetime):
                latest = latest.isoformat()
            results.append({
                **t.to_dict(),
                "episode_count": ep_info["count"],
                "concept_count": concept_map.get(t.id, 0),
                "latest_activity": latest,
            })
        results.sort(key=lambda x: x["latest_activity"] or "", reverse=True)
        return results

    def get_concepts_by_topic(self, topic_id: str) -> list[Concept]:
        with self._connect() as conn:
            rows = conn.execute(
                select(concepts_table.c.data, concepts_table.c.embedding)
                .where(concepts_table.c.topic_id == topic_id)
            ).fetchall()
            concepts = []
            for row in rows:
                data = _parse_json(row.data)
                if data.get("deleted_at"):
                    continue
                if row.embedding:
                    data["embedding"] = _bytes_to_embedding(row.embedding)
                concepts.append(Concept.from_dict(data))
            concepts.sort(
                key=lambda c: (c.confidence or 0) * (c.instance_count or 0),
                reverse=True,
            )
            return concepts

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
