"""
Snapshot module for batch reading memory state.

Provides a single read call returning a JSON document with combinable scopes.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from remind.models import Concept, Episode, Fact, Conflict, Entity, Topic
from remind.store import MemoryStore
from remind.providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)


@dataclass
class SnapshotScope:
    """Parsed scope specification."""
    
    scope_type: str  # pending, conflicts, entity, topic, concept, recent, stats, query
    value: Optional[str] = None  # For scopes with parameters


def parse_scopes(scope_specs: list[str]) -> list[SnapshotScope]:
    """Parse scope specifications into SnapshotScope objects.
    
    Examples:
        ["pending", "conflicts"]
        ["entity:concept:caching", "recent:10"]
        ["concept:abc123"]
        ["query:authentication issues"]
    """
    scopes = []
    for spec in scope_specs:
        if ":" in spec:
            scope_type, value = spec.split(":", 1)
            scopes.append(SnapshotScope(scope_type=scope_type.lower(), value=value))
        else:
            scopes.append(SnapshotScope(scope_type=spec.lower()))
    return scopes


def _episode_to_dict(episode: Episode) -> dict:
    """Convert episode to dict for snapshot output."""
    d = {
        "id": episode.id,
        "type": episode.episode_type,
        "content": episode.content,
        "created_at": episode.created_at.isoformat() if episode.created_at else None,
        "entity_ids": episode.entity_ids or [],
        "processed": episode.consolidated,
    }
    if episode.topic_id:
        d["topic_id"] = episode.topic_id
    if episode.asserted_by:
        d["asserted_by"] = episode.asserted_by
    if episode.source_ref:
        d["source_ref"] = episode.source_ref
    if episode.metadata:
        d["metadata"] = episode.metadata
    return d


def _concept_to_dict(concept: Concept) -> dict:
    """Convert concept to dict for snapshot output."""
    d = {
        "id": concept.id,
        "title": concept.title,
        "summary": concept.summary,
        "type": concept.concept_type,
        "confidence": concept.confidence,
        "created_at": concept.created_at.isoformat() if concept.created_at else None,
        "updated_at": concept.updated_at.isoformat() if concept.updated_at else None,
        "entity_ids": concept.entity_ids or [],
        "source_episodes": concept.source_episodes or [],
    }
    if concept.topic_id:
        d["topic_id"] = concept.topic_id
    if concept.concept_type in ("fact_cluster", "fact"):
        d["specifics"] = concept.specifics
    return d


def _fact_to_dict(fact: Fact) -> dict:
    """Convert fact to dict for snapshot output."""
    d = {
        "id": fact.id,
        "cluster_id": fact.cluster_id,
        "statement": fact.statement,
        "entity_ids": fact.entity_ids or [],
        "source_episode_id": fact.source_episode_id,
        "valid_from": fact.valid_from.isoformat() if fact.valid_from else None,
        "valid_to": fact.valid_to.isoformat() if fact.valid_to else None,
        "active": fact.valid_to is None,
    }
    if fact.asserted_by:
        d["asserted_by"] = fact.asserted_by
    if fact.source_ref:
        d["source_ref"] = fact.source_ref
    if fact.superseded_by:
        d["superseded_by"] = fact.superseded_by
    return d


def _conflict_to_dict(conflict: Conflict, store: MemoryStore) -> dict:
    """Convert conflict to dict with full fact details."""
    d = {
        "id": conflict.id,
        "kind": conflict.kind,
        "status": conflict.status,
        "severity": conflict.severity,
        "description": conflict.description,
        "created_at": conflict.created_at.isoformat() if conflict.created_at else None,
    }
    
    if conflict.concept_ids:
        d["concept_ids"] = conflict.concept_ids
    
    # Include full fact details for fact conflicts
    if conflict.fact_a_id:
        fact_a = store.get_fact(conflict.fact_a_id)
        if fact_a:
            d["fact_a"] = _fact_to_dict(fact_a)
        else:
            d["fact_a_id"] = conflict.fact_a_id
    
    if conflict.fact_b_id:
        fact_b = store.get_fact(conflict.fact_b_id)
        if fact_b:
            d["fact_b"] = _fact_to_dict(fact_b)
        else:
            d["fact_b_id"] = conflict.fact_b_id
    
    if conflict.resolved_at:
        d["resolved_at"] = conflict.resolved_at.isoformat()
    if conflict.resolved_by:
        d["resolved_by"] = conflict.resolved_by
    if conflict.resolution_note:
        d["resolution_note"] = conflict.resolution_note
    if conflict.winning_fact_id:
        d["winning_fact_id"] = conflict.winning_fact_id
    
    return d


def _entity_to_dict(entity: Entity) -> dict:
    """Convert entity to dict for snapshot output."""
    return {
        "id": entity.id,
        "type": entity.type.value if hasattr(entity.type, "value") else str(entity.type),
        "display_name": entity.display_name,
    }


def _topic_to_dict(topic: Topic) -> dict:
    """Convert topic to dict for snapshot output."""
    return {
        "id": topic.id,
        "name": topic.name,
        "description": topic.description,
    }


class SnapshotEngine:
    """Engine for generating memory snapshots."""
    
    def __init__(
        self,
        store: MemoryStore,
        embedding: Optional[EmbeddingProvider] = None,
    ):
        self.store = store
        self.embedding = embedding
    
    async def snapshot(self, scope_specs: list[str]) -> dict[str, Any]:
        """Generate a snapshot with the specified scopes.
        
        Args:
            scope_specs: List of scope specifications
                - "pending": Unprocessed episodes
                - "conflicts": Open conflicts with fact details
                - "entity:<id>": Episodes and concepts for entity
                - "topic:<id>": Episodes and concepts for topic
                - "concept:<id>": Concept detail with facts and history
                - "recent:<n>": N most recent episodes
                - "stats": Memory statistics
                - "query:<text>": Semantic search results
        
        Returns:
            Combined JSON document with all requested scopes
        """
        scopes = parse_scopes(scope_specs)
        result: dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "scopes": scope_specs,
        }
        
        for scope in scopes:
            if scope.scope_type == "pending":
                result["pending"] = self._scope_pending()
            elif scope.scope_type == "conflicts":
                result["conflicts"] = self._scope_conflicts()
            elif scope.scope_type == "entity":
                key = f"entity:{scope.value}"
                result[key] = self._scope_entity(scope.value)
            elif scope.scope_type == "topic":
                key = f"topic:{scope.value}"
                result[key] = self._scope_topic(scope.value)
            elif scope.scope_type == "concept":
                key = f"concept:{scope.value}"
                result[key] = self._scope_concept(scope.value)
            elif scope.scope_type == "recent":
                n = int(scope.value) if scope.value else 10
                result["recent"] = self._scope_recent(n)
            elif scope.scope_type == "stats":
                result["stats"] = self._scope_stats()
            elif scope.scope_type == "query":
                result["query"] = await self._scope_query(scope.value)
            else:
                result[f"error:{scope.scope_type}"] = f"Unknown scope type: {scope.scope_type}"
        
        return result
    
    def _scope_pending(self) -> dict[str, Any]:
        """Get unprocessed episodes with their entities."""
        episodes = self.store.get_unconsolidated_episodes()
        
        # Collect unique entities from pending episodes
        entity_ids = set()
        for ep in episodes:
            if ep.entity_ids:
                entity_ids.update(ep.entity_ids)
        
        entities = []
        for eid in entity_ids:
            entity = self.store.get_entity(eid)
            if entity:
                entities.append(_entity_to_dict(entity))
        
        return {
            "count": len(episodes),
            "episodes": [_episode_to_dict(ep) for ep in episodes],
            "entities": entities,
        }
    
    def _scope_conflicts(self) -> dict[str, Any]:
        """Get open conflicts with full fact details."""
        conflicts = self.store.get_conflicts(status="open")
        
        return {
            "count": len(conflicts),
            "conflicts": [_conflict_to_dict(c, self.store) for c in conflicts],
        }
    
    def _scope_entity(self, entity_id: str) -> dict[str, Any]:
        """Get all data for a specific entity."""
        entity = self.store.get_entity(entity_id)
        if not entity:
            return {"error": f"Entity not found: {entity_id}"}
        
        # Get episodes mentioning this entity
        episodes = self.store.get_episodes_mentioning(entity_id)
        
        # Get fact clusters linked to this entity
        clusters = self.store.get_fact_clusters_for_entity(entity_id)
        
        return {
            "entity": _entity_to_dict(entity),
            "episodes": [_episode_to_dict(ep) for ep in episodes],
            "fact_clusters": [_concept_to_dict(c) for c in clusters],
        }
    
    def _scope_topic(self, topic_id: str) -> dict[str, Any]:
        """Get all data for a specific topic."""
        topic = self.store.get_topic(topic_id)
        if not topic:
            return {"error": f"Topic not found: {topic_id}"}
        
        # Get episodes and concepts for this topic
        all_episodes = self.store.get_all_episodes()
        episodes = [ep for ep in all_episodes if ep.topic_id == topic_id]
        concepts = self.store.get_concepts_by_topic(topic_id)
        
        return {
            "topic": _topic_to_dict(topic),
            "episode_count": len(episodes),
            "concept_count": len(concepts),
            "episodes": [_episode_to_dict(ep) for ep in episodes],
            "concepts": [_concept_to_dict(c) for c in concepts],
        }
    
    def _scope_concept(self, concept_id: str) -> dict[str, Any]:
        """Get concept detail including facts and supersession history."""
        concept = self.store.get_concept(concept_id)
        if not concept:
            return {"error": f"Concept not found: {concept_id}"}
        
        result = {
            "concept": _concept_to_dict(concept),
        }
        
        # Get source episodes
        source_episodes_list = []
        for ep_id in concept.source_episodes or []:
            ep = self.store.get_episode(ep_id)
            if ep:
                source_episodes_list.append(_episode_to_dict(ep))
        result["source_episodes"] = source_episodes_list
        
        # For fact clusters, include all facts (active and superseded)
        if concept.concept_type in ("fact_cluster", "fact"):
            all_facts = self.store.get_facts(cluster_id=concept_id, active_only=False)
            active_facts = [f for f in all_facts if f.valid_to is None]
            superseded_facts = [f for f in all_facts if f.valid_to is not None]
            
            result["active_facts"] = [_fact_to_dict(f) for f in active_facts]
            result["superseded_facts"] = [_fact_to_dict(f) for f in superseded_facts]
        
        # Include relations from the concept itself
        if concept.relations:
            result["relations"] = [
                {"type": r.type.value if hasattr(r.type, "value") else str(r.type), "target_id": r.target_id}
                for r in concept.relations
            ]
        
        return result
    
    def _scope_recent(self, n: int) -> dict[str, Any]:
        """Get N most recent episodes."""
        episodes = self.store.get_recent_episodes(limit=n)
        return {
            "count": len(episodes),
            "episodes": [_episode_to_dict(ep) for ep in episodes],
        }
    
    def _scope_stats(self) -> dict[str, Any]:
        """Get memory statistics."""
        episodes = self.store.get_all_episodes()
        concepts = self.store.get_all_concepts()
        unconsolidated = self.store.get_unconsolidated_episodes()
        
        episode_types = {}
        for ep in episodes:
            t = ep.episode_type or "unknown"
            episode_types[t] = episode_types.get(t, 0) + 1
        
        concept_types = {}
        for c in concepts:
            t = c.concept_type or "unknown"
            concept_types[t] = concept_types.get(t, 0) + 1
        
        open_conflicts = self.store.count_conflicts(status="open")
        
        return {
            "total_episodes": len(episodes),
            "total_concepts": len(concepts),
            "pending_episodes": len(unconsolidated),
            "open_conflicts": open_conflicts,
            "episode_types": episode_types,
            "concept_types": concept_types,
        }
    
    async def _scope_query(self, query_text: str) -> dict[str, Any]:
        """Semantic search for concepts."""
        if not self.embedding:
            return {"error": "No embedding provider available for query scope"}
        
        try:
            query_embedding = await self.embedding.embed(query_text)
        except Exception as e:
            return {"error": f"Embedding failed: {e}"}
        
        # Vector search for concepts
        results = self.store.find_by_embedding(query_embedding, k=10)
        
        return {
            "query": query_text,
            "concepts": [_concept_to_dict(concept) for concept, score in results],
        }
