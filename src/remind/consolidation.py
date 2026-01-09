"""
Consolidation engine - the "sleep" process that generalizes episodes into concepts.

This is where the magic happens. Consolidation runs in two phases:

1. **Extraction Phase**: Classify episode types and extract entity mentions
   from episodes that haven't been processed yet.

2. **Generalization Phase**: The LLM reviews episodic memories and extracts
   generalized concepts, identifies patterns, updates existing knowledge,
   and resolves contradictions.
"""

from datetime import datetime
from typing import Optional
import json
import logging

from remind.models import Concept, Episode, Relation, RelationType, ConsolidationResult, ExtractionResult
from remind.store import MemoryStore
from remind.providers.base import LLMProvider, EmbeddingProvider
from remind.extraction import EntityExtractor

logger = logging.getLogger(__name__)


CONSOLIDATION_SYSTEM_PROMPT = """You are a memory consolidation system. Your role is to:

1. Analyze episodic memories (raw experiences/interactions)
2. Extract generalized concepts and patterns
3. Identify relationships between concepts
4. Update existing knowledge when new information refines it
5. Flag contradictions that need resolution

You think like a cognitive scientist studying memory consolidation. 
You look for:
- Recurring patterns across experiences
- Abstract principles that generalize beyond specific instances
- Causal relationships and correlations
- Hierarchical structure (specific → general)
- Exceptions and boundary conditions

Be precise and conservative. Only create concepts when there's clear evidence.
Prefer updating existing concepts over creating redundant ones."""


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

Respond with this exact JSON structure:

{{
  "analysis": "Brief narrative of what you observed across these episodes",
  
  "updates": [
    {{
      "concept_id": "existing concept ID",
      "new_title": "updated short title (5-10 words) or null to keep existing",
      "new_summary": "refined/updated summary (or null to keep existing)",
      "confidence_delta": 0.1,
      "source_episodes": ["episode_id1", "episode_id2"],
      "add_exceptions": ["new exception if any"],
      "add_tags": ["new tag if any"],
      "reasoning": "why this update"
    }}
  ],

  "new_concepts": [
    {{
      "temp_id": "NEW_0",
      "title": "short descriptive title (5-10 words)",
      "summary": "the generalized understanding - be specific and actionable",
      "confidence": 0.6,
      "source_episodes": ["episode_id1", "episode_id2"],
      "conditions": "when/where this applies (or null if universal)",
      "exceptions": ["known exceptions"],
      "tags": ["categorization", "tags"],
      "relations": [
        {{"type": "implies|contradicts|specializes|generalizes|causes|correlates|part_of|context_of", "target_id": "existing_id or NEW_1", "strength": 0.7, "context": "when this relation holds"}}
      ]
    }}
  ],

  "new_relations": [
    {{
      "source_id": "existing_id or NEW_0",
      "target_id": "existing_id or NEW_1",
      "type": "implies|contradicts|specializes|generalizes|causes|correlates|part_of|context_of",
      "strength": 0.7,
      "context": "when this relation holds"
    }}
  ],
  
  "contradictions": [
    {{
      "concept_id": "id of concept that's contradicted",
      "evidence": "what episode content contradicts it",
      "resolution": "suggested resolution or null if unclear"
    }}
  ]
}}

IMPORTANT for new concepts: Use temp_id (NEW_0, NEW_1, etc.) to identify each new concept you create.
When creating relations between new concepts, use these temp_ids as target_id or source_id.
For relations to existing concepts, use the existing concept's ID from the EXISTING CONCEPTUAL MEMORY section.

Be conservative: only include entries that have clear evidence. Empty arrays are fine."""


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
        batch_size: int = 10,
        min_confidence: float = 0.3,
    ):
        self.llm = llm
        self.embedding = embedding
        self.store = store
        self.batch_size = batch_size
        self.min_confidence = min_confidence
        self.extractor = EntityExtractor(llm, store)
    
    async def consolidate(self, force: bool = False) -> ConsolidationResult:
        """
        Run a consolidation pass.
        
        This runs in two phases:
        1. Extraction: Process any episodes that haven't had entity extraction
        2. Generalization: Create/update concepts from unconsolidated episodes
        
        Args:
            force: If True, process even if there aren't many episodes
            
        Returns:
            ConsolidationResult with statistics about what was done
        """
        result = ConsolidationResult()
        
        # Phase 1: Extract entities from unextracted episodes
        extraction_result = await self._run_extraction_phase()
        if extraction_result:
            logger.info(
                f"Extraction phase: processed {extraction_result['episodes_processed']} episodes, "
                f"created {extraction_result['entities_created']} entities"
            )
        
        # Phase 2: Generalize unconsolidated episodes into concepts
        # Get unconsolidated episodes
        episodes = self.store.get_unconsolidated_episodes(limit=self.batch_size)
        
        if not episodes:
            logger.info("No episodes to consolidate")
            return result
        
        if len(episodes) < 3 and not force:
            logger.info(f"Only {len(episodes)} episodes, waiting for more (use force=True to override)")
            return result
        
        result.episodes_processed = len(episodes)
        logger.info(f"Consolidating {len(episodes)} episodes")
        
        # Get existing concepts for context
        existing_concepts = self.store.get_concepts_summary()
        
        # Build the consolidation prompt
        prompt = CONSOLIDATION_PROMPT_TEMPLATE.format(
            existing_concepts=self._format_concepts(existing_concepts),
            episodes=self._format_episodes(episodes),
        )
        
        # Call LLM for consolidation
        try:
            operations = await self.llm.complete_json(
                prompt=prompt,
                system=CONSOLIDATION_SYSTEM_PROMPT,
                temperature=0.3,
                max_tokens=8192,
            )
        except Exception as e:
            logger.error(f"LLM consolidation failed: {e}")
            raise
        
        # Log the analysis
        if operations.get("analysis"):
            logger.info(f"Consolidation analysis: {operations['analysis']}")
        
        # Apply updates to existing concepts
        for update in operations.get("updates", []):
            try:
                await self._apply_update(update)
                result.concepts_updated += 1
                result.updated_concept_ids.append(update["concept_id"])
            except Exception as e:
                logger.warning(f"Failed to apply update to {update.get('concept_id')}: {e}")
        
        # Create new concepts - first pass without relations
        id_mapping = {}  # temp_id -> real_id
        deferred_relations = []

        for i, new_concept_data in enumerate(operations.get("new_concepts", [])):
            try:
                temp_id = new_concept_data.get("temp_id", f"NEW_{i}")
                # Extract relations for deferred processing
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

        # Helper to resolve temp IDs to real IDs
        def resolve_id(id_str: str) -> str:
            if id_str and id_str.startswith("NEW_"):
                return id_mapping.get(id_str, id_str)
            return id_str

        # Process deferred relations from new concepts
        for rel in deferred_relations:
            try:
                source_id = id_mapping.get(rel.pop("_source_temp_id"))
                if not source_id:
                    continue
                rel["source_id"] = source_id
                rel["target_id"] = resolve_id(rel.get("target_id", ""))
                await self._add_relation(rel)
            except Exception as e:
                logger.warning(f"Failed to add deferred relation: {e}")

        # Add new relations between concepts (with temp ID resolution)
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
        
        # Mark episodes as consolidated
        for episode in episodes:
            episode.consolidated = True
            self.store.update_episode(episode)
        
        logger.info(
            f"Consolidation complete: {result.concepts_created} created, "
            f"{result.concepts_updated} updated, {result.contradictions_found} contradictions"
        )
        
        return result
    
    async def _run_extraction_phase(self) -> dict:
        """
        Run entity extraction on episodes that haven't been processed yet.
        
        This is Phase 1 of consolidation - classifying episode types and
        extracting entity mentions.
        
        Returns:
            dict with extraction stats or None if no episodes needed extraction
        """
        # Check if there are unextracted episodes
        unextracted = self.store.get_unextracted_episodes(limit=self.batch_size)
        
        if not unextracted:
            return None
        
        logger.info(f"Running extraction on {len(unextracted)} episodes...")
        
        episodes_processed = 0
        entities_created = 0
        
        for episode in unextracted:
            try:
                extraction = await self.extractor.extract_and_store(episode)
                episodes_processed += 1
                entities_created += len(extraction.entities)
            except Exception as e:
                logger.warning(f"Failed to extract from {episode.id}: {e}")
        
        return {
            "episodes_processed": episodes_processed,
            "entities_created": entities_created,
        }
    
    def _format_concepts(self, concepts: list[dict]) -> str:
        """Format existing concepts for the prompt."""
        if not concepts:
            return "(No existing concepts yet)"

        lines = []
        for c in concepts:
            tags = ", ".join(c.get("tags", [])) if c.get("tags") else ""
            line = f"[{c['id']}] (conf: {c.get('confidence', 0.5):.2f}, n={c.get('instance_count', 1)})"
            if tags:
                line += f" [{tags}]"
            # Include title if present
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
            header = f"[{ep.id}] ({timestamp}, type={ep.episode_type.value}{conf_str})"

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
            relations=[],  # Relations added via _add_relation after all concepts created
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

