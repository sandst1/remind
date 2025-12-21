"""
Entity and type extraction from episodes.

Uses LLM to extract structured information from raw episodic memories:
- Episode type classification (observation, decision, question, meta, preference)
- Entity mentions (files, functions, people, concepts, etc.)
"""

import json
import logging
import re
from typing import Optional

from realmem.models import (
    Episode, Entity, EntityType, EpisodeType,
    ExtractionResult, BackfillResult,
)
from realmem.store import MemoryStore
from realmem.providers.base import LLMProvider

logger = logging.getLogger(__name__)

# Maximum characters of episode content to send for extraction
MAX_CONTENT_LENGTH = 2000


def try_fix_json(text: str) -> Optional[dict]:
    """Try to fix and parse malformed JSON."""
    # First try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Remove markdown code blocks
    text = re.sub(r'^```(?:json)?\s*', '', text.strip())
    text = re.sub(r'\s*```$', '', text)
    
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Try to find JSON object in the text
    match = re.search(r'\{[\s\S]*\}', text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    
    # Try to fix truncated JSON by closing open structures
    fixed = text.rstrip()
    
    # Count brackets to see what's missing
    open_braces = fixed.count('{') - fixed.count('}')
    open_brackets = fixed.count('[') - fixed.count(']')
    
    # If we're inside a string, try to close it
    if fixed.count('"') % 2 == 1:
        fixed += '"'
    
    # Close arrays first, then objects
    fixed += ']' * open_brackets
    fixed += '}' * open_braces
    
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass
    
    # Last resort: try to extract just type and entities array
    type_match = re.search(r'"type"\s*:\s*"(\w+)"', text)
    entities_match = re.search(r'"entities"\s*:\s*\[(.*?)\]', text, re.DOTALL)
    
    if type_match:
        result = {"type": type_match.group(1), "entities": []}
        
        if entities_match:
            # Try to parse entities - extract individual entity objects
            entity_pattern = r'\{[^}]+\}'
            entity_strs = re.findall(entity_pattern, entities_match.group(1))
            for es in entity_strs:
                try:
                    entity = json.loads(es)
                    result["entities"].append(entity)
                except json.JSONDecodeError:
                    pass
        
        return result
    
    return None


EXTRACTION_SYSTEM_PROMPT = """You are an information extraction system. Your job is to:

1. Classify the type of memory/episode
2. Extract entities mentioned in the text

Be conservative - only extract entities that are clearly mentioned.
Prefer specific entity types (file, function) over generic ones (concept).
Keep entity names SHORT (under 30 characters).
Respond with ONLY valid JSON, no explanations."""


EXTRACTION_PROMPT_TEMPLATE = """Classify and extract from this text:

{content}

Return JSON:
{{
  "type": "observation|decision|question|meta|preference",
  "entities": [{{"type": "file|function|class|person|concept|tool|project", "id": "type:name", "name": "short name"}}]
}}

Types: observation=noticed/learned, decision=choice made, question=uncertainty, meta=about thinking, preference=opinion/value
Entity examples: {{"type":"file","id":"file:auth.ts","name":"auth.ts"}}, {{"type":"person","id":"person:alice","name":"Alice"}}

Keep entity names under 30 chars. Empty entities array if none found."""


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
        # Truncate long content to avoid token limits
        if len(content) > MAX_CONTENT_LENGTH:
            content = content[:MAX_CONTENT_LENGTH] + "...[truncated]"
        
        prompt = EXTRACTION_PROMPT_TEMPLATE.format(content=content)
        
        try:
            result = await self.llm.complete_json(
                prompt=prompt,
                system=EXTRACTION_SYSTEM_PROMPT,
                temperature=0.1,  # Low temp for consistent extraction
                max_tokens=512,
            )
            
            return ExtractionResult.from_dict(result)
            
        except json.JSONDecodeError as e:
            # Try to fix malformed JSON
            logger.debug(f"JSON decode error, attempting recovery: {e}")
            try:
                # Get raw response and try to fix it
                raw_response = await self.llm.complete(
                    prompt=prompt,
                    system=EXTRACTION_SYSTEM_PROMPT,
                    temperature=0.1,
                    max_tokens=512,
                )
                fixed = try_fix_json(raw_response)
                if fixed:
                    logger.debug("JSON recovery successful")
                    return ExtractionResult.from_dict(fixed)
            except Exception:
                pass
            
            logger.warning(f"Extraction failed (JSON): {e}")
            return ExtractionResult(episode_type=EpisodeType.OBSERVATION, entities=[])
            
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

