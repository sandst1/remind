"""
Remind: Agent-driven memory layer for LLMs.

A hierarchical memory system featuring:
- Episodic buffers for raw experiences
- Semantic concept graphs with typed relations
- Temporal facts with conflict detection
- Spreading activation retrieval

Basic usage:
    from remind import MemoryInterface, create_memory
    
    # Quick setup with defaults (local embeddings)
    memory = create_memory()
    
    # Log experiences
    await memory.remember("User prefers Python for backend development")
    await memory.remember("User works on distributed systems")
    
    # Retrieve relevant context
    context = await memory.recall("What programming languages?")
    
    # Use in LLM prompts
    response = await llm.complete(f"{context}\\n\\nUser: {message}")
"""

__version__ = "0.12.0"

# Core models
from remind.models import (
    Concept,
    ConceptType,
    Conflict,
    Episode,
    Evidence,
    Fact,
    Relation,
    RelationType,
    Topic,
    Entity,
    EntityType,
    EntityRelation,
    EpisodeType,
    # Freeform concept type constants (new in 0.12.0)
    CONCEPT_TYPE_FACT,
    CONCEPT_TYPE_FACT_CLUSTER,
    CONCEPT_TYPE_PATTERN,
    CONCEPT_TYPE_RULE,
    CONCEPT_TYPE_PROCEDURE,
    CONCEPT_TYPE_HYPOTHESIS,
    CONCEPT_TYPE_LEGACY,
    # Evidence link type constants (new in 0.12.0)
    EVIDENCE_SUPPORTS,
    EVIDENCE_CONTRADICTS,
    EVIDENCE_EXEMPLIFIES,
    EVIDENCE_QUALIFIES,
    EVIDENCE_SUPERSEDES,
)

# Storage
from remind.store import (
    MemoryStore,
    SQLiteMemoryStore,
)

# Main interface
from remind.interface import (
    MemoryInterface,
    create_memory,
)

# Retrieval
from remind.retrieval import (
    MemoryRetriever,
    ActivatedConcept,
)

# Providers
from remind.providers import (
    EmbeddingProvider,
    LocalEmbedding,
    OpenAIEmbedding,
    OllamaEmbedding,
)

__all__ = [
    # Version
    "__version__",
    # Models
    "Concept",
    "ConceptType",
    "Conflict",
    "Episode",
    "Evidence",
    "Fact",
    "Relation",
    "RelationType",
    "Entity",
    "EntityType",
    "EntityRelation",
    "EpisodeType",
    "Topic",
    # Freeform concept type constants
    "CONCEPT_TYPE_FACT",
    "CONCEPT_TYPE_FACT_CLUSTER",
    "CONCEPT_TYPE_PATTERN",
    "CONCEPT_TYPE_RULE",
    "CONCEPT_TYPE_PROCEDURE",
    "CONCEPT_TYPE_HYPOTHESIS",
    "CONCEPT_TYPE_LEGACY",
    # Evidence link type constants
    "EVIDENCE_SUPPORTS",
    "EVIDENCE_CONTRADICTS",
    "EVIDENCE_EXEMPLIFIES",
    "EVIDENCE_QUALIFIES",
    "EVIDENCE_SUPERSEDES",
    # Storage
    "MemoryStore",
    "SQLiteMemoryStore",
    # Interface
    "MemoryInterface",
    "create_memory",
    # Retrieval
    "MemoryRetriever",
    "ActivatedConcept",
    # Providers
    "EmbeddingProvider",
    "LocalEmbedding",
    "OpenAIEmbedding",
    "OllamaEmbedding",
]
