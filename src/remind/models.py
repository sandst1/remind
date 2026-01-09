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


class EpisodeType(Enum):
    """Types of episodic memories."""
    
    OBSERVATION = "observation"   # Default - something noticed or learned
    DECISION = "decision"         # A choice or decision that was made
    QUESTION = "question"         # An open question or uncertainty
    META = "meta"                 # Meta-cognition about patterns/processes
    PREFERENCE = "preference"     # A preference, value, or opinion


class EntityType(Enum):
    """Types of entities that can be mentioned in episodes."""

    FILE = "file"                 # Source file (e.g., "file:src/auth.ts")
    FUNCTION = "function"         # Function or method (e.g., "function:authenticate")
    CLASS = "class"               # Class or type (e.g., "class:UserService")
    MODULE = "module"             # Module or package (e.g., "module:auth")
    SUBJECT = "subject"           # Abstract subject/topic (e.g., "subject:caching")
    PERSON = "person"             # Person (e.g., "person:alice")
    PROJECT = "project"           # Project (e.g., "project:backend-api")
    TOOL = "tool"                 # Tool or technology (e.g., "tool:redis")
    OTHER = "other"               # Catch-all for other entity types


# Valid entity type prefixes for ID validation
VALID_ENTITY_TYPE_PREFIXES = {t.value for t in EntityType}


def normalize_entity_name(name: str) -> str:
    """Normalize entity name for consistent matching and ID generation.

    - Strips leading/trailing whitespace
    - Collapses multiple spaces into one
    - Converts to lowercase for case-insensitive matching

    Args:
        name: The entity name to normalize

    Returns:
        Normalized name, or "unknown" if name is empty/None
    """
    if not name:
        return "unknown"
    return " ".join(name.lower().split())


@dataclass
class Entity:
    """
    An entity that can be mentioned in episodes.
    
    Entities are external referents - files, functions, people, concepts, etc.
    They form a graph alongside concepts, connected through mentions.
    """
    
    id: str  # e.g., "file:src/auth.ts", "person:alice", "subject:caching"
    type: EntityType
    display_name: Optional[str] = None  # Human-readable name
    created_at: datetime = field(default_factory=datetime.now)
    
    # Optional metadata
    metadata: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "id": self.id,
            "type": self.type.value,
            "display_name": self.display_name,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Entity":
        """Deserialize from dictionary."""
        return cls(
            id=data["id"],
            type=EntityType(data["type"]),
            display_name=data.get("display_name"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            metadata=data.get("metadata", {}),
        )
    
    @classmethod
    def parse_id(cls, entity_id: str) -> tuple[str, str]:
        """Parse entity ID into (type, name). E.g., 'file:src/auth.ts' -> ('file', 'src/auth.ts')"""
        if ":" in entity_id:
            type_str, name = entity_id.split(":", 1)
            return type_str, name
        # No prefix - assume subject
        return "subject", entity_id
    
    @classmethod
    def make_id(cls, entity_type: str, name: str) -> str:
        """Create entity ID from type and name."""
        return f"{entity_type}:{name}"


@dataclass
class EntityRelation:
    """
    A relationship between two entities, extracted from episode content.

    Unlike concept relations which use typed enums, entity relations use
    free-form strings since entities can represent anything across domains.
    """

    source_id: str  # Entity ID (e.g., "person:alice")
    target_id: str  # Entity ID (e.g., "person:bob")
    relation_type: str  # Free-form string (e.g., "manages", "imports", "authored")
    strength: float = 0.5  # 0.0-1.0 confidence
    context: Optional[str] = None  # When/where this relation holds
    source_episode_id: Optional[str] = None  # Provenance - which episode established this
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Serialize to dictionary."""
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation_type": self.relation_type,
            "strength": self.strength,
            "context": self.context,
            "source_episode_id": self.source_episode_id,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EntityRelation":
        """Deserialize from dictionary."""
        return cls(
            source_id=data["source_id"],
            target_id=data["target_id"],
            relation_type=data["relation_type"],
            strength=data.get("strength", 0.5),
            context=data.get("context"),
            source_episode_id=data.get("source_episode_id"),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
        )


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

    # Short title for the concept (5-10 words)
    title: Optional[str] = None

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
            "title": self.title,
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
            title=data.get("title"),
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

    # Short title for the episode (5-10 words)
    title: Optional[str] = None

    # The raw interaction content
    content: str = ""
    
    # Episode type classification (defaults to observation for backwards compat)
    episode_type: EpisodeType = EpisodeType.OBSERVATION
    
    # Optional compressed summary (created during consolidation)
    summary: Optional[str] = None
    
    # Which concepts were activated when this episode occurred
    concepts_activated: list[str] = field(default_factory=list)
    
    # Entity IDs mentioned in this episode (e.g., ["file:src/auth.ts", "subject:caching"])
    entity_ids: list[str] = field(default_factory=list)
    
    # Has this episode been processed into concepts?
    consolidated: bool = False
    
    # Has entity extraction been performed on this episode?
    entities_extracted: bool = False

    # Has entity relationship extraction been performed on this episode?
    relations_extracted: bool = False

    # How certain is this information? (0.0-1.0, default 1.0 = fully certain)
    confidence: float = 1.0

    # Optional metadata
    metadata: dict = field(default_factory=dict)
    
    def to_dict(self) -> dict:
        """Serialize to dictionary for storage."""
        return {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "title": self.title,
            "content": self.content,
            "episode_type": self.episode_type.value,
            "summary": self.summary,
            "concepts_activated": self.concepts_activated,
            "entity_ids": self.entity_ids,
            "consolidated": self.consolidated,
            "entities_extracted": self.entities_extracted,
            "relations_extracted": self.relations_extracted,
            "confidence": self.confidence,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Episode":
        """Deserialize from dictionary."""
        # Handle backwards compatibility for episode_type
        episode_type = EpisodeType.OBSERVATION
        if data.get("episode_type"):
            try:
                episode_type = EpisodeType(data["episode_type"])
            except ValueError:
                episode_type = EpisodeType.OBSERVATION
        
        return cls(
            id=data["id"],
            timestamp=datetime.fromisoformat(data["timestamp"]) if data.get("timestamp") else datetime.now(),
            title=data.get("title"),
            content=data.get("content", ""),
            episode_type=episode_type,
            summary=data.get("summary"),
            concepts_activated=data.get("concepts_activated", []),
            entity_ids=data.get("entity_ids", []),
            consolidated=data.get("consolidated", False),
            entities_extracted=data.get("entities_extracted", False),
            relations_extracted=data.get("relations_extracted", False),
            confidence=data.get("confidence", 1.0),
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


@dataclass
class ExtractionResult:
    """Result of entity/type extraction from an episode."""

    episode_type: EpisodeType
    title: Optional[str] = None
    entities: list[Entity] = field(default_factory=list)
    entity_relations: list[EntityRelation] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict, episode_id: Optional[str] = None) -> "ExtractionResult":
        """Create from LLM extraction response."""
        # Parse episode type
        episode_type = EpisodeType.OBSERVATION
        if data.get("type"):
            try:
                episode_type = EpisodeType(data["type"])
            except ValueError:
                pass

        # Parse title
        title = data.get("title")

        # Parse entities
        entities = []
        for e in data.get("entities", []):
            # Parse entity type, defaulting to OTHER if invalid/missing
            try:
                entity_type = EntityType(e.get("type", "other"))
            except ValueError:
                entity_type = EntityType.OTHER

            # Get entity name and normalize it for ID generation
            raw_name = e.get("name", "")
            normalized_name = normalize_entity_name(raw_name)

            # Always generate entity ID from type:normalized_name
            # This ensures consistent IDs regardless of what the LLM provides
            entity_id = Entity.make_id(entity_type.value, normalized_name)

            entities.append(Entity(
                id=entity_id,
                type=entity_type,
                display_name=raw_name or normalized_name,  # Preserve original casing for display
            ))

        # Parse entity relationships
        entity_relations = []
        for rel in data.get("entity_relationships", []):
            source = rel.get("source")
            target = rel.get("target")
            relationship = rel.get("relationship")

            if source and target and relationship:
                entity_relations.append(EntityRelation(
                    source_id=source,
                    target_id=target,
                    relation_type=relationship,
                    strength=rel.get("strength", 0.5),
                    context=rel.get("context"),
                    source_episode_id=episode_id,
                ))

        return cls(episode_type=episode_type, title=title, entities=entities, entity_relations=entity_relations)


