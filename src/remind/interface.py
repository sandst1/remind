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
    Entity, EpisodeType,
)
from remind.store import MemoryStore, SQLiteMemoryStore
from remind.providers.base import LLMProvider, EmbeddingProvider
from remind.consolidation import Consolidator
from remind.retrieval import MemoryRetriever, ActivatedConcept
from remind.extraction import EntityExtractor

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
        consolidation_threshold: int = 10,  # episodes before auto-consolidation
        auto_consolidate: bool = True,
        # Retrieval settings
        default_recall_k: int = 5,
        spread_hops: int = 2,
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
        
        # Settings
        self.consolidation_threshold = consolidation_threshold
        self.auto_consolidate = auto_consolidate
        self.default_recall_k = default_recall_k
        
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
            episode.entities_extracted = True  # Manual override counts as extracted
        
        if entities:
            episode.entity_ids = entities
            episode.entities_extracted = True
        
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
        
        # Entity-based retrieval
        if entity:
            episodes = await self.retriever.retrieve_by_entity(entity, limit=k * 4)
            if raw:
                return episodes
            return self.retriever.format_entity_context(entity, episodes)
        
        # Concept-based retrieval (semantic)
        activated = await self.retriever.retrieve(
            query=query,
            k=k,
            context=context,
        )
        
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
        
        This always triggers consolidation if there are pending episodes,
        regardless of the threshold setting.
        
        Usage in agent hooks:
            async def on_conversation_end(self):
                await memory.end_session()
            
            async def on_task_complete(self, task):
                await memory.remember(f"Completed task: {task.summary}")
                await memory.end_session()
        
        Returns:
            ConsolidationResult with statistics
        """
        pending = self.pending_episodes_count
        
        if pending == 0:
            logger.debug("end_session called but no pending episodes")
            return ConsolidationResult()
        
        logger.info(f"end_session: consolidating {pending} pending episodes")
        return await self.consolidate(force=True)
    
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
    from remind.mcp_server import resolve_db_path

    # Resolve database name to full path (skip if already absolute)
    if not os.path.isabs(db_path):
        db_path = resolve_db_path(db_path)

    # Resolve providers from env vars if not provided
    llm_provider = llm_provider or os.environ.get("LLM_PROVIDER", "anthropic")
    embedding_provider = embedding_provider or os.environ.get("EMBEDDING_PROVIDER", "openai")
    
    # Import providers
    from remind.providers import (
        AnthropicLLM, OpenAILLM, OllamaLLM, AzureOpenAILLM,
        OpenAIEmbedding, OllamaEmbedding, AzureOpenAIEmbedding,
    )
    
    # Create LLM provider
    llm_map = {
        "anthropic": AnthropicLLM,
        "openai": OpenAILLM,
        "azure_openai": AzureOpenAILLM,
        "ollama": OllamaLLM,
    }
    if llm_provider not in llm_map:
        raise ValueError(f"Unknown LLM provider: {llm_provider}. Choose from: {list(llm_map.keys())}")
    
    llm = llm_map[llm_provider]()
    
    # Create embedding provider
    embed_map = {
        "openai": OpenAIEmbedding,
        "azure_openai": AzureOpenAIEmbedding,
        "ollama": OllamaEmbedding,
    }
    if embedding_provider not in embed_map:
        raise ValueError(f"Unknown embedding provider: {embedding_provider}. Choose from: {list(embed_map.keys())}")
    
    embedding = embed_map[embedding_provider]()
    
    return MemoryInterface(
        llm=llm,
        embedding=embedding,
        db_path=db_path,
        **kwargs,
    )

