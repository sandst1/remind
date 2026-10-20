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
from copy import deepcopy

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
from remind.storage import open_store
from remind.results import RecallResult, BatchRememberResult, public_model
from remind.operations import revision_edit
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

    warnings: list[str] = field(default_factory=list)
    revisions: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"episode_id": self.episode_id, "fact_id": self.fact_id,
                "cluster_id": self.cluster_id, "cluster_created": self.cluster_created,
                "collisions": [public_model(f) for f in self.collisions],
                "related_facts": [public_model(f) for f in self.related_facts],
                "entity_resolutions": self.entity_resolutions, "warnings": self.warnings, "revisions": self.revisions,
                "nearby_episodes": [[public_model(item), score] for item, score in self.nearby_episodes],
                "nearby_concepts": [[public_model(item), score] for item, score in self.nearby_concepts]}

    @classmethod
    def from_dict(cls, data: dict) -> "RememberResult":
        value = dict(data)
        for key in ("collisions", "related_facts"):
            value[key] = [Fact.from_dict(item) for item in value.get(key, [])]
        for key, model in (("nearby_episodes", Episode), ("nearby_concepts", Concept)):
            value[key] = [(model.from_dict(item), score) for item, score in value.get(key, [])]
        return cls(**value)

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
        db_path: Optional[str] = None,
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
        source_root: Optional[Path] = None,
    ):
        self.source_root = source_root
        self.embedding = embedding
        if store:
            self.store = store
        elif db_url:
            self.store = open_store(db_url)
        else:
            from remind.config import resolve_db_url
            self.store = open_store(resolve_db_url(db_path, project_aware=db_path is None))
        
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
        self, content: str, metadata: Optional[dict] = None,
        episode_type: Optional[str] = None, entities: Optional[list[str]] = None,
        confidence: float = 1.0, embed: bool = True,
        labels: Optional[dict[str, str | list[str]]] = None,
        source_type: Optional[str] = None, asserted_by: Optional[str] = None,
        source_ref: Optional[str] = None, idempotency_key: Optional[str] = None,
    ) -> RememberResult:
        result = await self.remember_batch([dict(
            content=content, metadata=metadata, episode_type=episode_type,
            entities=entities, confidence=confidence, labels=labels,
            source_type=source_type, asserted_by=asserted_by, source_ref=source_ref,
        )], embed=embed, idempotency_key=idempotency_key)
        return result.results[0]

    async def remember_batch(
        self, items: list[dict], embed: bool = True, embed_batch_size: int = 100,
        idempotency_key: Optional[str] = None,
    ) -> BatchRememberResult:
        """Capture an entire batch atomically, with single-capture semantics."""
        from remind.results import BatchRememberResult
        from remind.operations import receipt, save_receipt
        request = {"operation": "remember_batch", "items": items, "embed": embed}
        cached = receipt(self.store, idempotency_key, request)
        if cached is not None:
            return BatchRememberResult([RememberResult.from_dict(r) for r in cached["results"]])
        if embed_batch_size < 1:
            raise ValueError("embed_batch_size must be positive")
        episodes = []
        warnings = []
        for item in items:
            if not isinstance(item.get("content"), str) or not item["content"].strip():
                raise ValueError("Capture requires nonempty content")
            episode = Episode(content=item["content"], metadata=deepcopy(item.get("metadata") or {}),
                              episode_type=item.get("episode_type") or "observation",
                              labels=normalize_labels(item.get("labels")),
                              confidence=max(0., min(1., item.get("confidence", 1.))),
                              source_type=(item.get("source_type") or "").strip().lower() or None,
                              asserted_by=(item.get("asserted_by") or "").strip() or None,
                              source_ref=(item.get("source_ref") or "").strip() or None)
            if self.source_root is not None:
                from remind.provenance import capture_sources
                episode.metadata["source_refs"] = capture_sources(self.source_root, item.get("entities") or [])
            episodes.append(episode)
        if embed and self.embedding:
            for offset in range(0, len(episodes), embed_batch_size):
                batch = episodes[offset:offset + embed_batch_size]
                try:
                    vectors = await self.embedding.embed_batch([e.content for e in batch])
                    if len(vectors) != len(batch):
                        raise ValueError("Embedding provider returned an incomplete batch")
                    for episode, vector in zip(batch, vectors):
                        episode.embedding = vector
                except Exception as exc:
                    warnings.append(f"Missing embeddings: {exc}")
        import json
        first = next((e.embedding for e in episodes if e.embedding), None)
        fingerprint = json.dumps({"provider": self.embedding.name, "dimensions": len(first) if first else self.embedding.dimensions,
                                  "input_version": 1}, sort_keys=True)
        existing_fingerprint = self.store.get_metadata("embedding_fingerprint")
        old_dims = self.store.get_metadata("embedding_dimensions")
        if first is not None and ((existing_fingerprint and existing_fingerprint != fingerprint)
                                  or (old_dims and int(old_dims) != len(first))):
            for episode in episodes:
                episode.embedding = None
            warnings.append("Embedding model changed; run re-embed --all. Capture stored without embeddings.")
            first = None
        if first is not None:
            self.store._ensure_vec_dimensions(first)
        results = []
        with self.store.transaction():
            cached = receipt(self.store, idempotency_key, request)
            if cached is not None:
                return BatchRememberResult([RememberResult.from_dict(r) for r in cached["results"]])
            if first is not None:
                self.store.set_metadata("embedding_fingerprint", fingerprint)
            for episode, item in zip(episodes, items):
                resolutions = []
                for raw in item.get("entities") or []:
                    canonical = self._resolve_entity_id(raw)
                    episode.entity_ids.append(canonical)
                    if raw.split(":", 1)[0] != canonical.split(":", 1)[0]:
                        resolutions.append(f"{raw} → {canonical}")
                self.store.add_episode(episode)
                for entity_id in episode.entity_ids:
                    self.store.add_mention(episode.id, entity_id)
                self.store.emit_event("remembered", "episode", episode.id)
                result = RememberResult(episode_id=episode.id, warnings=list(warnings),
                                        entity_resolutions=resolutions)
                if episode.episode_type == "fact":
                    fact = create_fact_from_episode(self.store, episode, embedding=episode.embedding,
                        jaccard_threshold=self.fact_cluster_jaccard_threshold,
                        related_similarity_threshold=self.fact_related_similarity_threshold,
                        related_max_results=self.fact_related_max_results,
                        collision_max_results=self.fact_collision_max_results)
                    result.fact_id, result.cluster_id = fact.fact_id, fact.cluster_id
                    result.cluster_created = fact.cluster_created
                    result.collisions, result.related_facts = fact.collisions, fact.related_facts
                    self.store.emit_event("remembered", "fact", fact.fact_id)
                if episode.embedding and self.remember_nearby_k:
                    result.nearby_episodes = [(e, score) for e, score in
                        self.store.find_episodes_by_embedding(episode.embedding, k=self.remember_nearby_k + 1)
                        if e.id != episode.id][:self.remember_nearby_k]
                    result.nearby_concepts = self.store.find_by_embedding(episode.embedding, k=self.remember_nearby_k)
                from remind.operations import record_revision
                result.revisions = {identifier: record_revision(self.store, identifier) for identifier in
                                    (result.episode_id, result.fact_id, result.cluster_id) if identifier}
                results.append(result)
            response = BatchRememberResult(results)
            save_receipt(self.store, idempotency_key, request, response.to_dict())
        self._episode_buffer.extend(e.id for e in episodes)
        return response

    async def recall(
        self, query: Optional[str] = None, k: Optional[int] = None,
        context: Optional[str] = None, entity: Optional[str] = None, raw: bool = False,
        episode_k: Optional[int] = None, labels: Optional[dict[str, str]] = None,
        as_of: Optional[Union[datetime, str]] = None, max_chars: Optional[int] = None,
        min_score: Optional[float] = None, timeout_ms: Optional[int] = None,
        track_usage: bool = False, explain: bool = False,
    ) -> RecallResult | list[ActivatedConcept] | list[Episode]:
        """Retrieve consistently; ordinary reads never update usage statistics."""
        request = dict(query=query, k=k, context=context, entity=entity, raw=raw,
                       episode_k=episode_k, labels=labels, as_of=as_of, max_chars=max_chars,
                       min_score=min_score, timeout_ms=timeout_ms, explain=explain)
        if not hasattr(self.store, "read_snapshot"):
            return await self._recall(**request, track_usage=track_usage)
        import copy
        with self.store.read_snapshot() as snapshot:
            view = copy.copy(self)
            view.store = snapshot
            view.retriever = copy.copy(self.retriever)
            view.retriever.store = snapshot
            result = await view._recall(**request)
        if track_usage:
            self._increment_recall_count()
            concepts = result.concepts if isinstance(result, RecallResult) else result
            if concepts and isinstance(concepts[0], ActivatedConcept) and self.decay_config.enabled:
                self._maybe_decay(concepts)
                self.retriever.rejuvenate(concepts)
        return result

    async def _recall(
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
        track_usage: bool = False,
        explain: bool = False,
    ) -> RecallResult | list[ActivatedConcept] | list[Episode]:
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

        import copy
        retriever = copy.copy(self.retriever)
        from remind.scope import FilteredStore
        retriever.store = FilteredStore(self.store, labels or {}, as_of_dt)
        # Entity-based recall mode
        if entity:
            existing = self.store.find_entity_by_name(Entity.parse_id(entity)[1])
            canonical = existing.id if existing else entity
            episodes = retriever.store.get_episodes_mentioning(canonical, limit=k)
            
            if raw:
                return episodes
            
            from remind.provenance import freshness
            from remind.operations import record_revision
            warnings = []
            for episode in episodes:
                episode._revision = record_revision(self.store, episode.id)
                warnings.extend(f"Source {s['status']}: {s['path']}" for s in
                                freshness(self.source_root, episode.metadata.get("source_refs", []))
                                if s["status"] != "unchanged")
            text = retriever.format_entity_context(entity, episodes)
            if warnings:
                text += "\n" + "\n".join(warnings)
            return RecallResult(text, episodes=episodes, warnings=warnings)
        
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

        concepts, episodes = await retriever.retrieve_all(query, **retrieve_kwargs)
        fact_sources = {f.source_episode_id: f for f in self.store.get_all_facts()}
        def temporally_eligible(item):
            episode = getattr(item, "episode", item)
            fact = fact_sources.get(episode.id)
            if fact is None:
                return True
            if as_of_dt is None:
                return fact.is_active
            when = as_of_dt.replace(tzinfo=None)
            return fact.valid_from.replace(tzinfo=None) <= when and (fact.valid_to is None or when < fact.valid_to.replace(tzinfo=None))
        episodes = [e for e in episodes or [] if temporally_eligible(e)]

        if min_score is not None and episodes:
            episodes = [e for e in episodes if e.score >= min_score]

        if track_usage:
            self._increment_recall_count()
        
        if track_usage and self.decay_config.enabled:
            self._maybe_decay(concepts)
            # Rejuvenate accessed concepts (update access count/time)
            if hasattr(self.retriever, 'rejuvenate'):
                self.retriever.rejuvenate(concepts)
        
        if raw:
            return concepts
        
        from remind.provenance import freshness
        source_status = []
        source_episodes = {getattr(e, "episode", e).id: getattr(e, "episode", e) for e in episodes or []}
        for concept in concepts:
            identifiers = list(concept.concept.source_episodes)
            if concept.concept.concept_type in {"fact", "fact_cluster"}:
                identifiers.extend(f.source_episode_id for f in retriever.store.get_facts(cluster_id=concept.concept.id) if f.source_episode_id)
            for episode in retriever.store.get_episodes_batch(identifiers):
                source_episodes[episode.id] = episode
        for episode in source_episodes.values():
            source_status.extend(freshness(self.source_root, episode.metadata.get("source_refs", [])))
        warnings = [f"Source {item['status']}: {item['path']}" for item in source_status
                    if item["status"] != "unchanged"]
        if getattr(retriever, "_last_trace", {}).get("lexical_only"):
            warnings.append("Semantic search unavailable or incompatible; using lexical recall. Run doctor and re-embed --all.")
        # Render with the same constrained store used for retrieval.
        rendered_concepts, rendered_episodes = list(concepts), list(episodes or [])
        text = retriever.format_for_llm(activated=rendered_concepts, direct_episodes=rendered_episodes, as_of=as_of_dt)
        while max_chars is not None and len(text) > max_chars and (rendered_concepts or rendered_episodes):
            if rendered_episodes and (not rendered_concepts or rendered_episodes[-1].score <= rendered_concepts[-1].activation):
                rendered_episodes.pop()
            else:
                rendered_concepts.pop()
            text = retriever.format_for_llm(activated=rendered_concepts, direct_episodes=rendered_episodes, as_of=as_of_dt)
        if warnings:
            text += "\n" + "\n".join(warnings)
        explanation = {**getattr(retriever, "_last_trace", {}), "labels": labels or {}, "sources": source_status,
                       "ranking": [{"id": c.concept.id, "score": c.activation, "channel": c.source, "hops": c.hops}
                                   for c in concepts],
                       "score_semantics": "Relative ranking; not confidence or probability"} if explain else {}
        from remind.operations import record_revision
        for item in rendered_concepts:
            item.concept._revision = record_revision(self.store, item.concept.id)
        for item in rendered_episodes:
            episode = getattr(item, "episode", item)
            episode._revision = record_revision(self.store, episode.id)
        return RecallResult(text, rendered_concepts, rendered_episodes, warnings, explanation)

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
        include_facts: bool = True,
    ) -> dict[str, Optional[int]]:
        """Inspect what a re-embedding run would do."""
        if not any((include_episodes, include_concepts, include_entities, include_facts)):
            raise ValueError("Select at least one target: episodes, concepts, entities, or facts.")
        if not self.embedding:
            raise RuntimeError("No embedding provider configured.")

        episodes = self.store.get_all_episodes() if include_episodes else []
        concepts = self.store.get_all_concepts() if include_concepts else []
        entities = self.store.get_all_entities() if include_entities else []
        facts = self.store.get_all_facts() if include_facts else []

        stored_dims_raw = self.store.get_metadata("embedding_dimensions")
        stored_dims = int(stored_dims_raw) if stored_dims_raw else None

        sample_text = None
        if include_episodes and episodes:
            sample_text = episodes[0].content
        elif include_concepts and concepts:
            sample_text = concepts[0].summary
        elif include_entities and entities:
            sample_text = f"{entities[0].type.value}: {entities[0].display_name}"
        elif include_facts and facts:
            sample_text = facts[0].statement

        target_dims = None
        if sample_text:
            target_dims = len(await self.embedding.embed(sample_text))
        elif getattr(self.embedding, "dimensions", None):
            target_dims = int(self.embedding.dimensions)

        return {
            "episodes": len(episodes),
            "concepts": len(concepts),
            "entities": len(entities),
            "facts": len(facts),
            "stored_dimensions": stored_dims,
            "target_dimensions": target_dims,
        }

    async def reembed(
        self,
        include_episodes: bool = True,
        include_concepts: bool = True,
        include_entities: bool = True,
        include_facts: bool = True,
        batch_size: int = 50,
    ) -> dict[str, Optional[int]]:
        """Recompute embeddings for selected record types using current provider."""
        plan = await self.get_reembed_plan(
            include_episodes=include_episodes,
            include_concepts=include_concepts,
            include_entities=include_entities,
            include_facts=include_facts,
        )
        stored_dims = plan["stored_dimensions"]
        target_dims = plan["target_dimensions"]

        if (
            stored_dims is not None
            and target_dims is not None
            and stored_dims != target_dims
            and not (
                include_episodes
                and include_concepts
                and include_entities
                and include_facts
            )
        ):
            raise ValueError(
                "Embedding dimensions are changing. Re-embedding only one type "
                "can leave mixed dimensions. Re-run with --all."
            )

        clear_stats = self.store.clear_embeddings(
            include_episodes=include_episodes,
            include_concepts=include_concepts,
            include_entities=include_entities,
            include_facts=include_facts,
        )

        concepts_embedded = 0
        episodes_embedded = 0
        entities_embedded = 0
        facts_embedded = 0

        if include_concepts:
            concepts = self.store.get_all_concepts()
            for i in range(0, len(concepts), batch_size):
                batch = concepts[i:i + batch_size]
                summaries = [c.summary for c in batch]
                embeddings = await self.embedding.embed_batch(summaries)
                if embeddings:
                    self.store._ensure_vec_dimensions(embeddings[0])
                    self.store._init_vector_tables()
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
                if embeddings:
                    self.store._ensure_vec_dimensions(embeddings[0])
                    self.store._init_vector_tables()
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
                if embeddings:
                    self.store._ensure_vec_dimensions(embeddings[0])
                    self.store._init_vector_tables()
                for entity, embedding in zip(batch, embeddings):
                    entity.embedding = embedding
                    self.store.update_entity(entity)
                    entities_embedded += 1

        if include_facts:
            facts = self.store.get_all_facts()
            for i in range(0, len(facts), batch_size):
                batch = facts[i:i + batch_size]
                statements = [fact.statement for fact in batch]
                embeddings = await self.embedding.embed_batch(statements)
                if embeddings:
                    self.store._ensure_vec_dimensions(embeddings[0])
                    self.store._init_vector_tables()
                for fact, embedding in zip(batch, embeddings):
                    fact.embedding = embedding
                    self.store.update_fact(fact)
                    facts_embedded += 1

        logger.info(
            "Re-embedded memory (concepts=%s, episodes=%s, entities=%s, facts=%s, dims=%s->%s)",
            concepts_embedded,
            episodes_embedded,
            entities_embedded,
            facts_embedded,
            stored_dims,
            target_dims,
        )

        import json
        self.store.set_metadata("embedding_fingerprint", json.dumps({"provider": self.embedding.name,
            "dimensions": self.embedding.dimensions, "input_version": 1}, sort_keys=True))
        return {
            "concepts_embedded": concepts_embedded,
            "episodes_embedded": episodes_embedded,
            "entities_embedded": entities_embedded,
            "facts_embedded": facts_embedded,
            "concepts_cleared": clear_stats["concepts_cleared"],
            "episodes_cleared": clear_stats["episodes_cleared"],
            "entities_cleared": clear_stats["entities_cleared"],
            "facts_cleared": clear_stats["facts_cleared"],
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
        self, conflict_id: str, winning_fact_id: str, note: Optional[str] = None,
        resolved_by: Optional[str] = None, expected_revision: Optional[str] = None,
    ) -> Optional[Conflict]:
        from remind.apply import ApplyEngine
        from remind.operations import RevisionConflict, record_revision
        if expected_revision is None:
            raise RevisionConflict(conflict_id, record_revision(self.store, conflict_id))
        result = await ApplyEngine(self.store, self.embedding).apply([{
            "op": "resolve", "id": conflict_id, "winner": winning_fact_id,
            "note": note, "by": resolved_by,
        }], expected_revisions={conflict_id: expected_revision})
        if not result.success:
            if result.errors[0].code == "revision_conflict":
                error = result.errors[0]
                raise RevisionConflict(error.subject_id, error.current_revision)
            raise ValueError(result.errors[0].message)
        return self.store.get_conflict(conflict_id)

    @revision_edit("conflict_dismissed")
    def dismiss_conflict(
        self,
        conflict_id: str,
        note: Optional[str] = None,
        dismissed_by: Optional[str] = None, expected_revision: Optional[str] = None) -> Optional[Conflict]:
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

    @revision_edit("updated")
    def update_episode(
        self,
        id: str,
        content: Optional[str] = None,
        metadata: Optional[dict] = None,
        labels: Optional[dict[str, str | list[str]]] = None,
        episode_type: Optional[str] = None,
        entities: Optional[list[str]] = None, expected_revision: Optional[str] = None) -> Optional[Episode]:
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

        if episode_type is not None:
            episode.episode_type = episode_type
        if entities is not None:
            episode.entity_ids = [self._resolve_entity_id(i) for i in entities]
            self.store.delete_mentions_for_episode(episode.id)
            for entity_id in episode.entity_ids:
                self.store.add_mention(episode.id, entity_id)
        episode.updated_at = datetime.now()
        self.store.update_episode(episode)
        return episode

    @revision_edit("deleted")
    def delete_episode(self, id: str, expected_revision: Optional[str] = None) -> bool:
        return self.store.delete_episode(id)

    @revision_edit("restored")
    def restore_episode(self, id: str, expected_revision: Optional[str] = None) -> bool:
        return self.store.restore_episode(id)

    @revision_edit("deleted")
    def purge_episode(self, id: str, expected_revision: Optional[str] = None) -> bool:
        return self.store.purge_episode(id)

    def get_deleted_episodes(self, limit: int = 100) -> list[Episode]:
        return self.store.get_deleted_episodes(limit=limit)

    @revision_edit("updated")
    def update_concept(
        self,
        id: str,
        summary: Optional[str] = None,
        title: Optional[str] = None,
        confidence: Optional[float] = None,
        tags: Optional[list[str]] = None,
        relations: Optional[list[dict]] = None,
        labels: Optional[dict[str, str | list[str]]] = None,
        conditions: Optional[str] = None,
        exceptions: Optional[list[str]] = None, expected_revision: Optional[str] = None) -> Optional[Concept]:
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

        if conditions is not None:
            concept.conditions = conditions
        if exceptions is not None:
            concept.exceptions = exceptions
        concept.updated_at = datetime.now()
        self.store.update_concept(concept)
        return concept

    @revision_edit("deleted")
    def delete_concept(self, id: str, expected_revision: Optional[str] = None) -> bool:
        return self.store.delete_concept(id)

    @revision_edit("restored")
    def restore_concept(self, id: str, expected_revision: Optional[str] = None) -> bool:
        return self.store.restore_concept(id)

    @revision_edit("deleted")
    def purge_concept(self, id: str, expected_revision: Optional[str] = None) -> bool:
        return self.store.purge_concept(id)

    def get_deleted_concepts(self, limit: int = 100) -> list[Concept]:
        return self.store.get_deleted_concepts(limit=limit)

    def purge_deleted(self, expected_revisions: dict[str, str]) -> dict[str, int]:
        """Purge the complete deleted set atomically against inspected revisions."""
        from remind.operations import check_revisions, RevisionConflict
        with self.store.transaction():
            episodes = self.store.get_deleted_episodes(limit=None)
            concepts = self.store.get_deleted_concepts(limit=None)
            for item in [*episodes, *concepts]:
                if item.id not in expected_revisions:
                    raise RevisionConflict(item.id, None)
            check_revisions(self.store, expected_revisions)
            counts = {"episodes_purged": 0, "concepts_purged": 0}
            for kind, items in (("episode", episodes), ("concept", concepts)):
                for item in items:
                    if getattr(self.store, f"purge_{kind}")(item.id):
                        counts[f"{kind}s_purged"] += 1
                        self.store.emit_event("deleted", kind, item.id, {"purged": True})
            return counts

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

    def export_memory(self, mode: str = "portable") -> dict:
        return self.store.export_data(mode=mode)

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
    db_path: Optional[str] = None,
    db_url: Optional[str] = None,
    project_dir: Optional[Path] = None,
    store_url: Optional[str] = None,
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

    if store_url and (db_url or db_path):
        raise ValueError("Use store_url or a legacy database selector, not both")
    db_url = store_url or db_url
    config = load_config(project_dir=project_dir)

    # Resolve database URL: explicit arg > config > resolve from db_path
    if not db_url:
        db_url = config.db_url
    if not db_url:
        if db_path is None:
            db_url = resolve_db_url(None, project_aware=True)
        elif _is_db_url(db_path):
            db_url = db_path
        elif os.path.isabs(db_path):
            db_url = resolve_db_url(db_path)
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
    if embedding_provider == "deterministic":
        from remind.providers.deterministic import DeterministicEmbedding
        embedding = DeterministicEmbedding()
    elif embedding_provider == "local":
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
        source_root=kwargs.pop("source_root", project_dir),
        **kwargs,
    )
