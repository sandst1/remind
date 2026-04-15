"""
Consolidation engine - the "sleep" process that generalizes episodes into concepts.

This is where the magic happens. Consolidation runs in two phases:

1. **Extraction Phase**: Classify episode types and extract entity mentions
   from episodes that haven't been processed yet.

2. **Generalization Phase**: The LLM reviews episodic memories and extracts
   generalized concepts, identifies patterns, updates existing knowledge,
   and resolves contradictions.
"""

import asyncio
from datetime import datetime
from typing import Callable, Optional
import json
import logging

from remind.llm_protocol import (
    ProtocolParseError,
    parse_consolidation_csv,
)
from remind.models import Concept, Episode, Relation, RelationType, ConsolidationResult, ExtractionResult
from remind.store import MemoryStore
from remind.providers.base import LLMProvider, EmbeddingProvider
from remind.extraction import EntityExtractor

logger = logging.getLogger(__name__)


CONSOLIDATION_SYSTEM_PROMPT = """You are a memory consolidation system. Your role is to:

1. Analyze episodic memories (raw experiences/interactions)
2. Extract grounded, specific concepts (not abstract truisms)
3. Identify relationships between concepts
4. Update existing knowledge when new information refines it
5. Flag contradictions and superseded knowledge

CRITICAL — SPECIFICITY OVER ABSTRACTION:
- If the source episodes are about a specific system, project, or domain, the concept
  should reflect that specificity. Do NOT abstract away context that makes the concept useful.
  GOOD: "We chose SQLite for zero-dependency local deploys"
  BAD: "Storage decisions involve tradeoffs between simplicity and scalability"
- Every concept summary must be falsifiable — it must be possible to say "this is wrong"
  based on future evidence. Generic truisms ("teams make tradeoffs") are NOT valid concepts.

For FACT episodes (type=fact), preserve specific details VERBATIM in concept summaries.
Do NOT generalize away concrete values, names, configurations, dates, or version numbers.
A fact episode like "Redis cache TTL is 300s" should appear in the concept summary as-is,
not abstracted to "moderate TTL values." Multiple related facts can consolidate into a single
concept that lists all the concrete details.

For OUTCOME episodes, look specifically for:
- Strategy-outcome patterns: "strategy X tends to succeed/fail in context Y"
- Use 'causes' relations to connect strategies to outcomes
- Use 'contradicts' when a strategy that usually works fails, or vice versa

For SUPERSEDED knowledge:
- When new information clearly replaces an older concept, use 'supersedes' relation type.
  Example: "We switched from session cookies to JWT" → new concept supersedes the old one.
- The superseded concept retains its history but is marked as replaced."""


CONSOLIDATION_PROMPT_TEMPLATE = """## EXISTING CONCEPTUAL MEMORY

{existing_concepts}

## NEW EPISODES TO INTEGRATE

{episodes}

---

Analyze these new episodes in the context of existing memory. Perform consolidation:

1. **Pattern Recognition**: What patterns or themes appear across these episodes?
2. **Concept Updates**: Which existing concepts should be refined, strengthened, or given new exceptions?
3. **New Concepts**: What new generalized understandings emerge that aren't covered by existing concepts?
4. **Relations**: What relationships exist between concepts (implies, contradicts, specializes, causes, etc.)?
5. **Contradictions**: Does any new information contradict existing concepts?

Return ONLY rows inside these tags:
BEGIN CONSOLIDATION_OPS
ANALYSIS,<analysis_text>
UPDATE,<c-id>,<new_title>,<new_summary>,<confidence_delta>,<topic_id>
UPDATE_SOURCE,<c-id>,<ep-id>
UPDATE_EXCEPTION,<c-id>,<exception>
UPDATE_TAG,<c-id>,<tag>
UPDATE_RELATION,<c-id>,<relation_type>,<target_c-id>,<strength>,<context>
NEW_CONCEPT,<temp_id>,<title>,<summary>,<confidence>,<conditions>,<topic_id>
NEW_SOURCE,<temp_id>,<ep-id>
NEW_EXCEPTION,<temp_id>,<exception>
NEW_TAG,<temp_id>,<tag>
NEW_RELATION,<source_id>,<relation_type>,<target_id>,<strength>,<context>
CONTRADICTION,<c-id>,<evidence>,<resolution>
END CONSOLIDATION_OPS

ID prefixes: concept IDs start with "c-", episode IDs start with "ep-". Use them exactly as shown.
Relation types must be full words:
implies, contradicts, specializes, generalizes, causes, correlates, part_of, context_of, supersedes

Use temp IDs NEW_0, NEW_1, ... for new concepts.
For relations to existing concepts, use c-prefixed IDs from EXISTING CONCEPTUAL MEMORY.
Use CSV quoting when fields contain commas.
Be conservative: only include entries with clear evidence."""


class Consolidator:
    """
    The consolidation engine - processes episodic memories into generalized concepts.
    
    This is analogous to what the brain does during sleep: replay experiences,
    extract patterns, and integrate new knowledge into existing schemas.
    
    Consolidation happens in two phases:
    1. Extraction: Classify episode types and extract entity mentions
    2. Generalization: Create/update concepts from patterns across episodes
    """
    
    def __init__(
        self,
        llm: LLMProvider,
        embedding: EmbeddingProvider,
        store: MemoryStore,
        consolidation_batch_size: int = 25,
        extraction_batch_size: int = 50,
        extraction_llm_batch_size: int = 10,
        min_confidence: float = 0.3,
        concepts_per_pass: int = 64,
        llm_concurrency: int = 3,
        valid_types: Optional[list[str]] = None,
        # Legacy aliases (kept for backward compatibility)
        batch_size: Optional[int] = None,
        concepts_per_consolidation_pass: Optional[int] = None,
        max_workers: Optional[int] = None,
        entity_extraction_batch_size: Optional[int] = None,
    ):
        # Legacy aliases override defaults when explicitly provided.
        if batch_size is not None:
            consolidation_batch_size = batch_size
        if concepts_per_consolidation_pass is not None:
            concepts_per_pass = concepts_per_consolidation_pass
        if max_workers is not None:
            llm_concurrency = max_workers
        if entity_extraction_batch_size is not None:
            extraction_llm_batch_size = entity_extraction_batch_size

        self.llm = llm
        self.embedding = embedding
        self.store = store
        self.consolidation_batch_size = consolidation_batch_size
        self.extraction_batch_size = extraction_batch_size
        self.extraction_llm_batch_size = extraction_llm_batch_size
        self.min_confidence = min_confidence
        self.concepts_per_pass = concepts_per_pass
        self.llm_concurrency = llm_concurrency
        self.topic_parallelism = llm_concurrency
        self._llm_semaphore = asyncio.Semaphore(llm_concurrency)
        self._topic_semaphore = asyncio.Semaphore(self.topic_parallelism)
        self.extractor = EntityExtractor(llm, store, valid_types=valid_types)
    
    async def consolidate(
        self,
        force: bool = False,
        on_batch_complete: Optional[Callable[[int, ConsolidationResult], None]] = None,
        on_extraction_batch_complete: Optional[Callable[[dict], None]] = None,
    ) -> ConsolidationResult:
        """
        Run a full consolidation pass, processing all pending episodes in batches.
        
        This runs in two phases:
        1. Extraction: Process any episodes that haven't had entity extraction
        2. Generalization: Create/update concepts from unconsolidated episodes
        
        Phase 2 loops over batches of `consolidation_batch_size` episodes until all pending
        episodes are processed.
        
        Args:
            force: If True, process even if there aren't many episodes
            on_batch_complete: Optional callback(batch_num, batch_result) called
                after each generalization batch completes, for progress reporting.
            on_extraction_batch_complete: Optional callback(progress_dict) called
                after each extraction or relation-only extraction batch completes.
            
        Returns:
            ConsolidationResult with aggregate statistics across all batches
        """
        result = ConsolidationResult()
        
        # Phase 1: Extract entities and relationships from all unextracted episodes
        while True:
            extraction_result = await self._run_extraction_phase(
                on_extraction_batch_complete=on_extraction_batch_complete
            )
            if not extraction_result:
                break
            logger.info(
                f"Extraction phase: processed {extraction_result['episodes_processed']} episodes, "
                f"created {extraction_result['entities_created']} entities, "
                f"extracted {extraction_result['relations_extracted']} relationships"
            )
        
        # Phase 2: Generalize unconsolidated episodes into concepts, batch by batch
        batch_num = 0
        while True:
            batch_result = await self._consolidate_batch(force=force, batch_num=batch_num)
            if batch_result is None:
                break
            
            result.episodes_processed += batch_result.episodes_processed
            result.concepts_created += batch_result.concepts_created
            result.concepts_updated += batch_result.concepts_updated
            result.contradictions_found += batch_result.contradictions_found
            result.created_concept_ids.extend(batch_result.created_concept_ids)
            result.updated_concept_ids.extend(batch_result.updated_concept_ids)
            result.contradiction_details.extend(batch_result.contradiction_details)
            
            batch_num += 1
            # After the first batch, force=True so stragglers (<3 episodes) still get processed
            force = True
            
            if on_batch_complete:
                on_batch_complete(batch_num, batch_result)
        
        if batch_num > 1:
            logger.info(
                f"All batches complete ({batch_num} batches): "
                f"{result.episodes_processed} episodes, "
                f"{result.concepts_created} created, "
                f"{result.concepts_updated} updated"
            )
        
        return result

    def _partition_concepts(self, concepts: list[dict]) -> list[list[dict]]:
        """Split concepts into chunks of at most concepts_per_pass, sorted by id."""
        if not concepts:
            return [[]]
        sorted_concepts = sorted(concepts, key=lambda c: c.get("id", ""))
        n = self.concepts_per_pass
        return [sorted_concepts[i:i + n] for i in range(0, len(sorted_concepts), n)]

    def _format_concept_index(self, concepts: list[dict]) -> str:
        """Format a compact id+title index for concepts not in the current chunk."""
        if not concepts:
            return ""
        lines = []
        for c in concepts:
            title = c.get("title") or ""
            if title:
                lines.append(f"[c-{c['id']}] {title}")
            else:
                lines.append(f"[c-{c['id']}]")
        return "\n".join(lines)

    async def _consolidate_batch(self, force: bool = False, batch_num: int = 0) -> Optional[ConsolidationResult]:
        """
        Consolidate a single batch of unconsolidated episodes.
        
        Episodes are grouped by topic and each topic group is consolidated
        independently to prevent cross-topic concept bleed. When there are
        more existing concepts than concepts_per_pass, runs
        multiple LLM sub-passes (one per concept chunk) and merges the
        operations before applying them once.
        
        Returns:
            ConsolidationResult for this batch, or None if no episodes to process.
        """
        result = ConsolidationResult()
        
        episodes = self.store.get_unconsolidated_episodes(limit=self.consolidation_batch_size)
        
        if not episodes:
            logger.info("No episodes to consolidate")
            return None
        
        if len(episodes) < 3 and not force:
            logger.info(f"Only {len(episodes)} episodes, waiting for more (use force=True to override)")
            return None
        
        result.episodes_processed = len(episodes)
        batch_label = f" (batch {batch_num + 1})" if batch_num > 0 else ""
        logger.info(f"Consolidating {len(episodes)} episodes{batch_label}")

        episodes_by_topic: dict[Optional[str], list[Episode]] = {}
        for ep in episodes:
            episodes_by_topic.setdefault(ep.topic_id, []).append(ep)

        topic_count = len(episodes_by_topic)
        if topic_count > 1:
            topic_labels = [t or "(no topic)" for t in episodes_by_topic.keys()]
            logger.info(f"Consolidating {topic_count} topic groups: {', '.join(topic_labels)}")

        async def _run_topic_group(topic_id: Optional[str], topic_episodes: list[Episode]):
            async with self._topic_semaphore:
                return await self._consolidate_topic_group(topic_id, topic_episodes, batch_num, batch_label)

        topic_results = await asyncio.gather(
            *[_run_topic_group(topic_id, topic_episodes) for topic_id, topic_episodes in episodes_by_topic.items()],
            return_exceptions=True,
        )
        for topic_result in topic_results:
            if isinstance(topic_result, Exception):
                logger.error(f"Topic group consolidation failed: {topic_result}")
                # Fail fast: callers expect consolidation errors to propagate,
                # and episodes must remain unconsolidated on failure.
                raise topic_result
            if topic_result:
                result.concepts_created += topic_result.concepts_created
                result.concepts_updated += topic_result.concepts_updated
                result.contradictions_found += topic_result.contradictions_found
                result.created_concept_ids.extend(topic_result.created_concept_ids)
                result.updated_concept_ids.extend(topic_result.updated_concept_ids)
                result.contradiction_details.extend(topic_result.contradiction_details)

        # Mark episodes as consolidated
        now = datetime.now()
        for episode in episodes:
            episode.consolidated = True
            episode.updated_at = now
            self.store.update_episode(episode)
        
        logger.info(
            f"Consolidation batch complete: {result.concepts_created} created, "
            f"{result.concepts_updated} updated, {result.contradictions_found} contradictions"
        )
        
        return result

    async def _consolidate_topic_group(
        self,
        topic_id: Optional[str],
        episodes: list[Episode],
        batch_num: int,
        batch_label: str,
    ) -> Optional[ConsolidationResult]:
        """Consolidate a group of episodes belonging to the same topic."""
        result = ConsolidationResult()
        topic_label = f" [topic={topic_id}]" if topic_id else ""

        all_concepts = self.store.get_concepts_summary()
        if topic_id:
            relevant_concepts = [
                c for c in all_concepts if c.get("topic_id") == topic_id or c.get("topic_id") is None
            ]
        else:
            relevant_concepts = all_concepts

        concept_chunks = self._partition_concepts(relevant_concepts)
        episodes_text = self._format_episodes(episodes)

        merged_operations = self._empty_operations()
        num_chunks = len(concept_chunks)

        async def _consolidate_chunk(chunk_idx: int, chunk: list[dict]):
            other_concepts = [c for c in all_concepts if c not in chunk]
            other_index = self._format_concept_index(other_concepts)

            existing_section = self._format_concepts(chunk)
            if other_index:
                existing_section += "\n\n## OTHER KNOWN CONCEPTS (id + title only, for relations)\n\n" + other_index

            prompt = CONSOLIDATION_PROMPT_TEMPLATE.format(
                existing_concepts=existing_section,
                episodes=episodes_text,
            )

            sub_pass_label = f" (sub-pass {chunk_idx + 1}/{num_chunks})" if num_chunks > 1 else ""
            logger.debug(
                f"Consolidation LLM request{topic_label}{sub_pass_label}:\n"
                f"  provider: {self.llm.name}\n"
                f"  episodes: {len(episodes)}\n"
                f"  chunk_concepts: {len(chunk)}\n"
                f"  total_concepts: {len(all_concepts)}\n"
                f"  prompt_length: {len(prompt)}\n"
                f"  prompt:\n{prompt}"
            )

            async with self._llm_semaphore:
                try:
                    raw_response = await self.llm.complete_structured_text(
                        prompt=prompt,
                        system=CONSOLIDATION_SYSTEM_PROMPT,
                        temperature=0.3,
                        max_tokens=16384,
                    )
                    logger.debug(
                        f"Consolidation structured response length{topic_label}{sub_pass_label}: {len(raw_response)}"
                    )
                    logger.debug(
                        f"Consolidation structured response{topic_label}{sub_pass_label}:\n{raw_response}"
                    )
                    operations = parse_consolidation_csv(raw_response)
                except (ProtocolParseError, ValueError, KeyError, IndexError) as parse_err:
                    logger.debug(
                        f"Consolidation CSV parse failed{topic_label}{sub_pass_label}, trying JSON fallback: {parse_err}"
                    )
                    operations = await self.llm.complete_json(
                        prompt=prompt,
                        system=CONSOLIDATION_SYSTEM_PROMPT + "\n\nRespond with valid JSON only.",
                        temperature=0.3,
                        max_tokens=16384,
                    )
                    logger.debug(
                        f"Consolidation JSON fallback response{topic_label}{sub_pass_label}: "
                        f"{json.dumps(operations, indent=2)}"
                    )
                except Exception as e:
                    logger.error(f"LLM consolidation failed{topic_label}{sub_pass_label}: {e}")
                    raise

            logger.debug(f"Consolidation LLM response{topic_label}{sub_pass_label}: {json.dumps(operations, indent=2)}")
            return (chunk_idx, operations)

        chunk_results = await asyncio.gather(
            *[_consolidate_chunk(i, c) for i, c in enumerate(concept_chunks)],
        )

        for chunk_idx, operations in sorted(chunk_results, key=lambda x: x[0]):
            self._merge_operations(merged_operations, operations, chunk_idx)

        if num_chunks > 1:
            logger.info(
                f"Merged {num_chunks} concept-chunk sub-passes{topic_label}: "
                f"{len(merged_operations['updates'])} updates, "
                f"{len(merged_operations['new_concepts'])} new concepts, "
                f"{len(merged_operations['new_relations'])} relations"
            )

        if merged_operations.get("analysis"):
            logger.info(f"Consolidation analysis{topic_label}: {merged_operations['analysis']}")

        if topic_id:
            for nc in merged_operations.get("new_concepts", []):
                if not nc.get("topic_id") and not nc.get("topic"):
                    nc["topic_id"] = topic_id

        await self._apply_operations(merged_operations, result)
        return result

    @staticmethod
    def _empty_operations() -> dict:
        return {
            "analysis": "",
            "updates": [],
            "new_concepts": [],
            "new_relations": [],
            "contradictions": [],
        }

    @staticmethod
    def _merge_operations(merged: dict, ops: dict, chunk_idx: int) -> None:
        """Merge a single sub-pass's operations into the accumulator, namespacing temp ids."""
        # Join analysis strings
        analysis = ops.get("analysis", "")
        if analysis:
            if merged["analysis"]:
                merged["analysis"] += "\n" + analysis
            else:
                merged["analysis"] = analysis

        prefix = f"NEW__c{chunk_idx}__"

        def rewrite_temp_id(id_str: str) -> str:
            if id_str and id_str.startswith("NEW_"):
                return prefix + id_str[4:]  # NEW_0 -> NEW__c0__0
            return id_str

        def rewrite_relations(rels: list[dict]) -> list[dict]:
            out = []
            for r in rels:
                r = dict(r)
                if "target_id" in r:
                    r["target_id"] = rewrite_temp_id(r["target_id"])
                if "source_id" in r:
                    r["source_id"] = rewrite_temp_id(r["source_id"])
                out.append(r)
            return out

        # Updates — rewrite relation target ids within add_relations
        for update in ops.get("updates", []):
            update = dict(update)
            if "add_relations" in update:
                update["add_relations"] = rewrite_relations(update["add_relations"])
            merged["updates"].append(update)

        # New concepts — rewrite temp_id and inline relation ids
        for nc in ops.get("new_concepts", []):
            nc = dict(nc)
            if "temp_id" in nc:
                nc["temp_id"] = rewrite_temp_id(nc["temp_id"])
            if "relations" in nc:
                nc["relations"] = rewrite_relations(nc["relations"])
            merged["new_concepts"].append(nc)

        # New relations — rewrite both ends
        merged["new_relations"].extend(rewrite_relations(ops.get("new_relations", [])))

        # Contradictions — pass through
        merged["contradictions"].extend(ops.get("contradictions", []))

    async def _apply_operations(self, operations: dict, result: ConsolidationResult) -> None:
        """Apply merged consolidation operations to the store."""
        # Collect all deferred relations to process after id_mapping is built
        deferred_relations = []

        # Apply updates to existing concepts (without relations)
        for update in operations.get("updates", []):
            try:
                update_relations = update.pop("add_relations", [])
                concept_id = update["concept_id"]
                deferred_relations.extend([
                    {**rel, "_source_id": concept_id} for rel in update_relations
                ])

                await self._apply_update(update)
                result.concepts_updated += 1
                result.updated_concept_ids.append(concept_id)
            except Exception as e:
                logger.warning(f"Failed to apply update to {update.get('concept_id')}: {e}")
        
        # Create new concepts - first pass without relations
        id_mapping = {}  # temp_id -> real_id

        for i, new_concept_data in enumerate(operations.get("new_concepts", [])):
            try:
                temp_id = new_concept_data.get("temp_id", f"NEW_{i}")
                relations = new_concept_data.pop("relations", [])
                deferred_relations.extend([
                    {**rel, "_source_temp_id": temp_id} for rel in relations
                ])

                concept_id = await self._create_concept(new_concept_data)
                id_mapping[temp_id] = concept_id
                result.concepts_created += 1
                result.created_concept_ids.append(concept_id)
            except Exception as e:
                logger.warning(f"Failed to create concept: {e}")

        def resolve_id(id_str: str) -> str:
            if id_str and id_str.startswith("NEW_"):
                return id_mapping.get(id_str, id_str)
            return id_str

        # Process all deferred relations (from updates and new concepts)
        for rel in deferred_relations:
            try:
                if "_source_id" in rel:
                    source_id = rel.pop("_source_id")
                else:
                    source_id = id_mapping.get(rel.pop("_source_temp_id"))
                if not source_id:
                    continue
                rel["source_id"] = source_id
                rel["target_id"] = resolve_id(rel.get("target_id", ""))
                await self._add_relation(rel)
            except Exception as e:
                logger.warning(f"Failed to add deferred relation: {e}")

        # Add new_relations between concepts (with temp ID resolution)
        for relation_data in operations.get("new_relations", []):
            try:
                relation_data["source_id"] = resolve_id(relation_data.get("source_id", ""))
                relation_data["target_id"] = resolve_id(relation_data.get("target_id", ""))
                await self._add_relation(relation_data)
            except Exception as e:
                logger.warning(f"Failed to add relation: {e}")
        
        # Handle contradictions
        for contradiction in operations.get("contradictions", []):
            result.contradictions_found += 1
            result.contradiction_details.append(contradiction)
            logger.warning(f"Contradiction found: {contradiction}")
    
    async def _run_extraction_phase(
        self,
        on_extraction_batch_complete: Optional[Callable[[dict], None]] = None,
    ) -> dict:
        """
        Run entity extraction on episodes that haven't been processed yet.
        
        This is Phase 1 of consolidation - classifying episode types and
        extracting entity mentions. Also extracts relationships for episodes
        that have entities but haven't had relationship extraction.

        Episodes are grouped into batches of ``extraction_llm_batch_size``
        for fewer LLM calls. Multiple batches run concurrently up to
        ``llm_concurrency``.
        
        Returns:
            dict with extraction stats or None if no episodes needed extraction
        """
        episodes_processed = 0
        entities_created = 0
        relations_extracted = 0

        # Step 1: Batched entity extraction
        unextracted = self.store.get_unextracted_episodes(limit=self.extraction_batch_size)

        if unextracted:
            bs = self.extraction_llm_batch_size
            episode_batches = [unextracted[i:i + bs] for i in range(0, len(unextracted), bs)]
            logger.info(
                f"Running extraction on {len(unextracted)} episodes "
                f"({len(episode_batches)} batches of up to {bs})..."
            )

            async def _extract_batch(batch: list) -> dict:
                async with self._llm_semaphore:
                    return await self.extractor.extract_batch(batch)

            batch_results = await asyncio.gather(
                *[_extract_batch(batch) for batch in episode_batches],
                return_exceptions=True,
            )

            # Fall back to individual calls for batches that failed entirely
            fallback_episodes = []
            all_results: dict = {}
            for batch_idx, (batch, batch_result) in enumerate(
                zip(episode_batches, batch_results),
                start=1,
            ):
                batch_episodes_processed = 0
                batch_entities_created = 0
                batch_relations_extracted = 0
                status = "ok"
                if isinstance(batch_result, Exception):
                    logger.warning(f"Batch extraction failed: {batch_result}")
                    fallback_episodes.extend(batch)
                    status = "failed"
                else:
                    all_results.update(batch_result)
                    missing = [ep for ep in batch if ep.id not in batch_result]
                    fallback_episodes.extend(missing)
                    batch_episodes_processed = len(batch_result)
                    for ep_result in batch_result.values():
                        batch_entities_created += len(ep_result.entities)
                        batch_relations_extracted += len(ep_result.entity_relations)
                    if missing:
                        status = "partial"
                if on_extraction_batch_complete:
                    on_extraction_batch_complete(
                        {
                            "phase": "entity_extraction",
                            "batch_num": batch_idx,
                            "total_batches": len(episode_batches),
                            "batch_size": len(batch),
                            "episodes_processed": batch_episodes_processed,
                            "entities_created": batch_entities_created,
                            "relations_extracted": batch_relations_extracted,
                            "status": status,
                        }
                    )

            if fallback_episodes:
                logger.info(f"Falling back to individual extraction for {len(fallback_episodes)} episodes")
                for ep in fallback_episodes:
                    try:
                        result = await self.extractor.extract(ep.content, episode_id=ep.id)
                        all_results[ep.id] = result
                    except Exception as e:
                        logger.warning(f"Individual extraction also failed for {ep.id}: {e}")

            # Sequential store writes
            episode_by_id = {ep.id: ep for ep in unextracted}
            for ep_id, result in all_results.items():
                ep = episode_by_id.get(ep_id)
                if ep:
                    self.extractor.store_extraction_result(ep, result)
                    episodes_processed += 1
                    entities_created += len(result.entities)
                    relations_extracted += len(result.entity_relations)

        # Step 2: Parallel relationship-only extraction (1 call per episode)
        unextracted_relations = self.store.get_unextracted_relation_episodes(limit=self.extraction_batch_size)

        if unextracted_relations:
            logger.info(f"Extracting relationships from {len(unextracted_relations)} episodes...")

            async def _extract_rels(ep):
                async with self._llm_semaphore:
                    return (ep, await self.extractor.extract_relations_only(ep))

            rel_results = await asyncio.gather(
                *[_extract_rels(ep) for ep in unextracted_relations],
                return_exceptions=True,
            )

            for idx, item in enumerate(rel_results, start=1):
                if isinstance(item, Exception):
                    logger.warning(f"Relation extraction failed: {item}")
                    if on_extraction_batch_complete:
                        on_extraction_batch_complete(
                            {
                                "phase": "relation_extraction",
                                "batch_num": idx,
                                "total_batches": len(unextracted_relations),
                                "batch_size": 1,
                                "episodes_processed": 0,
                                "entities_created": 0,
                                "relations_extracted": 0,
                                "status": "failed",
                            }
                        )
                    continue
                episode, relations = item
                self.extractor.store_relations_result(episode, relations)
                relations_extracted += len(relations)
                episodes_processed += 1
                if on_extraction_batch_complete:
                    on_extraction_batch_complete(
                        {
                            "phase": "relation_extraction",
                            "batch_num": idx,
                            "total_batches": len(unextracted_relations),
                            "batch_size": 1,
                            "episodes_processed": 1,
                            "entities_created": 0,
                            "relations_extracted": len(relations),
                            "status": "ok",
                        }
                    )

        if episodes_processed == 0:
            return None

        return {
            "episodes_processed": episodes_processed,
            "entities_created": entities_created,
            "relations_extracted": relations_extracted,
        }
    
    def _format_concepts(self, concepts: list[dict]) -> str:
        """Format existing concepts for the prompt."""
        if not concepts:
            return "(No existing concepts yet)"

        lines = []
        for c in concepts:
            tags = ", ".join(c.get("tags", [])) if c.get("tags") else ""
            line = f"[c-{c['id']}] (conf: {c.get('confidence', 0.5):.2f}, n={c.get('instance_count', 1)})"
            if tags:
                line += f" [{tags}]"
            if c.get("topic_id"):
                line += f" topic={c['topic_id']}"
            if c.get("title"):
                line += f"\n  Title: {c['title']}"
            line += f"\n  {c['summary']}"
            lines.append(line)

        return "\n\n".join(lines)
    
    def _format_episodes(self, episodes: list[Episode]) -> str:
        """Format episodes for the prompt, including extraction results and metadata."""
        lines = []
        for ep in episodes:
            timestamp = ep.timestamp.strftime("%Y-%m-%d %H:%M")
            # Include type and confidence in header
            conf_str = f", conf={ep.confidence:.1f}" if ep.confidence < 1.0 else ""
            header = f"[ep-{ep.id}] ({timestamp}, type={ep.episode_type}{conf_str})"

            # Include entities if present
            if ep.entity_ids:
                header += f"\n  Entities: {', '.join(ep.entity_ids[:5])}"
                if len(ep.entity_ids) > 5:
                    header += f" (+{len(ep.entity_ids) - 5} more)"

            # Include metadata if present (filter out internal keys starting with _)
            if ep.metadata:
                show_meta = {k: v for k, v in ep.metadata.items() if not k.startswith("_")}
                if show_meta:
                    header += f"\n  Meta: {show_meta}"

            lines.append(f"{header}\n{ep.content}")

        return "\n\n---\n\n".join(lines)
    
    async def _apply_update(self, update: dict) -> None:
        """Apply an update to an existing concept."""
        concept_id = update["concept_id"]
        concept = self.store.get_concept(concept_id)
        
        if not concept:
            logger.warning(f"Concept {concept_id} not found for update")
            return
        
        # Update title if provided
        if update.get("new_title"):
            concept.title = update["new_title"]

        # Update summary if provided
        if update.get("new_summary"):
            concept.summary = update["new_summary"]
            # Re-embed the updated summary
            concept.embedding = await self.embedding.embed(concept.summary)
        
        # Update confidence
        if update.get("confidence_delta"):
            concept.confidence = max(0.0, min(1.0, concept.confidence + update["confidence_delta"]))
        
        # Increment instance count
        concept.instance_count += 1
        
        # Add exceptions
        for exc in update.get("add_exceptions", []):
            if exc not in concept.exceptions:
                concept.exceptions.append(exc)
        
        # Add tags
        for tag in update.get("add_tags", []):
            if tag not in concept.tags:
                concept.tags.append(tag)

        topic_val = update.get("topic_id") or update.get("topic")
        if topic_val and not concept.topic_id:
            concept.topic_id = topic_val

        # Add source episodes
        for ep_id in update.get("source_episodes", []):
            if ep_id not in concept.source_episodes:
                concept.source_episodes.append(ep_id)

        concept.updated_at = datetime.now()
        self.store.update_concept(concept)
    
    async def _create_concept(self, data: dict) -> str:
        """Create a new concept from consolidation data (relations added separately)."""
        # Validate minimum confidence
        confidence = data.get("confidence", 0.5)
        if confidence < self.min_confidence:
            logger.info(f"Skipping low-confidence concept: {data.get('summary', '')[:50]}...")
            raise ValueError(f"Confidence {confidence} below threshold {self.min_confidence}")

        # Generate embedding for the summary
        embedding = await self.embedding.embed(data["summary"])

        concept = Concept(
            title=data.get("title"),
            summary=data["summary"],
            confidence=confidence,
            instance_count=len(data.get("source_episodes", [])) or 1,
            source_episodes=data.get("source_episodes", []),
            conditions=data.get("conditions"),
            exceptions=data.get("exceptions", []),
            tags=data.get("tags", []),
            topic_id=data.get("topic_id") or data.get("topic"),
            relations=[],
            embedding=embedding,
        )

        return self.store.add_concept(concept)
    
    async def _add_relation(self, data: dict) -> None:
        """Add a relation between existing concepts."""
        source_id = data["source_id"]
        source = self.store.get_concept(source_id)
        
        if not source:
            logger.warning(f"Source concept {source_id} not found for relation")
            return
        
        # Check target exists
        target_id = data["target_id"]
        if not self.store.get_concept(target_id):
            logger.warning(f"Target concept {target_id} not found for relation")
            return
        
        relation = Relation(
            type=RelationType(data["type"]),
            target_id=target_id,
            strength=data.get("strength", 0.5),
            context=data.get("context"),
        )
        
        source.add_relation(relation)
        source.updated_at = datetime.now()
        self.store.update_concept(source)
    
    async def analyze_contradictions(self) -> list[dict]:
        """
        Analyze memory for internal contradictions.
        
        This is a separate analysis pass that looks for tensions
        within the concept graph.
        """
        concepts = self.store.get_all_concepts()
        
        if len(concepts) < 2:
            return []
        
        # Format concepts with their relations
        concept_details = []
        for c in concepts:
            detail = f"[{c.id}] {c.summary}"
            if c.conditions:
                detail += f"\n  Conditions: {c.conditions}"
            if c.exceptions:
                detail += f"\n  Exceptions: {', '.join(c.exceptions)}"
            for rel in c.relations:
                detail += f"\n  → {rel.type.value} [{rel.target_id}] (strength: {rel.strength})"
            concept_details.append(detail)
        
        prompt = f"""Analyze this concept memory for internal contradictions or tensions:

{chr(10).join(concept_details)}

Look for:
1. Direct contradictions between concept summaries
2. Logical inconsistencies in the relation graph
3. Concepts that should be related but aren't
4. Overly broad concepts that need refinement

Respond with JSON:
{{
  "contradictions": [
    {{
      "concept_ids": ["id1", "id2"],
      "description": "what the contradiction is",
      "severity": "high|medium|low",
      "suggested_resolution": "how to resolve"
    }}
  ],
  "missing_relations": [
    {{
      "source_id": "id",
      "target_id": "id",
      "suggested_type": "relation type",
      "reasoning": "why this relation should exist"
    }}
  ],
  "refinement_suggestions": [
    {{
      "concept_id": "id",
      "suggestion": "how to improve this concept"
    }}
  ]
}}"""
        
        result = await self.llm.complete_json(
            prompt=prompt,
            system="You are a memory analysis system looking for logical inconsistencies.",
            temperature=0.2,
        )
        
        return result.get("contradictions", [])

