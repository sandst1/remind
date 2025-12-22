"""
RealMem: Generalization-capable memory layer for LLMs.

A hierarchical memory system featuring:
- Episodic buffers for raw experiences
- Semantic concept graphs with typed relations
- LLM-powered consolidation (generalization from episodes to concepts)
- Spreading activation retrieval

Basic usage:
    from realmem import MemoryInterface, create_memory
    
    # Quick setup with defaults
    memory = create_memory(llm_provider="anthropic", embedding_provider="openai")
    
    # Log experiences
    await memory.remember("User prefers Python for backend development")
    await memory.remember("User works on distributed systems")
    
    # Run consolidation (extracts generalized concepts)
    await memory.consolidate()
    
    # Retrieve relevant context
    context = await memory.recall("What programming languages?")
    
    # Use in LLM prompts
    response = await llm.complete(f"{context}\\n\\nUser: {message}")
"""

__version__ = "0.1.0"

# Core models
from realmem.models import (
    Concept,
    Episode,
    Relation,
    RelationType,
    ConsolidationResult,
    # v2 models
    Entity,
    EntityType,
    EpisodeType,
    ExtractionResult,
)

# Storage
from realmem.store import (
    MemoryStore,
    SQLiteMemoryStore,
)

# Main interface
from realmem.interface import (
    MemoryInterface,
    create_memory,
)

# Retrieval
from realmem.retrieval import (
    MemoryRetriever,
    ActivatedConcept,
)

# Consolidation
from realmem.consolidation import Consolidator

# Providers
from realmem.providers import (
    LLMProvider,
    EmbeddingProvider,
    AnthropicLLM,
    OpenAILLM,
    OpenAIEmbedding,
    OllamaLLM,
    OllamaEmbedding,
)

__all__ = [
    # Version
    "__version__",
    # Models
    "Concept",
    "Episode",
    "Relation",
    "RelationType",
    "ConsolidationResult",
    # v2 models
    "Entity",
    "EntityType",
    "EpisodeType",
    "ExtractionResult",
    # Storage
    "MemoryStore",
    "SQLiteMemoryStore",
    # Interface
    "MemoryInterface",
    "create_memory",
    # Retrieval
    "MemoryRetriever",
    "ActivatedConcept",
    # Consolidation
    "Consolidator",
    # Providers
    "LLMProvider",
    "EmbeddingProvider",
    "AnthropicLLM",
    "OpenAILLM",
    "OpenAIEmbedding",
    "OllamaLLM",
    "OllamaEmbedding",
]
