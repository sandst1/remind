"""
Memory retrieval with spreading activation.

Goes beyond simple vector similarity search by leveraging the concept graph.
When you recall something, related concepts get activated through the
relationship structure, mimicking associative memory in the brain.
"""

from dataclasses import dataclass
from typing import Optional
import logging

from realmem.models import Concept, RelationType
from realmem.store import MemoryStore
from realmem.providers.base import EmbeddingProvider

logger = logging.getLogger(__name__)


@dataclass
class ActivatedConcept:
    """A concept with its activation level and retrieval metadata."""
    
    concept: Concept
    activation: float  # 0.0 - 1.0, how strongly activated
    source: str  # "embedding" or "spread"
    hops: int = 0  # how many hops from initial activation
    
    def __repr__(self) -> str:
        return f"ActivatedConcept({self.concept.id}, activation={self.activation:.3f}, source={self.source})"


class MemoryRetriever:
    """
    Retrieves relevant concepts using spreading activation.
    
    The algorithm:
    1. Embed the query
    2. Find initial matches via embedding similarity
    3. Spread activation through the concept graph
    4. Return highest-activation concepts
    
    This mimics associative memory - you don't just match keywords,
    you follow conceptual links to find related understanding.
    """
    
    def __init__(
        self,
        embedding: EmbeddingProvider,
        store: MemoryStore,
        # Retrieval parameters
        initial_k: int = 10,  # how many initial embedding matches
        spread_hops: int = 2,  # how many hops to spread
        spread_decay: float = 0.5,  # activation decay per hop
        activation_threshold: float = 0.1,  # minimum activation to spread
        # Relation type weights (how much different relations spread activation)
        relation_weights: Optional[dict[RelationType, float]] = None,
    ):
        self.embedding = embedding
        self.store = store
        self.initial_k = initial_k
        self.spread_hops = spread_hops
        self.spread_decay = spread_decay
        self.activation_threshold = activation_threshold
        
        # Default relation weights - some relations spread activation more
        self.relation_weights = relation_weights or {
            RelationType.IMPLIES: 0.9,       # Strong spreading
            RelationType.GENERALIZES: 0.85,  # Very relevant
            RelationType.SPECIALIZES: 0.85,  # Very relevant
            RelationType.PART_OF: 0.8,       # Strong conceptual link
            RelationType.CONTEXT_OF: 0.7,    # Relevant context
            RelationType.CORRELATES: 0.6,    # Moderate spreading
            RelationType.CAUSES: 0.7,        # Causal link is meaningful
            RelationType.CONTRADICTS: 0.3,   # Weak spreading (but still useful)
        }
    
    async def retrieve(
        self,
        query: str,
        k: int = 5,
        context: Optional[str] = None,
        include_weak: bool = False,
    ) -> list[ActivatedConcept]:
        """
        Retrieve relevant concepts for a query.
        
        Args:
            query: The query text
            k: Number of concepts to return
            context: Optional additional context to include in embedding
            include_weak: If True, include lower-activation concepts
            
        Returns:
            List of ActivatedConcept objects, sorted by activation
        """
        # Combine query with context if provided
        embed_text = query
        if context:
            embed_text = f"{query}\n\nContext: {context}"
        
        # Get query embedding
        query_embedding = await self.embedding.embed(embed_text)
        
        # Step 1: Initial activation from embedding similarity
        initial_matches = self.store.find_by_embedding(
            query_embedding, 
            k=self.initial_k * 2  # Get more initially, we'll filter
        )
        
        # Build activation map: concept_id -> (activation, source, hops)
        activation_map: dict[str, tuple[float, str, int]] = {}
        concept_cache: dict[str, Concept] = {}
        
        for concept, similarity in initial_matches:
            if similarity > self.activation_threshold:
                activation_map[concept.id] = (similarity, "embedding", 0)
                concept_cache[concept.id] = concept
        
        logger.debug(f"Initial activation: {len(activation_map)} concepts")
        
        # Step 2: Spreading activation
        for hop in range(self.spread_hops):
            new_activations: dict[str, tuple[float, str, int]] = {}
            
            for concept_id, (activation, _, _) in list(activation_map.items()):
                if activation < self.activation_threshold:
                    continue
                
                # Get related concepts
                related = self.store.get_related(concept_id, depth=1)
                
                for related_concept, relation in related:
                    # Calculate spread activation
                    relation_weight = self.relation_weights.get(relation.type, 0.5)
                    spread_activation = (
                        activation 
                        * relation.strength 
                        * relation_weight 
                        * (self.spread_decay ** (hop + 1))
                    )
                    
                    if spread_activation < self.activation_threshold:
                        continue
                    
                    # Keep the higher activation
                    current = activation_map.get(related_concept.id, (0, "", 0))[0]
                    spread_current = new_activations.get(related_concept.id, (0, "", 0))[0]
                    
                    if spread_activation > max(current, spread_current):
                        new_activations[related_concept.id] = (
                            spread_activation,
                            "spread",
                            hop + 1
                        )
                        concept_cache[related_concept.id] = related_concept
            
            # Merge new activations
            for cid, (act, src, hops) in new_activations.items():
                current = activation_map.get(cid, (0, "", 0))[0]
                if act > current:
                    activation_map[cid] = (act, src, hops)
            
            logger.debug(f"After hop {hop + 1}: {len(activation_map)} concepts")
        
        # Step 3: Build result list
        results = []
        for concept_id, (activation, source, hops) in activation_map.items():
            if not include_weak and activation < self.activation_threshold * 2:
                continue
            
            concept = concept_cache.get(concept_id)
            if not concept:
                concept = self.store.get_concept(concept_id)
            
            if concept:
                results.append(ActivatedConcept(
                    concept=concept,
                    activation=activation,
                    source=source,
                    hops=hops,
                ))
        
        # Sort by activation (highest first) and take top k
        results.sort(key=lambda x: x.activation, reverse=True)
        return results[:k]
    
    async def retrieve_by_tags(
        self,
        tags: list[str],
        k: int = 5,
    ) -> list[Concept]:
        """
        Retrieve concepts by tag matching.
        
        Simple tag-based retrieval, useful for categorical lookups.
        """
        all_concepts = self.store.get_all_concepts()
        
        # Score by tag overlap
        scored = []
        for concept in all_concepts:
            overlap = len(set(tags) & set(concept.tags))
            if overlap > 0:
                scored.append((concept, overlap / len(tags)))
        
        scored.sort(key=lambda x: x[1], reverse=True)
        return [c for c, _ in scored[:k]]
    
    async def find_related_chain(
        self,
        start_concept_id: str,
        end_concept_id: str,
        max_depth: int = 4,
    ) -> Optional[list[tuple[Concept, Optional[str]]]]:
        """
        Find a path between two concepts through the relation graph.
        
        Useful for understanding how concepts connect.
        
        Returns:
            List of (concept, relation_type_to_next) tuples forming the path,
            or None if no path found.
        """
        start = self.store.get_concept(start_concept_id)
        end = self.store.get_concept(end_concept_id)
        
        if not start or not end:
            return None
        
        # BFS to find path
        from collections import deque
        
        queue = deque([(start_concept_id, [(start, None)])])
        visited = {start_concept_id}
        
        while queue:
            current_id, path = queue.popleft()
            
            if current_id == end_concept_id:
                return path
            
            if len(path) >= max_depth:
                continue
            
            # Get related concepts
            related = self.store.get_related(current_id, depth=1)
            
            for concept, relation in related:
                if concept.id not in visited:
                    visited.add(concept.id)
                    new_path = path.copy()
                    # Update last item's relation type
                    if new_path:
                        last_concept, _ = new_path[-1]
                        new_path[-1] = (last_concept, relation.type.value)
                    new_path.append((concept, None))
                    
                    if concept.id == end_concept_id:
                        return new_path
                    
                    queue.append((concept.id, new_path))
        
        return None
    
    def format_for_llm(
        self,
        activated: list[ActivatedConcept],
        include_relations: bool = True,
        max_relations: int = 3,
    ) -> str:
        """
        Format retrieved concepts for injection into an LLM prompt.
        
        This is the "recall" output that gets added to context.
        """
        if not activated:
            return "(No relevant memories found)"
        
        lines = ["RELEVANT MEMORY:\n"]
        
        for ac in activated:
            c = ac.concept
            
            # Header with ID and confidence
            header = f"[{c.id}] (confidence: {c.confidence:.2f}"
            if ac.source == "spread":
                header += f", via association"
            header += ")"
            lines.append(header)
            
            # Summary
            lines.append(f"  {c.summary}")
            
            # Conditions/Exceptions
            if c.conditions:
                lines.append(f"  → Applies when: {c.conditions}")
            if c.exceptions:
                lines.append(f"  → Exceptions: {', '.join(c.exceptions[:3])}")
            
            # Key relations
            if include_relations and c.relations:
                shown = 0
                for rel in c.relations:
                    if shown >= max_relations:
                        break
                    
                    # Get target concept summary
                    target = self.store.get_concept(rel.target_id)
                    if target:
                        rel_str = f"  → {rel.type.value}: {target.summary[:60]}"
                        if len(target.summary) > 60:
                            rel_str += "..."
                        lines.append(rel_str)
                        shown += 1
            
            lines.append("")  # Blank line between concepts
        
        return "\n".join(lines)

