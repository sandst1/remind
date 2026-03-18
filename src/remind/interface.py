"""
MemoryInterface - The unified API for the memory system.

This is the main entry point for applications integrating Remind.
It provides a simple interface for:
- remember() - log experiences/interactions
- recall() - retrieve relevant concepts
"""

from datetime import datetime
from typing import Optional
from pathlib import Path
import logging
import json

from remind.models import (
    Episode, Concept, ConsolidationResult, 
    Entity, EpisodeType, TaskStatus, Relation, RelationType,
)
from remind.store import MemoryStore, SQLiteMemoryStore
from remind.providers.base import LLMProvider, EmbeddingProvider
from remind.consolidation import Consolidator
from remind.retrieval import MemoryRetriever, ActivatedConcept
from remind.extraction import EntityExtractor
from remind.config import load_config, DecayConfig, RemindConfig
from remind.triage import IngestionBuffer, IngestionTriager, TriageResult

logger = logging.getLogger(__name__)


class MemoryInterface:
    """
    The main interface to the memory system.
    
    Key Design:
    -----------
    - `remember()` is fast and synchronous - just stores episodes, no LLM calls
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
        db_path: str = "memory.db",
        # Consolidation settings
        consolidation_threshold: int = 5,  # episodes before auto-consolidation
        auto_consolidate: bool = True,
        # Retrieval settings
        default_recall_k: int = 5,
        spread_hops: int = 2,
        # Decay settings
        decay_config=None,
        # Auto-ingest settings
        ingest_buffer_size: int = 4000,
        ingest_min_density: float = 0.4,
        triage_llm: Optional[LLMProvider] = None,
    ):
        self.llm = llm
        self.embedding = embedding
        self.store = store or SQLiteMemoryStore(db_path)
        
        # Initialize components
        self.consolidator = Consolidator(
            llm=llm,
            embedding=embedding,
            store=self.store,
        )
        
        self.retriever = MemoryRetriever(
            embedding=embedding,
            store=self.store,
            spread_hops=spread_hops,
        )
        
        self.extractor = EntityExtractor(
            llm=llm,
            store=self.store,
        )
        
        # Auto-ingest components
        self._ingest_buffer = IngestionBuffer(threshold=ingest_buffer_size)
        self._triager = IngestionTriager(
            llm=triage_llm or llm,
            min_density=ingest_min_density,
        )
        
        # Settings
        self.consolidation_threshold = consolidation_threshold
        self.auto_consolidate = auto_consolidate
        self.default_recall_k = default_recall_k
        
        # Decay settings
        self.decay_config = decay_config or DecayConfig()
        
        # Recall tracking for decay (persisted in metadata table)
        self._recall_count: int = self._load_recall_count()
        
        # Episode buffer for tracking (this session only)
        self._episode_buffer: list[str] = []
        self._last_consolidation: Optional[datetime] = None
    
    def remember(
        self,
        content: str,
        metadata: Optional[dict] = None,
        episode_type: Optional[EpisodeType] = None,
        entities: Optional[list[str]] = None,
        confidence: float = 1.0,
    ) -> str:
        """
        Log an experience/interaction to be consolidated later.

        This is a fast operation - no LLM calls. Entity extraction and
        type classification happen during consolidate().

        Args:
            content: The interaction or experience to remember
            metadata: Optional metadata about the episode
            episode_type: Optional explicit type (observation, decision, question, meta, preference).
                          If not provided, will be auto-detected during consolidation.
            entities: Optional explicit list of entity IDs (e.g., ["file:src/auth.ts", "person:alice"]).
                      If not provided, will be auto-detected during consolidation.
            confidence: How certain this information is (0.0-1.0, default 1.0).
                        Lower values indicate uncertainty or weak signals.

        Returns:
            The episode ID
        """
        # Create episode
        episode = Episode(
            content=content,
            metadata=metadata or {},
            confidence=max(0.0, min(1.0, confidence)),  # Clamp to valid range
        )
        
        # Apply explicit type/entities if provided
        if episode_type:
            episode.episode_type = episode_type
            # Note: Don't set entities_extracted here - type can be set independently
        
        if entities:
            episode.entity_ids = entities
            episode.entities_extracted = True
            # Note: relations_extracted stays False so consolidation can extract relationships
        
        # Store the episode
        episode_id = self.store.add_episode(episode)
        self._episode_buffer.append(episode_id)
        
        # Store explicitly provided entities
        if entities:
            for entity_id in entities:
                # Ensure entity exists
                if not self.store.get_entity(entity_id):
                    type_str, name = Entity.parse_id(entity_id)
                    from remind.models import EntityType
                    try:
                        etype = EntityType(type_str)
                    except ValueError:
                        etype = EntityType.OTHER
                    entity = Entity(id=entity_id, type=etype, display_name=name)
                    self.store.add_entity(entity)
                self.store.add_mention(episode_id, entity_id)
        
        logger.debug(f"Remembered episode {episode_id}: {content[:50]}...")
        
        return episode_id
    
    async def recall(
        self,
        query: str,
        k: Optional[int] = None,
        context: Optional[str] = None,
        entity: Optional[str] = None,
        raw: bool = False,
    ) -> str | list[ActivatedConcept] | list[Episode]:
        """
        Retrieve relevant memory for a query.
        
        Args:
            query: What to search for
            k: Number of concepts to return
            context: Additional context for the search
            entity: If provided, retrieve by entity instead of semantic search
            raw: If True, return raw objects instead of formatted string
            
        Returns:
            Formatted memory string for LLM injection, or raw objects if raw=True
        """
        k = k or self.default_recall_k
        
        # Increment recall count and persist when decay is enabled
        self._recall_count += 1
        if self.decay_config.enabled:
            self._save_recall_count()
        
        # Entity-based retrieval
        if entity:
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
        )
        
        # Rejuvenation: reset decay for recalled concepts (only for concept-based)
        if activated and self.decay_config.enabled:
            self._rejuvenate_concepts(activated)
        
        # Trigger decay every N recalls
        if self.decay_config.enabled and self._recall_count % self.decay_config.decay_interval == 0:
            self._trigger_decay()
        
        if raw:
            return activated
        
        return self.retriever.format_for_llm(activated)
    
    async def consolidate(self, force: bool = False) -> ConsolidationResult:
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
            
        Returns:
            ConsolidationResult with statistics
        """
        result = await self.consolidator.consolidate(force=force)
        
        if result.episodes_processed > 0:
            self._last_consolidation = datetime.now()
            self._episode_buffer = []  # Clear buffer after successful consolidation
        
        return result
    
    async def end_session(self) -> ConsolidationResult:
        """
        Hook for ending a session/conversation.
        
        Call this at natural boundaries in your agent:
        - End of a conversation
        - Task completion
        - Before shutting down
        - Scheduled maintenance
        
        This flushes any pending ingestion buffer and then triggers
        consolidation if there are pending episodes.
        
        Usage in agent hooks:
            async def on_conversation_end(self):
                await memory.end_session()
            
            async def on_task_complete(self, task):
                await memory.remember(f"Completed task: {task.summary}")
                await memory.end_session()
        
        Returns:
            ConsolidationResult with statistics
        """
        # Flush ingestion buffer first
        if not self._ingest_buffer.is_empty:
            logger.info("end_session: flushing ingestion buffer")
            await self.flush_ingest()
        
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
        density scoring + episode extraction). Episodes that pass triage
        are stored via remember() and immediately consolidated.

        This is separate from remember() -- explicit remember() calls bypass
        triage entirely. Auto-ingest is additive.

        Args:
            content: Raw text to ingest (conversation fragments, tool output, etc.)
            source: Source label for metadata (default: "conversation")

        Returns:
            List of episode IDs created (empty if buffer didn't flush or
            triage dropped everything).
        """
        chunk = self._ingest_buffer.add(content)
        if chunk is None:
            logger.debug(
                f"Ingested {len(content)} chars, buffer at {self._ingest_buffer.size} "
                f"(threshold: {self._ingest_buffer.threshold})"
            )
            return []

        return await self._process_ingest_chunk(chunk, source)

    async def flush_ingest(self) -> list[str]:
        """Force-flush the ingestion buffer and process whatever is in it.

        Call at session end or when you want to ensure everything is processed.

        Returns:
            List of episode IDs created (empty if buffer was empty or
            triage dropped everything).
        """
        chunk = self._ingest_buffer.flush()
        if chunk is None:
            return []

        return await self._process_ingest_chunk(chunk, source="flush")

    async def _process_ingest_chunk(self, chunk: str, source: str) -> list[str]:
        """Run triage on a chunk and store/consolidate resulting episodes."""
        # Get existing concept context for the triage prompt
        existing_concepts = ""
        try:
            result = await self.recall(chunk[:500], k=5, raw=True)
            if isinstance(result, list) and result:
                lines = []
                for item in result:
                    concept = item.concept if hasattr(item, 'concept') else item
                    if hasattr(concept, 'summary'):
                        lines.append(f"- {concept.summary}")
                if lines:
                    existing_concepts = "\n".join(lines)
        except Exception as e:
            logger.debug(f"Recall for triage context failed (ok for empty memory): {e}")

        # Run triage
        triage_result = await self._triager.triage(chunk, existing_concepts)

        logger.info(
            f"Triage: density={triage_result.density:.2f}, "
            f"episodes={len(triage_result.episodes)}, "
            f"reasoning={triage_result.reasoning}"
        )

        if not triage_result.episodes:
            return []

        # Store extracted episodes via remember()
        episode_ids = []
        for ep in triage_result.episodes:
            ep_type = None
            try:
                ep_type = EpisodeType(ep.episode_type)
            except ValueError:
                ep_type = EpisodeType.OBSERVATION

            metadata = ep.metadata.copy() if ep.metadata else {}
            metadata["source"] = source
            metadata["triage_density"] = triage_result.density

            episode_id = self.remember(
                content=ep.content,
                metadata=metadata,
                episode_type=ep_type,
                entities=ep.entities if ep.entities else None,
            )
            episode_ids.append(episode_id)

        # Immediate consolidation -- triage already filtered for quality
        if episode_ids:
            try:
                result = await self.consolidate(force=True)
                logger.info(
                    f"Post-ingest consolidation: {result.episodes_processed} episodes, "
                    f"{result.concepts_created} concepts created"
                )
            except Exception as e:
                logger.warning(f"Post-ingest consolidation failed: {e}")

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
    
    def get_episodes_by_type(self, episode_type: EpisodeType, limit: int = 50) -> list[Episode]:
        """Get episodes of a specific type (decision, question, meta, etc.)."""
        return self.store.get_episodes_by_type(episode_type, limit=limit)

    # Episode update/delete operations

    def update_episode(
        self,
        episode_id: str,
        content: Optional[str] = None,
        episode_type: Optional[EpisodeType] = None,
        entities: Optional[list[str]] = None,
        metadata: Optional[dict] = None,
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
            episode.episode_type = episode_type

        if entities is not None:
            episode.entity_ids = entities
            episode.entities_extracted = True
            # Sync mentions table to match the new entity list
            self.store.delete_mentions_for_episode(episode_id)
            for entity_id in entities:
                if not self.store.get_entity(entity_id):
                    type_str, name = Entity.parse_id(entity_id)
                    from remind.models import EntityType
                    try:
                        etype = EntityType(type_str)
                    except ValueError:
                        etype = EntityType.OTHER
                    entity = Entity(id=entity_id, type=etype, display_name=name)
                    self.store.add_entity(entity)
                self.store.add_mention(episode_id, entity_id)

        if metadata is not None:
            episode.metadata = {**(episode.metadata or {}), **metadata}

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
    
    def get_entity(self, entity_id: str) -> Optional[Entity]:
        """Get an entity by ID."""
        return self.store.get_entity(entity_id)
    
    def get_all_entities(self) -> list[Entity]:
        """Get all entities."""
        return self.store.get_all_entities()
    
    def get_episodes_mentioning(self, entity_id: str, limit: int = 50) -> list[Episode]:
        """Get all episodes that mention a specific entity."""
        return self.store.get_episodes_mentioning(entity_id, limit=limit)
    
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
        all_tasks = self.store.get_episodes_by_type(EpisodeType.TASK, limit=1000)

        filtered = []
        for task in all_tasks:
            meta = task.metadata or {}
            if status and meta.get("status") != status:
                continue
            if entity_id and entity_id not in task.entity_ids:
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
        if not episode or episode.episode_type != EpisodeType.TASK:
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
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Consolidate pending episodes when exiting context
        if self.pending_episodes_count > 0:
            logger.info("Context exit: consolidating pending episodes")
            await self.end_session()


def create_memory(
    llm_provider: Optional[str] = None,
    embedding_provider: Optional[str] = None,
    db_path: str = "memory",
    **kwargs,
) -> MemoryInterface:
    """
    Factory function to create a MemoryInterface with sensible defaults.

    Args:
        llm_provider: "anthropic", "openai", "azure_openai", or "ollama"
        embedding_provider: "openai", "azure_openai", or "ollama"
        db_path: Database name (stored in ~/.remind/)
        **kwargs: Additional arguments passed to MemoryInterface

    Returns:
        Configured MemoryInterface
    """
    import os
    from remind.config import load_config, resolve_db_path

    # Load config (priority: env vars > config file > defaults)
    config = load_config()

    # Resolve database name to full path (skip if already absolute)
    if not os.path.isabs(db_path):
        db_path = resolve_db_path(db_path)

    # Use config values if not explicitly provided
    llm_provider = llm_provider or config.llm_provider
    embedding_provider = embedding_provider or config.embedding_provider

    # Apply config defaults for kwargs if not provided
    if "consolidation_threshold" not in kwargs:
        kwargs["consolidation_threshold"] = config.consolidation_threshold
    if "auto_consolidate" not in kwargs:
        kwargs["auto_consolidate"] = config.auto_consolidate
    if "decay_config" not in kwargs:
        kwargs["decay_config"] = config.decay
    if "ingest_buffer_size" not in kwargs:
        kwargs["ingest_buffer_size"] = config.ingest_buffer_size
    if "ingest_min_density" not in kwargs:
        kwargs["ingest_min_density"] = config.ingest_min_density
    
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
            api_version=config.azure_openai.api_version,
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
            api_version=config.azure_openai.api_version,
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
    
    # Create triage LLM if a separate provider is configured
    triage_llm = None
    if config.triage_provider and config.triage_provider != llm_provider:
        if config.triage_provider == "anthropic":
            triage_llm = AnthropicLLM(api_key=config.anthropic.api_key, model=config.anthropic.model)
        elif config.triage_provider == "openai":
            triage_llm = OpenAILLM(api_key=config.openai.api_key, base_url=config.openai.base_url, model=config.openai.model)
        elif config.triage_provider == "azure_openai":
            triage_llm = AzureOpenAILLM(api_key=config.azure_openai.api_key, base_url=config.azure_openai.base_url, api_version=config.azure_openai.api_version, deployment_name=config.azure_openai.deployment_name)
        elif config.triage_provider == "ollama":
            triage_llm = OllamaLLM(model=config.ollama.llm_model, base_url=config.ollama.url)

    return MemoryInterface(
        llm=llm,
        embedding=embedding,
        db_path=db_path,
        triage_llm=triage_llm,
        **kwargs,
    )

