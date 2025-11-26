"""Memory storage backends."""

from abc import ABC, abstractmethod
from typing import Optional
import sqlite3
import json
import numpy as np
from pathlib import Path

from realmem.models import Concept, Episode, Relation, RelationType


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
    def get_recent_episodes(self, limit: int = 10) -> list[Episode]:
        """Get most recent episodes."""
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
        """Initialize database schema."""
        conn = self._get_conn()
        try:
            # Concepts table - stores full concept data as JSON
            conn.execute("""
                CREATE TABLE IF NOT EXISTS concepts (
                    id TEXT PRIMARY KEY,
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
            
            # Indexes for faster queries
            conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_consolidated ON episodes(consolidated)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_episodes_timestamp ON episodes(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(source_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(target_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_relations_type ON relations(type)")
            
            conn.commit()
        finally:
            conn.close()
    
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
                INSERT INTO concepts (id, summary, data, embedding, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    concept.id,
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
                SET summary = ?, data = ?, embedding = ?, updated_at = ?
                WHERE id = ?
                """,
                (
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
                SELECT id, summary, 
                       json_extract(data, '$.confidence') as confidence,
                       json_extract(data, '$.instance_count') as instance_count,
                       json_extract(data, '$.tags') as tags
                FROM concepts
                """
            ).fetchall()
            
            return [
                {
                    "id": row["id"],
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
                INSERT INTO episodes (id, content, data, consolidated, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    episode.id,
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
                SET content = ?, data = ?, consolidated = ?, timestamp = ?
                WHERE id = ?
                """,
                (
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
            
            return {
                "concepts": concept_count,
                "episodes": episode_count,
                "unconsolidated_episodes": unconsolidated_count,
                "relations": relation_count,
                "relation_types": {row["type"]: row["count"] for row in relation_types},
            }
        finally:
            conn.close()
    
    def export_data(self) -> dict:
        """Export all data for backup."""
        return {
            "concepts": [c.to_dict() for c in self.get_all_concepts()],
            "episodes": [e.to_dict() for e in self.get_recent_episodes(limit=10000)],
        }
    
    def import_data(self, data: dict) -> dict:
        """Import data from backup. Returns counts."""
        concepts_imported = 0
        episodes_imported = 0
        
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
                # Already exists
                pass
        
        return {
            "concepts_imported": concepts_imported,
            "episodes_imported": episodes_imported,
        }

