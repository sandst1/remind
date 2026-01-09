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

from remind.models import (
    Episode, Entity, EntityType, EntityRelation, EpisodeType,
    ExtractionResult,
)
from remind.store import MemoryStore
from remind.providers.base import LLMProvider

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
3. Identify relationships between extracted entities

Be conservative - only extract entities that are clearly mentioned.
Prefer specific entity types (file, function) over generic ones (subject).
Keep entity names SHORT (under 30 characters).
Only include relationships that are explicitly stated or strongly implied.
Respond with ONLY valid JSON, no explanations."""


EXTRACTION_PROMPT_TEMPLATE = """Classify and extract from this text:

{content}

Return JSON:
{{
  "type": "observation|decision|question|meta|preference",
  "title": "Short descriptive title (5-10 words)",
  "entities": [{{"type": "file|function|class|person|subject|tool|project", "id": "type:name", "name": "short name"}}],
  "entity_relationships": [{{"source": "type:name", "target": "type:name", "relationship": "verb or description", "strength": 0.7}}]
}}

Types: observation=noticed/learned, decision=choice made, question=uncertainty, meta=about thinking, preference=opinion/value
Title: Concise summary capturing the main insight, decision, or topic (e.g., "User prefers Python for backends", "Bug in auth flow identified")
Entity examples: {{"type":"file","id":"file:auth.ts","name":"auth.ts"}}, {{"type":"person","id":"person:alice","name":"Alice"}}
Relationship examples: {{"source":"person:alice","target":"project:backend","relationship":"maintains","strength":0.8}}, {{"source":"file:auth.ts","target":"file:utils.ts","relationship":"imports","strength":0.9}}

Keep entity names under 30 chars. Empty arrays if none found. Strength is 0.0-1.0 confidence."""


# Prompt for extracting relationships from episodes that already have entities extracted
RELATIONS_ONLY_PROMPT_TEMPLATE = """Given this text and its already-identified entities, identify relationships between them:

Text: {content}

Entities present: {entities}

Return JSON with relationships between these entities:
{{
  "entity_relationships": [{{"source": "entity_id", "target": "entity_id", "relationship": "verb or description", "strength": 0.7}}]
}}

Only identify relationships that are explicitly stated or strongly implied in the text.
Use the exact entity IDs from the list above.
Relationship examples: "manages", "imports", "depends_on", "authored_by", "works_on", "uses"
Empty array if no relationships found. Strength is 0.0-1.0 confidence."""


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
    
    async def extract(self, content: str, episode_id: Optional[str] = None) -> ExtractionResult:
        """
        Extract type, entities, and relationships from episode content.

        Args:
            content: The raw episode content
            episode_id: Optional episode ID for provenance tracking

        Returns:
            ExtractionResult with episode_type, entities, and entity_relations
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
                max_tokens=1024,  # Increased for relationships
            )

            return ExtractionResult.from_dict(result, episode_id=episode_id)

        except json.JSONDecodeError as e:
            # Try to fix malformed JSON
            logger.debug(f"JSON decode error, attempting recovery: {e}")
            try:
                # Get raw response and try to fix it
                raw_response = await self.llm.complete(
                    prompt=prompt,
                    system=EXTRACTION_SYSTEM_PROMPT,
                    temperature=0.1,
                    max_tokens=1024,
                )
                fixed = try_fix_json(raw_response)
                if fixed:
                    logger.debug("JSON recovery successful")
                    return ExtractionResult.from_dict(fixed, episode_id=episode_id)
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
        Extract entities and relationships from an episode and store them.

        Updates the episode with extracted info and creates entity/mention/relation records.

        Args:
            episode: The episode to process

        Returns:
            ExtractionResult with what was extracted
        """
        result = await self.extract(episode.content, episode_id=episode.id)

        # Update episode metadata
        episode.episode_type = result.episode_type
        episode.title = result.title
        episode.entities_extracted = True
        episode.relations_extracted = True

        # Store entities with deduplication, and track final entity IDs
        final_entity_ids = []
        for entity in result.entities:
            # Check if an entity with the same name already exists
            existing = self.store.find_entity_by_name(entity.display_name)
            if existing:
                # Reuse existing entity ID for consistency
                entity_id = existing.id
                # Update type to most recent extraction (but keep ID stable)
                if entity.type != existing.type:
                    existing.type = entity.type
                    self.store.add_entity(existing)  # INSERT OR REPLACE updates the type
            else:
                # New entity - store it
                self.store.add_entity(entity)
                entity_id = entity.id

            final_entity_ids.append(entity_id)
            self.store.add_mention(episode.id, entity_id)

        # Update episode with deduplicated entity IDs
        episode.entity_ids = final_entity_ids
        self.store.update_episode(episode)

        # Store entity relationships
        for relation in result.entity_relations:
            self.store.add_entity_relation(relation)

        logger.debug(
            f"Extracted from {episode.id}: type={result.episode_type.value}, "
            f"entities={[e.id for e in result.entities]}, "
            f"relations={len(result.entity_relations)}"
        )

        return result

    async def extract_relations_only(self, episode: Episode) -> list[EntityRelation]:
        """
        Extract only relationships from an episode that already has entities.

        Used for backfilling relationships in existing databases.
        Skips entity pairs that already have relations to avoid unnecessary LLM calls.

        Args:
            episode: Episode with entities_extracted=True

        Returns:
            List of extracted EntityRelation objects
        """
        if not episode.entity_ids or len(episode.entity_ids) < 2:
            # Need at least 2 entities for a relationship
            return []

        # Check which entity pairs already have relations
        existing_pairs = self.store.get_existing_relation_pairs(episode.entity_ids)

        # Build set of all possible pairs (both directions) that already have relations
        related_pairs = set()
        for source, target in existing_pairs:
            related_pairs.add((source, target))
            related_pairs.add((target, source))

        # Find entities that have at least one unrelated pair
        entities_with_unrelated = set()
        entity_ids = episode.entity_ids
        for i, e1 in enumerate(entity_ids):
            for e2 in entity_ids[i + 1:]:
                if (e1, e2) not in related_pairs:
                    entities_with_unrelated.add(e1)
                    entities_with_unrelated.add(e2)

        if not entities_with_unrelated:
            # All entity pairs already have relations, skip LLM call
            logger.debug(
                f"Skipping relation extraction for {episode.id}: "
                f"all {len(entity_ids)} entities already related"
            )
            return []

        # Filter to only entities with unrelated pairs
        filtered_entities = [e for e in entity_ids if e in entities_with_unrelated]

        # Truncate long content
        content = episode.content
        if len(content) > MAX_CONTENT_LENGTH:
            content = content[:MAX_CONTENT_LENGTH] + "...[truncated]"

        # Format entity list for the prompt
        entities_str = ", ".join(filtered_entities)

        prompt = RELATIONS_ONLY_PROMPT_TEMPLATE.format(
            content=content,
            entities=entities_str,
        )

        try:
            result = await self.llm.complete_json(
                prompt=prompt,
                system=EXTRACTION_SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=512,
            )

            relations = []
            for rel in result.get("entity_relationships", []):
                source = rel.get("source")
                target = rel.get("target")
                relationship = rel.get("relationship")

                # Validate that source and target are in the filtered entities
                # and this pair doesn't already have a relation
                if source and target and relationship:
                    if source in filtered_entities and target in filtered_entities:
                        if (source, target) not in related_pairs:
                            relations.append(EntityRelation(
                                source_id=source,
                                target_id=target,
                                relation_type=relationship,
                                strength=rel.get("strength", 0.5),
                                context=rel.get("context"),
                                source_episode_id=episode.id,
                            ))

            return relations

        except Exception as e:
            logger.warning(f"Relation extraction failed for {episode.id}: {e}")
            return []

    async def extract_and_store_relations_only(self, episode: Episode) -> int:
        """
        Extract and store relationships for an episode that already has entities.

        Updates the episode's relations_extracted flag and stores relationships.

        Args:
            episode: Episode with entities_extracted=True

        Returns:
            Number of relationships extracted and stored
        """
        relations = await self.extract_relations_only(episode)

        # Store relationships
        for relation in relations:
            self.store.add_entity_relation(relation)

        # Mark episode as having relations extracted
        episode.relations_extracted = True
        self.store.update_episode(episode)

        logger.debug(
            f"Extracted relations from {episode.id}: {len(relations)} relationships"
        )

        return len(relations)


async def extract_for_remember(
    llm: LLMProvider,
    store: MemoryStore,
    episode: Episode,
    auto_extract: bool = True,
) -> Episode:
    """
    Helper function to extract entities and relationships when remembering.

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
        result = await extractor.extract(episode.content, episode_id=episode.id)

        # Update episode with extracted info
        episode.episode_type = result.episode_type
        episode.entity_ids = [e.id for e in result.entities]
        episode.entities_extracted = True
        episode.relations_extracted = True

        # Note: We don't store entities/mentions/relations here - that happens after
        # the episode is added to the store (to ensure episode exists first)
        # Instead, we return the entities and relations to be stored by the caller
        episode.metadata["_pending_entities"] = [e.to_dict() for e in result.entities]
        episode.metadata["_pending_entity_relations"] = [r.to_dict() for r in result.entity_relations]

    except Exception as e:
        logger.warning(f"Auto-extraction failed, continuing without: {e}")
        # Don't fail the remember() call if extraction fails

    return episode

