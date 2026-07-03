"""
Deterministic fact handling for Remind.

Provides Jaccard-based clustering of facts without LLM involvement.
All curation decisions are delegated to the calling agent.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from uuid import uuid4

from remind.models import (
    Concept, Episode, Fact, Entity,
)
from remind.store import MemoryStore

logger = logging.getLogger(__name__)


def jaccard_similarity(set_a: set, set_b: set) -> float:
    """Compute Jaccard similarity between two sets."""
    if not set_a or not set_b:
        return 0.0
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union > 0 else 0.0


@dataclass
class FactResult:
    """Result of creating a fact with collision detection."""
    
    fact_id: str
    cluster_id: str
    cluster_created: bool
    episode_id: str
    collisions: list[Fact]  # Active facts that may conflict


@dataclass
class ClusterMatch:
    """A potential cluster match with similarity score."""
    
    cluster: Concept
    similarity: float
    shared_entities: set[str]


def find_matching_cluster(
    store: MemoryStore,
    entity_ids: list[str],
    threshold: float = 0.5,
) -> Optional[ClusterMatch]:
    """Find the best matching fact_cluster for a set of entities.
    
    Uses Jaccard similarity on entity sets. Returns the cluster with
    highest similarity if it meets the threshold, otherwise None.
    """
    if not entity_ids:
        return None
    
    episode_entities = set(entity_ids)
    best_match: Optional[ClusterMatch] = None
    
    # Get all fact_cluster concepts that share any entity
    for entity_id in entity_ids:
        clusters = store.get_fact_clusters_for_entity(entity_id)
        for cluster in clusters:
            cluster_entities = set(cluster.entity_ids or [])
            similarity = jaccard_similarity(episode_entities, cluster_entities)
            
            if similarity >= threshold:
                shared = episode_entities & cluster_entities
                if best_match is None or similarity > best_match.similarity:
                    best_match = ClusterMatch(
                        cluster=cluster,
                        similarity=similarity,
                        shared_entities=shared,
                    )
    
    return best_match


def create_fact_cluster(
    store: MemoryStore,
    entity_ids: list[str],
    initial_statement: str,
) -> Concept:
    """Create a new fact_cluster concept from entities.
    
    Title is templated from entity display names.
    """
    # Build title from entity display names
    entities = []
    for eid in entity_ids:
        entity = store.get_entity(eid)
        if entity:
            entities.append(entity)
    
    if entities:
        # Use first entity type and join names
        primary = entities[0]
        if len(entities) == 1:
            title = f"Facts about {primary.display_name or primary.id}"
        else:
            names = [e.display_name or e.id.split(":", 1)[-1] for e in entities[:3]]
            title = f"Facts about {', '.join(names)}"
            if len(entities) > 3:
                title += f" (+{len(entities) - 3})"
    else:
        title = "Fact cluster"
    
    concept = Concept(
        id=str(uuid4())[:8],
        title=title,
        summary="",  # No LLM summary
        concept_type="fact_cluster",
        entity_ids=list(entity_ids),
        specifics=initial_statement,  # Start with first fact
        confidence=1.0,
    )
    store.add_concept(concept)
    
    logger.debug(f"Created fact_cluster {concept.id}: {title}")
    return concept


def detect_collisions(
    store: MemoryStore,
    cluster_id: str,
    new_fact: Fact,
    entity_ids: list[str],
    embedding: Optional[list[float]] = None,
    similarity_threshold: float = 0.7,
) -> list[Fact]:
    """Find active facts in the cluster that may conflict with a new fact.
    
    Uses two heuristics:
    1. Entity overlap: facts sharing entities with the new fact
    2. Embedding similarity: facts with high semantic similarity (cosine > threshold)
    
    Returns list of potentially conflicting facts for the agent to review.
    """
    seen_ids: set[str] = {new_fact.id}
    collisions: list[Fact] = []
    
    # 1. Entity overlap detection
    active_facts = store.get_facts(cluster_id=cluster_id, active_only=True)
    new_entity_set = set(entity_ids)
    
    for fact in active_facts:
        if fact.id in seen_ids:
            continue
        
        fact_entities = set(fact.entity_ids or [])
        if new_entity_set & fact_entities:
            collisions.append(fact)
            seen_ids.add(fact.id)
    
    # 2. Embedding similarity detection
    if embedding:
        similar_facts = store.find_facts_by_embedding(
            embedding,
            k=10,
            cluster_id=cluster_id,
            active_only=True,
        )
        for fact, similarity in similar_facts:
            if fact.id in seen_ids:
                continue
            if similarity >= similarity_threshold:
                collisions.append(fact)
                seen_ids.add(fact.id)
                logger.debug(
                    f"Semantic collision: {new_fact.id} <-> {fact.id} "
                    f"(cosine={similarity:.3f})"
                )
    
    return collisions


def create_fact_from_episode(
    store: MemoryStore,
    episode: Episode,
    embedding: Optional[list[float]] = None,
    jaccard_threshold: float = 0.5,
) -> FactResult:
    """Create a Fact from a fact-type episode with cluster assignment.
    
    This is the main entry point for deterministic fact processing.
    Called by remember() when episode_type == "fact".
    
    Process:
    1. Find matching cluster via Jaccard similarity on entities
    2. Create new cluster if no match found
    3. Create Fact row linked to cluster
    4. Detect collisions with existing active facts
    5. Update cluster's specifics cache
    6. Mark episode as processed
    
    Returns FactResult with collision information for agent review.
    """
    entity_ids = episode.entity_ids or []
    
    # Find or create cluster
    cluster_match = find_matching_cluster(store, entity_ids, threshold=jaccard_threshold)
    cluster_created = False
    
    if cluster_match:
        cluster = cluster_match.cluster
        logger.debug(
            f"Matched cluster {cluster.id} (jaccard={cluster_match.similarity:.2f})"
        )
    else:
        cluster = create_fact_cluster(store, entity_ids, episode.content)
        cluster_created = True
    
    # Create the Fact row with embedding for semantic collision detection
    fact = Fact(
        id=str(uuid4())[:8],
        cluster_id=cluster.id,
        statement=episode.content,
        entity_ids=entity_ids,
        source_episode_id=episode.id,
        asserted_by=episode.asserted_by,
        source_ref=episode.source_ref,
        valid_from=episode.created_at,
        embedding=embedding,
    )
    store.add_fact(fact)
    
    # Detect collisions
    collisions = detect_collisions(
        store, cluster.id, fact, entity_ids, embedding
    )
    
    # Update cluster specifics cache (all active facts)
    active_facts = store.get_facts(cluster_id=cluster.id, active_only=True)
    cluster.specifics = "\n".join(f.statement for f in active_facts)
    cluster.updated_at = datetime.now()
    store.update_concept(cluster)
    
    # Mark episode as processed
    episode.consolidated = True
    episode.consolidated_at = datetime.now()
    store.update_episode(episode)
    
    logger.info(
        f"Created fact {fact.id} in cluster {cluster.id} "
        f"(new={cluster_created}, collisions={len(collisions)})"
    )
    
    return FactResult(
        fact_id=fact.id,
        cluster_id=cluster.id,
        cluster_created=cluster_created,
        episode_id=episode.id,
        collisions=collisions,
    )
