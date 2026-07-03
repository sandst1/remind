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

__version__ = "0.11.0"

# Core models
from remind.models import (
    Concept,
    ConceptType,
    Conflict,
    Episode,
    Fact,
    Relation,
    RelationType,
    Topic,
    Entity,
    EntityType,
    EntityRelation,
    EpisodeType,
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
    "Fact",
    "Relation",
    "RelationType",
    "Entity",
    "EntityType",
    "EntityRelation",
    "EpisodeType",
    "Topic",
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
