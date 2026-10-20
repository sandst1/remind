"""
Memory retrieval with spreading activation.

Goes beyond simple vector similarity search by leveraging the concept graph.
When you recall something, related concepts get activated through the
relationship structure, mimicking associative memory in the brain.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, TYPE_CHECKING
from concurrent.futures import ThreadPoolExecutor
import asyncio
import logging
import math
import time

from remind.models import Concept, Episode, Entity, RelationType
from remind.store import MemoryStore
from remind.providers.base import EmbeddingProvider

if TYPE_CHECKING:
    from remind.reranker import Reranker

logger = logging.getLogger(__name__)


def _fuse_vector_lexical(
    vector_results: list[tuple],
    lexical_results: list[tuple],
    id_fn,
    lexical_weight: float,
    rrf_k: int,
) -> dict:
    """Fuse ranked vector-similarity and lexical-search results.

    Both inputs are ``(obj, score)`` pairs already ranked best-first. When
    there are no lexical results (lexical disabled, no backend configured,
    or the query had no searchable terms), this degrades to the raw vector
    similarity scores untouched, preserving the historical [0, 1]
    cosine-similarity semantics that ``activation_threshold``/``min_activation``
    are calibrated against.

    Once a lexical arm is present, both sides are combined via weighted
    Reciprocal Rank Fusion (rank-based, so it doesn't need BM25 and cosine
    scores to be on comparable scales), then min-max normalized against the
    batch's own top score so the fused result stays in the same [0, 1] range
    a similarity score would occupy.

    Returns a dict mapping id -> (fused_score, obj).
    """
    if not lexical_results:
        return {id_fn(obj): (score, obj) for obj, score in vector_results}

    vector_weight = 1.0 - lexical_weight
    fused: dict[str, list] = {}
    for rank, (obj, _sim) in enumerate(vector_results):
        oid = id_fn(obj)
        entry = fused.setdefault(oid, [0.0, obj])
        entry[0] += vector_weight / (rrf_k + rank + 1)

    for rank, (obj, _score) in enumerate(lexical_results):
        oid = id_fn(obj)
        entry = fused.setdefault(oid, [0.0, obj])
        entry[0] += lexical_weight / (rrf_k + rank + 1)

    max_score = max((v[0] for v in fused.values()), default=0.0)
    if max_score <= 0:
        return {oid: (0.0, obj) for oid, (_score, obj) in fused.items()}
    return {oid: (score / max_score, obj) for oid, (score, obj) in fused.items()}

# Metadata keys to suppress in recall output (internal bookkeeping)
_HIDDEN_METADATA_KEYS = {"source", "triage_density"}

# Default weight for custom episode types not in the built-in map
_DEFAULT_EPISODE_TYPE_WEIGHT = 0.6


def _format_episode_line(ep: "Episode", prefix: str = "    • ") -> str:
    """Format a single episode as a compact one-liner with metadata."""
    date = ep.created_at.strftime("%Y-%m-%d %H:%M")
    meta = ep.metadata or {}

    header_parts = [ep.episode_type, date]
    if ep.asserted_by:
        header_parts.append(f"by {ep.asserted_by}")

    meta_parts = []
    for k, v in meta.items():
        if k in _HIDDEN_METADATA_KEYS:
            continue
        meta_parts.append(f"{k}={v}")

    meta_str = f" ({', '.join(meta_parts)})" if meta_parts else ""
    ref_str = f" <{ep.source_ref}>" if ep.source_ref else ""
    return f"{prefix}[{', '.join(header_parts)}]{meta_str} {ep.content}{ref_str}"


# Episode type weights for scoring -- higher value = more signal
_EPISODE_TYPE_WEIGHTS: dict[str, float] = {
    "fact": 1.0,
    "decision": 0.95,
    "preference": 0.85,
    "outcome": 0.8,
    "observation": 0.6,
    "question": 0.5,
    "meta": 0.3,
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
        return f"ScoredEpisode({self.episode.id}, score={self.score:.3f}, type={self.episode.episode_type})"


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
        # Hybrid scoring -- weight of the lexical (BM25/FTS) arm in RRF fusion
        # against the vector arm. 0.0 = pure embedding, 1.0 = pure lexical.
        hybrid_keyword_weight: float = 0.0,
        # Whether to query the lexical backend at all (no-op if the store has none)
        lexical_enabled: bool = True,
        # RRF rank-damping constant; higher = ranks matter less
        rrf_k: int = 60,
        # Relation type weights (how much different relations spread activation)
        relation_weights: Optional[dict[RelationType, float]] = None,
        # Optional cross-encoder reranker
        reranker: Optional["Reranker"] = None,
    ):
        self.embedding = embedding
        self.store = store
        self.initial_k = initial_k
        self.spread_hops = spread_hops
        self.spread_decay = spread_decay
        self.activation_threshold = activation_threshold
        self.hybrid_keyword_weight = max(0.0, min(1.0, hybrid_keyword_weight))
        self.lexical_enabled = lexical_enabled
        self.rrf_k = rrf_k
        self.reranker = reranker
        
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
            RelationType.SUPERSEDES: 0.1,    # Very weak — superseded concepts shouldn't dominate
        }
    
    def _compute_evidence_weight(self, concept_id: str) -> float:
        """Compute net evidence strength for a concept.
        
        Returns a multiplier based on the balance of supporting vs contradicting
        evidence. Default is 1.0 (no evidence or balanced evidence).
        
        - More supporting evidence -> weight > 1.0 (up to 1.5)
        - More contradicting evidence -> weight < 1.0 (down to 0.5)
        """
        evidence_links = self.store.get_evidence_for_concept(concept_id)
        if not evidence_links:
            return 1.0
        
        net_strength = 0.0
        for ev in evidence_links:
            if ev.link_type == "supports":
                net_strength += ev.strength
            elif ev.link_type == "contradicts":
                net_strength -= ev.strength
            elif ev.link_type == "exemplifies":
                net_strength += ev.strength * 0.5
            elif ev.link_type == "qualifies":
                net_strength += ev.strength * 0.3
            elif ev.link_type == "supersedes":
                net_strength -= ev.strength * 0.7
        
        # Clamp to reasonable range [0.5, 1.5]
        # positive net -> boost, negative net -> penalty
        weight = 1.0 + (net_strength * 0.2)
        return max(0.5, min(1.5, weight))
    
    async def retrieve(
        self,
        query: str,
        k: int = 3,
        min_activation: float = 0.15,
        context: Optional[str] = None,
        include_weak: bool = False,
        labels: Optional[dict[str, str]] = None,
        timeout_ms: Optional[int] = None,
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
            labels: If set, pre-filter initial matches to concepts matching
                ALL given key=value label filters. Spreading still follows
                the graph beyond the filtered set.
            timeout_ms: Soft deadline. Once exceeded, remaining phases
                (spreading, reranking) are skipped and results are built
                from whatever was already gathered, instead of raising.
            
        Returns:
            List of ActivatedConcept objects, sorted by activation
        """
        t_start = time.perf_counter()
        deadline = t_start + timeout_ms / 1000.0 if timeout_ms else None
        # Combine query with context if provided
        embed_text = query
        if context:
            embed_text = f"{query}\n\nContext: {context}"
        
        # Get query embedding
        t_embed_start = time.perf_counter()
        query_embedding = await self.embedding.embed(embed_text)
        t_embed_ms = (time.perf_counter() - t_embed_start) * 1000.0
        
        # Step 1: Initial activation from embedding similarity + lexical search
        t_initial_search_start = time.perf_counter()
        initial_matches = self.store.find_by_embedding(
            query_embedding, 
            k=self.initial_k * 2,  # Get more initially, we'll filter
            labels=labels,
        )
        lexical_matches: list[tuple[Concept, float]] = []
        if self.lexical_enabled and self.hybrid_keyword_weight > 0.0:
            lexical_matches = self.store.search_concepts_lexical(
                query, k=self.initial_k * 2, labels=labels,
            )
        t_initial_search_ms = (time.perf_counter() - t_initial_search_start) * 1000.0

        # Build activation map: concept_id -> (activation, source, hops)
        t_initial_activation_start = time.perf_counter()
        activation_map: dict[str, tuple[float, str, int]] = {}
        concept_cache: dict[str, Concept] = {}

        fused_matches = _fuse_vector_lexical(
            initial_matches, lexical_matches, lambda c: c.id,
            self.hybrid_keyword_weight, self.rrf_k,
        )
        for fused, concept in fused_matches.values():
            weighted_activation = fused * concept.confidence
            decay_factor = max(0.0, min(1.0, concept.decay_factor))
            evidence_weight = self._compute_evidence_weight(concept.id)
            final_activation = weighted_activation * decay_factor * evidence_weight

            if final_activation > self.activation_threshold:
                activation_map[concept.id] = (final_activation, "embedding", 0)
                concept_cache[concept.id] = concept
                if decay_factor < 0.5 or evidence_weight < 0.8:
                    logger.debug(f"Concept {concept.id} activation adjusted: decay={decay_factor:.2f}, evidence={evidence_weight:.2f}")
        t_initial_activation_ms = (time.perf_counter() - t_initial_activation_start) * 1000.0
        
        logger.debug(f"Initial activation: {len(activation_map)} concepts (labels={labels})")
        
        # Step 2: Spreading activation (skipped if the deadline already passed)
        t_spread_start = time.perf_counter()
        deadline_hit = deadline is not None and t_spread_start > deadline
        if deadline_hit:
            logger.warning("recall timeout_ms exceeded before spreading; returning best-so-far")
        for hop in range(self.spread_hops if not deadline_hit else 0):
            new_activations: dict[str, tuple[float, str, int]] = {}
            
            for concept_id, (activation, _, _) in list(activation_map.items()):
                if activation < self.activation_threshold:
                    continue
                
                # Get related concepts
                related = self.store.get_related(concept_id, depth=1)
                
                for related_concept, relation in related:
                    # Calculate spread activation, weighted by target concept's confidence
                    relation_weight = self.relation_weights.get(relation.type, 0.5)
                    # Apply decay factor and evidence weight to target concept
                    target_decay = max(0.0, min(1.0, related_concept.decay_factor))
                    target_evidence = self._compute_evidence_weight(related_concept.id)
                    spread_activation = (
                        activation
                        * relation.strength
                        * relation_weight
                        * (self.spread_decay ** (hop + 1))
                        * related_concept.confidence  # Weight by target's reliability
                        * target_decay  # Weight by target's decay factor
                        * target_evidence  # Weight by net evidence strength
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
            if deadline is not None and time.perf_counter() > deadline:
                logger.warning("recall timeout_ms exceeded during spreading; stopping early")
                break
        t_spread_ms = (time.perf_counter() - t_spread_start) * 1000.0
        
        # Step 2.5: Entity name matching (fast, no embedding needed)
        t_entity_start = time.perf_counter()
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
        t_entity_ms = (time.perf_counter() - t_entity_start) * 1000.0

        # Step 2.75: Cross-encoder reranking (skipped past the deadline -- rerank
        # is the most expensive remaining phase and best-so-far without it is
        # still a valid ranking)
        t_rerank_ms = 0.0
        if self.reranker and activation_map and not (deadline is not None and time.perf_counter() > deadline):
            t_rerank_start = time.perf_counter()
            rerank_ids = list(activation_map.keys())
            rerank_docs = []
            for cid in rerank_ids:
                c = concept_cache.get(cid) or self.store.get_concept(cid)
                if c:
                    concept_cache[cid] = c
                    rerank_docs.append(f"{c.title or ''} {c.summary or ''}".strip())
                else:
                    rerank_docs.append("")

            rerank_scores = self.reranker.score(query, rerank_docs)
            for cid, rs in zip(rerank_ids, rerank_scores):
                old_act, src, hops = activation_map[cid]
                blended = 0.4 * old_act + 0.6 * rs
                activation_map[cid] = (blended, src, hops)

            logger.debug(f"Reranked {len(rerank_ids)} concepts")
            t_rerank_ms = (time.perf_counter() - t_rerank_start) * 1000.0

        # Step 3: Build result list
        t_finalize_start = time.perf_counter()
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
        results = results[:k]
        t_finalize_ms = (time.perf_counter() - t_finalize_start) * 1000.0
        t_total_ms = (time.perf_counter() - t_start) * 1000.0

        logger.debug(
            "Recall timing (retrieve): embed=%.1fms vector=%.1fms "
            "initial_activation=%.1fms spread=%.1fms entity_match=%.1fms rerank=%.1fms "
            "finalize=%.1fms total=%.1fms candidates=%d returned=%d",
            t_embed_ms,
            t_initial_search_ms,
            t_initial_activation_ms,
            t_spread_ms,
            t_entity_ms,
            t_rerank_ms,
            t_finalize_ms,
            t_total_ms,
            len(activation_map),
            len(results),
        )
        return results
    
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
    
    async def retrieve_episodes_by_embedding(
        self,
        query: str,
        k: int = 5,
        query_embedding: Optional[list[float]] = None,
        labels: Optional[dict[str, str]] = None,
    ) -> list[ScoredEpisode]:
        """
        Retrieve episodes by direct embedding similarity search.

        Complements concept-based retrieval by finding episodes whose
        content is semantically close to the query, regardless of whether
        they were consolidated into concepts.

        Args:
            query: The query text to search for.
            k: Maximum number of episodes to return.
            query_embedding: Pre-computed embedding to reuse. When provided
                the embedding API call is skipped.
            labels: Optional key=value label pre-filter.

        Returns:
            Scored episodes sorted by similarity, highest first.
        """
        if query_embedding is None:
            query_embedding = await self.embedding.embed(query)
        matches = self.store.find_episodes_by_embedding(query_embedding, k=k, labels=labels)

        lexical_matches: list[tuple[Episode, float]] = []
        if self.lexical_enabled and self.hybrid_keyword_weight > 0.0:
            lexical_matches = self.store.search_episodes_lexical(query, k=k * 2, labels=labels)

        fused_matches = _fuse_vector_lexical(
            matches, lexical_matches, lambda e: e.id,
            self.hybrid_keyword_weight, self.rrf_k,
        )
        results = [
            ScoredEpisode(episode=episode, score=fused)
            for fused, episode in fused_matches.values()
        ]

        if self.reranker and results:
            docs = [se.episode.content or "" for se in results]
            rerank_scores = self.reranker.score(query, docs)
            for se, rs in zip(results, rerank_scores):
                se.score = 0.4 * se.score + 0.6 * rs

        results.sort(key=lambda s: s.score, reverse=True)
        return results

    async def retrieve_all(
        self,
        query: str,
        k: int = 3,
        episode_k: int = 5,
        min_activation: float = 0.15,
        context: Optional[str] = None,
        labels: Optional[dict[str, str]] = None,
        timeout_ms: Optional[int] = None,
    ) -> tuple[list[ActivatedConcept], Optional[list[ScoredEpisode]]]:
        """Retrieve concepts and episodes in a single pass.

        Combines :meth:`retrieve` and :meth:`retrieve_episodes_by_embedding`
        while computing the query embedding only once and batching the
        cross-encoder reranker into a single ``predict()`` call.

        Args:
            query: The query text.
            k: Maximum number of concepts to return.
            episode_k: Maximum number of episodes to return (0 to skip).
            min_activation: Minimum activation score for concepts.
            context: Optional additional context for the concept embedding.
            labels: Optional key=value label pre-filter for concept and
                episode vector search (ANDed across keys).
            timeout_ms: Soft deadline. Once exceeded, remaining phases
                (spreading, reranking) are skipped and results are built
                from whatever was already gathered, instead of raising.

        Returns:
            ``(activated_concepts, scored_episodes)`` — the same objects
            that ``retrieve()`` and ``retrieve_episodes_by_embedding()``
            would return individually.
        """
        t_start = time.perf_counter()
        deadline = t_start + timeout_ms / 1000.0 if timeout_ms else None
        # --- single embedding ------------------------------------------
        embed_text = query
        if context:
            embed_text = f"{query}\n\nContext: {context}"
        t_embed_start = time.perf_counter()
        fallback = False
        import json
        expected = json.dumps({"provider": self.embedding.name, "dimensions": self.embedding.dimensions,
                               "input_version": 1}, sort_keys=True)
        stored = self.store.get_metadata("embedding_fingerprint")
        try:
            query_embedding = await self.embedding.embed(embed_text)
            expected = json.dumps({"provider": self.embedding.name, "dimensions": len(query_embedding), "input_version": 1}, sort_keys=True)
            old_dims = self.store.get_metadata("embedding_dimensions")
            if (stored and stored != expected) or (old_dims and int(old_dims) != len(query_embedding)):
                raise ValueError("Embedding fingerprint mismatch; re-embed all records")
        except Exception as exc:
            logger.warning("Lexical-only recall: %s", exc)
            query_embedding = [0.0] * int(self.store.get_metadata("embedding_dimensions") or self.embedding.dimensions)
            fallback = True
        t_embed_ms = (time.perf_counter() - t_embed_start) * 1000.0

        # --- parallel vector + lexical search for concepts, episodes, entities --
        t_initial_search_start = time.perf_counter()
        run_lexical = self.lexical_enabled and (fallback or self.hybrid_keyword_weight > 0.0)

        # Run all searches in parallel using thread pool
        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=5) as pool:
            concept_future = asyncio.sleep(0, result=[]) if fallback else loop.run_in_executor(
                pool, self.store.find_by_embedding, query_embedding, self.initial_k * 2, labels
            )
            episode_future = asyncio.sleep(0, result=[]) if fallback else loop.run_in_executor(
                pool, self.store.find_episodes_by_embedding, query_embedding,
                episode_k if episode_k > 0 else 1, labels,
            )
            entity_future = asyncio.sleep(0, result=[]) if fallback else loop.run_in_executor(
                pool, self.store.find_entities_by_embedding, query_embedding, self.initial_k
            )
            futures = [concept_future, episode_future, entity_future]
            if run_lexical:
                lexical_concept_future = loop.run_in_executor(
                    pool, self.store.search_concepts_lexical, query, self.initial_k * 2, labels
                )
                lexical_episode_future = loop.run_in_executor(
                    pool, self.store.search_episodes_lexical, query,
                    episode_k if episode_k > 0 else 1, labels,
                )
                futures.extend([lexical_concept_future, lexical_episode_future])

            gathered = await asyncio.gather(*futures)

        initial_matches, ep_matches_parallel, entity_matches = gathered[:3]
        lexical_concept_matches, lexical_episode_matches = (
            gathered[3:5] if run_lexical else ([], [])
        )

        self._last_trace = {
            "vector": [{"id": item.id, "similarity": score} for item, score in initial_matches],
            "lexical": [{"id": item.id, "score": score} for item, score in lexical_concept_matches],
            "episode_vector": [{"id": item.id, "similarity": score} for item, score in ep_matches_parallel],
            "lexical_only": fallback, "graph_edges": [],
        }
        t_initial_search_ms = (time.perf_counter() - t_initial_search_start) * 1000.0

        t_initial_activation_start = time.perf_counter()
        activation_map: dict[str, tuple[float, str, int]] = {}
        concept_cache: dict[str, Concept] = {}
        
        # Boost concepts linked to matched entities (entity-first recall)
        for entity, similarity in entity_matches:
            if similarity < 0.3:  # Skip low-similarity entity matches
                continue
            # Get all concepts linked to this entity (fact_clusters and patterns)
            linked_concepts = self.store.get_concepts_for_entity(entity.id)
            for concept in linked_concepts:
                entity_derived_activation = similarity * 0.8 * concept.confidence
                current = activation_map.get(concept.id, (0, "", 0))[0]
                if entity_derived_activation > current:
                    activation_map[concept.id] = (entity_derived_activation, "entity_embedding", 0)
                    concept_cache[concept.id] = concept

        fused_concept_matches = _fuse_vector_lexical(
            initial_matches, lexical_concept_matches, lambda c: c.id,
            1.0 if fallback else self.hybrid_keyword_weight, self.rrf_k,
        )
        for fused, concept in fused_concept_matches.values():
            weighted_activation = fused * concept.confidence
            decay_factor = max(0.0, min(1.0, concept.decay_factor))
            evidence_weight = self._compute_evidence_weight(concept.id)
            final_activation = weighted_activation * decay_factor * evidence_weight

            if final_activation > self.activation_threshold:
                activation_map[concept.id] = (final_activation, "embedding", 0)
                concept_cache[concept.id] = concept
                if decay_factor < 0.5 or evidence_weight < 0.8:
                    logger.debug(
                        f"Concept {concept.id} activation adjusted: "
                        f"decay={decay_factor:.2f}, evidence={evidence_weight:.2f}"
                    )
        t_initial_activation_ms = (time.perf_counter() - t_initial_activation_start) * 1000.0

        logger.debug(f"Initial activation: {len(activation_map)} concepts (labels={labels})")

        t_spread_start = time.perf_counter()
        deadline_hit = deadline is not None and t_spread_start > deadline
        if deadline_hit:
            logger.warning("recall timeout_ms exceeded before spreading; returning best-so-far")
        for hop in range(self.spread_hops if not deadline_hit else 0):
            new_activations: dict[str, tuple[float, str, int]] = {}

            for concept_id, (activation, _, _) in list(activation_map.items()):
                if activation < self.activation_threshold:
                    continue

                related = self.store.get_related(concept_id, depth=1)

                for related_concept, relation in related:
                    relation_weight = self.relation_weights.get(relation.type, 0.5)
                    target_decay = max(0.0, min(1.0, related_concept.decay_factor))
                    target_evidence = self._compute_evidence_weight(related_concept.id)
                    spread_activation = (
                        activation
                        * relation.strength
                        * relation_weight
                        * (self.spread_decay ** (hop + 1))
                        * related_concept.confidence
                        * target_decay
                        * target_evidence
                    )

                    if spread_activation < self.activation_threshold:
                        continue

                    current = activation_map.get(related_concept.id, (0, "", 0))[0]
                    spread_current = new_activations.get(related_concept.id, (0, "", 0))[0]

                    if spread_activation > max(current, spread_current):
                        new_activations[related_concept.id] = (
                            spread_activation,
                            "spread",
                            hop + 1,
                        )
                        concept_cache[related_concept.id] = related_concept
                        self._last_trace["graph_edges"].append({"from": concept_id, "to": related_concept.id,
                            "relation": relation.type.value, "strength": relation.strength,
                            "activation": spread_activation, "hop": hop + 1})

            for cid, (act, src, hops) in new_activations.items():
                current = activation_map.get(cid, (0, "", 0))[0]
                if act > current:
                    activation_map[cid] = (act, src, hops)

            logger.debug(f"After hop {hop + 1}: {len(activation_map)} concepts")
            if deadline is not None and time.perf_counter() > deadline:
                logger.warning("recall timeout_ms exceeded during spreading; stopping early")
                break
        t_spread_ms = (time.perf_counter() - t_spread_start) * 1000.0

        # Entity name matching
        t_entity_start = time.perf_counter()
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
        t_entity_ms = (time.perf_counter() - t_entity_start) * 1000.0

        # --- process episode results from parallel search ----------------
        t_episode_search_start = time.perf_counter()
        episode_results: Optional[list[ScoredEpisode]] = None
        if episode_k > 0 and (ep_matches_parallel or lexical_episode_matches):
            fused_episode_matches = _fuse_vector_lexical(
                ep_matches_parallel, lexical_episode_matches, lambda e: e.id,
                1.0 if fallback else self.hybrid_keyword_weight, self.rrf_k,
            )
            episode_results = [
                ScoredEpisode(episode=episode, score=fused)
                for fused, episode in fused_episode_matches.values()
            ]
        t_episode_search_ms = (time.perf_counter() - t_episode_search_start) * 1000.0

        # --- single batched reranker pass (skipped past the deadline) ----
        t_rerank_ms = 0.0
        if (
            self.reranker and (activation_map or episode_results)
            and not (deadline is not None and time.perf_counter() > deadline)
        ):
            t_rerank_start = time.perf_counter()
            concept_ids = list(activation_map.keys()) if activation_map else []
            concept_docs: list[str] = []
            for cid in concept_ids:
                c = concept_cache.get(cid) or self.store.get_concept(cid)
                if c:
                    concept_cache[cid] = c
                    concept_docs.append(f"{c.title or ''} {c.summary or ''}".strip())
                else:
                    concept_docs.append("")

            episode_docs: list[str] = []
            if episode_results:
                episode_docs = [se.episode.content or "" for se in episode_results]

            all_docs = concept_docs + episode_docs
            if all_docs:
                all_scores = self.reranker.score(query, all_docs)

                n_concepts = len(concept_ids)
                for idx, cid in enumerate(concept_ids):
                    old_act, src, hops = activation_map[cid]
                    blended = 0.4 * old_act + 0.6 * all_scores[idx]
                    activation_map[cid] = (blended, src, hops)

                if episode_results:
                    for idx, se in enumerate(episode_results):
                        se.score = 0.4 * se.score + 0.6 * all_scores[n_concepts + idx]

            logger.debug(
                f"Reranked {len(concept_ids)} concepts + {len(episode_docs)} episodes"
            )
            t_rerank_ms = (time.perf_counter() - t_rerank_start) * 1000.0

        # --- build concept results --------------------------------------
        t_finalize_start = time.perf_counter()
        results: list[ActivatedConcept] = []
        for concept_id, (activation, source, hops) in activation_map.items():
            if activation < self.activation_threshold * 2:
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

        results.sort(key=lambda x: x.activation, reverse=True)
        results = [r for r in results if r.activation >= min_activation]
        results = results[:k]

        # --- sort episodes -----------------------------------------------
        if episode_results:
            episode_results.sort(key=lambda s: s.score, reverse=True)

        t_finalize_ms = (time.perf_counter() - t_finalize_start) * 1000.0
        t_total_ms = (time.perf_counter() - t_start) * 1000.0
        logger.debug(
            "Recall timing (retrieve_all): embed=%.1fms vector=%.1fms "
            "initial_activation=%.1fms spread=%.1fms entity_match=%.1fms "
            "episode_search=%.1fms rerank=%.1fms finalize=%.1fms total=%.1fms "
            "candidates(concepts=%d,episodes=%d) returned(concepts=%d,episodes=%d)",
            t_embed_ms,
            t_initial_search_ms,
            t_initial_activation_ms,
            t_spread_ms,
            t_entity_ms,
            t_episode_search_ms,
            t_rerank_ms,
            t_finalize_ms,
            t_total_ms,
            len(activation_map),
            len(episode_results) if episode_results else 0,
            len(results),
            len(episode_results) if episode_results else 0,
        )
        self._last_trace["timing_ms"] = {"embedding": t_embed_ms, "search": t_initial_search_ms,
            "spreading": t_spread_ms, "reranking": t_rerank_ms, "total": t_total_ms}
        return results, episode_results

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
        type_weight = _EPISODE_TYPE_WEIGHTS.get(episode.episode_type, _DEFAULT_EPISODE_TYPE_WEIGHT)

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
        direct_episodes: Optional[list["ScoredEpisode"]] = None,
        as_of: Optional[datetime] = None,
    ) -> str:
        """
        Format retrieved concepts and episodes for injection into an LLM prompt.

        Args:
            activated: Concept matches from spreading activation.
            include_relations: Show concept relations.
            max_relations: Max relations per concept.
            include_episodes: Show source episodes under each concept.
            matched_entities: Entities matched by name from the query.
            max_entity_episodes: Max episodes to show per matched entity.
            direct_episodes: Episodes matched by direct embedding search.
            as_of: When set, fact_cluster concepts show the facts that were
                   valid at this point in time instead of the current ones.
        """
        if matched_entities is None:
            matched_entities = getattr(self, "_last_matched_entities", None) or []

        if not activated and not matched_entities and not direct_episodes:
            return "(No relevant memories found)"

        lines = []

        if direct_episodes:
            lines.append("RELEVANT EPISODES:\n")
            for se in direct_episodes:
                lines.append(_format_episode_line(se.episode, prefix="  • "))
            lines.append("")

        lines.append("RELEVANT MEMORY:\n")

        for ac in activated:
            self._format_concept_block(ac, lines, include_relations, max_relations, include_episodes, as_of)

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
                    by_type.setdefault(ep.episode_type, []).append(ep)
                type_order = [
                    "fact", "decision", "question", "preference",
                    "observation", "outcome", "meta",
                ]
                for type_name in type_order:
                    if type_name not in by_type:
                        continue
                    lines.append(f"  [{type_name.upper()}S]")
                    for ep in by_type[type_name]:
                        lines.append(_format_episode_line(ep))
                lines.append("")

        return "\n".join(lines)

    def _format_concept_block(
        self,
        ac: ActivatedConcept,
        lines: list[str],
        include_relations: bool,
        max_relations: int,
        include_episodes: bool,
        as_of: Optional[datetime] = None,
    ) -> None:
        """Render a single activated concept into *lines*."""
        c = ac.concept

        updated = c.updated_at.strftime("%Y-%m-%d %H:%M")

        # Include concept type badge for non-legacy concepts
        # Supports any string type (freeform concept types)
        type_badge = ""
        if c.concept_type == "fact_cluster" or c.concept_type == "fact":
            type_badge = "[facts] "
        elif c.concept_type and c.concept_type != "legacy":
            type_badge = f"[{c.concept_type}] "

        if c.title:
            header = f"[{c.id}] {type_badge}{c.title} (confidence: {c.confidence:.2f}, last updated: {updated}"
        else:
            header = f"[{c.id}] {type_badge}(confidence: {c.confidence:.2f}, last updated: {updated}"
        if ac.source == "spread":
            header += ", via association"
        elif ac.source == "entity_name":
            header += ", via entity match"
        header += ")"
        lines.append(header)

        # Format differently based on concept type
        # "fact" and "fact_cluster" both show validity windows
        if c.concept_type in ("fact_cluster", "fact") and (c.specifics or as_of):
            def _fact_line(fact) -> str:
                meta = []
                if fact.asserted_by:
                    meta.append(fact.asserted_by)
                meta.append(f"since {fact.valid_from.strftime('%Y-%m-%d')}")
                return f"    • {fact.statement} ({', '.join(meta)})"

            if as_of is not None:
                # Time-travel view: show the facts valid at that point in time
                historical = self.store.get_facts(cluster_id=c.id, as_of=as_of)
                lines.append(f"  Facts (as of {as_of.strftime('%Y-%m-%d')}):")
                if historical:
                    for fact in historical:
                        lines.append(_fact_line(fact))
                else:
                    lines.append("    (no facts were valid at that time)")
            else:
                # Current view: active fact rows with provenance; fall back to
                # the specifics render cache for clusters without fact rows.
                active = self.store.get_facts(cluster_id=c.id, active_only=True)
                lines.append("  Facts:")
                if active:
                    for fact in active:
                        lines.append(_fact_line(fact))
                else:
                    for specific in c.specifics:
                        lines.append(f"    • {specific}")

            # Show open (untriaged) conflicts prominently
            open_conflicts = self.store.get_conflicts(status="open", concept_id=c.id)
            if open_conflicts:
                lines.append(f"  ⚠ OPEN CONFLICTS ({len(open_conflicts)}):")
                for conflict in open_conflicts:
                    lines.append(f"    • [{conflict.id}] {conflict.description}")
                    lines.append(f"      (detected: {conflict.created_at.strftime('%Y-%m-%d')}, severity: {conflict.severity})")

            # Show recent resolved conflicts — provides provenance context so the
            # calling agent can challenge a prior resolution if it has newer info.
            resolved_conflicts = self.store.get_conflicts(status="resolved", concept_id=c.id)
            if resolved_conflicts:
                # Most-recently-resolved first, cap at 3
                resolved_conflicts = sorted(
                    resolved_conflicts,
                    key=lambda x: x.resolved_at or datetime.min,
                    reverse=True,
                )[:3]
                lines.append(f"  Conflict history ({len(resolved_conflicts)} shown):")
                for conflict in resolved_conflicts:
                    winner = self.store.get_fact(conflict.winning_fact_id) if conflict.winning_fact_id else None
                    loser_id = (
                        conflict.fact_b_id
                        if conflict.winning_fact_id == conflict.fact_a_id
                        else conflict.fact_a_id
                    )
                    loser = self.store.get_fact(loser_id) if loser_id else None

                    date_str = conflict.resolved_at.strftime("%Y-%m-%d") if conflict.resolved_at else "?"
                    by_str = f" by {conflict.resolved_by}" if conflict.resolved_by else ""
                    note_str = f" — \"{conflict.resolution_note}\"" if conflict.resolution_note else ""

                    def _truncate(s: str, n: int = 60) -> str:
                        return (s[:n] + "...") if len(s) > n else s

                    winner_stmt = _truncate(winner.statement) if winner else "?"
                    loser_stmt = _truncate(loser.statement) if loser else "?"
                    lines.append(
                        f"    • [resolved {date_str}{by_str}]"
                        f" \"{winner_stmt}\" replaced \"{loser_stmt}\"{note_str}"
                    )
        else:
            # Standard summary for patterns and legacy concepts
            lines.append(f"  {c.summary}")

            # Show evidence quotes if available
            if c.evidence:
                lines.append("  Evidence:")
                for evidence in c.evidence[:3]:  # Limit to 3 quotes
                    lines.append(f"    • \"{evidence}\"")

        if c.conditions:
            lines.append(f"  → Applies when: {c.conditions}")
        if c.exceptions:
            lines.append(f"  → Exceptions: {', '.join(c.exceptions)}")

        outbound_contradictions = [
            rel for rel in c.relations if rel.type == RelationType.CONTRADICTS
        ]
        inbound_contradictions = self.store.get_incoming_relations(
            c.id, RelationType.CONTRADICTS
        )
        if outbound_contradictions or inbound_contradictions:
            lines.append("  Contradictions:")
            for rel in outbound_contradictions:
                target = self.store.get_concept(rel.target_id)
                if target:
                    label = f"  → contradicts [{target.id}]: {target.summary}"
                    if rel.context:
                        label += f" (context: {rel.context})"
                    lines.append(label)
            for source_concept, rel in inbound_contradictions:
                if source_concept.id == c.id:
                    continue
                label = f"  → [{source_concept.id}] contradicts this: {source_concept.summary}"
                if rel.context:
                    label += f" (context: {rel.context})"
                lines.append(label)
        else:
            lines.append("  Contradictions: (none)")

        outbound_supersedes = [
            rel for rel in c.relations if rel.type == RelationType.SUPERSEDES
        ]
        inbound_supersedes = self.store.get_incoming_relations(
            c.id, RelationType.SUPERSEDES
        )
        if outbound_supersedes or inbound_supersedes:
            for rel in outbound_supersedes:
                target = self.store.get_concept(rel.target_id)
                if target:
                    label = f"  → supersedes [{target.id}]: {target.summary}"
                    if rel.context:
                        label += f" (context: {rel.context})"
                    lines.append(label)
            for source_concept, rel in inbound_supersedes:
                if source_concept.id == c.id:
                    continue
                label = f"  → SUPERSEDED BY [{source_concept.id}]: {source_concept.summary}"
                if rel.context:
                    label += f" (context: {rel.context})"
                lines.append(label)

        if include_relations and c.relations:
            shown = 0
            for rel in c.relations:
                if rel.type in (RelationType.CONTRADICTS, RelationType.SUPERSEDES):
                    continue
                if shown >= max_relations:
                    break
                target = self.store.get_concept(rel.target_id)
                if target:
                    rel_str = f"  → {rel.type.value}: {target.summary}"
                    lines.append(rel_str)
                    shown += 1

        if include_episodes and c.source_episodes:
            source_eps = self.store.get_episodes_batch(c.source_episodes)

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

            # Fact clusters render their fact rows (with provenance and
            # validity) above; repeating raw episodes would resurface
            # superseded values as if current.
            if c.concept_type not in ("fact_cluster", "fact"):
                lines.append("")
                lines.append("  Source episodes:")
                for episode in source_eps:
                    lines.append(_format_episode_line(episode))

        lines.append("")
    
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
                by_type.setdefault(ep.episode_type, []).append(ep)
            
            type_order = ["fact", "decision", "question", "preference", "observation", "meta"]
            for type_name in type_order:
                if type_name not in by_type:
                    continue
                
                type_episodes = by_type[type_name]
                lines.append(f"[{type_name.upper()}S]")

                for ep in type_episodes:
                    lines.append(_format_episode_line(ep, prefix="  • "))

                lines.append("")
        else:
            # Simple chronological list
            for ep in episodes:
                lines.append(_format_episode_line(ep, prefix="  "))
        
        return "\n".join(lines)

