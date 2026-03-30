"""
MemoryInterface - The unified API for the memory system.

This is the main entry point for applications integrating Remind.
It provides a simple interface for:
- remember() - log experiences/interactions
- recall() - retrieve relevant concepts
"""

from datetime import datetime
from typing import Callable, Optional
from pathlib import Path
import asyncio
import logging
import json

from remind.models import (
    Episode, Concept, ConsolidationResult,
    Entity, EntityType, EpisodeType, TaskStatus, Relation, RelationType,
    normalize_entity_name,
)
from remind.store import MemoryStore, SQLAlchemyMemoryStore, SQLiteMemoryStore
from remind.providers.base import LLMProvider, EmbeddingProvider
from remind.consolidation import Consolidator
from remind.retrieval import MemoryRetriever, ActivatedConcept
from remind.extraction import EntityExtractor
from remind.config import load_config, DecayConfig, RemindConfig, setup_file_logging
from remind.triage import IngestionBuffer, IngestionTriager, TriageResult, split_text

logger = logging.getLogger(__name__)


class MemoryInterface:
    """
    The main interface to the memory system.
    
    Key Design:
    -----------
    - `remember()` is async - stores episodes and embeds them by default
    - `consolidate()` does all LLM work in two phases:
      1. Extract entities/types from unextracted episodes
      2. Generalize episodes into concepts (the "sleep" process)
    
    Consolidation Modes:
    -------------------
    1. **Automatic (threshold-based)**: Set `auto_consolidate=True` (default).
       Consolidation runs automatically after `consolidation_threshold` episodes.
    
    2. **Manual/Hook-based**: Set `auto_consolidate=False`.
       Call `consolidate()` or `end_session()` explicitly from your agent hooks.
    
    3. **Hybrid**: Keep `auto_consolidate=True` as a safety net, but also call
       `end_session()` at natural boundaries (end of conversation, task completion).
    
    Usage:
        memory = MemoryInterface(
            llm=AnthropicLLM(),
            embedding=OpenAIEmbedding(),
            auto_consolidate=True,       # Automatic after threshold
            consolidation_threshold=10,  # Episodes before auto-consolidate
        )
        
        # Log experiences (fast, no LLM call)
        await memory.remember("User prefers Python for backend development")
        await memory.remember("User mentioned they work on distributed systems")
        
        # Retrieve relevant context
        context = await memory.recall("What programming languages does the user like?")
        
        # Hook: Call at end of conversation/task for explicit consolidation
        await memory.end_session()
        
        # Or manually consolidate anytime (this is where LLM work happens)
        await memory.consolidate(force=True)
    """
    
    def __init__(
        self,
        llm: LLMProvider,
        embedding: EmbeddingProvider,
        store: Optional[MemoryStore] = None,
        db_url: Optional[str] = None,
        db_path: str = "memory.db",
        # Consolidation settings
        consolidation_threshold: int = 5,  # episodes before auto-consolidation
        consolidation_concepts_per_pass: int = 64,
        auto_consolidate: bool = True,
        # Retrieval settings
        default_recall_k: int = 3,
        default_episode_k: int = 5,
        spread_hops: int = 2,
        # Decay settings
        decay_config=None,
        # Auto-ingest settings
        ingest_buffer_size: int = 4000,
        ingest_min_density: float = 0.4,
        triage_llm: Optional[LLMProvider] = None,
        ingest_background: bool = True,
        # Configurable episode types
        episode_types: Optional[list[str]] = None,
    ):
        self.llm = llm
        self.embedding = embedding
        if store:
            self.store = store
        elif db_url:
            self.store = SQLAlchemyMemoryStore(db_url)
        else:
            self.store = SQLAlchemyMemoryStore(db_path)
        
        # Initialize components
        self.consolidator = Consolidator(
            llm=llm,
            embedding=embedding,
            store=self.store,
            concepts_per_consolidation_pass=consolidation_concepts_per_pass,
        )
        
        self.retriever = MemoryRetriever(
            embedding=embedding,
            store=self.store,
            spread_hops=spread_hops,
        )
        
        self.extractor = EntityExtractor(
            llm=llm,
            store=self.store,
            valid_types=episode_types,
        )
        
        # Auto-ingest components
        self._ingest_buffer = IngestionBuffer(threshold=ingest_buffer_size)
        self._triager = IngestionTriager(
            llm=triage_llm or llm,
            min_density=ingest_min_density,
            valid_types=episode_types,
        )
        self._ingest_background = ingest_background
        self._background_tasks: set[asyncio.Task] = set()
        self._ingest_semaphore = asyncio.Semaphore(2)
        
        # Settings
        self.consolidation_threshold = consolidation_threshold
        self.auto_consolidate = auto_consolidate
        self.default_recall_k = default_recall_k
        self.default_episode_k = default_episode_k
        
        # Decay settings
        self.decay_config = decay_config or DecayConfig()
        
        # Recall tracking for decay (persisted in metadata table)
        self._recall_count: int = self._load_recall_count()
        
        # Episode buffer for tracking (this session only)
        self._episode_buffer: list[str] = []
        self._last_consolidation: Optional[datetime] = None

    def _resolve_entity_id(self, raw_entity_id: str) -> str:
        """Resolve a raw entity ID to a canonical one, deduplicating by name.

        If an entity with the same display name already exists (regardless of
        type prefix), returns the existing entity's ID so that mentions
        accumulate on a single entity rather than creating duplicates like
        ``family:Capulet`` and ``character:Capulet``.

        If no match is found, creates a new entity and returns its ID.
        Entity IDs are always normalized to lowercase.
        """
        type_str, name = Entity.parse_id(raw_entity_id)
        existing = self.store.find_entity_by_name(name)
        if existing:
            return existing.id

        normalized_id = Entity.make_id(type_str, normalize_entity_name(name))
        if not self.store.get_entity(normalized_id):
            try:
                etype = EntityType(type_str)
            except ValueError:
                etype = EntityType.OTHER
            entity = Entity(id=normalized_id, type=etype, display_name=name)
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
        topic: Optional[str] = None,
        source_type: Optional[str] = None,
    ) -> str:
        """
        Log an experience/interaction to be consolidated later.

        Embeds the episode content by default for vector search during recall.
        Entity extraction and type classification happen during consolidate().

        Args:
            content: The interaction or experience to remember
            metadata: Optional metadata about the episode
            episode_type: Optional explicit type (observation, decision, question, meta, preference).
                          If not provided, will be auto-detected during consolidation.
            entities: Optional explicit list of entity IDs (e.g., ["file:src/auth.ts", "person:alice"]).
                      If not provided, will be auto-detected during consolidation.
            confidence: How certain this information is (0.0-1.0, default 1.0).
                        Lower values indicate uncertainty or weak signals.
            embed: Whether to generate an embedding for the episode (default True).
                   Set to False when batch-importing and planning to backfill later.
            topic: Primary knowledge area (e.g. "architecture", "product", "infra").
            source_type: Origin of this episode (e.g. "agent", "slack", "github", "manual").

        Returns:
            The episode ID
        """
        # Create episode
        episode = Episode(
            content=content,
            metadata=metadata or {},
            confidence=max(0.0, min(1.0, confidence)),  # Clamp to valid range
            topic=topic.lower().strip() if topic else None,
            source_type=source_type.lower().strip() if source_type else None,
        )
        
        # Apply explicit type/entities if provided
        if episode_type:
            episode.episode_type = episode_type.value if isinstance(episode_type, EpisodeType) else str(episode_type)
        
        if entities:
            episode.entities_extracted = True

        # Embed the episode content
        if embed and self.embedding:
            try:
                episode.embedding = await self.embedding.embed(content)
            except Exception as e:
                logger.warning(f"Failed to embed episode: {e}")
        
        # Store the episode
        episode_id = self.store.add_episode(episode)
        self._episode_buffer.append(episode_id)
        
        # Resolve and store explicitly provided entities (dedup by name)
        if entities:
            resolved_ids = []
            for raw_id in entities:
                canonical_id = self._resolve_entity_id(raw_id)
                resolved_ids.append(canonical_id)
                self.store.add_mention(episode_id, canonical_id)
            episode.entity_ids = resolved_ids
            self.store.update_episode(episode)
        
        logger.debug(f"Remembered episode {episode_id}: {content[:50]}...")
        
        return episode_id
    
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
        Much faster than calling remember() in a loop.

        Args:
            items: List of dicts, each with:
                - content (str, required)
                - metadata (dict, optional)
                - episode_type (EpisodeType, optional)
                - entities (list[str], optional)
                - confidence (float, optional, default 1.0)
            embed: Whether to generate embeddings (default True).
            embed_batch_size: Max texts per embedding API call (default 100).

        Returns:
            List of episode IDs in the same order as items.
        """
        if not items:
            return []

        episodes = []
        for item in items:
            episode = Episode(
                content=item["content"],
                metadata=item.get("metadata") or {},
                confidence=max(0.0, min(1.0, item.get("confidence", 1.0))),
            )
            if item.get("episode_type"):
                et = item["episode_type"]
                episode.episode_type = et.value if isinstance(et, EpisodeType) else str(et)
            if item.get("entities"):
                episode.entities_extracted = True
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
        topic: Optional[str] = None,
    ) -> str | list[ActivatedConcept] | list[Episode]:
        """
        Retrieve relevant memory for a query.
        
        Args:
            query: What to search for (required for semantic search, ignored for entity recall)
            k: Number of concepts to return
            context: Additional context for the search
            entity: If provided, retrieve by entity instead of semantic search
            raw: If True, return raw objects instead of formatted string
            episode_k: Number of episodes to retrieve via direct vector search.
                       Defaults to self.default_episode_k (5). Set to 0 to disable.
            topic: If set, restrict recall to this topic (cross-topic results
                   are penalized but not excluded).
            
        Returns:
            Formatted memory string for LLM injection, or raw objects if raw=True.
            When raw=True: list[ActivatedConcept] for concept-based,
            list[Episode] for entity-based.
        """
        if not entity and query is None:
            raise ValueError("Either query or entity must be provided")
        
        k = k or self.default_recall_k
        episode_k = episode_k if episode_k is not None else self.default_episode_k
        
        # Increment recall count and persist when decay is enabled
        self._recall_count += 1
        if self.decay_config.enabled:
            self._save_recall_count()
        
        # Entity-based retrieval
        if entity:
            type_str, name = Entity.parse_id(entity)
            entity = Entity.make_id(type_str, normalize_entity_name(name))
            episodes = await self.retriever.retrieve_by_entity(entity, limit=k * 4)
            # Trigger decay every N recalls (consistent with concept-based path)
            if self.decay_config.enabled and self._recall_count % self.decay_config.decay_interval == 0:
                self._trigger_decay()
            if raw:
                return episodes
            return self.retriever.format_entity_context(entity, episodes)
        
        # Concept-based retrieval (semantic)
        activated = await self.retriever.retrieve(
            query=query,
            k=k,
            context=context,
            topic=topic,
        )

        # Direct episode vector search
        direct_episodes = None
        if episode_k > 0:
            direct_episodes = await self.retriever.retrieve_episodes_by_embedding(
                query=query, k=episode_k
            )
        
        # Rejuvenation: reset decay for recalled concepts (only for concept-based)
        if activated and self.decay_config.enabled:
            self._rejuvenate_concepts(activated)
        
        # Trigger decay every N recalls
        if self.decay_config.enabled and self._recall_count % self.decay_config.decay_interval == 0:
            self._trigger_decay()
        
        if raw:
            return activated
        
        return self.retriever.format_for_llm(activated, direct_episodes=direct_episodes)
    
    async def consolidate(
        self,
        force: bool = False,
        on_batch_complete: Optional[Callable[[int, ConsolidationResult], None]] = None,
    ) -> ConsolidationResult:
        """
        Run memory consolidation manually.
        
        Processes unconsolidated episodes into generalized concepts.
        This is the "sleep" process where raw experiences become knowledge.
        
        Use this for:
        - Manual consolidation triggers
        - Agent hooks (task completion, scheduled jobs)
        - Forcing consolidation regardless of episode count
        
        Args:
            force: If True, consolidate even with few episodes (< 3)
            on_batch_complete: Optional callback(batch_num, batch_result) called
                after each batch completes, for progress reporting.
            
        Returns:
            ConsolidationResult with statistics
        """
        result = await self.consolidator.consolidate(
            force=force,
            on_batch_complete=on_batch_complete,
        )
        
        if result.episodes_processed > 0:
            self._last_consolidation = datetime.now()
            self._episode_buffer = []  # Clear buffer after successful consolidation
        
        return result
    
    async def embed_episodes(self, batch_size: int = 50) -> int:
        """
        Backfill embeddings for episodes that don't have them yet.

        Useful for vectorizing episodes in existing databases that were
        created before episode embedding was enabled.

        Args:
            batch_size: Number of episodes to embed per batch.

        Returns:
            Number of episodes embedded.
        """
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

    async def end_session(self) -> ConsolidationResult:
        """
        Hook for ending a session/conversation.
        
        Call this at natural boundaries in your agent:
        - End of a conversation
        - Task completion
        - Before shutting down
        - Scheduled maintenance
        
        This drains any in-flight background ingest tasks, flushes any
        pending ingestion buffer, and then triggers consolidation if there
        are pending episodes.
        
        Usage in agent hooks:
            async def on_conversation_end(self):
                await memory.end_session()
            
            async def on_task_complete(self, task):
                await memory.remember(f"Completed task: {task.summary}")
                await memory.end_session()
        
        Returns:
            ConsolidationResult with statistics
        """
        # Drain in-flight background ingest tasks first
        if self._background_tasks:
            logger.info(f"end_session: waiting for {len(self._background_tasks)} background ingest tasks")
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

        # Flush ingestion buffer (force foreground so we capture episodes)
        if not self._ingest_buffer.is_empty:
            logger.info("end_session: flushing ingestion buffer")
            was_bg = self._ingest_background
            self._ingest_background = False
            try:
                await self.flush_ingest()
            finally:
                self._ingest_background = was_bg
        
        pending = self.pending_episodes_count
        
        if pending == 0:
            logger.debug("end_session called but no pending episodes")
            return ConsolidationResult()
        
        logger.info(f"end_session: consolidating {pending} pending episodes")
        return await self.consolidate(force=True)
    
    async def ingest(self, content: str, source: str = "conversation") -> list[str]:
        """Ingest raw text for automatic memory curation.

        Text accumulates in an internal buffer. When the buffer exceeds
        the character threshold, it flushes and triggers triage (LLM-based
        density scoring + episode extraction). Triage and consolidation
        run in the background by default (controlled by ingest_background).

        This is separate from remember() -- explicit remember() calls bypass
        triage entirely. Auto-ingest is additive.

        Args:
            content: Raw text to ingest (conversation fragments, tool output, etc.)
            source: Source label for metadata (default: "conversation")

        Returns:
            List of episode IDs created (empty if buffer didn't flush,
            triage dropped everything, or processing is running in background).
        """
        chunk = self._ingest_buffer.add(content)
        if chunk is None:
            logger.debug(
                f"Ingested {len(content)} chars, buffer at {self._ingest_buffer.size} "
                f"(threshold: {self._ingest_buffer.threshold})"
            )
            return []

        if self._ingest_background:
            self._schedule_background_ingest(chunk, source)
            return []

        return await self._process_ingest_chunk(chunk, source)

    async def flush_ingest(self) -> list[str]:
        """Force-flush the ingestion buffer and process whatever is in it.

        Call at session end or when you want to ensure everything is processed.

        Returns:
            List of episode IDs created (empty if buffer was empty,
            triage dropped everything, or processing is running in background).
        """
        chunk = self._ingest_buffer.flush()
        if chunk is None:
            return []

        if self._ingest_background:
            self._schedule_background_ingest(chunk, source="flush")
            return []

        return await self._process_ingest_chunk(chunk, source="flush")

    def _schedule_background_ingest(self, chunk: str, source: str) -> None:
        """Schedule ingest processing as a background async task.

        Concurrency is capped by self._ingest_semaphore (default 2) so
        at most two chunks process simultaneously in-process.
        """
        async def _guarded():
            async with self._ingest_semaphore:
                return await self._process_ingest_chunk(chunk, source)

        task = asyncio.create_task(
            _guarded(),
            name=f"remind-ingest-{len(self._background_tasks)}",
        )
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        logger.info(
            f"Scheduled background ingest ({len(chunk)} chars, "
            f"{len(self._background_tasks)} tasks in flight)"
        )

    async def _process_ingest_chunk(self, chunk: str, source: str) -> list[str]:
        """Run triage on a chunk and store/consolidate resulting episodes.

        Large chunks are split into sub-chunks of at most
        ``self._ingest_buffer.threshold`` characters before triage so that
        each LLM call receives a reasonable amount of text.  Consolidation
        runs once at the end after all sub-chunks have been triaged.
        """
        sub_chunks = split_text(chunk, max_size=self._ingest_buffer.threshold)
        if not sub_chunks:
            return []

        all_episode_ids: list[str] = []

        for i, sub_chunk in enumerate(sub_chunks):
            ids = await self._triage_sub_chunk(sub_chunk, source, i, len(sub_chunks))
            all_episode_ids.extend(ids)

        # Single consolidation pass after all sub-chunks are processed
        if all_episode_ids:
            try:
                result = await self.consolidate(force=True)
                logger.info(
                    f"Post-ingest consolidation: {result.episodes_processed} episodes, "
                    f"{result.concepts_created} concepts created"
                )
            except Exception as e:
                logger.warning(f"Post-ingest consolidation failed: {e}")

        return all_episode_ids

    async def _triage_sub_chunk(
        self, chunk: str, source: str, chunk_index: int, total_chunks: int,
    ) -> list[str]:
        """Triage a single sub-chunk and store extracted episodes."""
        existing_concepts = ""
        try:
            activated = await self.recall(
                chunk[:500], k=5, raw=True,
            )
            if activated:
                lines = []
                for item in activated:
                    concept = item.concept if hasattr(item, 'concept') else item
                    if hasattr(concept, 'summary'):
                        lines.append(f"- {concept.summary}")
                if lines:
                    existing_concepts = "\n".join(lines)
        except Exception as e:
            logger.debug(f"Recall for triage context failed (ok for empty memory): {e}")

        triage_result = await self._triager.triage(chunk, existing_concepts)

        logger.info(
            f"Triage [{chunk_index + 1}/{total_chunks}]: "
            f"density={triage_result.density:.2f}, "
            f"episodes={len(triage_result.episodes)}, "
            f"reasoning={triage_result.reasoning}"
        )

        if not triage_result.episodes:
            return []

        episode_ids: list[str] = []
        for ep in triage_result.episodes:
            metadata = ep.metadata.copy() if ep.metadata else {}
            metadata["source"] = source
            metadata["triage_density"] = triage_result.density

            episode_id = await self.remember(
                content=ep.content,
                metadata=metadata,
                episode_type=ep.episode_type or "observation",
                entities=ep.entities if ep.entities else None,
            )
            episode_ids.append(episode_id)

        return episode_ids

    @property
    def ingest_buffer_size(self) -> int:
        """Current character count in the ingestion buffer."""
        return self._ingest_buffer.size

    @property
    def pending_episodes_count(self) -> int:
        """Number of episodes waiting to be consolidated."""
        return self.store.get_stats().get("unconsolidated_episodes", 0)
    
    @property
    def should_consolidate(self) -> bool:
        """
        Check if consolidation should run based on current state.
        
        Useful for agents that want to check before deciding to consolidate:
            if memory.should_consolidate:
                await memory.consolidate()
        """
        return self.pending_episodes_count >= self.consolidation_threshold
    
    def get_pending_episodes(self, limit: int = 50) -> list[Episode]:
        """
        Get episodes that are pending consolidation.
        
        Useful for:
        - Human review before consolidation
        - Debugging what will be consolidated
        - Custom filtering logic
        """
        return self.store.get_unconsolidated_episodes(limit=limit)
    
    def _load_recall_count(self) -> int:
        """Load recall count from persistent metadata storage."""
        value = self.store.get_metadata("recall_count")
        if value is None:
            return 0
        try:
            return int(value)
        except ValueError:
            logger.warning(f"Invalid recall_count in metadata: {value}, defaulting to 0")
            return 0
    
    def _save_recall_count(self) -> None:
        """Save recall count to persistent metadata storage."""
        self.store.set_metadata("recall_count", str(self._recall_count))
    
    def _trigger_decay(self) -> None:
        """
        Trigger decay process on concepts.
        
        Applies linear decay to all concepts and their related concepts.
        This is called automatically every N recalls (based on decay_interval).
        """
        logger.info(
            f"Triggering decay (recall #{self._recall_count}): "
            f"decay_rate={self.decay_config.decay_rate}"
        )
        
        decayed_count = self.store.decay_concepts(
            decay_rate=self.decay_config.decay_rate,
            skip_recently_accessed_seconds=60,
        )
        
        logger.info(f"Decay complete: {decayed_count} concepts affected")

    def _rejuvenate_concepts(self, activated: list[ActivatedConcept]) -> None:
        """
        Apply proportional rejuvenation to recalled concepts.
        
        When a concept is recalled, it gets a boost scaled by its activation score.
        Higher activation = larger boost (max 0.3), lower activation = smaller boost.
        This prevents barely-above-threshold concepts from getting the same boost as top results.
        
        Args:
            activated: List of ActivatedConcept objects that were just recalled
        """
        for ac in activated:
            concept = ac.concept
            # Scale boost by activation score (0.0-1.0)
            # Max boost is 0.3, scaled by how strongly the concept was activated
            activation_boost = 0.3 * ac.activation
            concept.decay_factor = min(1.0, concept.decay_factor + activation_boost)
            concept.access_count += 1
            concept.last_accessed = datetime.now()
            concept.updated_at = datetime.now()
            
            # Save updated concept back to store
            self.store.update_concept(concept)
            
            logger.debug(f"Rejuvenated concept {concept.id}: activation={ac.activation:.3f}, boost={activation_boost:.3f}, decay_factor={concept.decay_factor:.3f}, access_count={concept.access_count}, last_accessed={concept.last_accessed.isoformat()}")
    
    # Topic operations

    def list_topics(self) -> list[dict]:
        """List all topics with episode/concept counts and latest activity."""
        return self.store.list_topics()

    def get_topic_overview(self, topic: str, k: int = 5) -> list[Concept]:
        """Get top-k concepts for a topic, no query needed.

        Returns concepts ordered by confidence * instance_count.
        Useful for browsing/drill-down without a specific query.
        """
        return self.store.get_concepts_by_topic(topic)[:k]

    # Direct access methods
    
    def get_concept(self, concept_id: str) -> Optional[Concept]:
        """Get a concept by ID."""
        return self.store.get_concept(concept_id)
    
    def get_all_concepts(self) -> list[Concept]:
        """Get all concepts."""
        return self.store.get_all_concepts()
    
    def get_recent_episodes(self, limit: int = 10) -> list[Episode]:
        """Get recent episodes."""
        return self.store.get_recent_episodes(limit=limit)
    
    def get_episodes_by_type(self, episode_type: str, limit: int = 50) -> list[Episode]:
        """Get episodes of a specific type (decision, question, meta, etc.)."""
        return self.store.get_episodes_by_type(episode_type, limit=limit)

    # Episode update/delete operations

    def update_episode(
        self,
        episode_id: str,
        content: Optional[str] = None,
        episode_type: Optional[str] = None,
        entities: Optional[list[str]] = None,
        metadata: Optional[dict] = None,
        topic: Optional[str] = None,
    ) -> Optional[Episode]:
        """
        Update an existing episode.

        Only provided fields are updated; None values preserve existing data.
        If content is updated, resets consolidation flags so episode will be re-processed.
        Metadata is shallow-merged into existing metadata (not replaced).

        Args:
            episode_id: ID of the episode to update
            content: New content (if None, preserves existing)
            episode_type: New type (if None, preserves existing)
            entities: New entity list (if None, preserves existing)
            metadata: Metadata keys to merge in (if None, preserves existing)
            topic: New topic (if None, preserves existing)

        Returns:
            Updated Episode object, or None if not found
        """
        episode = self.store.get_episode(episode_id)
        if not episode:
            return None

        if content is not None:
            episode.content = content
            # Clear stale entity relations and mentions derived from old content
            self.store.delete_entity_relations_from_episode(episode_id)
            self.store.delete_mentions_for_episode(episode_id)
            # Reset extraction/consolidation flags since content changed
            episode.entities_extracted = False if entities is None else True
            episode.relations_extracted = False
            episode.consolidated = False
            episode.entity_ids = [] if entities is None else entities

        if episode_type is not None:
            episode.episode_type = episode_type.value if isinstance(episode_type, EpisodeType) else str(episode_type)

        if entities is not None:
            episode.entities_extracted = True
            self.store.delete_mentions_for_episode(episode_id)
            resolved_ids = []
            for raw_id in entities:
                canonical_id = self._resolve_entity_id(raw_id)
                resolved_ids.append(canonical_id)
                self.store.add_mention(episode_id, canonical_id)
            episode.entity_ids = resolved_ids

        if metadata is not None:
            episode.metadata = {**(episode.metadata or {}), **metadata}

        if topic is not None:
            episode.topic = topic.lower().strip() if topic else None

        episode.updated_at = datetime.now()
        self.store.update_episode(episode)
        return episode

    def delete_episode(self, episode_id: str) -> bool:
        """
        Soft delete an episode from memory.

        The episode is marked as deleted but not permanently removed.
        Use purge_episode() to permanently remove, or restore_episode() to undelete.

        Args:
            episode_id: ID of the episode to delete

        Returns:
            True if deleted, False if not found
        """
        return self.store.delete_episode(episode_id)

    def restore_episode(self, episode_id: str) -> bool:
        """
        Restore a soft-deleted episode.

        Args:
            episode_id: ID of the episode to restore

        Returns:
            True if restored, False if not found or not deleted
        """
        return self.store.restore_episode(episode_id)

    def purge_episode(self, episode_id: str) -> bool:
        """
        Permanently delete an episode.

        This cannot be undone. Also removes entity mentions and relations
        derived from this episode.

        Args:
            episode_id: ID of the episode to purge

        Returns:
            True if purged, False if not found
        """
        return self.store.purge_episode(episode_id)

    def get_deleted_episodes(self, limit: int = 50) -> list[Episode]:
        """Get soft-deleted episodes."""
        return self.store.get_deleted_episodes(limit=limit)

    # Concept update/delete operations

    def update_concept(
        self,
        concept_id: str,
        title: Optional[str] = None,
        summary: Optional[str] = None,
        confidence: Optional[float] = None,
        conditions: Optional[str] = None,
        exceptions: Optional[list[str]] = None,
        tags: Optional[list[str]] = None,
        relations: Optional[list[dict]] = None,
    ) -> Optional[Concept]:
        """
        Update an existing concept.

        Only provided fields are updated; None values preserve existing data.
        If summary is updated, clears the embedding (will be regenerated on next recall).

        Args:
            concept_id: ID of the concept to update
            title: New title
            summary: New summary (triggers embedding clear)
            confidence: New confidence score (0.0-1.0)
            conditions: New applicability conditions
            exceptions: New exceptions list
            tags: New tags list
            relations: New relations list (replaces existing). Each dict has
                type, target_id, strength, context.

        Returns:
            Updated Concept object, or None if not found
        """
        concept = self.store.get_concept(concept_id)
        if not concept:
            return None

        if title is not None:
            concept.title = title

        if summary is not None and summary != concept.summary:
            concept.summary = summary
            concept.embedding = None

        if confidence is not None:
            concept.confidence = max(0.0, min(1.0, confidence))

        if conditions is not None:
            concept.conditions = conditions

        if exceptions is not None:
            concept.exceptions = exceptions

        if tags is not None:
            concept.tags = tags

        if relations is not None:
            concept.relations = [
                Relation(
                    type=RelationType(r["type"]),
                    target_id=r["target_id"],
                    strength=r.get("strength", 0.5),
                    context=r.get("context"),
                )
                for r in relations
            ]

        concept.updated_at = datetime.now()
        self.store.update_concept(concept)
        return concept

    def delete_concept(self, concept_id: str) -> bool:
        """
        Soft delete a concept from memory.

        The concept is marked as deleted but not permanently removed.
        Use purge_concept() to permanently remove, or restore_concept() to undelete.

        Args:
            concept_id: ID of the concept to delete

        Returns:
            True if deleted, False if not found
        """
        return self.store.delete_concept(concept_id)

    def restore_concept(self, concept_id: str) -> bool:
        """
        Restore a soft-deleted concept.

        Args:
            concept_id: ID of the concept to restore

        Returns:
            True if restored, False if not found or not deleted
        """
        return self.store.restore_concept(concept_id)

    def purge_concept(self, concept_id: str) -> bool:
        """
        Permanently delete a concept.

        This cannot be undone. Also removes all relations pointing to this concept.

        Args:
            concept_id: ID of the concept to purge

        Returns:
            True if purged, False if not found
        """
        return self.store.purge_concept(concept_id)

    def get_deleted_concepts(self) -> list[Concept]:
        """Get soft-deleted concepts."""
        return self.store.get_deleted_concepts()

    # Entity operations
    
    def _normalize_entity_id(self, entity_id: str) -> str:
        """Normalize an entity ID to canonical lowercase form."""
        type_str, name = Entity.parse_id(entity_id)
        return Entity.make_id(type_str, normalize_entity_name(name))

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """Get an entity by ID."""
        return self.store.get_entity(self._normalize_entity_id(entity_id))

    def get_all_entities(self) -> list[Entity]:
        """Get all entities."""
        return self.store.get_all_entities()

    def get_episodes_mentioning(self, entity_id: str, limit: int = 50) -> list[Episode]:
        """Get all episodes that mention a specific entity."""
        return self.store.get_episodes_mentioning(self._normalize_entity_id(entity_id), limit=limit)
    
    def get_entity_mention_counts(self) -> list[tuple[Entity, int]]:
        """Get all entities with their mention counts, sorted by most mentioned."""
        return self.store.get_entity_mention_counts()
    
    # Task operations

    def get_tasks(
        self,
        status: Optional[str] = None,
        entity_id: Optional[str] = None,
        plan_id: Optional[str] = None,
        limit: int = 50,
    ) -> list[Episode]:
        """Get task episodes with optional filters.

        Args:
            status: Filter by task status (todo, in_progress, done, blocked)
            entity_id: Filter by entity association
            plan_id: Filter by originating plan episode ID
            limit: Maximum number of tasks to return
        """
        all_tasks = self.store.get_episodes_by_type(EpisodeType.TASK.value, limit=1000)
        normalized_entity = self._normalize_entity_id(entity_id) if entity_id else None

        filtered = []
        for task in all_tasks:
            meta = task.metadata or {}
            if status and meta.get("status") != status:
                continue
            if normalized_entity and normalized_entity not in task.entity_ids:
                continue
            if plan_id and meta.get("plan_id") != plan_id:
                continue
            filtered.append(task)
            if len(filtered) >= limit:
                break

        return filtered

    def update_task_status(
        self,
        task_id: str,
        status: str,
        reason: Optional[str] = None,
    ) -> Optional[Episode]:
        """Transition a task's status with timestamp tracking.

        Valid transitions:
            todo -> in_progress, blocked
            in_progress -> done, blocked, todo
            blocked -> todo, in_progress
            done -> todo (reopen)

        Args:
            task_id: Episode ID of the task
            status: New status value
            reason: Optional reason (used for blocked status)

        Returns:
            Updated Episode, or None if not found or invalid
        """
        episode = self.store.get_episode(task_id)
        if not episode or episode.episode_type != EpisodeType.TASK.value:
            return None

        try:
            new_status = TaskStatus(status)
        except ValueError:
            return None

        meta = episode.metadata or {}
        old_status = meta.get("status", "todo")

        meta["status"] = new_status.value

        if new_status == TaskStatus.IN_PROGRESS and old_status != "in_progress":
            meta["started_at"] = datetime.now().isoformat()
        elif new_status == TaskStatus.DONE:
            meta["completed_at"] = datetime.now().isoformat()
        elif new_status == TaskStatus.BLOCKED and reason:
            meta["blocked_reason"] = reason
        elif new_status in (TaskStatus.TODO, TaskStatus.IN_PROGRESS):
            meta.pop("blocked_reason", None)

        episode.metadata = meta
        episode.updated_at = datetime.now()
        self.store.update_episode(episode)
        return episode

    def get_stats(self) -> dict:
        """Get memory statistics including consolidation state."""
        stats = self.store.get_stats()
        stats["session_episode_buffer"] = len(self._episode_buffer)
        stats["consolidation_threshold"] = self.consolidation_threshold
        stats["auto_consolidate"] = self.auto_consolidate
        stats["should_consolidate"] = self.should_consolidate
        stats["last_consolidation"] = self._last_consolidation.isoformat() if self._last_consolidation else None
        stats["llm_provider"] = self.llm.name
        stats["embedding_provider"] = self.embedding.name
        
        # Decay stats
        stats["decay_enabled"] = self.decay_config.enabled
        stats["recall_count"] = self._recall_count
        stats["decay_interval"] = self.decay_config.decay_interval
        stats["decay_rate"] = self.decay_config.decay_rate
        stats["next_decay_at"] = (
            ((self._recall_count // self.decay_config.decay_interval) + 1) * 
            self.decay_config.decay_interval
        )
        stats["recalls_since_last_decay"] = self._recall_count % self.decay_config.decay_interval
        
        return stats
    
    # Import/Export
    
    def export_memory(self, path: Optional[str] = None) -> dict:
        """
        Export all memory data.
        
        Args:
            path: If provided, save to this file path
            
        Returns:
            The exported data dictionary
        """
        data = self.store.export_data()
        data["exported_at"] = datetime.now().isoformat()
        data["stats"] = self.get_stats()
        
        if path:
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
            logger.info(f"Exported memory to {path}")
        
        return data
    
    def import_memory(self, path_or_data: str | dict) -> dict:
        """
        Import memory data.
        
        Args:
            path_or_data: File path to JSON or data dictionary
            
        Returns:
            Import statistics
        """
        if isinstance(path_or_data, str):
            with open(path_or_data) as f:
                data = json.load(f)
        else:
            data = path_or_data
        
        result = self.store.import_data(data)
        logger.info(f"Imported {result['concepts_imported']} concepts, {result['episodes_imported']} episodes")
        return result
    
    # Context manager support
    
    async def aclose(self) -> None:
        """Close underlying provider HTTP clients to avoid event-loop-closed errors."""
        await self.llm.aclose()
        await self.embedding.aclose()
        if self._triager and self._triager.llm is not self.llm:
            await self._triager.llm.aclose()

    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Consolidate pending episodes when exiting context
        if self.pending_episodes_count > 0:
            logger.info("Context exit: consolidating pending episodes")
            await self.end_session()
        await self.aclose()


def create_memory(
    llm_provider: Optional[str] = None,
    embedding_provider: Optional[str] = None,
    db_path: str = "memory",
    db_url: Optional[str] = None,
    project_dir: Optional[Path] = None,
    **kwargs,
) -> MemoryInterface:
    """
    Factory function to create a MemoryInterface with sensible defaults.

    Args:
        llm_provider: "anthropic", "openai", "azure_openai", or "ollama"
        embedding_provider: "openai", "azure_openai", or "ollama"
        db_path: Database name (stored in ~/.remind/). Ignored when db_url is set.
        db_url: Full SQLAlchemy database URL (e.g. "postgresql+psycopg://...").
                When set, takes precedence over db_path.
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
        setup_file_logging(db_url)

    # Use config values if not explicitly provided
    llm_provider = llm_provider or config.llm_provider
    embedding_provider = embedding_provider or config.embedding_provider

    # Apply config defaults for kwargs if not provided
    if "consolidation_threshold" not in kwargs:
        kwargs["consolidation_threshold"] = config.consolidation_threshold
    if "consolidation_concepts_per_pass" not in kwargs:
        kwargs["consolidation_concepts_per_pass"] = config.consolidation_concepts_per_pass
    if "auto_consolidate" not in kwargs:
        kwargs["auto_consolidate"] = config.auto_consolidate
    if "decay_config" not in kwargs:
        kwargs["decay_config"] = config.decay
    if "ingest_buffer_size" not in kwargs:
        kwargs["ingest_buffer_size"] = config.ingest_buffer_size
    if "ingest_min_density" not in kwargs:
        kwargs["ingest_min_density"] = config.ingest_min_density
    if "episode_types" not in kwargs:
        kwargs["episode_types"] = config.episode_types
    
    # Import providers
    from remind.providers import (
        AnthropicLLM, OpenAILLM, OllamaLLM, AzureOpenAILLM,
        OpenAIEmbedding, OllamaEmbedding, AzureOpenAIEmbedding,
    )

    # Create LLM provider with config values
    if llm_provider == "anthropic":
        llm = AnthropicLLM(
            api_key=config.anthropic.api_key,
            model=config.anthropic.model,
        )
    elif llm_provider == "openai":
        llm = OpenAILLM(
            api_key=config.openai.api_key,
            base_url=config.openai.base_url,
            model=config.openai.model,
        )
    elif llm_provider == "azure_openai":
        llm = AzureOpenAILLM(
            api_key=config.azure_openai.api_key,
            base_url=config.azure_openai.base_url,
            deployment_name=config.azure_openai.deployment_name,
        )
    elif llm_provider == "ollama":
        llm = OllamaLLM(
            model=config.ollama.llm_model,
            base_url=config.ollama.url,
        )
    else:
        raise ValueError(f"Unknown LLM provider: {llm_provider}. Choose from: anthropic, openai, azure_openai, ollama")

    # Create embedding provider with config values
    if embedding_provider == "openai":
        embedding = OpenAIEmbedding(
            api_key=config.openai.api_key,
            base_url=config.openai.base_url,
        )
    elif embedding_provider == "azure_openai":
        embedding = AzureOpenAIEmbedding(
            api_key=config.azure_openai.api_key,
            base_url=config.azure_openai.base_url,
            deployment_name=config.azure_openai.embedding_deployment_name,
            dimensions=config.azure_openai.embedding_size,
        )
    elif embedding_provider == "ollama":
        embedding = OllamaEmbedding(
            model=config.ollama.embedding_model,
            base_url=config.ollama.url,
        )
    else:
        raise ValueError(f"Unknown embedding provider: {embedding_provider}. Choose from: openai, azure_openai, ollama")
    
    # Create triage LLM if ingest_model is configured for the active provider
    triage_llm = None
    if llm_provider == "anthropic" and config.anthropic.ingest_model:
        triage_llm = AnthropicLLM(api_key=config.anthropic.api_key, model=config.anthropic.ingest_model)
    elif llm_provider == "openai" and config.openai.ingest_model:
        triage_llm = OpenAILLM(api_key=config.openai.api_key, base_url=config.openai.base_url, model=config.openai.ingest_model)
    elif llm_provider == "azure_openai" and config.azure_openai.ingest_deployment_name:
        triage_llm = AzureOpenAILLM(api_key=config.azure_openai.api_key, base_url=config.azure_openai.base_url, deployment_name=config.azure_openai.ingest_deployment_name)
    elif llm_provider == "ollama" and config.ollama.ingest_model:
        triage_llm = OllamaLLM(model=config.ollama.ingest_model, base_url=config.ollama.url)

    return MemoryInterface(
        llm=llm,
        embedding=embedding,
        db_url=db_url,
        triage_llm=triage_llm,
        **kwargs,
    )

