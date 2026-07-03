"""
Deterministic fact handling for Remind.

Provides Jaccard-based clustering of facts without LLM involvement.
All curation decisions are delegated to the calling agent.
"""

import logging
from dataclasses import dataclass, field
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
    collisions: list[Fact]  # Active facts that may conflict (same cluster)
    related_facts: list[Fact] = field(default_factory=list)  # Cross-cluster candidates


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
    max_collisions: int = 5,
) -> list[Fact]:
    """Find active facts in the cluster that may conflict with a new fact.
    
    Uses two heuristics:
    1. Entity overlap: facts sharing entities with the new fact
    2. Embedding similarity: facts with high semantic similarity (cosine > threshold)

    When an embedding is available, candidates from both heuristics are ranked
    by cosine similarity before capping at *max_collisions*, so the most
    semantically relevant collisions appear first.

    Returns list of potentially conflicting facts for the agent to review.
    """
    seen_ids: set[str] = {new_fact.id}
    candidates: list[Fact] = []
    embedding_scores: dict[str, float] = {}

    # 1. Entity overlap detection
    active_facts = store.get_facts(cluster_id=cluster_id, active_only=True)
    new_entity_set = set(entity_ids)

    for fact in active_facts:
        if fact.id in seen_ids:
            continue
        fact_entities = set(fact.entity_ids or [])
        if new_entity_set & fact_entities:
            candidates.append(fact)
            seen_ids.add(fact.id)

    # 2. Embedding similarity detection — also scores entity-overlap candidates
    if embedding:
        similar_facts = store.find_facts_by_embedding(
            embedding,
            k=max_collisions * 3,
            cluster_id=cluster_id,
            active_only=True,
        )
        for fact, similarity in similar_facts:
            embedding_scores[fact.id] = similarity
            if fact.id in seen_ids:
                continue
            if similarity >= similarity_threshold:
                candidates.append(fact)
                seen_ids.add(fact.id)
                logger.debug(
                    f"Semantic collision: {new_fact.id} <-> {fact.id} "
                    f"(cosine={similarity:.3f})"
                )

    # Rank by embedding similarity when available, then cap
    if embedding_scores:
        candidates.sort(key=lambda f: embedding_scores.get(f.id, 0.0), reverse=True)

    return candidates[:max_collisions]


def find_related_facts(
    store: MemoryStore,
    entity_ids: list[str],
    own_cluster_id: str,
    exclude_fact_ids: set[str],
    embedding: Optional[list[float]] = None,
    similarity_threshold: float = 0.6,
    max_results: int = 10,
) -> list[Fact]:
    """Find active facts in other clusters that share a subject with the new fact.

    Uses two complementary heuristics:
    1. Bare-name entity match — strips the type prefix (``person:alice`` →
       ``alice``) and queries all clusters for facts mentioning the same name.
    2. Global embedding similarity — finds facts across all clusters with cosine
       similarity ≥ *similarity_threshold*.

    Results are deduplicated, *exclude_fact_ids* are removed, and the list is
    capped at *max_results*.  Returned to the caller for conflict triage; no
    ``Conflict`` rows are created here.
    """
    seen_ids: set[str] = set(exclude_fact_ids)
    related: list[Fact] = []

    # 1. Bare-name entity match across all other clusters
    for entity_id in entity_ids:
        # Strip type prefix: "person:alice" → "alice"
        bare_name = entity_id.split(":", 1)[-1] if ":" in entity_id else entity_id
        if not bare_name:
            continue
        candidates = store.find_facts_by_entity_name(
            bare_name,
            active_only=True,
            exclude_cluster_id=own_cluster_id,
        )
        for fact in candidates:
            if fact.id not in seen_ids:
                related.append(fact)
                seen_ids.add(fact.id)

    # 2. Global embedding similarity (cross-cluster)
    if embedding:
        similar = store.find_facts_by_embedding(
            embedding,
            k=20,
            cluster_id=None,
            active_only=True,
        )
        for fact, similarity in similar:
            if fact.id in seen_ids:
                continue
            if fact.cluster_id == own_cluster_id:
                continue
            if similarity >= similarity_threshold:
                related.append(fact)
                seen_ids.add(fact.id)
                logger.debug(
                    f"Cross-cluster related fact: {fact.id} (cosine={similarity:.3f})"
                )

    return related[:max_results]


def create_fact_from_episode(
    store: MemoryStore,
    episode: Episode,
    embedding: Optional[list[float]] = None,
    jaccard_threshold: float = 0.5,
    related_similarity_threshold: float = 0.6,
    related_max_results: int = 10,
    collision_max_results: int = 5,
) -> FactResult:
    """Create a Fact from a fact-type episode with cluster assignment.
    
    This is the main entry point for deterministic fact processing.
    Called by remember() when episode_type == "fact".
    
    Process:
    1. Find matching cluster via Jaccard similarity on entities
    2. Create new cluster if no match found
    3. Create Fact row linked to cluster
    4. Detect collisions with existing active facts (same cluster)
    5. Find related facts in other clusters (cross-cluster conflict candidates)
    6. Update cluster's specifics cache
    7. Mark episode as processed
    
    Returns FactResult with collision and related_facts information for agent review.
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
    
    # Detect collisions (same cluster, exact entity match + embedding similarity)
    collisions = detect_collisions(
        store, cluster.id, fact, entity_ids, embedding,
        max_collisions=collision_max_results,
    )

    # Find related facts in other clusters (cross-cluster conflict candidates)
    related = find_related_facts(
        store,
        entity_ids,
        own_cluster_id=cluster.id,
        exclude_fact_ids={fact.id} | {c.id for c in collisions},
        embedding=embedding,
        similarity_threshold=related_similarity_threshold,
        max_results=related_max_results,
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
        f"(new={cluster_created}, collisions={len(collisions)}, related={len(related)})"
    )
    
    return FactResult(
        fact_id=fact.id,
        cluster_id=cluster.id,
        cluster_created=cluster_created,
        episode_id=episode.id,
        collisions=collisions,
        related_facts=related,
    )
