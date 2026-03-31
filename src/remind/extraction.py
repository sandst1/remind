"""
Entity and type extraction from episodes.

Uses LLM to extract structured information from raw episodic memories:
- Episode type classification
- Entity mentions
- Entity relationships
"""

import json
import logging
import re
from dataclasses import replace
from datetime import datetime
from typing import Optional

from remind.llm_protocol import (
    ProtocolParseError,
    parse_extraction_batch_csv,
    parse_extraction_single_csv,
    parse_relations_only_csv,
)
from remind.models import (
    Entity,
    EntityRelation,
    EntityType,
    Episode,
    ExtractionResult,
    normalize_entity_name,
)
from remind.providers.base import LLMProvider
from remind.store import MemoryStore

logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 2000


def _entity_stub_for_id(entity_id: str) -> Entity:
    """Create minimal entity rows so FK-backed stores accept relation inserts."""
    type_str, name = Entity.parse_id(entity_id)
    try:
        entity_type = EntityType(type_str)
    except ValueError:
        entity_type = EntityType.OTHER
    display = name.replace("_", " ").strip() or entity_id
    return Entity(id=entity_id, type=entity_type, display_name=display)


def try_fix_json(text: str) -> Optional[dict]:
    """Try to fix and parse malformed JSON."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    text = re.sub(r'^```(?:json)?\s*', "", text.strip())
    text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    fixed = text.rstrip()
    open_braces = fixed.count("{") - fixed.count("}")
    open_brackets = fixed.count("[") - fixed.count("]")
    if fixed.count('"') % 2 == 1:
        fixed += '"'
    fixed += "]" * open_brackets
    fixed += "}" * open_braces

    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    type_match = re.search(r'"type"\s*:\s*"(\w+)"', text)
    entities_match = re.search(r'"entities"\s*:\s*\[(.*?)\]', text, re.DOTALL)
    if type_match:
        result = {"type": type_match.group(1), "entities": []}
        if entities_match:
            entity_pattern = r"\{[^}]+\}"
            entity_strs = re.findall(entity_pattern, entities_match.group(1))
            for es in entity_strs:
                try:
                    entity = json.loads(es)
                    result["entities"].append(entity)
                except json.JSONDecodeError:
                    pass
        return result
    return None


EXTRACTION_SYSTEM_PROMPT = """You are an information extraction system.

Your job is to:
1. Classify episode type
2. Extract entity mentions
3. Extract explicit or strongly implied relationships

Be conservative and concise.
Respond with ONLY CSV rows."""


EXTRACTION_PROMPT_TEMPLATE = """Classify and extract from this text:

{content}

Return ONLY rows inside these tags:
BEGIN EXTRACT_RESULTS
EPISODE,<type>,<title>
ENTITY,<entity_type>,<entity_name>
ENTITY_RELATION,<source_type>,<source_name>,<target_type>,<target_name>,<relationship>,<strength>,<context>
END EXTRACT_RESULTS

Rules:
- Exactly one EPISODE row
- Zero or more ENTITY and ENTITY_RELATION rows
- Use CSV quoting for commas
- Strength is 0.0-1.0
- Leave context empty when unknown
- Keep entity names under 30 chars

Types: observation|decision|question|meta|preference|spec|plan|task|outcome|fact"""


BATCH_EXTRACTION_PROMPT_TEMPLATE = """Classify and extract from each episode below. Episodes are delimited by [EPISODE_ID] headers.

{episodes}

Return ONLY rows inside these tags:
BEGIN EXTRACT_RESULTS
EPISODE,<episode_id>,<type>,<title>
ENTITY,<episode_id>,<entity_type>,<entity_name>
ENTITY_RELATION,<episode_id>,<source_type>,<source_name>,<target_type>,<target_name>,<relationship>,<strength>,<context>
END EXTRACT_RESULTS

Rules:
- Include one EPISODE row for every episode ID
- Zero or more ENTITY and ENTITY_RELATION rows per episode
- Use CSV quoting for commas
- Strength is 0.0-1.0
- Leave context empty when unknown
- Keep entity names under 30 chars

Types: observation|decision|question|meta|preference|spec|plan|task|outcome|fact"""

_DEFAULT_EXTRACTION_TYPES = "observation|decision|question|meta|preference|spec|plan|task|outcome|fact"


def _build_extraction_prompt(valid_types: list[str]) -> str:
    return EXTRACTION_PROMPT_TEMPLATE.replace(
        _DEFAULT_EXTRACTION_TYPES,
        "|".join(valid_types),
    )


def _build_batch_extraction_prompt(valid_types: list[str]) -> str:
    return BATCH_EXTRACTION_PROMPT_TEMPLATE.replace(
        _DEFAULT_EXTRACTION_TYPES,
        "|".join(valid_types),
    )


RELATIONS_ONLY_PROMPT_TEMPLATE = """Given this text and already identified entities, extract relationships between them:

Text: {content}
Entities: {entities}

Return ONLY rows inside these tags:
BEGIN RELATION_RESULTS
ENTITY_RELATION,<source_entity_id>,<target_entity_id>,<relationship>,<strength>,<context>
END RELATION_RESULTS

Rules:
- Use exact entity IDs from the provided list
- Only explicit or strongly implied relationships
- Strength is 0.0-1.0
- Leave context empty when unknown"""


class EntityExtractor:
    """Extracts episode type, entities, and relationships."""

    def __init__(
        self,
        llm: LLMProvider,
        store: MemoryStore,
        valid_types: Optional[list[str]] = None,
    ):
        self.llm = llm
        self.store = store
        self._valid_types: Optional[set[str]] = set(valid_types) if valid_types else None
        self._default_type = valid_types[0] if valid_types else "observation"
        if valid_types:
            self._prompt_template = _build_extraction_prompt(valid_types)
            self._batch_prompt_template = _build_batch_extraction_prompt(valid_types)
        else:
            self._prompt_template = EXTRACTION_PROMPT_TEMPLATE
            self._batch_prompt_template = BATCH_EXTRACTION_PROMPT_TEMPLATE

    def _clamp_episode_type(self, episode_type: str) -> str:
        """Validate episode_type against configured valid_types, defaulting if invalid."""
        if not self._valid_types:
            return episode_type
        if episode_type in self._valid_types:
            return episode_type
        logger.debug(
            f"Extraction returned invalid episode type '{episode_type}', "
            f"defaulting to '{self._default_type}'"
        )
        return self._default_type

    def _ensure_entity_row(self, entity_id: str) -> str:
        if self.store.get_entity(entity_id):
            return entity_id
        _, name = Entity.parse_id(entity_id)
        existing = self.store.find_entity_by_name(name)
        if existing:
            return existing.id
        self.store.add_entity(_entity_stub_for_id(entity_id))
        return entity_id

    def _persist_entity_relations(
        self, relations: list[EntityRelation], id_remap: dict[str, str]
    ) -> None:
        for rel in relations:
            src = id_remap.get(rel.source_id, rel.source_id)
            tgt = id_remap.get(rel.target_id, rel.target_id)
            canonical_src = self._ensure_entity_row(src)
            canonical_tgt = self._ensure_entity_row(tgt)
            if canonical_src != rel.source_id or canonical_tgt != rel.target_id:
                rel = replace(rel, source_id=canonical_src, target_id=canonical_tgt)
            self.store.add_entity_relation(rel)

    async def _extract_json_fallback(
        self, prompt: str, episode_id: Optional[str], max_tokens: int
    ) -> ExtractionResult:
        try:
            result = await self.llm.complete_json(
                prompt=prompt,
                system=EXTRACTION_SYSTEM_PROMPT.replace("ONLY CSV rows", "valid JSON only"),
                temperature=0.1,
                max_tokens=max_tokens,
            )
            logger.debug(
                "Extraction JSON fallback response:\n"
                f"  episode_id: {episode_id}\n"
                f"  response:\n{json.dumps(result, indent=2)}"
            )
            return ExtractionResult.from_dict(result, episode_id=episode_id)
        except json.JSONDecodeError:
            raw_response = await self.llm.complete(
                prompt=prompt,
                system=EXTRACTION_SYSTEM_PROMPT.replace("ONLY CSV rows", "valid JSON only"),
                temperature=0.1,
                max_tokens=max_tokens,
            )
            logger.debug(
                "Extraction raw JSON fallback response:\n"
                f"  episode_id: {episode_id}\n"
                f"  response_length: {len(raw_response)}\n"
                f"  response:\n{raw_response}"
            )
            fixed = try_fix_json(raw_response)
            if fixed:
                logger.debug(
                    "Extraction fixed JSON fallback response:\n"
                    f"  episode_id: {episode_id}\n"
                    f"  response:\n{json.dumps(fixed, indent=2)}"
                )
                return ExtractionResult.from_dict(fixed, episode_id=episode_id)
            raise

    async def extract(self, content: str, episode_id: Optional[str] = None) -> ExtractionResult:
        if len(content) > MAX_CONTENT_LENGTH:
            content = content[:MAX_CONTENT_LENGTH] + "...[truncated]"
        prompt = self._prompt_template.format(content=content)

        logger.debug(
            "Extraction LLM request:\n"
            f"  provider: {self.llm.name}\n"
            f"  episode_id: {episode_id}\n"
            f"  content_length: {len(content)}\n"
            f"  prompt:\n{prompt}"
        )

        try:
            response = await self.llm.complete_structured_text(
                prompt=prompt,
                system=EXTRACTION_SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=1024,
            )
            logger.debug(
                "Extraction LLM structured response:\n"
                f"  episode_id: {episode_id}\n"
                f"  response_length: {len(response)}\n"
                f"  response:\n{response}"
            )
            result = parse_extraction_single_csv(response)
            er = ExtractionResult.from_dict(result, episode_id=episode_id)
            er.episode_type = self._clamp_episode_type(er.episode_type)
            return er
        except (ProtocolParseError, ValueError, KeyError, IndexError) as e:
            logger.debug(f"CSV extraction parse failed, trying JSON fallback: {e}")
            try:
                er = await self._extract_json_fallback(prompt, episode_id, 1024)
                er.episode_type = self._clamp_episode_type(er.episode_type)
                return er
            except Exception as fallback_err:
                logger.warning(f"Extraction failed after fallback: {fallback_err}")
                return ExtractionResult(episode_type=self._default_type, entities=[])
        except Exception as e:
            logger.warning(f"Extraction failed: {e}")
            return ExtractionResult(episode_type=self._default_type, entities=[])

    async def extract_batch(self, episodes: list[Episode]) -> dict[str, ExtractionResult]:
        if not episodes:
            return {}
        if len(episodes) == 1:
            result = await self.extract(episodes[0].content, episode_id=episodes[0].id)
            return {episodes[0].id: result}

        sections = []
        for ep in episodes:
            content = ep.content
            if len(content) > MAX_CONTENT_LENGTH:
                content = content[:MAX_CONTENT_LENGTH] + "...[truncated]"
            sections.append(f"[{ep.id}]\n{content}")
        prompt = self._batch_prompt_template.format(episodes="\n\n".join(sections))
        max_tokens = 1024 * len(episodes)

        logger.debug(
            "Batch extraction LLM request:\n"
            f"  provider: {self.llm.name}\n"
            f"  episodes: {len(episodes)}\n"
            f"  prompt_length: {len(prompt)}\n"
            f"  prompt:\n{prompt}"
        )

        try:
            response = await self.llm.complete_structured_text(
                prompt=prompt,
                system=EXTRACTION_SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=max_tokens,
            )
            logger.debug(
                "Batch extraction LLM structured response:\n"
                f"  episodes: {len(episodes)}\n"
                f"  response_length: {len(response)}\n"
                f"  response:\n{response}"
            )
            parsed = parse_extraction_batch_csv(response)
            results_dict = parsed.get("results", {})
        except (ProtocolParseError, ValueError, KeyError, IndexError) as e:
            logger.debug(f"Batch CSV parse failed, trying JSON fallback: {e}")
            try:
                raw = await self.llm.complete_json(
                    prompt=prompt,
                    system=EXTRACTION_SYSTEM_PROMPT.replace("ONLY CSV rows", "valid JSON only"),
                    temperature=0.1,
                    max_tokens=max_tokens,
                )
                logger.debug(
                    "Batch extraction JSON fallback response:\n"
                    f"  episodes: {len(episodes)}\n"
                    f"  response:\n{json.dumps(raw, indent=2)}"
                )
                results_dict = raw.get("results", raw)
            except Exception as fallback_err:
                logger.warning(f"Batch extraction failed ({len(episodes)} episodes): {fallback_err}")
                return {}
        except Exception as e:
            logger.warning(f"Batch extraction failed ({len(episodes)} episodes): {e}")
            return {}

        output: dict[str, ExtractionResult] = {}
        for ep in episodes:
            ep_result = results_dict.get(ep.id)
            if ep_result:
                er = ExtractionResult.from_dict(ep_result, episode_id=ep.id)
                er.episode_type = self._clamp_episode_type(er.episode_type)
                output[ep.id] = er
        return output

    def store_extraction_result(self, episode: Episode, result: ExtractionResult) -> None:
        episode.episode_type = result.episode_type
        episode.title = result.title
        episode.entities_extracted = True
        episode.relations_extracted = True

        prior_ids = list(episode.entity_ids or [])
        seen: set[str] = set(prior_ids)
        final_entity_ids = list(prior_ids)
        id_remap: dict[str, str] = {}

        for entity in result.entities:
            existing = self.store.find_entity_by_name(entity.display_name)
            if existing:
                entity_id = existing.id
                if entity.type != existing.type:
                    existing.type = entity.type
                    self.store.add_entity(existing)
            else:
                self.store.add_entity(entity)
                entity_id = entity.id

            id_remap[entity.id] = entity_id
            if entity_id not in seen:
                seen.add(entity_id)
                final_entity_ids.append(entity_id)
            self.store.add_mention(episode.id, entity_id)

        episode.entity_ids = final_entity_ids
        episode.updated_at = datetime.now()
        self.store.update_episode(episode)
        self._persist_entity_relations(result.entity_relations, id_remap)

    def store_relations_result(self, episode: Episode, relations: list[EntityRelation]) -> None:
        self._persist_entity_relations(relations, {})
        episode.relations_extracted = True
        episode.updated_at = datetime.now()
        self.store.update_episode(episode)

    async def extract_and_store(self, episode: Episode) -> ExtractionResult:
        result = await self.extract(episode.content, episode_id=episode.id)
        self.store_extraction_result(episode, result)
        logger.debug(
            f"Stored extraction for {episode.id}: type={result.episode_type}, "
            f"entities={[e.id for e in result.entities]}, relations={len(result.entity_relations)}"
        )
        return result

    async def extract_relations_only(self, episode: Episode) -> list[EntityRelation]:
        if not episode.entity_ids or len(episode.entity_ids) < 2:
            return []

        existing_pairs = self.store.get_existing_relation_pairs(episode.entity_ids)
        related_pairs = set()
        for source, target in existing_pairs:
            related_pairs.add((source, target))
            related_pairs.add((target, source))

        entities_with_unrelated = set()
        for i, e1 in enumerate(episode.entity_ids):
            for e2 in episode.entity_ids[i + 1:]:
                if (e1, e2) not in related_pairs:
                    entities_with_unrelated.add(e1)
                    entities_with_unrelated.add(e2)
        if not entities_with_unrelated:
            return []

        filtered_entities = [e for e in episode.entity_ids if e in entities_with_unrelated]
        normalized_to_original: dict[str, str] = {}
        for eid in filtered_entities:
            etype, ename = Entity.parse_id(eid)
            normalized = Entity.make_id(etype, normalize_entity_name(ename))
            normalized_to_original[normalized] = eid

        content = episode.content
        if len(content) > MAX_CONTENT_LENGTH:
            content = content[:MAX_CONTENT_LENGTH] + "...[truncated]"
        prompt = RELATIONS_ONLY_PROMPT_TEMPLATE.format(content=content, entities=", ".join(filtered_entities))
        logger.debug(
            "Relations-only extraction LLM request:\n"
            f"  provider: {self.llm.name}\n"
            f"  episode_id: {episode.id}\n"
            f"  entities: {len(filtered_entities)}\n"
            f"  content_length: {len(content)}\n"
            f"  prompt:\n{prompt}"
        )

        try:
            response = await self.llm.complete_structured_text(
                prompt=prompt,
                system=EXTRACTION_SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=512,
            )
            logger.debug(
                "Relations-only extraction LLM structured response:\n"
                f"  episode_id: {episode.id}\n"
                f"  response_length: {len(response)}\n"
                f"  response:\n{response}"
            )
            parsed = parse_relations_only_csv(response)
        except (ProtocolParseError, ValueError, KeyError, IndexError) as e:
            logger.debug(f"Relations CSV parse failed, trying JSON fallback: {e}")
            try:
                parsed = await self.llm.complete_json(
                    prompt=prompt,
                    system=EXTRACTION_SYSTEM_PROMPT.replace("ONLY CSV rows", "valid JSON only"),
                    temperature=0.1,
                    max_tokens=512,
                )
                logger.debug(
                    "Relations-only extraction JSON fallback response:\n"
                    f"  episode_id: {episode.id}\n"
                    f"  response:\n{json.dumps(parsed, indent=2)}"
                )
            except Exception as fallback_err:
                logger.warning(f"Relation extraction failed for {episode.id}: {fallback_err}")
                return []
        except Exception as e:
            logger.warning(f"Relation extraction failed for {episode.id}: {e}")
            return []

        relations: list[EntityRelation] = []
        for rel in parsed.get("entity_relationships", []):
            source = rel.get("source")
            target = rel.get("target")
            relationship = rel.get("relationship")
            if not (source and target and relationship):
                continue
            source_type, source_name = Entity.parse_id(source)
            target_type, target_name = Entity.parse_id(target)
            normalized_source = Entity.make_id(source_type, normalize_entity_name(source_name))
            normalized_target = Entity.make_id(target_type, normalize_entity_name(target_name))
            original_source = normalized_to_original.get(normalized_source)
            original_target = normalized_to_original.get(normalized_target)
            if original_source and original_target and (original_source, original_target) not in related_pairs:
                relations.append(
                    EntityRelation(
                        source_id=original_source,
                        target_id=original_target,
                        relation_type=relationship,
                        strength=rel.get("strength", 0.5),
                        context=rel.get("context"),
                        source_episode_id=episode.id,
                    )
                )
        return relations

    async def extract_and_store_relations_only(self, episode: Episode) -> int:
        relations = await self.extract_relations_only(episode)
        self.store_relations_result(episode, relations)
        return len(relations)


async def extract_for_remember(
    llm: LLMProvider,
    store: MemoryStore,
    episode: Episode,
    auto_extract: bool = True,
) -> Episode:
    if not auto_extract:
        return episode

    extractor = EntityExtractor(llm, store)
    try:
        result = await extractor.extract(episode.content, episode_id=episode.id)
        episode.episode_type = result.episode_type
        episode.entity_ids = [e.id for e in result.entities]
        episode.entities_extracted = True
        episode.relations_extracted = True
        episode.metadata["_pending_entities"] = [e.to_dict() for e in result.entities]
        episode.metadata["_pending_entity_relations"] = [r.to_dict() for r in result.entity_relations]
    except Exception as e:
        logger.warning(f"Auto-extraction failed, continuing without: {e}")
    return episode

