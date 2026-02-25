"""Memory decay system for concept confidence management."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging

from remind.models import Concept, AccessEvent, RelationType
from remind.store import MemoryStore

logger = logging.getLogger(__name__)


@dataclass
class DecayResult:
    """Result of a decay operation."""
    
    concepts_decayed: int = 0
    concepts_reinforced: int = 0
    access_events_processed: int = 0
    confidence_changes: list[dict] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "concepts_decayed": self.concepts_decayed,
            "concepts_reinforced": self.concepts_reinforced,
            "access_events_processed": self.access_events_processed,
            "confidence_changes": self.confidence_changes,
        }


class MemoryDecayer:
    """
    Applies memory decay and reinforcement to concepts.
    
    Memory decay simulates how human memory works:
    - Concepts gradually lose confidence over time (decay)
    - Frequently accessed concepts are reinforced (strengthened)
    - Reinforcement spreads to related concepts via the graph
    """
    
    def __init__(
        self,
        store: MemoryStore,
        decay_rate: float = 0.95,
        reinforcement_spread_depth: int = 2,
        reinforcement_spread_decay: float = 0.7,
    ):
        """
        Initialize the memory decayer.
        
        Args:
            store: The memory store to read/write concepts and access events.
            decay_rate: Multiplier applied to all concept confidences (0.0-1.0).
                       Default 0.95 = 5% decay per batch.
            reinforcement_spread_depth: How many hops to spread reinforcement.
            reinforcement_spread_decay: Decay factor per hop when spreading.
        """
        self.store = store
        self.decay_rate = decay_rate
        self.reinforcement_spread_depth = reinforcement_spread_depth
        self.reinforcement_spread_decay = reinforcement_spread_decay
    
    def decay(self) -> DecayResult:
        """
        Apply decay and reinforcement to all concepts.
        
        Process:
        1. Get all concepts and apply relative decay to confidence
        2. Get access events and reinforce accessed concepts
        3. Spread reinforcement to neighbors via relations
        4. Update access tracking fields on reinforced concepts
        5. Save updated concepts back to store
        6. Clear access events and reset recall counter
        
        Returns:
            DecayResult with statistics about the operation.
        """
        result = DecayResult()
        
        # Step 1: Get all concepts and apply decay
        concepts = self.store.get_all_concepts()
        if not concepts:
            logger.debug("No concepts to decay")
            return result
        
        # Build a map of concept_id -> Concept for quick lookup
        concept_map = {c.id: c for c in concepts}
        
        # Track which concepts were reinforced
        reinforced_concepts = set()
        
        # Step 2: Apply decay to all concepts
        for concept in concepts:
            old_confidence = concept.confidence
            new_confidence = old_confidence * self.decay_rate
            # Clamp to valid range
            concept.confidence = max(0.0, min(1.0, new_confidence))
            concept.updated_at = datetime.now()
            
            if concept.confidence < old_confidence:
                result.concepts_decayed += 1
            
            result.confidence_changes.append({
                "concept_id": concept.id,
                "old_confidence": old_confidence,
                "new_confidence": concept.confidence,
                "reason": "decay",
            })
        
        # Step 3: Get access events and reinforce
        access_events = self.store.get_access_events()
        result.access_events_processed = len(access_events)
        
        if access_events:
            logger.info(f"Processing {len(access_events)} access events for reinforcement")
            
            # Group access events by concept_id, keeping max activation
            concept_activations: dict[str, float] = {}
            for event in access_events:
                if event.concept_id not in concept_activations:
                    concept_activations[event.concept_id] = event.activation
                else:
                    concept_activations[event.concept_id] = max(
                        concept_activations[event.concept_id],
                        event.activation,
                    )
            
            # Reinforce accessed concepts and spread to neighbors
            for concept_id, activation in concept_activations.items():
                if concept_id in concept_map:
                    self._reinforce_concept(
                        concept_map[concept_id],
                        activation,
                        concept_map,
                        reinforced_concepts,
                        result,
                    )
        
        # Step 4: Save updated concepts back to store
        for concept in concepts:
            self.store.update_concept(concept)
        
        # Step 5: Clear access events and reset recall counter
        self.store.clear_access_events()
        self.store.reset_recall_count()
        
        logger.info(
            f"Decay complete: {result.concepts_decayed} concepts decayed, "
            f"{result.concepts_reinforced} reinforced, "
            f"{result.access_events_processed} access events processed"
        )
        
        return result
    
    def _reinforce_concept(
        self,
        concept: Concept,
        activation: float,
        concept_map: dict[str, Concept],
        reinforced_concepts: set[str],
        result: DecayResult,
        depth: int = 0,
        current_strength: Optional[float] = None,
    ) -> None:
        """
        Reinforce a concept and spread to neighbors.
        
        Args:
            concept: The concept to reinforce.
            activation: The activation level from access (0.0-1.0).
            concept_map: Map of concept_id -> Concept for neighbor lookup.
            reinforced_concepts: Set of already-reinforced concept IDs.
            result: Accumulator for statistics.
            depth: Current depth in spreading (0 = direct access).
            current_strength: Current reinforcement strength after decay.
        """
        if concept.id in reinforced_concepts:
            return
        
        if current_strength is None:
            current_strength = activation
        
        # Apply reinforcement: confidence = max(confidence, activation)
        old_confidence = concept.confidence
        new_confidence = max(old_confidence, current_strength)
        
        # Only update if there's an actual change
        if new_confidence > old_confidence:
            concept.confidence = new_confidence
            concept.updated_at = datetime.now()
            concept.last_accessed_at = datetime.now()
            concept.access_count += 1
            
            reinforced_concepts.add(concept.id)
            result.concepts_reinforced += 1
            
            result.confidence_changes.append({
                "concept_id": concept.id,
                "old_confidence": old_confidence,
                "new_confidence": new_confidence,
                "reason": "reinforcement",
                "activation": activation,
                "depth": depth,
            })
            
            logger.debug(
                f"Reinforced concept {concept.id}: "
                f"{old_confidence:.3f} -> {new_confidence:.3f} "
                f"(activation={activation:.3f}, depth={depth})"
            )
        
        # Spread to neighbors if we haven't reached max depth
        if depth < self.reinforcement_spread_depth:
            next_strength = current_strength * self.reinforcement_spread_decay
            
            for relation in concept.relations:
                target_id = relation.target_id
                if target_id in concept_map and target_id not in reinforced_concepts:
                    target_concept = concept_map[target_id]
                    self._reinforce_concept(
                        target_concept,
                        activation,
                        concept_map,
                        reinforced_concepts,
                        result,
                        depth + 1,
                        next_strength * relation.strength,
                    )