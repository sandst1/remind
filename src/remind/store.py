"""Memory storage backends."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional
import sqlite3
import json
import logging
import numpy as np
from pathlib import Path

from remind.models import (
    Concept, Episode, Relation, RelationType,
    Entity, EntityType, EntityRelation, EpisodeType,
)

logger = logging.getLogger(__name__)


class MemoryStore(ABC):
    """
    Abstract base class for memory storage.
    
    Defines the interface for storing and retrieving concepts, episodes,
    and their relationships. Implementations can use SQLite, Neo4j, etc.
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
        """Delete a concept. Returns True if deleted."""
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
    
    # Episode operations
    @abstractmethod
    def add_episode(self, episode: Episode) -> str:
        """Add an episode and return its ID."""
        ...
    
    @abstractmethod
    def get_episode(self, id: str) -> Optional[Episode]:
        """Get an episode by ID."""
        ...
    
    @abstractmethod
    def update_episode(self, episode: Episode) -> None:
        """Update an existing episode."""
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
    def get_entities_mentioned_in(self, episode_id: str) -> list[Entity]:
        """Get all entities mentioned in an episode."""
        ...
    
    @abstractmethod
    def get_unextracted_episodes(self, limit: int = 100) -> list[Episode]:
        """Get episodes that haven't had entity extraction performed."""
        ...
    
    @abstractmethod
    def get_episodes_by_type(self, episode_type: EpisodeType, limit: int = 50) -> list[Episode]:
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


class SQLiteMemoryStore(MemoryStore):
    """
    SQLite-based memory store.
    
    Simple, portable, no external dependencies.
    Uses JSON for flexible concept/episode storage while maintaining
    a separate relations table for efficient graph queries.
    """
    
    def __init__(self, db_path: str = "memory.db"):
        self.db_path = Path(db_path)
        self._init_db()
    
    def _get_conn(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
    def _init_db(self):
        """Initialize database schema with migration support."""
        conn = self._get_conn()
        try:
            # Concepts table - stores full concept data as JSON
            conn.execute("""
                CREATE TABLE IF NOT EXISTS concepts (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    summary TEXT,
                    data JSON NOT NULL,
                    embedding BLOB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Episodes table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id TEXT PRIMARY KEY,
                    content TEXT,
                    data JSON NOT NULL,
                    consolidated BOOLEAN DEFAULT FALSE,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Relations table for efficient graph queries
            conn.execute("""
                CREATE TABLE IF NOT EXISTS relations (
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    strength REAL DEFAULT 0.5,
                    context TEXT,
                    PRIMARY KEY (source_id, target_id, type),
                    FOREIGN KEY (source_id) REFERENCES concepts(id) ON DELETE CASCADE,
                    FOREIGN KEY (target_id) REFERENCES concepts(id) ON DELETE CASCADE
                )
            """)
            
            # === NEW TABLES (v2 schema) ===
            
            # Entities table - external referents (files, functions, people, etc.)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    display_name TEXT,
                    data JSON,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Mentions table - links episodes to entities
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mentions (
                    episode_id TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (episode_id, entity_id),
                    FOREIGN KEY (episode_id) REFERENCES episodes(id) ON DELETE CASCADE,
                    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
                )
            """)

            # Entity relations table - relationships between entities
            conn.execute("""
                CREATE TABLE IF NOT EXISTS entity_relations (
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    relation_type TEXT NOT NULL,
                    strength REAL DEFAULT 0.5,
                    context TEXT,
                    source_episode_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (source_id, target_id, relation_type),
                    FOREIGN KEY (source_id) REFERENCES entities(id) ON DELETE CASCADE,
                    FOREIGN KEY (target_id) REFERENCES entities(id) ON DELETE CASCADE,
                    FOREIGN KEY (source_episode_id) REFERENCES episodes(id) ON DELETE SET NULL
                )
            """)

            # === INDEXES ===
            
            # Episode indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_consolidated ON episodes(consolidated)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_timestamp ON episodes(timestamp)")
            
            # Relation indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_relations_type ON relations(type)")
            
            # Entity indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(type)")
            
            # Mention indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mentions_episode ON mentions(episode_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_mentions_entity ON mentions(entity_id)")

            # Entity relation indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_relations_source ON entity_relations(source_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_relations_target ON entity_relations(target_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_entity_relations_episode ON entity_relations(source_episode_id)")

            conn.commit()
            
            # Run migrations for existing databases
            self._run_migrations(conn)
            
        finally:
            conn.close()
    
    def _run_migrations(self, conn: sqlite3.Connection):
        """Run schema migrations for backwards compatibility."""
        # Check if episodes table has the entities_extracted indicator in data
        # This is handled via JSON in the data column, so no schema migration needed
        # The Episode.from_dict() handles missing fields with defaults

        # Migration: Add title column to concepts table if it doesn't exist
        try:
            conn.execute("SELECT title FROM concepts LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE concepts ADD COLUMN title TEXT")
            conn.commit()
            logger.info("Migration: Added title column to concepts table")

        # Migration: Add title column to episodes table if it doesn't exist
        try:
            conn.execute("SELECT title FROM episodes LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE episodes ADD COLUMN title TEXT")
            conn.commit()
            logger.info("Migration: Added title column to episodes table")

        # Log migration status
        try:
            entity_count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            mention_count = conn.execute("SELECT COUNT(*) FROM mentions").fetchone()[0]
            logger.debug(f"Schema v2: {entity_count} entities, {mention_count} mentions")
        except sqlite3.OperationalError:
            # Tables don't exist yet (shouldn't happen, but handle gracefully)
            logger.warning("Entity tables not found, will be created on next init")
    
    # Concept operations
    
    def add_concept(self, concept: Concept) -> str:
        """Add a concept and return its ID."""
        conn = self._get_conn()
        try:
            data = concept.to_dict()
            embedding_blob = None
            if concept.embedding:
                embedding_blob = np.array(concept.embedding, dtype=np.float32).tobytes()
            
            conn.execute(
                """
                INSERT INTO concepts (id, title, summary, data, embedding, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    concept.id,
                    concept.title,
                    concept.summary,
                    json.dumps(data),
                    embedding_blob,
                    concept.created_at.isoformat(),
                    concept.updated_at.isoformat(),
                )
            )
            
            # Add relations to relations table
            self._sync_relations(conn, concept)
            
            conn.commit()
            return concept.id
        finally:
            conn.close()
    
    def _sync_relations(self, conn: sqlite3.Connection, concept: Concept):
        """Sync concept's relations to the relations table."""
        # Delete existing relations from this concept
        conn.execute("DELETE FROM relations WHERE source_id = ?", (concept.id,))
        
        # Insert current relations
        for rel in concept.relations:
            conn.execute(
                """
                INSERT OR REPLACE INTO relations (source_id, target_id, type, strength, context)
                VALUES (?, ?, ?, ?, ?)
                """,
                (concept.id, rel.target_id, rel.type.value, rel.strength, rel.context)
            )
    
    def get_concept(self, id: str) -> Optional[Concept]:
        """Get a concept by ID."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT data, embedding FROM concepts WHERE id = ?",
                (id,)
            ).fetchone()
            
            if not row:
                return None
            
            data = json.loads(row["data"])
            
            # Restore embedding from blob
            if row["embedding"]:
                data["embedding"] = np.frombuffer(row["embedding"], dtype=np.float32).tolist()
            
            return Concept.from_dict(data)
        finally:
            conn.close()
    
    def update_concept(self, concept: Concept) -> None:
        """Update an existing concept."""
        conn = self._get_conn()
        try:
            data = concept.to_dict()
            embedding_blob = None
            if concept.embedding:
                embedding_blob = np.array(concept.embedding, dtype=np.float32).tobytes()
            
            conn.execute(
                """
                UPDATE concepts
                SET title = ?, summary = ?, data = ?, embedding = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    concept.title,
                    concept.summary,
                    json.dumps(data),
                    embedding_blob,
                    concept.updated_at.isoformat(),
                    concept.id,
                )
            )
            
            # Sync relations
            self._sync_relations(conn, concept)
            
            conn.commit()
        finally:
            conn.close()
    
    def delete_concept(self, id: str) -> bool:
        """Delete a concept. Returns True if deleted."""
        conn = self._get_conn()
        try:
            cursor = conn.execute("DELETE FROM concepts WHERE id = ?", (id,))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()
    
    def get_all_concepts(self) -> list[Concept]:
        """Get all concepts."""
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT data, embedding FROM concepts").fetchall()
            concepts = []
            for row in rows:
                data = json.loads(row["data"])
                if row["embedding"]:
                    data["embedding"] = np.frombuffer(row["embedding"], dtype=np.float32).tolist()
                concepts.append(Concept.from_dict(data))
            return concepts
        finally:
            conn.close()
    
    def get_concepts_summary(self) -> list[dict]:
        """Get a lightweight summary of all concepts."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT id, title, summary,
                       json_extract(data, '$.confidence') as confidence,
                       json_extract(data, '$.instance_count') as instance_count,
                       json_extract(data, '$.tags') as tags
                FROM concepts
                """
            ).fetchall()

            return [
                {
                    "id": row["id"],
                    "title": row["title"],
                    "summary": row["summary"],
                    "confidence": row["confidence"],
                    "instance_count": row["instance_count"],
                    "tags": json.loads(row["tags"]) if row["tags"] else [],
                }
                for row in rows
            ]
        finally:
            conn.close()
    
    # Embedding-based retrieval
    
    def find_by_embedding(self, embedding: list[float], k: int = 5) -> list[tuple[Concept, float]]:
        """Find concepts by embedding similarity."""
        conn = self._get_conn()
        try:
            rows = conn.execute("SELECT data, embedding FROM concepts WHERE embedding IS NOT NULL").fetchall()
            
            results = []
            for row in rows:
                if not row["embedding"]:
                    continue
                
                stored_embedding = np.frombuffer(row["embedding"], dtype=np.float32).tolist()
                similarity = cosine_similarity(embedding, stored_embedding)
                
                data = json.loads(row["data"])
                data["embedding"] = stored_embedding
                concept = Concept.from_dict(data)
                
                results.append((concept, similarity))
            
            # Sort by similarity descending and take top k
            results.sort(key=lambda x: x[1], reverse=True)
            return results[:k]
        finally:
            conn.close()
    
    # Graph traversal
    
    def get_related(
        self,
        concept_id: str,
        relation_types: Optional[list[RelationType]] = None,
        depth: int = 1
    ) -> list[tuple[Concept, Relation]]:
        """Get related concepts with their relations."""
        conn = self._get_conn()
        try:
            visited = set()
            results = []
            
            self._traverse_relations(conn, concept_id, relation_types, depth, visited, results)
            
            return results
        finally:
            conn.close()
    
    def _traverse_relations(
        self,
        conn: sqlite3.Connection,
        concept_id: str,
        relation_types: Optional[list[RelationType]],
        remaining_depth: int,
        visited: set,
        results: list
    ):
        """Recursively traverse relations."""
        if remaining_depth <= 0 or concept_id in visited:
            return
        
        visited.add(concept_id)
        
        # Build query
        query = "SELECT target_id, type, strength, context FROM relations WHERE source_id = ?"
        params = [concept_id]
        
        if relation_types:
            placeholders = ",".join("?" * len(relation_types))
            query += f" AND type IN ({placeholders})"
            params.extend(rt.value for rt in relation_types)
        
        rows = conn.execute(query, params).fetchall()
        
        for row in rows:
            target_id = row["target_id"]
            
            # Skip if already visited
            if target_id in visited:
                continue
            
            # Get the target concept
            concept_row = conn.execute(
                "SELECT data, embedding FROM concepts WHERE id = ?",
                (target_id,)
            ).fetchone()
            
            if not concept_row:
                continue
            
            data = json.loads(concept_row["data"])
            if concept_row["embedding"]:
                data["embedding"] = np.frombuffer(concept_row["embedding"], dtype=np.float32).tolist()
            
            concept = Concept.from_dict(data)
            relation = Relation(
                type=RelationType(row["type"]),
                target_id=target_id,
                strength=row["strength"],
                context=row["context"],
            )
            
            results.append((concept, relation))
            
            # Recurse if we have more depth
            if remaining_depth > 1:
                self._traverse_relations(
                    conn, target_id, relation_types, remaining_depth - 1, visited, results
                )
    
    # Episode operations
    
    def add_episode(self, episode: Episode) -> str:
        """Add an episode and return its ID."""
        conn = self._get_conn()
        try:
            data = episode.to_dict()

            conn.execute(
                """
                INSERT INTO episodes (id, title, content, data, consolidated, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    episode.id,
                    episode.title,
                    episode.content,
                    json.dumps(data),
                    episode.consolidated,
                    episode.timestamp.isoformat(),
                )
            )
            conn.commit()
            return episode.id
        finally:
            conn.close()
    
    def get_episode(self, id: str) -> Optional[Episode]:
        """Get an episode by ID."""
        conn = self._get_conn()
        try:
            row = conn.execute("SELECT data FROM episodes WHERE id = ?", (id,)).fetchone()
            if not row:
                return None
            return Episode.from_dict(json.loads(row["data"]))
        finally:
            conn.close()
    
    def update_episode(self, episode: Episode) -> None:
        """Update an existing episode."""
        conn = self._get_conn()
        try:
            data = episode.to_dict()

            conn.execute(
                """
                UPDATE episodes
                SET title = ?, content = ?, data = ?, consolidated = ?, timestamp = ?
                WHERE id = ?
                """,
                (
                    episode.title,
                    episode.content,
                    json.dumps(data),
                    episode.consolidated,
                    episode.timestamp.isoformat(),
                    episode.id,
                )
            )
            conn.commit()
        finally:
            conn.close()
    
    def get_unconsolidated_episodes(self, limit: int = 10) -> list[Episode]:
        """Get episodes that haven't been consolidated yet."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT data FROM episodes 
                WHERE consolidated = FALSE 
                ORDER BY timestamp ASC 
                LIMIT ?
                """,
                (limit,)
            ).fetchall()
            
            return [Episode.from_dict(json.loads(row["data"])) for row in rows]
        finally:
            conn.close()

    def count_unconsolidated_episodes(self) -> int:
        """Count episodes that haven't been consolidated yet."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) as count FROM episodes WHERE consolidated = FALSE"
            ).fetchone()
            return row["count"]
        finally:
            conn.close()

    def get_recent_episodes(self, limit: int = 10) -> list[Episode]:
        """Get most recent episodes."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT data FROM episodes 
                ORDER BY timestamp DESC 
                LIMIT ?
                """,
                (limit,)
            ).fetchall()
            
            return [Episode.from_dict(json.loads(row["data"])) for row in rows]
        finally:
            conn.close()
    
    def get_episodes_by_date_range(
        self, 
        start_date: Optional[str] = None, 
        end_date: Optional[str] = None,
        limit: int = 100
    ) -> list[Episode]:
        """Get episodes within a date range.
        
        Args:
            start_date: ISO format datetime string (inclusive), e.g., "2024-01-01" or "2024-01-01T10:00:00"
            end_date: ISO format datetime string (inclusive), e.g., "2024-12-31" or "2024-12-31T23:59:59"
            limit: Maximum number of episodes to return
            
        Returns:
            List of episodes sorted by timestamp (newest first)
        """
        conn = self._get_conn()
        try:
            query = "SELECT data FROM episodes WHERE 1=1"
            params = []
            
            if start_date:
                query += " AND timestamp >= ?"
                params.append(start_date)
            
            if end_date:
                query += " AND timestamp <= ?"
                params.append(end_date)
            
            query += " ORDER BY timestamp DESC LIMIT ?"
            params.append(limit)
            
            rows = conn.execute(query, params).fetchall()
            
            return [Episode.from_dict(json.loads(row["data"])) for row in rows]
        finally:
            conn.close()

    def get_unextracted_episodes(self, limit: int = 100) -> list[Episode]:
        """Get episodes that haven't had entity extraction performed."""
        conn = self._get_conn()
        try:
            # Check entities_extracted flag in JSON data
            rows = conn.execute(
                """
                SELECT data FROM episodes 
                WHERE json_extract(data, '$.entities_extracted') IS NULL 
                   OR json_extract(data, '$.entities_extracted') = 0
                   OR json_extract(data, '$.entities_extracted') = 'false'
                ORDER BY timestamp ASC 
                LIMIT ?
                """,
                (limit,)
            ).fetchall()
            
            return [Episode.from_dict(json.loads(row["data"])) for row in rows]
        finally:
            conn.close()
    
    def get_episodes_by_type(self, episode_type: EpisodeType, limit: int = 50) -> list[Episode]:
        """Get episodes of a specific type."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT data FROM episodes 
                WHERE json_extract(data, '$.episode_type') = ?
                ORDER BY timestamp DESC 
                LIMIT ?
                """,
                (episode_type.value, limit)
            ).fetchall()
            
            return [Episode.from_dict(json.loads(row["data"])) for row in rows]
        finally:
            conn.close()
    
    # Entity operations
    
    def add_entity(self, entity: Entity) -> str:
        """Add an entity and return its ID. Updates if exists."""
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO entities (id, type, display_name, data, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    entity.id,
                    entity.type.value,
                    entity.display_name,
                    json.dumps(entity.to_dict()),
                    entity.created_at.isoformat(),
                )
            )
            conn.commit()
            return entity.id
        finally:
            conn.close()
    
    def get_entity(self, id: str) -> Optional[Entity]:
        """Get an entity by ID."""
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT data FROM entities WHERE id = ?",
                (id,)
            ).fetchone()
            
            if not row:
                return None
            
            return Entity.from_dict(json.loads(row["data"]))
        finally:
            conn.close()
    
    def get_entities_by_type(self, entity_type: EntityType) -> list[Entity]:
        """Get all entities of a given type."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT data FROM entities WHERE type = ? ORDER BY created_at DESC",
                (entity_type.value,)
            ).fetchall()
            
            return [Entity.from_dict(json.loads(row["data"])) for row in rows]
        finally:
            conn.close()
    
    def get_all_entities(self) -> list[Entity]:
        """Get all entities."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT data FROM entities ORDER BY type, created_at DESC"
            ).fetchall()

            return [Entity.from_dict(json.loads(row["data"])) for row in rows]
        finally:
            conn.close()

    def find_entity_by_name(self, name: str) -> Optional[Entity]:
        """Find an entity by display name, case-insensitive.

        Uses LOWER() for case-insensitive comparison and TRIM() for whitespace.
        Returns the first match if multiple entities have the same normalized name.

        Args:
            name: The entity name to search for

        Returns:
            Entity if found, None otherwise
        """
        if not name:
            return None

        # Normalize the search name
        normalized = " ".join(name.lower().split())

        conn = self._get_conn()
        try:
            # Search by normalized display_name (case-insensitive, trimmed)
            row = conn.execute(
                """
                SELECT data FROM entities
                WHERE LOWER(TRIM(display_name)) = ?
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (normalized,)
            ).fetchone()

            if not row:
                return None

            return Entity.from_dict(json.loads(row["data"]))
        finally:
            conn.close()

    # Mention operations
    
    def add_mention(self, episode_id: str, entity_id: str) -> None:
        """Create a mention link between episode and entity."""
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT OR IGNORE INTO mentions (episode_id, entity_id)
                VALUES (?, ?)
                """,
                (episode_id, entity_id)
            )
            conn.commit()
        finally:
            conn.close()
    
    def get_episodes_mentioning(self, entity_id: str, limit: int = 50) -> list[Episode]:
        """Get all episodes that mention an entity."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT e.data FROM episodes e
                JOIN mentions m ON e.id = m.episode_id
                WHERE m.entity_id = ?
                ORDER BY e.timestamp DESC
                LIMIT ?
                """,
                (entity_id, limit)
            ).fetchall()
            
            return [Episode.from_dict(json.loads(row["data"])) for row in rows]
        finally:
            conn.close()
    
    def get_entities_mentioned_in(self, episode_id: str) -> list[Entity]:
        """Get all entities mentioned in an episode."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT ent.data FROM entities ent
                JOIN mentions m ON ent.id = m.entity_id
                WHERE m.episode_id = ?
                ORDER BY ent.type, ent.display_name
                """,
                (episode_id,)
            ).fetchall()
            
            return [Entity.from_dict(json.loads(row["data"])) for row in rows]
        finally:
            conn.close()
    
    def get_entity_mention_counts(self) -> list[tuple[Entity, int]]:
        """Get all entities with their mention counts, sorted by count desc."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT ent.data, COUNT(m.episode_id) as mention_count
                FROM entities ent
                LEFT JOIN mentions m ON ent.id = m.entity_id
                GROUP BY ent.id
                ORDER BY mention_count DESC, ent.type
                """
            ).fetchall()
            
            return [
                (Entity.from_dict(json.loads(row["data"])), row["mention_count"])
                for row in rows
            ]
        finally:
            conn.close()

    def get_concepts_for_entity(self, entity_id: str, limit: int = 50) -> list[Concept]:
        """Get concepts derived from episodes mentioning an entity.

        Finds concepts whose source_episodes overlap with episodes that mention
        this entity, sorted by relevance (number of overlapping episodes).

        Args:
            entity_id: The entity ID (e.g., "file:src/auth.ts")
            limit: Maximum number of concepts to return

        Returns:
            List of concepts sorted by relevance
        """
        conn = self._get_conn()
        try:
            # Get episode IDs that mention this entity
            episode_rows = conn.execute(
                "SELECT episode_id FROM mentions WHERE entity_id = ?",
                (entity_id,)
            ).fetchall()
            episode_ids = {row["episode_id"] for row in episode_rows}

            if not episode_ids:
                return []

            # Get all concepts and check which ones have overlapping source_episodes
            all_concepts = self.get_all_concepts()

            matching_concepts = []
            for concept in all_concepts:
                overlap = set(concept.source_episodes) & episode_ids
                if overlap:
                    matching_concepts.append((concept, len(overlap)))

            # Sort by number of overlapping episodes (most relevant first)
            matching_concepts.sort(key=lambda x: x[1], reverse=True)

            return [c for c, _ in matching_concepts[:limit]]
        finally:
            conn.close()

    # Entity relation operations

    def add_entity_relation(self, relation: EntityRelation) -> None:
        """Add an entity relation. Updates if same source/target/type exists."""
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT OR REPLACE INTO entity_relations
                (source_id, target_id, relation_type, strength, context, source_episode_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    relation.source_id,
                    relation.target_id,
                    relation.relation_type,
                    relation.strength,
                    relation.context,
                    relation.source_episode_id,
                    relation.created_at.isoformat(),
                )
            )
            conn.commit()
        finally:
            conn.close()

    def get_entity_relations(self, entity_id: str) -> list[EntityRelation]:
        """Get all relations involving an entity (as source or target)."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT source_id, target_id, relation_type, strength, context, source_episode_id, created_at
                FROM entity_relations
                WHERE source_id = ? OR target_id = ?
                ORDER BY strength DESC, created_at DESC
                """,
                (entity_id, entity_id)
            ).fetchall()
            return [
                EntityRelation(
                    source_id=row["source_id"],
                    target_id=row["target_id"],
                    relation_type=row["relation_type"],
                    strength=row["strength"],
                    context=row["context"],
                    source_episode_id=row["source_episode_id"],
                    created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(),
                )
                for row in rows
            ]
        finally:
            conn.close()

    def get_entity_relations_from(self, entity_id: str) -> list[EntityRelation]:
        """Get relations where entity is the source (outgoing relations)."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                """
                SELECT source_id, target_id, relation_type, strength, context, source_episode_id, created_at
                FROM entity_relations
                WHERE source_id = ?
                ORDER BY strength DESC, created_at DESC
                """,
                (entity_id,)
            ).fetchall()
            return [
                EntityRelation(
                    source_id=row["source_id"],
                    target_id=row["target_id"],
                    relation_type=row["relation_type"],
                    strength=row["strength"],
                    context=row["context"],
                    source_episode_id=row["source_episode_id"],
                    created_at=datetime.fromisoformat(row["created_at"]) if row["created_at"] else datetime.now(),
                )
                for row in rows
            ]
        finally:
            conn.close()

    def delete_entity_relations_from_episode(self, episode_id: str) -> int:
        """Delete all entity relations derived from an episode. Returns count deleted."""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "DELETE FROM entity_relations WHERE source_episode_id = ?",
                (episode_id,)
            )
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def get_existing_relation_pairs(self, entity_ids: list[str]) -> set[tuple[str, str]]:
        """Get pairs of entities that already have relations between them."""
        if len(entity_ids) < 2:
            return set()

        conn = self._get_conn()
        try:
            placeholders = ",".join("?" * len(entity_ids))
            rows = conn.execute(
                f"""
                SELECT DISTINCT source_id, target_id
                FROM entity_relations
                WHERE source_id IN ({placeholders})
                  AND target_id IN ({placeholders})
                """,
                entity_ids + entity_ids
            ).fetchall()
            return {(row["source_id"], row["target_id"]) for row in rows}
        finally:
            conn.close()

    def get_unextracted_relation_episodes(self, limit: int = 100) -> list[Episode]:
        """Get episodes that have entities but haven't had relation extraction performed.

        Only returns episodes with 2+ entities (need at least 2 for a relationship).
        """
        conn = self._get_conn()
        try:
            # Get episodes where:
            # - entities_extracted = true (has entities)
            # - relations_extracted is false or null
            # - has at least 2 entity_ids
            rows = conn.execute(
                """
                SELECT data FROM episodes
                WHERE (json_extract(data, '$.entities_extracted') = 1
                       OR json_extract(data, '$.entities_extracted') = 'true')
                  AND (json_extract(data, '$.relations_extracted') IS NULL
                       OR json_extract(data, '$.relations_extracted') = 0
                       OR json_extract(data, '$.relations_extracted') = 'false')
                  AND json_array_length(json_extract(data, '$.entity_ids')) >= 2
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (limit,)
            ).fetchall()
            return [Episode.from_dict(json.loads(row["data"])) for row in rows]
        finally:
            conn.close()

    # Bulk operations for reconsolidation

    def delete_all_concepts(self) -> int:
        """Delete all concepts and their relations. Returns count deleted."""
        conn = self._get_conn()
        try:
            # Delete relations first (foreign key constraint)
            conn.execute("DELETE FROM relations")
            # Delete concepts
            cursor = conn.execute("DELETE FROM concepts")
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def delete_all_entities(self) -> int:
        """Delete all entities, mentions, and entity relations. Returns count deleted."""
        conn = self._get_conn()
        try:
            # Delete in order of foreign key dependencies
            conn.execute("DELETE FROM entity_relations")
            conn.execute("DELETE FROM mentions")
            cursor = conn.execute("DELETE FROM entities")
            conn.commit()
            return cursor.rowcount
        finally:
            conn.close()

    def reset_episode_flags(self) -> int:
        """Reset consolidated, entities_extracted, and relations_extracted flags on all episodes.

        Also clears entity_ids and concepts_activated lists.
        Returns count of episodes reset.
        """
        conn = self._get_conn()
        try:
            # Get all episodes
            rows = conn.execute("SELECT id, data FROM episodes").fetchall()

            count = 0
            for row in rows:
                data = json.loads(row["data"])
                # Reset flags
                data["consolidated"] = False
                data["entities_extracted"] = False
                data["relations_extracted"] = False
                # Clear derived data
                data["entity_ids"] = []
                data["concepts_activated"] = []

                conn.execute(
                    "UPDATE episodes SET data = ?, consolidated = ? WHERE id = ?",
                    (json.dumps(data), False, row["id"])
                )
                count += 1

            conn.commit()
            return count
        finally:
            conn.close()

    # Statistics

    def get_stats(self) -> dict:
        """Get storage statistics."""
        conn = self._get_conn()
        try:
            concept_count = conn.execute("SELECT COUNT(*) FROM concepts").fetchone()[0]
            episode_count = conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
            unconsolidated_count = conn.execute(
                "SELECT COUNT(*) FROM episodes WHERE consolidated = FALSE"
            ).fetchone()[0]
            relation_count = conn.execute("SELECT COUNT(*) FROM relations").fetchone()[0]
            
            # Get relation type distribution
            relation_types = conn.execute(
                "SELECT type, COUNT(*) as count FROM relations GROUP BY type"
            ).fetchall()
            
            # Entity/mention stats (v2 schema)
            entity_count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
            mention_count = conn.execute("SELECT COUNT(*) FROM mentions").fetchone()[0]
            entity_relation_count = conn.execute("SELECT COUNT(*) FROM entity_relations").fetchone()[0]

            # Entity relation type distribution
            entity_relation_types = conn.execute(
                "SELECT relation_type, COUNT(*) as count FROM entity_relations GROUP BY relation_type"
            ).fetchall()
            
            # Episode type distribution
            episode_types = conn.execute(
                """
                SELECT json_extract(data, '$.episode_type') as type, COUNT(*) as count 
                FROM episodes 
                GROUP BY json_extract(data, '$.episode_type')
                """
            ).fetchall()
            
            # Entity type distribution
            entity_types = conn.execute(
                "SELECT type, COUNT(*) as count FROM entities GROUP BY type"
            ).fetchall()
            
            # Count unextracted episodes
            unextracted_count = conn.execute(
                """
                SELECT COUNT(*) FROM episodes 
                WHERE json_extract(data, '$.entities_extracted') IS NULL 
                   OR json_extract(data, '$.entities_extracted') = 0
                   OR json_extract(data, '$.entities_extracted') = 'false'
                """
            ).fetchone()[0]
            
            return {
                "concepts": concept_count,
                "episodes": episode_count,
                "entities": entity_count,
                "mentions": mention_count,
                "relations": relation_count,
                "entity_relations": entity_relation_count,
                "unconsolidated_episodes": unconsolidated_count,
                "unextracted_episodes": unextracted_count,
                "relation_types": {row["type"]: row["count"] for row in relation_types},
                "entity_relation_types": {row["relation_type"]: row["count"] for row in entity_relation_types},
                "entity_types": {row["type"]: row["count"] for row in entity_types},
                "episode_types": {
                    (row["type"] or "observation"): row["count"]
                    for row in episode_types
                },
            }
        finally:
            conn.close()
    
    def export_data(self) -> dict:
        """Export all data for backup."""
        conn = self._get_conn()
        try:
            # Export mentions as list of (episode_id, entity_id) tuples
            mentions = conn.execute(
                "SELECT episode_id, entity_id FROM mentions"
            ).fetchall()

            # Export entity relations
            entity_relations = conn.execute(
                "SELECT source_id, target_id, relation_type, strength, context, source_episode_id, created_at FROM entity_relations"
            ).fetchall()

            return {
                "version": 3,
                "concepts": [c.to_dict() for c in self.get_all_concepts()],
                "episodes": [e.to_dict() for e in self.get_recent_episodes(limit=10000)],
                "entities": [e.to_dict() for e in self.get_all_entities()],
                "mentions": [
                    {"episode_id": row["episode_id"], "entity_id": row["entity_id"]}
                    for row in mentions
                ],
                "entity_relations": [
                    {
                        "source_id": row["source_id"],
                        "target_id": row["target_id"],
                        "relation_type": row["relation_type"],
                        "strength": row["strength"],
                        "context": row["context"],
                        "source_episode_id": row["source_episode_id"],
                        "created_at": row["created_at"],
                    }
                    for row in entity_relations
                ],
            }
        finally:
            conn.close()
    
    def import_data(self, data: dict) -> dict:
        """Import data from backup. Returns counts."""
        concepts_imported = 0
        episodes_imported = 0
        entities_imported = 0
        mentions_imported = 0
        
        for concept_data in data.get("concepts", []):
            concept = Concept.from_dict(concept_data)
            try:
                self.add_concept(concept)
                concepts_imported += 1
            except sqlite3.IntegrityError:
                # Already exists, update instead
                self.update_concept(concept)
                concepts_imported += 1
        
        for episode_data in data.get("episodes", []):
            episode = Episode.from_dict(episode_data)
            try:
                self.add_episode(episode)
                episodes_imported += 1
            except sqlite3.IntegrityError:
                # Already exists, update instead
                self.update_episode(episode)
                episodes_imported += 1
        
        # Import entities (v2 schema)
        for entity_data in data.get("entities", []):
            entity = Entity.from_dict(entity_data)
            self.add_entity(entity)  # Uses INSERT OR REPLACE
            entities_imported += 1
        
        # Import mentions (v2 schema)
        for mention in data.get("mentions", []):
            self.add_mention(mention["episode_id"], mention["entity_id"])
            mentions_imported += 1

        # Import entity relations (v3 schema)
        entity_relations_imported = 0
        for rel_data in data.get("entity_relations", []):
            relation = EntityRelation.from_dict(rel_data)
            self.add_entity_relation(relation)  # Uses INSERT OR REPLACE
            entity_relations_imported += 1

        return {
            "concepts_imported": concepts_imported,
            "episodes_imported": episodes_imported,
            "entities_imported": entities_imported,
            "mentions_imported": mentions_imported,
            "entity_relations_imported": entity_relations_imported,
        }

