"""
Entity and type extraction from episodes.

Uses LLM to extract structured information from raw episodic memories:
- Episode type classification (observation, decision, question, meta, preference)
- Entity mentions (files, functions, people, concepts, etc.)
"""

import logging
from typing import Optional

from realmem.models import (
    Episode, Entity, EntityType, EpisodeType,
    ExtractionResult, BackfillResult,
)
from realmem.store import MemoryStore
from realmem.providers.base import LLMProvider

logger = logging.getLogger(__name__)


EXTRACTION_SYSTEM_PROMPT = """You are an information extraction system. Your job is to:

1. Classify the type of memory/episode
2. Extract entities mentioned in the text

Be conservative - only extract entities that are clearly mentioned.
Prefer specific entity types (file, function) over generic ones (concept).
"""


EXTRACTION_PROMPT_TEMPLATE = """Analyze this memory/episode and extract structured information:

---
{content}
---

Return JSON with:
1. "type": The type of this memory. One of:
   - "observation" - Something noticed, learned, or discovered
   - "decision" - A choice or decision that was made
   - "question" - An open question, uncertainty, or thing to investigate
   - "meta" - Meta-cognition about thinking patterns or processes
   - "preference" - A preference, value, opinion, or personal stance

2. "entities": Array of entities mentioned. Each entity has:
   - "type": One of: file, function, class, module, concept, person, project, tool, other
   - "id": Unique identifier like "file:src/auth.ts" or "person:alice" or "concept:caching"
   - "name": Human-readable display name

Examples of entity extraction:
- "Fixed a bug in auth.ts" → {{"type": "file", "id": "file:auth.ts", "name": "auth.ts"}}
- "Alice prefers Python" → {{"type": "person", "id": "person:alice", "name": "Alice"}}
- "Using Redis for caching" → {{"type": "tool", "id": "tool:redis", "name": "Redis"}}
- "The rate limiting approach works well" → {{"type": "concept", "id": "concept:rate-limiting", "name": "rate limiting"}}

Respond with JSON only:
{{
  "type": "observation|decision|question|meta|preference",
  "entities": [
    {{"type": "...", "id": "...", "name": "..."}}
  ]
}}

If no entities are mentioned, return an empty array for "entities"."""


class EntityExtractor:
    """
    Extracts episode types and entity mentions using an LLM.
    
    This is a lightweight extraction pass that runs on each episode,
    separate from the heavier consolidation process.
    """
    
    def __init__(
        self,
        llm: LLMProvider,
        store: MemoryStore,
    ):
        self.llm = llm
        self.store = store
    
    async def extract(self, content: str) -> ExtractionResult:
        """
        Extract type and entities from episode content.
        
        Args:
            content: The raw episode content
            
        Returns:
            ExtractionResult with episode_type and entities
        """
        prompt = EXTRACTION_PROMPT_TEMPLATE.format(content=content)
        
        try:
            result = await self.llm.complete_json(
                prompt=prompt,
                system=EXTRACTION_SYSTEM_PROMPT,
                temperature=0.1,  # Low temp for consistent extraction
                max_tokens=512,
            )
            
            return ExtractionResult.from_dict(result)
            
        except Exception as e:
            logger.warning(f"Extraction failed: {e}")
            # Return defaults on failure
            return ExtractionResult(episode_type=EpisodeType.OBSERVATION, entities=[])
    
    async def extract_and_store(self, episode: Episode) -> ExtractionResult:
        """
        Extract entities from an episode and store them.
        
        Updates the episode with extracted info and creates entity/mention records.
        
        Args:
            episode: The episode to process
            
        Returns:
            ExtractionResult with what was extracted
        """
        result = await self.extract(episode.content)
        
        # Update episode
        episode.episode_type = result.episode_type
        episode.entity_ids = [e.id for e in result.entities]
        episode.entities_extracted = True
        self.store.update_episode(episode)
        
        # Store entities and mentions
        for entity in result.entities:
            self.store.add_entity(entity)
            self.store.add_mention(episode.id, entity.id)
        
        logger.debug(
            f"Extracted from {episode.id}: type={result.episode_type.value}, "
            f"entities={[e.id for e in result.entities]}"
        )
        
        return result
    
    async def backfill(
        self,
        limit: int = 100,
        batch_size: int = 10,
    ) -> BackfillResult:
        """
        Backfill entity extraction for existing episodes.
        
        Processes episodes that haven't had extraction performed yet.
        
        Args:
            limit: Maximum number of episodes to process
            batch_size: How many to process before logging progress
            
        Returns:
            BackfillResult with statistics
        """
        result = BackfillResult()
        
        # Get unextracted episodes
        episodes = self.store.get_unextracted_episodes(limit=limit)
        
        if not episodes:
            logger.info("No episodes need extraction")
            return result
        
        logger.info(f"Backfilling {len(episodes)} episodes...")
        
        for i, episode in enumerate(episodes):
            try:
                extraction = await self.extract_and_store(episode)
                result.episodes_processed += 1
                result.episodes_updated += 1
                result.entities_created += len(extraction.entities)
                
                if (i + 1) % batch_size == 0:
                    logger.info(f"Processed {i + 1}/{len(episodes)} episodes...")
                    
            except Exception as e:
                error_msg = f"Failed to extract from {episode.id}: {e}"
                logger.warning(error_msg)
                result.errors.append(error_msg)
        
        logger.info(
            f"Backfill complete: {result.episodes_processed} episodes, "
            f"{result.entities_created} entities created"
        )
        
        return result


async def extract_for_remember(
    llm: LLMProvider,
    store: MemoryStore,
    episode: Episode,
    auto_extract: bool = True,
) -> Episode:
    """
    Helper function to extract entities when remembering.
    
    Called by the main memory interface during remember().
    
    Args:
        llm: LLM provider for extraction
        store: Memory store
        episode: The episode being remembered
        auto_extract: Whether to actually run extraction
        
    Returns:
        The episode, potentially updated with extracted info
    """
    if not auto_extract:
        return episode
    
    extractor = EntityExtractor(llm, store)
    
    try:
        result = await extractor.extract(episode.content)
        
        # Update episode with extracted info
        episode.episode_type = result.episode_type
        episode.entity_ids = [e.id for e in result.entities]
        episode.entities_extracted = True
        
        # Note: We don't store entities/mentions here - that happens after
        # the episode is added to the store (to ensure episode exists first)
        # Instead, we return the entities to be stored by the caller
        episode.metadata["_pending_entities"] = [e.to_dict() for e in result.entities]
        
    except Exception as e:
        logger.warning(f"Auto-extraction failed, continuing without: {e}")
        # Don't fail the remember() call if extraction fails
    
    return episode

