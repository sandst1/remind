"""
Memory retrieval with spreading activation.

Goes beyond simple vector similarity search by leveraging the concept graph.
When you recall something, related concepts get activated through the
relationship structure, mimicking associative memory in the brain.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
import logging
import math

from remind.models import Concept, Episode, Entity, EpisodeType, RelationType
from remind.store import MemoryStore
from remind.providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)


# Episode type weights for scoring -- higher value = more signal
_EPISODE_TYPE_WEIGHTS: dict[EpisodeType, float] = {
    EpisodeType.FACT: 1.0,
    EpisodeType.DECISION: 0.95,
    EpisodeType.PREFERENCE: 0.85,
    EpisodeType.OUTCOME: 0.8,
    EpisodeType.SPEC: 0.8,
    EpisodeType.OBSERVATION: 0.6,
    EpisodeType.QUESTION: 0.5,
    EpisodeType.PLAN: 0.5,
    EpisodeType.TASK: 0.4,
    EpisodeType.META: 0.3,
}


@dataclass
class ActivatedConcept:
    """A concept with its activation level and retrieval metadata."""
    
    concept: Concept
    activation: float  # 0.0 - 1.0, how strongly activated
    source: str  # "embedding" or "spread"
    hops: int = 0  # how many hops from initial activation
    
    def __repr__(self) -> str:
        return f"ActivatedConcept({self.concept.id}, activation={self.activation:.3f}, source={self.source})"


@dataclass
class ScoredEpisode:
    """An episode with a relevance score from hybrid recall."""

    episode: Episode
    score: float  # 0.0 - 1.0 composite relevance score

    def __repr__(self) -> str:
        return f"ScoredEpisode({self.episode.id}, score={self.score:.3f}, type={self.episode.episode_type.value})"


class MemoryRetriever:
    """
    Retrieves relevant concepts using spreading activation.
    
    The algorithm:
    1. Embed the query
    2. Find initial matches via embedding similarity
    3. Spread activation through the concept graph
    4. Return highest-activation concepts
    
    This mimics associative memory - you don't just match keywords,
    you follow conceptual links to find related understanding.
    """
    
    def __init__(
        self,
        embedding: EmbeddingProvider,
        store: MemoryStore,
        # Retrieval parameters
        initial_k: int = 10,  # how many initial embedding matches
        spread_hops: int = 2,  # how many hops to spread
        spread_decay: float = 0.5,  # activation decay per hop
        activation_threshold: float = 0.1,  # minimum activation to spread
        # Relation type weights (how much different relations spread activation)
        relation_weights: Optional[dict[RelationType, float]] = None,
    ):
        self.embedding = embedding
        self.store = store
        self.initial_k = initial_k
        self.spread_hops = spread_hops
        self.spread_decay = spread_decay
        self.activation_threshold = activation_threshold
        
        # Default relation weights - some relations spread activation more
        self.relation_weights = relation_weights or {
            RelationType.IMPLIES: 0.9,       # Strong spreading
            RelationType.GENERALIZES: 0.85,  # Very relevant
            RelationType.SPECIALIZES: 0.85,  # Very relevant
            RelationType.PART_OF: 0.8,       # Strong conceptual link
            RelationType.CONTEXT_OF: 0.7,    # Relevant context
            RelationType.CORRELATES: 0.6,    # Moderate spreading
            RelationType.CAUSES: 0.7,        # Causal link is meaningful
            RelationType.CONTRADICTS: 0.3,   # Weak spreading (but still useful)
        }
    
    async def retrieve(
        self,
        query: str,
        k: int = 3,
        min_activation: float = 0.15,
        context: Optional[str] = None,
        include_weak: bool = False,
    ) -> list[ActivatedConcept]:
        """
        Retrieve relevant concepts for a query.
        
        Args:
            query: The query text
            k: Maximum number of concepts to return
            min_activation: Minimum activation score to include in results.
                Concepts below this floor are dropped even if k budget remains.
            context: Optional additional context to include in embedding
            include_weak: If True, include lower-activation concepts
            
        Returns:
            List of ActivatedConcept objects, sorted by activation
        """
        # Combine query with context if provided
        embed_text = query
        if context:
            embed_text = f"{query}\n\nContext: {context}"
        
        # Get query embedding
        query_embedding = await self.embedding.embed(embed_text)
        
        # Step 1: Initial activation from embedding similarity
        initial_matches = self.store.find_by_embedding(
            query_embedding, 
            k=self.initial_k * 2  # Get more initially, we'll filter
        )
        
        # Build activation map: concept_id -> (activation, source, hops)
        activation_map: dict[str, tuple[float, str, int]] = {}
        concept_cache: dict[str, Concept] = {}
        
        for concept, similarity in initial_matches:
            # Weight similarity by concept confidence
            weighted_activation = similarity * concept.confidence
            # Apply decay factor - concepts with low decay_factor rank lower
            decay_factor = max(0.0, min(1.0, concept.decay_factor))
            final_activation = weighted_activation * decay_factor
            if final_activation > self.activation_threshold:
                activation_map[concept.id] = (final_activation, "embedding", 0)
                concept_cache[concept.id] = concept
                if decay_factor < 0.5:
                    logger.debug(f"Concept {concept.id} activation reduced by decay_factor {decay_factor:.2f}: {weighted_activation:.3f} -> {final_activation:.3f}")
        
        logger.debug(f"Initial activation: {len(activation_map)} concepts")
        
        # Step 2: Spreading activation
        for hop in range(self.spread_hops):
            new_activations: dict[str, tuple[float, str, int]] = {}
            
            for concept_id, (activation, _, _) in list(activation_map.items()):
                if activation < self.activation_threshold:
                    continue
                
                # Get related concepts
                related = self.store.get_related(concept_id, depth=1)
                
                for related_concept, relation in related:
                    # Calculate spread activation, weighted by target concept's confidence
                    relation_weight = self.relation_weights.get(relation.type, 0.5)
                    # Apply decay factor to target concept
                    target_decay = max(0.0, min(1.0, related_concept.decay_factor))
                    spread_activation = (
                        activation
                        * relation.strength
                        * relation_weight
                        * (self.spread_decay ** (hop + 1))
                        * related_concept.confidence  # Weight by target's reliability
                        * target_decay  # Weight by target's decay factor
                    )
                    
                    if spread_activation < self.activation_threshold:
                        continue
                    
                    # Keep the higher activation
                    current = activation_map.get(related_concept.id, (0, "", 0))[0]
                    spread_current = new_activations.get(related_concept.id, (0, "", 0))[0]
                    
                    if spread_activation > max(current, spread_current):
                        new_activations[related_concept.id] = (
                            spread_activation,
                            "spread",
                            hop + 1
                        )
                        concept_cache[related_concept.id] = related_concept
            
            # Merge new activations
            for cid, (act, src, hops) in new_activations.items():
                current = activation_map.get(cid, (0, "", 0))[0]
                if act > current:
                    activation_map[cid] = (act, src, hops)
            
            logger.debug(f"After hop {hop + 1}: {len(activation_map)} concepts")
        
        # Step 2.5: Entity name matching (fast, no embedding needed)
        entity_matches, self._last_matched_entities = self._entity_name_matches(
            query, max_concepts=k
        )
        for em in entity_matches:
            current = activation_map.get(em.concept.id, (0, "", 0))[0]
            if em.activation > current:
                activation_map[em.concept.id] = (em.activation, "entity_name", 0)
                concept_cache[em.concept.id] = em.concept

        if entity_matches:
            entity_sourced = sum(
                1 for cid, (_, src, _) in activation_map.items()
                if src == "entity_name"
            )
            logger.debug(f"Entity name matching: {entity_sourced} concepts from entities")
        
        # Step 3: Build result list
        results = []
        for concept_id, (activation, source, hops) in activation_map.items():
            if not include_weak and activation < self.activation_threshold * 2:
                continue
            
            concept = concept_cache.get(concept_id)
            if not concept:
                concept = self.store.get_concept(concept_id)
            
            if concept:
                results.append(ActivatedConcept(
                    concept=concept,
                    activation=activation,
                    source=source,
                    hops=hops,
                ))
        
        # Sort by activation (highest first), apply floor, take top k
        results.sort(key=lambda x: x.activation, reverse=True)
        if not include_weak:
            results = [r for r in results if r.activation >= min_activation]
        return results[:k]
    
    def _entity_name_matches(
        self,
        query: str,
        max_entities: int = 5,
        max_concepts: int = 5,
    ) -> tuple[list[ActivatedConcept], list[Entity]]:
        """Find concepts via entity name matching on the query words.

        Splits the query into words (3+ chars), finds entities whose name or ID
        contains those words, then retrieves concepts derived from those entities'
        episodes.

        Returns:
            Tuple of (activated_concepts, matched_entities). The concepts have
            source="entity_name" and heuristic activation scores. The entities
            are the raw Entity objects that matched the query words.
        """
        words = [w.lower() for w in query.split() if len(w) >= 3]
        if not words:
            return [], []

        matched_entities = self.store.search_entities_by_words(words, limit=max_entities)
        if not matched_entities:
            return [], []

        entity_list = [entity for entity, _ in matched_entities]

        # Collect episode IDs per entity so we can link concepts back
        entity_episode_ids: dict[str, set[str]] = {}
        for entity, _match_count in matched_entities:
            eps = self.store.get_episodes_mentioning(entity.id, limit=100)
            entity_episode_ids[entity.id] = {ep.id for ep in eps}

        all_ep_ids = set()
        for ep_set in entity_episode_ids.values():
            all_ep_ids |= ep_set

        if not all_ep_ids:
            return [], entity_list

        # Find concepts whose source_episodes overlap with matched entity episodes
        all_concepts = self.store.get_all_concepts()
        concept_scores: list[tuple[Concept, float]] = []

        for concept in all_concepts:
            overlap = set(concept.source_episodes) & all_ep_ids
            if not overlap:
                continue

            # Heuristic activation score:
            # - word_ratio: fraction of query words that matched the best entity
            # - overlap_ratio: how many of the concept's source episodes are relevant
            # - mention_boost: log-scaled boost for high-mention entities
            best_word_ratio = 0.0
            best_mention_boost = 0.0
            for entity, match_count in matched_entities:
                ep_ids = entity_episode_ids.get(entity.id, set())
                if ep_ids & set(concept.source_episodes):
                    word_ratio = match_count / len(words)
                    mention_count = len(ep_ids)
                    mention_boost = min(1.0, math.log1p(mention_count) / math.log1p(50))
                    if word_ratio > best_word_ratio:
                        best_word_ratio = word_ratio
                        best_mention_boost = mention_boost

            overlap_ratio = len(overlap) / max(len(concept.source_episodes), 1)

            activation = (
                0.30 * best_word_ratio
                + 0.15 * overlap_ratio
                + 0.15 * best_mention_boost
            )

            activation *= concept.confidence
            activation *= max(0.0, min(1.0, concept.decay_factor))

            # Floor: don't surface noise
            if activation > 0.05:
                concept_scores.append((concept, activation))

        concept_scores.sort(key=lambda x: x[1], reverse=True)

        results = []
        for concept, activation in concept_scores[:max_concepts]:
            results.append(ActivatedConcept(
                concept=concept,
                activation=activation,
                source="entity_name",
                hops=0,
            ))

        logger.debug(
            f"Entity name matching: {len(matched_entities)} entities, "
            f"{len(results)} concepts"
        )
        return results, entity_list

    async def retrieve_by_tags(
        self,
        tags: list[str],
        k: int = 3,
    ) -> list[Concept]:
        """
        Retrieve concepts by tag matching.
        
        Simple tag-based retrieval, useful for categorical lookups.
        """
        all_concepts = self.store.get_all_concepts()
        
        # Score by tag overlap
        scored = []
        for concept in all_concepts:
            overlap = len(set(tags) & set(concept.tags))
            if overlap > 0:
                scored.append((concept, overlap / len(tags)))
        
        scored.sort(key=lambda x: x[1], reverse=True)
        return [c for c, _ in scored[:k]]
    
    async def retrieve_by_entity(
        self,
        entity_id: str,
        limit: int = 20,
    ) -> list[Episode]:
        """
        Retrieve episodes mentioning a specific entity.
        
        Direct entity-based lookup - finds all memories about a file, person, etc.
        
        Args:
            entity_id: The entity ID (e.g., "file:src/auth.ts", "person:alice")
            limit: Maximum episodes to return
            
        Returns:
            List of episodes mentioning this entity, newest first
        """
        return self.store.get_episodes_mentioning(entity_id, limit=limit)
    
    def retrieve_related_episodes(
        self,
        activated: list[ActivatedConcept],
        max_episodes: int = 10,
    ) -> list[ScoredEpisode]:
        """Retrieve episodes related to activated concepts via entity overlap.

        Finds episodes that share entities with the source episodes of matched
        concepts, scores them using a lightweight composite function (no
        embeddings), and returns the top-scored ones.

        Args:
            activated: Concepts returned by retrieve().
            max_episodes: Maximum episodes to return.

        Returns:
            Scored episodes sorted by relevance, highest first.
        """
        if not activated:
            return []

        # Collect source episode IDs and their entity IDs from matched concepts
        source_ep_ids: set[str] = set()
        for ac in activated:
            source_ep_ids.update(ac.concept.source_episodes)

        concept_entity_ids: set[str] = set()
        if source_ep_ids:
            source_episodes = self.store.get_episodes_batch(list(source_ep_ids))
            for ep in source_episodes:
                concept_entity_ids.update(ep.entity_ids)

        if not concept_entity_ids:
            return []

        # Find candidate episodes sharing those entities (exclude source episodes)
        candidates = self.store.find_episodes_by_entities(
            entity_ids=list(concept_entity_ids),
            exclude_episode_ids=source_ep_ids,
            limit=max_episodes * 3,
        )

        if not candidates:
            return []

        # Score each candidate
        now = datetime.now()
        scored: list[ScoredEpisode] = []

        for ep in candidates:
            score = self._score_episode(ep, concept_entity_ids, now)
            if score > 0.05:
                scored.append(ScoredEpisode(episode=ep, score=score))

        scored.sort(key=lambda s: s.score, reverse=True)
        return scored[:max_episodes]

    @staticmethod
    def _score_episode(
        episode: Episode,
        concept_entity_ids: set[str],
        now: datetime,
    ) -> float:
        """Compute a composite relevance score for an episode.

        Weights:
          - Entity overlap:        ~60%
          - Unconsolidated bonus:  ~20%
          - Episode type weight:   ~10%
          - Recency:               ~10%
        """
        # Entity overlap (0.0 - 1.0)
        if episode.entity_ids:
            overlap = len(set(episode.entity_ids) & concept_entity_ids)
            entity_score = overlap / max(len(episode.entity_ids), 1)
        else:
            entity_score = 0.0

        # Unconsolidated bonus
        unconsolidated_bonus = 1.0 if not episode.consolidated else 0.0

        # Episode type weight
        type_weight = _EPISODE_TYPE_WEIGHTS.get(episode.episode_type, 0.5)

        # Recency (1.0 for today, decays to 0.3 over 90 days)
        age = now - episode.timestamp
        recency = max(0.3, 1.0 - (age.total_seconds() / (90 * 86400)) * 0.7)

        return (
            0.60 * entity_score
            + 0.20 * unconsolidated_bonus
            + 0.10 * type_weight
            + 0.10 * recency
        )

    async def retrieve_related_entities(
        self,
        entity_id: str,
        limit: int = 10,
    ) -> list[tuple[Entity, int]]:
        """
        Find entities that co-occur with a given entity.
        
        Uses episode co-mention to find related entities - entities that
        are frequently mentioned together are likely related.
        
        Args:
            entity_id: The entity to find relations for
            limit: Maximum related entities to return
            
        Returns:
            List of (entity, co_occurrence_count) tuples
        """
        # Get episodes mentioning this entity
        episodes = self.store.get_episodes_mentioning(entity_id, limit=100)
        
        # Count co-occurring entities
        co_occurrences: dict[str, int] = {}
        for episode in episodes:
            for other_entity_id in episode.entity_ids:
                if other_entity_id != entity_id:
                    co_occurrences[other_entity_id] = co_occurrences.get(other_entity_id, 0) + 1
        
        # Sort by count and fetch entity objects
        sorted_ids = sorted(co_occurrences.items(), key=lambda x: x[1], reverse=True)[:limit]
        
        results = []
        for eid, count in sorted_ids:
            entity = self.store.get_entity(eid)
            if entity:
                results.append((entity, count))
        
        return results
    
    async def find_related_chain(
        self,
        start_concept_id: str,
        end_concept_id: str,
        max_depth: int = 4,
    ) -> Optional[list[tuple[Concept, Optional[str]]]]:
        """
        Find a path between two concepts through the relation graph.
        
        Useful for understanding how concepts connect.
        
        Returns:
            List of (concept, relation_type_to_next) tuples forming the path,
            or None if no path found.
        """
        start = self.store.get_concept(start_concept_id)
        end = self.store.get_concept(end_concept_id)
        
        if not start or not end:
            return None
        
        # BFS to find path
        from collections import deque
        
        queue = deque([(start_concept_id, [(start, None)])])
        visited = {start_concept_id}
        
        while queue:
            current_id, path = queue.popleft()
            
            if current_id == end_concept_id:
                return path
            
            if len(path) >= max_depth:
                continue
            
            # Get related concepts
            related = self.store.get_related(current_id, depth=1)
            
            for concept, relation in related:
                if concept.id not in visited:
                    visited.add(concept.id)
                    new_path = path.copy()
                    # Update last item's relation type
                    if new_path:
                        last_concept, _ = new_path[-1]
                        new_path[-1] = (last_concept, relation.type.value)
                    new_path.append((concept, None))
                    
                    if concept.id == end_concept_id:
                        return new_path
                    
                    queue.append((concept.id, new_path))
        
        return None
    
    def format_for_llm(
        self,
        activated: list[ActivatedConcept],
        include_relations: bool = True,
        max_relations: int = 5,
        include_episodes: bool = True,
        matched_entities: Optional[list[Entity]] = None,
        max_entity_episodes: int = 10,
    ) -> str:
        """
        Format retrieved concepts and episodes for injection into an LLM prompt.

        This is the "recall" output that gets added to context.

        Args:
            activated: Concept matches from spreading activation.
            include_relations: Show concept relations.
            max_relations: Max relations per concept.
            include_episodes: Show source episodes under each concept.
            matched_entities: Entities matched by name from the query. If provided,
                appends entity context sections after concepts.
            max_entity_episodes: Max episodes to show per matched entity.
        """
        # Use stashed entities from last retrieve() if not explicitly provided
        if matched_entities is None:
            matched_entities = getattr(self, "_last_matched_entities", None) or []

        if not activated and not matched_entities:
            return "(No relevant memories found)"

        lines = ["RELEVANT MEMORY:\n"]

        for ac in activated:
            c = ac.concept

            # Header with ID, title (if present), and confidence
            if c.title:
                header = f"[{c.id}] {c.title} (confidence: {c.confidence:.2f}"
            else:
                header = f"[{c.id}] (confidence: {c.confidence:.2f}"
            if ac.source == "spread":
                header += f", via association"
            elif ac.source == "entity_name":
                header += f", via entity match"
            header += ")"
            lines.append(header)

            # Summary
            lines.append(f"  {c.summary}")

            # Conditions/Exceptions
            if c.conditions:
                lines.append(f"  → Applies when: {c.conditions}")
            if c.exceptions:
                lines.append(f"  → Exceptions: {', '.join(c.exceptions)}")

            # Key relations
            if include_relations and c.relations:
                shown = 0
                for rel in c.relations:
                    if shown >= max_relations:
                        break

                    # Get target concept summary
                    target = self.store.get_concept(rel.target_id)
                    if target:
                        rel_str = f"  → {rel.type.value}: {target.summary}"
                        lines.append(rel_str)
                        shown += 1

            # Source episodes with type labels and entity context
            if include_episodes and c.source_episodes:
                source_eps = self.store.get_episodes_batch(c.source_episodes)

                # Collect entities from source episodes
                entity_names: list[str] = []
                seen_entities: set[str] = set()
                for ep in source_eps:
                    for eid in ep.entity_ids:
                        if eid not in seen_entities:
                            seen_entities.add(eid)
                            _, name = Entity.parse_id(eid)
                            entity_names.append(name)
                if entity_names:
                    lines.append(f"  Entities: {', '.join(entity_names)}")

                lines.append("")
                lines.append("  Source episodes:")
                for episode in source_eps:
                    lines.append(f"    • [{episode.episode_type.value}] {episode.content}")

            lines.append("")  # Blank line between concepts

        # Append entity context for name-matched entities
        if matched_entities:
            lines.append("---")
            lines.append("MATCHED ENTITIES:\n")
            for entity in matched_entities:
                episodes = self.store.get_episodes_mentioning(
                    entity.id, limit=max_entity_episodes
                )
                if not episodes:
                    continue
                lines.append(f"[{entity.id}] {entity.display_name}")
                by_type: dict[str, list[Episode]] = {}
                for ep in episodes:
                    by_type.setdefault(ep.episode_type.value, []).append(ep)
                type_order = [
                    "fact", "decision", "question", "preference",
                    "observation", "outcome", "meta",
                ]
                for type_name in type_order:
                    if type_name not in by_type:
                        continue
                    lines.append(f"  [{type_name.upper()}S]")
                    for ep in by_type[type_name]:
                        lines.append(f"    • {ep.content}")
                lines.append("")

        return "\n".join(lines)
    
    def format_entity_context(
        self,
        entity_id: str,
        episodes: list[Episode],
        include_type_breakdown: bool = True,
    ) -> str:
        """
        Format entity-centric context for LLM injection.
        
        Shows what's known about a specific entity (file, person, etc.).
        
        Args:
            entity_id: The entity being recalled
            episodes: Episodes mentioning this entity
            include_type_breakdown: Group episodes by type
            
        Returns:
            Formatted string for LLM context
        """
        if not episodes:
            return f"(No memories about {entity_id})"
        
        entity = self.store.get_entity(entity_id)
        entity_name = entity.display_name if entity else entity_id
        
        lines = [f"MEMORY ABOUT: {entity_name}\n"]
        
        if include_type_breakdown:
            # Group by episode type
            by_type: dict[str, list[Episode]] = {}
            for ep in episodes:
                type_name = ep.episode_type.value
                by_type.setdefault(type_name, []).append(ep)
            
            type_order = ["fact", "decision", "question", "preference", "observation", "meta"]
            for type_name in type_order:
                if type_name not in by_type:
                    continue
                
                type_episodes = by_type[type_name]
                lines.append(f"[{type_name.upper()}S]")

                for ep in type_episodes:
                    lines.append(f"  • {ep.content}")

                lines.append("")
        else:
            # Simple chronological list
            for ep in episodes:
                type_label = f"[{ep.episode_type.value[:3]}]"
                lines.append(f"  {type_label} {ep.content}")
        
        return "\n".join(lines)

