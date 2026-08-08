"""
MemoryInterface - The unified API for the memory system.

This is the main entry point for applications integrating Remind.
It provides a simple interface for:
- remember() - log experiences/interactions
- recall() - retrieve relevant concepts
"""

from datetime import datetime
from typing import Optional, Union
from pathlib import Path
import logging

from dataclasses import dataclass, field

from remind.models import (
    Episode, Concept, Conflict, Fact,
    Entity, EntityType, EpisodeType, Relation, RelationType,
    normalize_entity_name,
    normalize_labels,
    canonicalize_entity_name,
    strip_entity_label_prefix,
)
from remind.store import MemoryStore, SQLAlchemyMemoryStore
from remind.providers.base import EmbeddingProvider
from remind.retrieval import MemoryRetriever, ActivatedConcept
from remind.config import load_config, DecayConfig, RemindConfig, setup_file_logging, DEFAULT_EPISODE_TYPES
from remind.facts import create_fact_from_episode, FactResult


@dataclass
class RememberResult:
    """Result of a remember() call with optional fact collision info."""
    
    episode_id: str
    fact_id: Optional[str] = None
    cluster_id: Optional[str] = None
    cluster_created: bool = False
    collisions: list[Fact] = field(default_factory=list)
    related_facts: list[Fact] = field(default_factory=list)
    entity_resolutions: list[str] = field(default_factory=list)
    # Nearest-neighbor episodes and concepts — agent decides if any conflict
    nearby_episodes: list[tuple["Episode", float]] = field(default_factory=list)
    nearby_concepts: list[tuple["Concept", float]] = field(default_factory=list)

    def has_collisions(self) -> bool:
        return len(self.collisions) > 0

    def has_related(self) -> bool:
        return len(self.related_facts) > 0

    def has_entity_resolutions(self) -> bool:
        return len(self.entity_resolutions) > 0

    def has_nearby(self) -> bool:
        return bool(self.nearby_episodes or self.nearby_concepts)

logger = logging.getLogger(__name__)


class MemoryInterface:
    """
    The main interface to the memory system.
    
    Key Design:
    -----------
    - `remember()` is async - stores episodes and embeds them by default
    - `recall()` retrieves relevant concepts using spreading activation
    - All judgment/curation is done by the calling agent via snapshot/apply tools
    
    Usage:
        memory = MemoryInterface(
            embedding=LocalEmbedding(),
        )
        
        # Log experiences (fast, no LLM call)
        await memory.remember("User prefers Python for backend development")
        await memory.remember("User mentioned they work on distributed systems")
        
        # Retrieve relevant context
        context = await memory.recall("What programming languages does the user like?")
    """
    
    def __init__(
        self,
        embedding: EmbeddingProvider,
        store: Optional[MemoryStore] = None,
        db_url: Optional[str] = None,
        db_path: str = "memory.db",
        # Retrieval settings
        default_recall_k: int = 3,
        default_episode_k: int = 5,
        spread_hops: int = 2,
        # Decay settings
        decay_config: Optional[DecayConfig] = None,
        # Configurable episode types
        episode_types: Optional[list[str]] = None,
        # Retrieval tuning
        hybrid_keyword_weight: float = 0.0,
        recall_initial_candidates: int = 10,
        lexical_enabled: bool = True,
        rrf_k: int = 60,
        # Recall budget controls (defaults used when recall() doesn't override)
        recall_max_chars: Optional[int] = None,
        recall_min_score: Optional[float] = None,
        recall_timeout_ms: Optional[int] = None,
        # Reranking
        reranking_enabled: bool = False,
        reranking_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2",
        # Fact clustering
        fact_cluster_jaccard_threshold: float = 0.5,
        # Cross-cluster related facts
        fact_related_similarity_threshold: float = 0.6,
        fact_related_max_results: int = 10,
        # Same-cluster collision cap
        fact_collision_max_results: int = 5,
        # Nearest-neighbor surfacing on remember() — agent decides if conflicts exist
        remember_nearby_k: int = 5,
    ):
        self.embedding = embedding
        if store:
            self.store = store
        elif db_url:
            self.store = SQLAlchemyMemoryStore(db_url)
        else:
            self.store = SQLAlchemyMemoryStore(db_path)
        
        reranker = None
        if reranking_enabled:
            from remind.reranker import Reranker
            reranker = Reranker(model_name=reranking_model)

        self.retriever = MemoryRetriever(
            embedding=embedding,
            store=self.store,
            initial_k=recall_initial_candidates,
            spread_hops=spread_hops,
            hybrid_keyword_weight=hybrid_keyword_weight,
            lexical_enabled=lexical_enabled,
            rrf_k=rrf_k,
            reranker=reranker,
        )
        
        self.recall_max_chars = recall_max_chars
        self.recall_min_score = recall_min_score
        self.recall_timeout_ms = recall_timeout_ms

        self.episode_types: list[str] = episode_types or list(DEFAULT_EPISODE_TYPES)
        self.fact_cluster_jaccard_threshold = fact_cluster_jaccard_threshold
        self.fact_related_similarity_threshold = fact_related_similarity_threshold
        self.fact_related_max_results = fact_related_max_results
        self.fact_collision_max_results = fact_collision_max_results
        self.remember_nearby_k = remember_nearby_k
        
        # Settings
        self.default_recall_k = default_recall_k
        self.default_episode_k = default_episode_k
        
        # Decay settings
        self.decay_config = decay_config or DecayConfig()
        
        # Recall tracking for decay (persisted in metadata table)
        self._recall_count: int = self._load_recall_count()
        
        # Episode buffer for tracking (this session only)
        self._episode_buffer: list[str] = []

    def _resolve_entity_id(self, raw_entity_id: str) -> str:
        """Resolve a raw entity ID to a canonical one, deduplicating by name."""
        type_str, name = Entity.parse_id(raw_entity_id)
        canonical_name = canonicalize_entity_name(name)
        existing = self.store.find_entity_by_name(canonical_name)
        if existing:
            return existing.id

        normalized_id = Entity.make_id(type_str, canonical_name)
        if not self.store.get_entity(normalized_id):
            try:
                etype = EntityType(type_str)
            except ValueError:
                etype = EntityType.OTHER
            display_name = strip_entity_label_prefix(name) or canonical_name
            entity = Entity(id=normalized_id, type=etype, display_name=display_name)
            self.store.add_entity(entity)
        return normalized_id

    async def remember(
        self,
        content: str,
        metadata: Optional[dict] = None,
        episode_type: Optional[str] = None,
        entities: Optional[list[str]] = None,
        confidence: float = 1.0,
        embed: bool = True,
        labels: Optional[dict[str, str | list[str]]] = None,
        source_type: Optional[str] = None,
        asserted_by: Optional[str] = None,
        source_ref: Optional[str] = None,
    ) -> RememberResult:
        """
        Log an experience/interaction.

        Embeds the episode content by default for vector search during recall.
        For fact-type episodes, also creates a Fact row with cluster assignment
        and reports any potential collisions.

        Args:
            content: The interaction or experience to remember
            metadata: Optional metadata about the episode
            episode_type: Optional explicit type (observation, decision, question, fact, etc.)
            entities: Optional entity ID hints (e.g., ["file:src/auth.ts", "person:alice"]).
            confidence: How certain this information is (0.0-1.0, default 1.0).
            embed: Whether to generate an embedding for the episode (default True).
            labels: Optional freeform key -> value(s) labels (e.g. {"topic": "architecture"}).
            source_type: Origin of this episode (e.g. "agent", "slack", "github", "manual").
            asserted_by: Who asserted this information (e.g. "alice", "agent:cursor").
            source_ref: Link back to the original artifact (URL/permalink).

        Returns:
            RememberResult with episode_id and (for facts) collision info
        """
        episode = Episode(
            content=content,
            metadata=metadata or {},
            confidence=max(0.0, min(1.0, confidence)),
            labels=normalize_labels(labels),
            source_type=source_type.lower().strip() if source_type else None,
            asserted_by=asserted_by.strip() if asserted_by else None,
            source_ref=source_ref.strip() if source_ref else None,
        )
        
        if episode_type:
            episode.episode_type = episode_type.value if isinstance(episode_type, EpisodeType) else str(episode_type)
        
        # Embed the episode content
        embedding = None
        if embed and self.embedding:
            try:
                embedding = await self.embedding.embed(content)
                episode.embedding = embedding
            except Exception as e:
                logger.warning(f"Failed to embed episode: {e}")
        
        # Store the episode
        episode_id = self.store.add_episode(episode)
        self._episode_buffer.append(episode_id)
        self.store.emit_event("remembered", "episode", episode_id)
        
        # Resolve and store explicitly provided entities
        entity_resolutions: list[str] = []
        if entities:
            resolved_ids = []
            for raw_id in entities:
                canonical_id = self._resolve_entity_id(raw_id)
                # Warn when type prefix changed (entity dedup fired across types)
                raw_type = raw_id.split(":", 1)[0] if ":" in raw_id else ""
                canonical_type = canonical_id.split(":", 1)[0] if ":" in canonical_id else ""
                if raw_type and canonical_type and raw_type != canonical_type:
                    entity_resolutions.append(f"{raw_id} → {canonical_id}")
                    logger.debug(f"Entity type coercion: {raw_id} → {canonical_id}")
                resolved_ids.append(canonical_id)
                self.store.add_mention(episode_id, canonical_id)
                # Also embed the entity
                if embed and self.embedding:
                    entity = self.store.get_entity(canonical_id)
                    if entity and not entity.embedding:
                        try:
                            entity.embedding = await self.embedding.embed(
                                f"{entity.type.value}: {entity.display_name}"
                            )
                            self.store.update_entity(entity)
                        except Exception as e:
                            logger.warning(f"Failed to embed entity: {e}")
            episode.entity_ids = resolved_ids
            self.store.update_episode(episode)
        
        logger.debug(f"Remembered episode {episode_id}: {content[:50]}...")

        # Surface nearest-neighbor episodes and concepts for agent conflict triage
        nearby_episodes: list[tuple[Episode, float]] = []
        nearby_concepts: list[tuple[Concept, float]] = []
        if embedding and self.remember_nearby_k > 0:
            raw_eps = self.store.find_episodes_by_embedding(embedding, k=self.remember_nearby_k + 1)
            nearby_episodes = [(ep, score) for ep, score in raw_eps if ep.id != episode_id][: self.remember_nearby_k]
            nearby_concepts = self.store.find_by_embedding(embedding, k=self.remember_nearby_k)

        # For fact-type episodes, create Fact row with cluster assignment
        if episode.episode_type == "fact":
            fact_result = create_fact_from_episode(
                self.store,
                episode,
                embedding=embedding,
                jaccard_threshold=self.fact_cluster_jaccard_threshold,
                related_similarity_threshold=self.fact_related_similarity_threshold,
                related_max_results=self.fact_related_max_results,
                collision_max_results=self.fact_collision_max_results,
            )
            if fact_result.fact_id:
                self.store.emit_event("remembered", "fact", fact_result.fact_id)
            return RememberResult(
                episode_id=episode_id,
                fact_id=fact_result.fact_id,
                cluster_id=fact_result.cluster_id,
                cluster_created=fact_result.cluster_created,
                collisions=fact_result.collisions,
                related_facts=fact_result.related_facts,
                entity_resolutions=entity_resolutions,
                nearby_episodes=nearby_episodes,
                nearby_concepts=nearby_concepts,
            )

        return RememberResult(
            episode_id=episode_id,
            entity_resolutions=entity_resolutions,
            nearby_episodes=nearby_episodes,
            nearby_concepts=nearby_concepts,
        )
    
    async def remember_batch(
        self,
        items: list[dict],
        embed: bool = True,
        embed_batch_size: int = 100,
    ) -> list[str]:
        """
        Batch-remember multiple episodes efficiently.

        Creates all episodes, embeds them in batches via the provider's
        embed_batch() API, and writes them in a single DB transaction.
        """
        if not items:
            return []

        episodes = []
        for item in items:
            source_type = item.get("source_type")
            asserted_by = item.get("asserted_by")
            source_ref = item.get("source_ref")
            episode = Episode(
                content=item["content"],
                metadata=item.get("metadata") or {},
                confidence=max(0.0, min(1.0, item.get("confidence", 1.0))),
                source_type=source_type.lower().strip() if source_type else None,
                asserted_by=asserted_by.strip() if asserted_by else None,
                source_ref=source_ref.strip() if source_ref else None,
            )
            if item.get("episode_type"):
                et = item["episode_type"]
                episode.episode_type = et.value if isinstance(et, EpisodeType) else str(et)
            episodes.append(episode)

        if embed and self.embedding:
            texts = [ep.content for ep in episodes]
            all_embeddings: list[list[float] | None] = [None] * len(texts)

            for i in range(0, len(texts), embed_batch_size):
                batch = texts[i:i + embed_batch_size]
                try:
                    batch_embeddings = await self.embedding.embed_batch(batch)
                    for j, emb in enumerate(batch_embeddings):
                        all_embeddings[i + j] = emb
                except Exception as e:
                    logger.warning(f"Failed to embed batch {i//embed_batch_size}: {e}")

            for episode, emb in zip(episodes, all_embeddings):
                if emb is not None:
                    episode.embedding = emb

        episode_ids = self.store.add_episodes_batch(episodes)
        self._episode_buffer.extend(episode_ids)
        for episode_id in episode_ids:
            self.store.emit_event("remembered", "episode", episode_id)

        for episode, item in zip(episodes, items):
            entities = item.get("entities")
            if entities:
                for raw_id in entities:
                    canonical_id = self._resolve_entity_id(raw_id)
                    self.store.add_mention(episode.id, canonical_id)

        logger.debug(f"Batch-remembered {len(episode_ids)} episodes")
        return episode_ids

    async def recall(
        self,
        query: Optional[str] = None,
        k: Optional[int] = None,
        context: Optional[str] = None,
        entity: Optional[str] = None,
        raw: bool = False,
        episode_k: Optional[int] = None,
        labels: Optional[dict[str, str]] = None,
        as_of: Optional[Union[datetime, str]] = None,
        max_chars: Optional[int] = None,
        min_score: Optional[float] = None,
        timeout_ms: Optional[int] = None,
    ) -> str | list[ActivatedConcept] | list[Episode]:
        """
        Retrieve relevant memory context for a query.

        Uses spreading activation to find conceptually relevant memories,
        optionally enhanced with direct episode vector search.

        Args:
            labels: Optional key=value label pre-filter (e.g. {"topic": "architecture"}).
                Applied before vector search, not as a post-filter.
            max_chars: Cap on the formatted output length. When the rendered
                text would exceed this, the lowest-ranked concepts/episodes
                are dropped whole (never truncated mid-item) until it fits.
                Falls back to the ``recall_max_chars`` constructor default.
                Ignored when ``raw=True``.
            min_score: Floor below which concepts/episodes are dropped even
                if the ``k``/``episode_k`` budget has room left. Falls back
                to the ``recall_min_score`` constructor default.
            timeout_ms: Soft deadline for the retrieval. If exceeded,
                returns the best results gathered so far (skipping
                remaining spreading-activation hops / reranking) instead of
                raising. Falls back to the ``recall_timeout_ms`` constructor
                default.
        """
        k = k or self.default_recall_k
        episode_k = episode_k if episode_k is not None else self.default_episode_k
        max_chars = max_chars if max_chars is not None else self.recall_max_chars
        min_score = min_score if min_score is not None else self.recall_min_score
        timeout_ms = timeout_ms if timeout_ms is not None else self.recall_timeout_ms

        as_of_dt = None
        if as_of is not None:
            if isinstance(as_of, str):
                as_of_dt = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
            else:
                as_of_dt = as_of

        # Entity-based recall mode
        if entity:
            canonical = self._resolve_entity_id(entity)
            episodes = self.store.get_episodes_mentioning(canonical, limit=k)
            
            if raw:
                return episodes
            
            return self.retriever.format_entity_context(entity, episodes)
        
        if not query:
            raise ValueError("Either 'query' or 'entity' must be provided")
        
        retrieve_kwargs: dict = dict(
            k=k,
            episode_k=episode_k,
            labels=labels,
        )
        if min_score is not None:
            retrieve_kwargs["min_activation"] = min_score
        if timeout_ms is not None:
            retrieve_kwargs["timeout_ms"] = timeout_ms

        concepts, episodes = await self.retriever.retrieve_all(query, **retrieve_kwargs)

        if min_score is not None and episodes:
            episodes = [e for e in episodes if e.score >= min_score]

        self._increment_recall_count()
        
        if self.decay_config.enabled:
            self._maybe_decay(concepts)
            # Rejuvenate accessed concepts (update access count/time)
            if hasattr(self.retriever, 'rejuvenate'):
                self.retriever.rejuvenate(concepts)
        
        if raw:
            return concepts
        
        if max_chars is None:
            return self.retriever.format_for_llm(
                activated=concepts,
                direct_episodes=episodes,
                as_of=as_of_dt,
            )

        return self._format_with_char_budget(concepts, episodes, as_of_dt, max_chars)

    def _format_with_char_budget(
        self,
        concepts: list[ActivatedConcept],
        episodes: Optional[list],
        as_of_dt: Optional[datetime],
        max_chars: int,
    ) -> str:
        """Render concepts/episodes, dropping the lowest-ranked whole item at
        a time (never truncating mid-item) until the result fits max_chars.

        Both lists are expected sorted best-first; the last element is
        always the weakest one to drop.
        """
        concepts = list(concepts)
        episodes = list(episodes) if episodes else []

        text = self.retriever.format_for_llm(
            activated=concepts, direct_episodes=episodes, as_of=as_of_dt,
        )
        while len(text) > max_chars and (concepts or episodes):
            drop_concept = bool(concepts) and (
                not episodes or concepts[-1].activation <= episodes[-1].score
            )
            if drop_concept:
                concepts.pop()
            else:
                episodes.pop()
            text = self.retriever.format_for_llm(
                activated=concepts, direct_episodes=episodes, as_of=as_of_dt,
            )
        return text

    def _load_recall_count(self) -> int:
        raw = self.store.get_metadata("recall_count")
        return int(raw) if raw else 0

    def _increment_recall_count(self) -> None:
        self._recall_count += 1
        self.store.set_metadata("recall_count", str(self._recall_count))

    def _maybe_decay(self, concepts: list[ActivatedConcept]) -> None:
        if not self.decay_config.enabled:
            return
        
        if self._recall_count % self.decay_config.decay_interval != 0:
            return
        
        decayed = self.store.decay_concepts(
            decay_rate=self.decay_config.decay_rate,
            skip_recently_accessed_seconds=60,
        )
        if decayed > 0:
            logger.info(f"Decayed {decayed} concepts (recall #{self._recall_count})")

    async def embed_episodes(self, batch_size: int = 50) -> int:
        """Backfill embeddings for episodes that don't have them yet."""
        if not self.embedding:
            logger.warning("No embedding provider configured, cannot embed episodes")
            return 0

        all_episodes = self.store.get_recent_episodes(limit=100000)
        unembedded = [ep for ep in all_episodes if ep.embedding is None]

        if not unembedded:
            return 0

        total_embedded = 0
        for i in range(0, len(unembedded), batch_size):
            batch = unembedded[i:i + batch_size]
            texts = [ep.content for ep in batch]
            try:
                embeddings = await self.embedding.embed_batch(texts)
            except Exception as e:
                logger.error(f"Failed to embed batch: {e}")
                continue

            for ep, emb in zip(batch, embeddings):
                ep.embedding = emb
                self.store.update_episode(ep)
                total_embedded += 1

        logger.info(f"Embedded {total_embedded} episodes")
        return total_embedded

    async def get_reembed_plan(
        self,
        include_episodes: bool = True,
        include_concepts: bool = True,
        include_entities: bool = True,
    ) -> dict[str, Optional[int]]:
        """Inspect what a re-embedding run would do."""
        if not include_episodes and not include_concepts and not include_entities:
            raise ValueError("Select at least one target: episodes, concepts, or entities.")
        if not self.embedding:
            raise RuntimeError("No embedding provider configured.")

        episodes = self.store.get_all_episodes() if include_episodes else []
        concepts = self.store.get_all_concepts() if include_concepts else []
        entities = self.store.get_all_entities() if include_entities else []

        stored_dims_raw = self.store.get_metadata("embedding_dimensions")
        stored_dims = int(stored_dims_raw) if stored_dims_raw else None

        sample_text = None
        if include_episodes and episodes:
            sample_text = episodes[0].content
        elif include_concepts and concepts:
            sample_text = concepts[0].summary
        elif include_entities and entities:
            sample_text = f"{entities[0].type.value}: {entities[0].display_name}"

        target_dims = None
        if sample_text:
            target_dims = len(await self.embedding.embed(sample_text))
        elif getattr(self.embedding, "dimensions", None):
            target_dims = int(self.embedding.dimensions)

        return {
            "episodes": len(episodes),
            "concepts": len(concepts),
            "entities": len(entities),
            "stored_dimensions": stored_dims,
            "target_dimensions": target_dims,
        }

    async def reembed(
        self,
        include_episodes: bool = True,
        include_concepts: bool = True,
        include_entities: bool = True,
        batch_size: int = 50,
    ) -> dict[str, Optional[int]]:
        """Recompute embeddings for selected record types using current provider."""
        plan = await self.get_reembed_plan(
            include_episodes=include_episodes,
            include_concepts=include_concepts,
            include_entities=include_entities,
        )
        stored_dims = plan["stored_dimensions"]
        target_dims = plan["target_dimensions"]

        if (
            stored_dims is not None
            and target_dims is not None
            and stored_dims != target_dims
            and not (include_episodes and include_concepts and include_entities)
        ):
            raise ValueError(
                "Embedding dimensions are changing. Re-embedding only one type "
                "can leave mixed dimensions. Re-run with --all."
            )

        clear_stats = self.store.clear_embeddings(
            include_episodes=include_episodes,
            include_concepts=include_concepts,
            include_entities=include_entities,
        )

        concepts_embedded = 0
        episodes_embedded = 0
        entities_embedded = 0

        if include_concepts:
            concepts = self.store.get_all_concepts()
            for i in range(0, len(concepts), batch_size):
                batch = concepts[i:i + batch_size]
                summaries = [c.summary for c in batch]
                embeddings = await self.embedding.embed_batch(summaries)
                for concept, embedding in zip(batch, embeddings):
                    concept.embedding = embedding
                    self.store.update_concept(concept)
                    concepts_embedded += 1

        if include_episodes:
            episodes = self.store.get_all_episodes()
            for i in range(0, len(episodes), batch_size):
                batch = episodes[i:i + batch_size]
                contents = [ep.content for ep in batch]
                embeddings = await self.embedding.embed_batch(contents)
                for episode, embedding in zip(batch, embeddings):
                    episode.embedding = embedding
                    self.store.update_episode(episode)
                    episodes_embedded += 1

        if include_entities:
            entities = self.store.get_all_entities()
            for i in range(0, len(entities), batch_size):
                batch = entities[i:i + batch_size]
                texts = [f"{e.type.value}: {e.display_name}" for e in batch]
                embeddings = await self.embedding.embed_batch(texts)
                for entity, embedding in zip(batch, embeddings):
                    entity.embedding = embedding
                    self.store.update_entity(entity)
                    entities_embedded += 1

        logger.info(
            "Re-embedded memory (concepts=%s, episodes=%s, entities=%s, dims=%s->%s)",
            concepts_embedded,
            episodes_embedded,
            entities_embedded,
            stored_dims,
            target_dims,
        )

        return {
            "concepts_embedded": concepts_embedded,
            "episodes_embedded": episodes_embedded,
            "entities_embedded": entities_embedded,
            "concepts_cleared": clear_stats["concepts_cleared"],
            "episodes_cleared": clear_stats["episodes_cleared"],
            "entities_cleared": clear_stats["entities_cleared"],
            "stored_dimensions": stored_dims,
            "target_dimensions": target_dims,
        }

    # Label operations

    def get_labels(self, subject_type: str, subject_id: str) -> dict[str, list[str]]:
        """Get all labels on an episode, concept, or fact."""
        if subject_type == "episode":
            obj = self.store.get_episode(subject_id)
            return dict(obj.labels) if obj else {}
        if subject_type == "concept":
            obj = self.store.get_concept(subject_id)
            return dict(obj.labels) if obj else {}
        return self.store.get_labels(subject_type, subject_id)

    def add_label(self, subject_type: str, subject_id: str, key: str, value: str) -> bool:
        """Add a key=value label to an episode, concept, or fact.

        Returns False if the subject does not exist (episode/concept only;
        fact labels are stored independently of the fact row).
        """
        if subject_type in ("episode", "concept"):
            obj = (
                self.store.get_episode(subject_id)
                if subject_type == "episode"
                else self.store.get_concept(subject_id)
            )
            if not obj:
                return False
            values = obj.labels.setdefault(key, [])
            if value not in values:
                values.append(value)
                if subject_type == "episode":
                    self.store.update_episode(obj)
                else:
                    self.store.update_concept(obj)
            return True
        self.store.add_label(subject_type, subject_id, key, value)
        return True

    def remove_label(
        self, subject_type: str, subject_id: str, key: str, value: Optional[str] = None
    ) -> bool:
        """Remove a label (or all values for *key* if *value* is None)."""
        if subject_type in ("episode", "concept"):
            obj = (
                self.store.get_episode(subject_id)
                if subject_type == "episode"
                else self.store.get_concept(subject_id)
            )
            if not obj or key not in obj.labels:
                return False
            if value is None:
                obj.labels.pop(key, None)
            else:
                remaining = [v for v in obj.labels[key] if v != value]
                if remaining:
                    obj.labels[key] = remaining
                else:
                    obj.labels.pop(key, None)
            if subject_type == "episode":
                self.store.update_episode(obj)
            else:
                self.store.update_concept(obj)
            return True
        return self.store.remove_label(subject_type, subject_id, key, value) > 0

    def list_labels(self, subject_type: Optional[str] = None) -> list[dict]:
        """List distinct key/value labels currently in use, with counts."""
        return self.store.get_distinct_labels(subject_type)

    # Conflict operations

    def list_conflicts(
        self,
        status: str = "open",
        kind: Optional[str] = None,
        concept_id: Optional[str] = None,
    ) -> list[Conflict]:
        """List conflicts. Default filters to open conflicts only."""
        return self.store.get_conflicts(status=status, kind=kind, concept_id=concept_id)

    def get_conflict(self, id: str) -> Optional[Conflict]:
        return self.store.get_conflict(id)

    async def resolve_conflict(
        self,
        conflict_id: str,
        winning_fact_id: str,
        note: Optional[str] = None,
        resolved_by: Optional[str] = None,
    ) -> Optional[Conflict]:
        """Resolve a fact conflict by picking a winner."""
        conflict = self.store.get_conflict(conflict_id)
        if not conflict:
            return None
        if conflict.status != "open":
            return conflict

        # Validate winning_fact_id is one of the facts in the conflict
        valid_fact_ids = {conflict.fact_a_id, conflict.fact_b_id}
        if winning_fact_id not in valid_fact_ids:
            raise ValueError(f"winning_fact_id must be one of {valid_fact_ids}, got '{winning_fact_id}'")

        losing_fact_id = (
            conflict.fact_b_id
            if winning_fact_id == conflict.fact_a_id
            else conflict.fact_a_id
        )

        if losing_fact_id:
            self.store.supersede_fact(losing_fact_id, winning_fact_id)

        conflict.status = "resolved"
        conflict.resolved_at = datetime.now()
        conflict.resolved_by = resolved_by
        conflict.resolution_note = note
        conflict.winning_fact_id = winning_fact_id
        self.store.update_conflict(conflict)

        # Record decision as an episode
        winner = self.store.get_fact(winning_fact_id)
        loser = self.store.get_fact(losing_fact_id) if losing_fact_id else None
        decision_content = f"Resolved conflict: chose '{winner.statement if winner else winning_fact_id}'"
        if loser:
            decision_content += f" over '{loser.statement}'"
        if note:
            decision_content += f" ({note})"

        await self.remember(
            decision_content,
            episode_type="decision",
            asserted_by=resolved_by,
        )

        # Refresh concept specifics if it's a fact cluster
        for cid in (conflict.concept_ids or []):
            concept = self.store.get_concept(cid)
            if concept and concept.concept_type in ("fact_cluster", "fact"):
                facts = self.store.get_facts(cluster_id=concept.id, active_only=True)
                concept.specifics = [f.statement for f in facts]
                concept.conflicts = []  # Clear conflicts from cluster
                self.store.update_concept(concept)

        return conflict

    def dismiss_conflict(
        self,
        conflict_id: str,
        note: Optional[str] = None,
        dismissed_by: Optional[str] = None,
    ) -> Optional[Conflict]:
        """Dismiss a conflict (both facts stay active)."""
        conflict = self.store.get_conflict(conflict_id)
        if not conflict:
            return None
        if conflict.status != "open":
            return conflict

        conflict.status = "dismissed"
        conflict.resolved_at = datetime.now()
        conflict.resolved_by = dismissed_by
        conflict.resolution_note = note
        self.store.update_conflict(conflict)

        # Clear conflicts from affected clusters
        for cid in (conflict.concept_ids or []):
            concept = self.store.get_concept(cid)
            if concept and concept.concept_type in ("fact_cluster", "fact"):
                concept.conflicts = []
                self.store.update_concept(concept)

        return conflict

    # CRUD operations

    def get_concept(self, id: str) -> Optional[Concept]:
        return self.store.get_concept(id)

    def get_all_concepts(self) -> list[Concept]:
        return self.store.get_all_concepts()

    def get_recent_episodes(self, limit: int = 100) -> list[Episode]:
        return self.store.get_recent_episodes(limit=limit)

    def get_episodes_by_type(self, episode_type: str) -> list[Episode]:
        return self.store.get_episodes_by_type(episode_type)

    def get_all_episodes(self) -> list[Episode]:
        return self.store.get_all_episodes()

    def get_episode(self, id: str) -> Optional[Episode]:
        return self.store.get_episode(id)

    def update_episode(
        self,
        id: str,
        content: Optional[str] = None,
        metadata: Optional[dict] = None,
        labels: Optional[dict[str, str | list[str]]] = None,
    ) -> Optional[Episode]:
        episode = self.store.get_episode(id)
        if not episode:
            return None

        if content is not None and content != episode.content:
            episode.content = content
            episode.embedding = None  # Clear embedding to re-embed

        if metadata is not None:
            episode.metadata = metadata

        if labels is not None:
            episode.labels = normalize_labels(labels)

        episode.updated_at = datetime.now()
        self.store.update_episode(episode)
        return episode

    def delete_episode(self, id: str) -> bool:
        return self.store.delete_episode(id)

    def restore_episode(self, id: str) -> bool:
        return self.store.restore_episode(id)

    def purge_episode(self, id: str) -> bool:
        return self.store.purge_episode(id)

    def get_deleted_episodes(self, limit: int = 100) -> list[Episode]:
        return self.store.get_deleted_episodes(limit=limit)

    def update_concept(
        self,
        id: str,
        summary: Optional[str] = None,
        title: Optional[str] = None,
        confidence: Optional[float] = None,
        tags: Optional[list[str]] = None,
        relations: Optional[list[dict]] = None,
        labels: Optional[dict[str, str | list[str]]] = None,
    ) -> Optional[Concept]:
        concept = self.store.get_concept(id)
        if not concept:
            return None

        if summary is not None and summary != concept.summary:
            concept.summary = summary
            concept.embedding = None  # Clear embedding to re-embed

        if title is not None:
            concept.title = title

        if confidence is not None:
            concept.confidence = max(0.0, min(1.0, confidence))

        if tags is not None:
            concept.tags = tags

        if relations is not None:
            new_relations = []
            for rel_dict in relations:
                rel_type_str = rel_dict.get("type", "related_to")
                try:
                    rel_type = RelationType(rel_type_str)
                except ValueError:
                    rel_type = RelationType.RELATED_TO
                new_relations.append(Relation(
                    type=rel_type,
                    target_id=rel_dict.get("target_id", ""),
                    strength=float(rel_dict.get("strength", 0.5)),
                    context=rel_dict.get("context"),
                ))
            concept.relations = new_relations

        if labels is not None:
            concept.labels = normalize_labels(labels)

        concept.updated_at = datetime.now()
        self.store.update_concept(concept)
        return concept

    def delete_concept(self, id: str) -> bool:
        return self.store.delete_concept(id)

    def restore_concept(self, id: str) -> bool:
        return self.store.restore_concept(id)

    def purge_concept(self, id: str) -> bool:
        return self.store.purge_concept(id)

    def get_deleted_concepts(self, limit: int = 100) -> list[Concept]:
        return self.store.get_deleted_concepts(limit=limit)

    # Entity operations

    def get_entity(self, id: str) -> Optional[Entity]:
        return self.store.get_entity(id)

    def get_all_entities(self) -> list[Entity]:
        return self.store.get_all_entities()

    def get_episodes_mentioning(self, entity_id: str, limit: int = 100) -> list[Episode]:
        return self.store.get_episodes_mentioning(entity_id, limit=limit)

    def get_entity_mention_counts(self) -> list[tuple[Entity, int]]:
        return self.store.get_entity_mention_counts()

    # Stats and export

    def get_stats(self) -> dict:
        stats = self.store.get_stats()
        stats["decay_enabled"] = self.decay_config.enabled
        stats["recall_count"] = self._recall_count
        stats["next_decay_at"] = (
            (self._recall_count // self.decay_config.decay_interval + 1)
            * self.decay_config.decay_interval
            if self.decay_config.enabled
            else None
        )
        return stats

    def export_memory(self) -> dict:
        return self.store.export_data()

    def import_memory(self, data: dict) -> dict:
        result = self.store.import_data(data)
        logger.info(f"Imported {result['concepts_imported']} concepts, {result['episodes_imported']} episodes")
        return result

    # Context manager support

    async def aclose(self) -> None:
        """Close underlying provider HTTP clients."""
        await self.embedding.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclose()


def create_memory(
    embedding_provider: Optional[str] = None,
    db_path: str = "memory",
    db_url: Optional[str] = None,
    project_dir: Optional[Path] = None,
    **kwargs,
) -> MemoryInterface:
    """
    Factory function to create a MemoryInterface with sensible defaults.

    Args:
        embedding_provider: "local" (default), "openai", "azure_openai", or "ollama"
        db_path: Database name (stored in ~/.remind/). Ignored when db_url is set.
        db_url: Full SQLAlchemy database URL (e.g. "postgresql+psycopg://...").
        project_dir: Optional project directory for loading project-local config
        **kwargs: Additional arguments passed to MemoryInterface

    Returns:
        Configured MemoryInterface
    """
    import os
    from remind.config import load_config, resolve_db_url, _is_db_url

    config = load_config(project_dir=project_dir)

    # Resolve database URL: explicit arg > config > resolve from db_path
    if not db_url:
        db_url = config.db_url
    if not db_url:
        if _is_db_url(db_path):
            db_url = db_path
        elif os.path.isabs(db_path):
            db_url = f"sqlite:///{db_path}"
        else:
            db_url = resolve_db_url(db_path)

    if config.logging_enabled:
        setup_file_logging(db_url, project_dir=project_dir)

    # Use config values if not explicitly provided
    embedding_provider = embedding_provider or config.embedding_provider

    # Apply config defaults for kwargs if not provided
    if "decay_config" not in kwargs:
        kwargs["decay_config"] = config.decay
    if "episode_types" not in kwargs:
        kwargs["episode_types"] = config.episode_types
    if "hybrid_keyword_weight" not in kwargs:
        kwargs["hybrid_keyword_weight"] = config.hybrid_keyword_weight
    else:
        kwargs["hybrid_keyword_weight"] = float(kwargs["hybrid_keyword_weight"])
    if "recall_initial_candidates" not in kwargs:
        kwargs["recall_initial_candidates"] = config.recall_initial_candidates
    if "lexical_enabled" not in kwargs:
        kwargs["lexical_enabled"] = config.lexical_enabled
    if "rrf_k" not in kwargs:
        kwargs["rrf_k"] = config.rrf_k
    if "recall_max_chars" not in kwargs:
        kwargs["recall_max_chars"] = config.recall_max_chars
    if "recall_min_score" not in kwargs:
        kwargs["recall_min_score"] = config.recall_min_score
    if "recall_timeout_ms" not in kwargs:
        kwargs["recall_timeout_ms"] = config.recall_timeout_ms
    if "reranking_enabled" not in kwargs:
        kwargs["reranking_enabled"] = config.reranking_enabled
    if "reranking_model" not in kwargs:
        kwargs["reranking_model"] = config.reranking_model
    if "fact_cluster_jaccard_threshold" not in kwargs:
        kwargs["fact_cluster_jaccard_threshold"] = config.fact_cluster_jaccard_threshold
    if "fact_related_similarity_threshold" not in kwargs:
        kwargs["fact_related_similarity_threshold"] = config.fact_related_similarity_threshold
    if "fact_related_max_results" not in kwargs:
        kwargs["fact_related_max_results"] = config.fact_related_max_results
    if "fact_collision_max_results" not in kwargs:
        kwargs["fact_collision_max_results"] = config.fact_collision_max_results
    if "remember_nearby_k" not in kwargs:
        kwargs["remember_nearby_k"] = config.remember_nearby_k

    # Create embedding provider with config values
    if embedding_provider == "local":
        from remind.providers.local import LocalEmbedding
        embedding = LocalEmbedding(
            model=config.local.embedding_model,
        )
    elif embedding_provider == "openai":
        from remind.providers.openai import OpenAIEmbedding
        embedding = OpenAIEmbedding(
            model=config.openai.embedding_model,
            api_key=config.openai.api_key,
            base_url=config.openai.base_url,
            dimensions=config.openai.embedding_size,
        )
    elif embedding_provider == "azure_openai":
        from remind.providers.azure_openai import AzureOpenAIEmbedding
        embedding = AzureOpenAIEmbedding(
            api_key=config.azure_openai.api_key,
            base_url=config.azure_openai.base_url,
            deployment_name=config.azure_openai.embedding_deployment_name,
            dimensions=config.azure_openai.embedding_size,
        )
    elif embedding_provider == "ollama":
        from remind.providers.ollama import OllamaEmbedding
        embedding = OllamaEmbedding(
            model=config.ollama.embedding_model,
            base_url=config.ollama.url,
        )
    else:
        raise ValueError(f"Unknown embedding provider: {embedding_provider}. Choose from: local, openai, azure_openai, ollama")

    return MemoryInterface(
        embedding=embedding,
        db_url=db_url,
        **kwargs,
    )
