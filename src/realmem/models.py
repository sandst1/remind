"""Core data models for the memory system."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid
import json


class RelationType(Enum):
    """Types of relationships between concepts."""
    
    IMPLIES = "implies"           # A implies B (if A then likely B)
    CONTRADICTS = "contradicts"   # A contradicts B (tension/conflict)
    SPECIALIZES = "specializes"   # A is a more specific version of B
    GENERALIZES = "generalizes"   # A is a more general version of B
    CAUSES = "causes"             # A causally leads to B
    CORRELATES = "correlates"     # A and B tend to co-occur
    PART_OF = "part_of"           # A is a component/aspect of B
    CONTEXT_OF = "context_of"     # A provides context for understanding B


@dataclass
class Relation:
    """A directed relationship between two concepts."""
    
    type: RelationType
    target_id: str
    strength: float = 0.5  # 0.0 - 1.0, how strong is this relation
    context: Optional[str] = None  # when/where does this relation hold?
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "type": self.type.value,
            "target_id": self.target_id,
            "strength": self.strength,
            "context": self.context,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Relation":
        """Deserialize from dictionary."""
        return cls(
            type=RelationType(data["type"]),
            target_id=data["target_id"],
            strength=data.get("strength", 0.5),
            context=data.get("context"),
        )


@dataclass
class Concept:
    """
    A generalized concept extracted from episodic memories.
    
    This is the core unit of semantic memory - not a verbatim record
    but a generalized understanding derived from multiple experiences.
    """
    
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    
    # The generalized understanding in natural language
    summary: str = ""
    
    # Confidence and evidence tracking
    confidence: float = 0.5  # 0.0 - 1.0
    instance_count: int = 1  # how many episodes support this concept
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    # Relational structure (edges in the concept graph)
    relations: list[Relation] = field(default_factory=list)
    
    # Grounding to episodes
    source_episodes: list[str] = field(default_factory=list)  # episode IDs
    
    # Applicability constraints
    conditions: Optional[str] = None  # when does this concept apply?
    exceptions: list[str] = field(default_factory=list)  # known exceptions
    
    # For retrieval
    embedding: Optional[list[float]] = None
    tags: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        """Serialize to dictionary for storage."""
        return {
            "id": self.id,
            "summary": self.summary,
            "confidence": self.confidence,
            "instance_count": self.instance_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "relations": [r.to_dict() for r in self.relations],
            "source_episodes": self.source_episodes,
            "conditions": self.conditions,
            "exceptions": self.exceptions,
            "embedding": self.embedding,
            "tags": self.tags,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Concept":
        """Deserialize from dictionary."""
        return cls(
            id=data["id"],
            summary=data["summary"],
            confidence=data.get("confidence", 0.5),
            instance_count=data.get("instance_count", 1),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else datetime.now(),
            relations=[Relation.from_dict(r) for r in data.get("relations", [])],
            source_episodes=data.get("source_episodes", []),
            conditions=data.get("conditions"),
            exceptions=data.get("exceptions", []),
            embedding=data.get("embedding"),
            tags=data.get("tags", []),
        )
    
    def add_relation(self, relation: Relation) -> None:
        """Add a relation, updating if same type+target exists."""
        for i, existing in enumerate(self.relations):
            if existing.type == relation.type and existing.target_id == relation.target_id:
                # Update existing relation
                self.relations[i] = relation
                return
        self.relations.append(relation)
    
    def get_relations_by_type(self, rel_type: RelationType) -> list[Relation]:
        """Get all relations of a specific type."""
        return [r for r in self.relations if r.type == rel_type]


@dataclass
class Episode:
    """
    A raw episodic memory - a specific interaction or experience.
    
    Episodes are temporary and get consolidated into concepts.
    Think of these as "working memory" that gets processed during "sleep".
    """
    
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: datetime = field(default_factory=datetime.now)
    
    # The raw interaction content
    content: str = ""
    
    # Optional compressed summary (created during consolidation)
    summary: Optional[str] = None
    
    # Which concepts were activated when this episode occurred
    concepts_activated: list[str] = field(default_factory=list)
    
    # Has this episode been processed into concepts?
    consolidated: bool = False
    
    # Optional metadata
    metadata: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """Serialize to dictionary for storage."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "content": self.content,
            "summary": self.summary,
            "concepts_activated": self.concepts_activated,
            "consolidated": self.consolidated,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Episode":
        """Deserialize from dictionary."""
        return cls(
            id=data["id"],
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.now(),
            content=data.get("content", ""),
            summary=data.get("summary"),
            concepts_activated=data.get("concepts_activated", []),
            consolidated=data.get("consolidated", False),
            metadata=data.get("metadata", {}),
        )


@dataclass
class ConsolidationResult:
    """Result of a consolidation operation."""
    
    episodes_processed: int = 0
    concepts_created: int = 0
    concepts_updated: int = 0
    contradictions_found: int = 0
    
    # Details for debugging/inspection
    created_concept_ids: list[str] = field(default_factory=list)
    updated_concept_ids: list[str] = field(default_factory=list)
    contradiction_details: list[dict] = field(default_factory=list)

