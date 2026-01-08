"""
Remind MCP Server - Memory system exposed via Model Context Protocol.

Single server instance supporting multiple databases. Each client specifies
its database via URL query parameter.

Usage:
    remind-mcp --port 8765
    Connect: http://127.0.0.1:8765/sse?db=my-project
    Web UI:  http://127.0.0.1:8765/ui/?db=my-project
"""

import asyncio
import json
import logging
import os
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from dotenv import load_dotenv

load_dotenv()

from remind.interface import create_memory, MemoryInterface

logger = logging.getLogger(__name__)

# Central directory for databases when using simple names
REMIND_DIR = Path.home() / ".remind"

# Context variable to track current database path per async context
_current_db: ContextVar[str] = ContextVar('current_db', default='')

# Session ID to database path mapping (for SSE sessions)
_session_db_map: dict[str, str] = {}

# Cache of MemoryInterface instances keyed by database path
_memory_instances: dict[str, MemoryInterface] = {}
_memory_locks: dict[str, asyncio.Lock] = {}
_global_lock = asyncio.Lock()

# Default providers - can be overridden via CLI args or env vars
DEFAULT_LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")
DEFAULT_EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "openai")


def resolve_db_path(db_name: str) -> str:
    """Resolve a database name to ~/.remind/{name}.db.

    Only simple names are accepted. Paths are not allowed.

    Examples:
        my-project → ~/.remind/my-project.db
        my-project.db → ~/.remind/my-project.db

    Raises:
        ValueError: If the name contains path separators or starts with special characters.
    """
    db_name = db_name.strip()

    # Reject paths - only simple names allowed
    if "/" in db_name or db_name.startswith("~") or db_name.startswith("."):
        raise ValueError(
            f"Invalid database name '{db_name}'. "
            "Only simple names are allowed (e.g., 'my-project'). "
            "Paths are not supported."
        )

    # Ensure the ~/.remind directory exists
    REMIND_DIR.mkdir(parents=True, exist_ok=True)

    # Add .db extension if not present
    if not db_name.endswith(".db"):
        db_name = f"{db_name}.db"

    return str(REMIND_DIR / db_name)


async def get_memory_for_db(db_path: str) -> MemoryInterface:
    """Get or create a MemoryInterface for the given database path.

    Note: db_path should already be resolved via resolve_db_path() by the caller.
    """
    
    # Get or create lock for this db
    async with _global_lock:
        if db_path not in _memory_locks:
            _memory_locks[db_path] = asyncio.Lock()
        lock = _memory_locks[db_path]
    
    # Get or create memory instance
    async with lock:
        if db_path not in _memory_instances:
            logger.info(f"Creating MemoryInterface for database: {db_path}")
            _memory_instances[db_path] = create_memory(
                llm_provider=DEFAULT_LLM_PROVIDER,
                embedding_provider=DEFAULT_EMBEDDING_PROVIDER,
                db_path=db_path,
                auto_consolidate=True,
                consolidation_threshold=10,
            )
        return _memory_instances[db_path]


def get_current_db() -> str:
    """Get the current database path from context."""
    db_path = _current_db.get()
    if not db_path:
        raise ValueError(
            "No database path specified. Configure via URL query parameter: "
            "?db=/path/to/memory.db"
        )
    return db_path


async def get_memory() -> MemoryInterface:
    """Get the MemoryInterface for the current context's database."""
    return await get_memory_for_db(get_current_db())


# ============================================================================
# MCP Tool Implementations
# ============================================================================

async def tool_remember(
    content: str, 
    metadata: Optional[str] = None,
    episode_type: Optional[str] = None,
    entities: Optional[str] = None,
) -> str:
    """Store an experience or observation in memory.
    
    This is a fast operation - no LLM calls. Entity extraction and
    type classification happen during consolidation.
    
    Auto-consolidation triggers when episode threshold (default: 10) is reached.
    """
    from remind.models import EpisodeType
    
    memory = await get_memory()
    
    meta = json.loads(metadata) if metadata else None
    
    # Parse episode type if provided
    ep_type = None
    if episode_type:
        try:
            ep_type = EpisodeType(episode_type)
        except ValueError:
            return f"Invalid episode_type: {episode_type}. Valid: observation, decision, question, meta, preference"
    
    # Parse entities if provided (comma-separated)
    entity_list = None
    if entities:
        entity_list = [e.strip() for e in entities.split(",") if e.strip()]
    
    # remember() is now sync - no LLM call
    episode_id = memory.remember(
        content, 
        metadata=meta,
        episode_type=ep_type,
        entities=entity_list,
    )
    
    lines = [f"Remembered as episode {episode_id}"]
    
    if ep_type:
        lines.append(f"  Type: {ep_type.value}")
    if entity_list:
        lines.append(f"  Entities: {', '.join(entity_list)}")
    
    # Auto-consolidate if threshold reached and auto_consolidate is enabled
    if memory.auto_consolidate and memory.should_consolidate:
        result = await memory.consolidate()
        lines.append("")
        lines.append("Auto-consolidation triggered:")
        lines.append(f"  Episodes processed: {result.episodes_processed}")
        lines.append(f"  Concepts created: {result.concepts_created}")
        lines.append(f"  Concepts updated: {result.concepts_updated}")
        if result.contradictions_found:
            lines.append(f"  Contradictions found: {result.contradictions_found}")
    else:
        # Show pending count if not consolidating
        stats = memory.get_stats()
        pending = stats.get("unconsolidated_episodes", 0)
        if pending >= 5:
            lines.append(f"\n({pending} episodes pending consolidation)")
    
    return "\n".join(lines)


async def tool_recall(
    query: str, 
    k: int = 5, 
    context: Optional[str] = None,
    entity: Optional[str] = None,
) -> str:
    """Retrieve relevant memories for a query."""
    memory = await get_memory()
    return await memory.recall(query, k=k, context=context, entity=entity)


async def tool_consolidate(force: bool = False) -> str:
    """Process pending episodes into generalized concepts."""
    memory = await get_memory()
    
    stats = memory.get_stats()
    pending = stats.get("unconsolidated_episodes", 0)
    
    if pending == 0:
        return "No episodes pending consolidation."
    
    result = await memory.consolidate(force=force)
    
    lines = ["Consolidation complete:"]
    lines.append(f"  Episodes processed: {result.episodes_processed}")
    lines.append(f"  Concepts created: {result.concepts_created}")
    lines.append(f"  Concepts updated: {result.concepts_updated}")
    
    if result.contradictions_found:
        lines.append(f"  Contradictions found: {result.contradictions_found}")
        for detail in result.contradiction_details[:3]:
            lines.append(f"    - {detail}")
    
    return "\n".join(lines)


async def tool_inspect(
    concept_id: Optional[str] = None,
    show_episodes: bool = False,
    limit: int = 10,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> str:
    """Inspect concepts or episodes in memory."""
    memory = await get_memory()
    store = memory.store
    
    if show_episodes:
        # Get episodes - either by date range or recent
        if start_date or end_date:
            episodes = store.get_episodes_by_date_range(
                start_date=start_date,
                end_date=end_date,
                limit=limit
            )
            date_info = []
            if start_date:
                date_info.append(f"from {start_date}")
            if end_date:
                date_info.append(f"to {end_date}")
            header = f"Episodes {' '.join(date_info)} ({len(episodes)}):" if date_info else f"Episodes ({len(episodes)}):"
        else:
            episodes = store.get_recent_episodes(limit=limit)
            header = f"Recent Episodes ({len(episodes)}):"
        
        if not episodes:
            return "No episodes found."
        
        lines = [header]
        for ep in episodes:
            status = "✓" if ep.consolidated else "pending"
            timestamp = ep.timestamp.strftime('%Y-%m-%d %H:%M:%S')
            ep_type = ep.episode_type.value
            lines.append(f"  [{ep.id}] {timestamp} ({ep_type}, {status})")
            lines.append(f"      {ep.content}")
            if ep.entity_ids:
                entities = ", ".join(ep.entity_ids)
                lines.append(f"      → entities: {entities}")
        return "\n".join(lines)
    
    if concept_id:
        concept = store.get_concept(concept_id)
        if not concept:
            return f"Concept {concept_id} not found."
        
        lines = [f"Concept: {concept.id}"]
        if concept.title:
            lines.append(f"  Title: {concept.title}")
        lines.append(f"  Summary: {concept.summary}")
        lines.append(f"  Confidence: {concept.confidence:.2f}")
        lines.append(f"  Instances: {concept.instance_count}")
        lines.append(f"  Created: {concept.created_at.strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"  Updated: {concept.updated_at.strftime('%Y-%m-%d %H:%M')}")
        
        if concept.conditions:
            lines.append(f"  Conditions: {concept.conditions}")
        if concept.exceptions:
            lines.append(f"  Exceptions: {', '.join(concept.exceptions)}")
        if concept.tags:
            lines.append(f"  Tags: {', '.join(concept.tags)}")
        
        if concept.relations:
            lines.append(f"  Relations ({len(concept.relations)}):")
            for rel in concept.relations:
                target = store.get_concept(rel.target_id)
                target_summary = target.summary if target else "[unknown]"
                lines.append(f"    {rel.type.value} → [{rel.target_id}] {target_summary}")
        
        return "\n".join(lines)
    
    # List all concepts
    concepts = store.get_all_concepts()
    if not concepts:
        return "No concepts in memory. Run consolidate after adding episodes."
    
    lines = [f"All Concepts ({len(concepts)}):"]
    for c in concepts[:limit]:
        tags = f" [{', '.join(c.tags)}]" if c.tags else ""
        title_display = c.title or c.summary[:50] + ("..." if len(c.summary) > 50 else "")
        lines.append(f"  [{c.id}] {title_display} (conf: {c.confidence:.2f}, n={c.instance_count}){tags}")
    
    if len(concepts) > limit:
        lines.append(f"  ... and {len(concepts) - limit} more")
    
    return "\n".join(lines)


async def tool_stats() -> str:
    """Get memory statistics."""
    memory = await get_memory()
    db_path = get_current_db()
    
    s = memory.get_stats()
    
    lines = ["Memory Statistics:"]
    lines.append(f"  Concepts: {s['concepts']}")
    lines.append(f"  Episodes: {s['episodes']}")
    lines.append(f"  Relations: {s['relations']}")
    lines.append(f"  Entities: {s.get('entities', 0)}")
    lines.append(f"  Entity Relations: {s.get('entity_relations', 0)}")
    lines.append(f"  Mentions: {s.get('mentions', 0)}")
    lines.append("")
    lines.append("Consolidation:")
    lines.append(f"  Pending episodes: {s.get('unconsolidated_episodes', 0)}")
    lines.append(f"  Unextracted episodes: {s.get('unextracted_episodes', 0)}")
    lines.append(f"  Threshold: {s.get('consolidation_threshold', 10)}")
    lines.append(f"  Auto-consolidate: {s.get('auto_consolidate', True)}")
    lines.append(f"  Should consolidate: {s.get('should_consolidate', False)}")
    
    if s.get('episode_types'):
        lines.append("")
        lines.append("Episode Types:")
        for ep_type, count in s['episode_types'].items():
            lines.append(f"  {ep_type}: {count}")
    
    if s.get('entity_types'):
        lines.append("")
        lines.append("Entity Types:")
        for ent_type, count in s['entity_types'].items():
            lines.append(f"  {ent_type}: {count}")
    
    if s.get('relation_types'):
        lines.append("")
        lines.append("Concept Relation Types:")
        for rel_type, count in s['relation_types'].items():
            lines.append(f"  {rel_type}: {count}")

    if s.get('entity_relation_types'):
        lines.append("")
        lines.append("Entity Relation Types:")
        for rel_type, count in s['entity_relation_types'].items():
            lines.append(f"  {rel_type}: {count}")

    lines.append("")
    lines.append(f"Database: {db_path}")

    return "\n".join(lines)


async def tool_entities(
    entity_type: Optional[str] = None,
    limit: int = 50,
) -> str:
    """List entities in memory with mention counts."""
    from remind.models import EntityType

    memory = await get_memory()
    store = memory.store

    # Get entities with mention counts
    entity_counts = store.get_entity_mention_counts()

    if not entity_counts:
        return "No entities in memory."

    # Filter by type if specified
    if entity_type:
        try:
            ent_type = EntityType(entity_type)
            entity_counts = [(e, c) for e, c in entity_counts if e.type == ent_type]
        except ValueError:
            valid_types = ", ".join(t.value for t in EntityType)
            return f"Invalid entity_type: {entity_type}. Valid: {valid_types}"

    if not entity_counts:
        return f"No entities of type '{entity_type}' in memory."

    # Apply limit
    total = len(entity_counts)
    entity_counts = entity_counts[:limit]

    # Format output
    lines = [f"Entities ({total} total):"]
    for entity, count in entity_counts:
        display = entity.display_name or entity.id.split(":", 1)[1] if ":" in entity.id else entity.id
        lines.append(f"  {entity.id} ({count} mentions)")
        if entity.display_name and entity.display_name != display:
            lines.append(f"      Display: {entity.display_name}")

    if total > limit:
        lines.append(f"  ... and {total - limit} more")

    return "\n".join(lines)


async def tool_inspect_entity(
    entity_id: str,
    show_relations: bool = True,
) -> str:
    """Inspect an entity and its relationships."""
    memory = await get_memory()
    store = memory.store

    entity = store.get_entity(entity_id)
    if not entity:
        return f"Entity '{entity_id}' not found."

    # Get mention count
    entity_counts = store.get_entity_mention_counts()
    mention_count = next((c for e, c in entity_counts if e.id == entity_id), 0)

    lines = [f"Entity: {entity.id}"]
    lines.append(f"  Type: {entity.type.value}")
    if entity.display_name:
        lines.append(f"  Display: {entity.display_name}")
    lines.append(f"  Mentions: {mention_count}")
    lines.append(f"  Created: {entity.created_at.strftime('%Y-%m-%d %H:%M')}")

    if show_relations:
        relations = store.get_entity_relations(entity_id)

        if relations:
            # Separate outgoing and incoming
            outgoing = [r for r in relations if r.source_id == entity_id]
            incoming = [r for r in relations if r.target_id == entity_id]

            lines.append("")
            lines.append(f"Relationships ({len(relations)}):")

            for rel in outgoing:
                target = store.get_entity(rel.target_id)
                target_name = target.display_name if target else rel.target_id
                lines.append(f"  → {rel.relation_type} {target_name} ({rel.strength:.0%})")

            for rel in incoming:
                source = store.get_entity(rel.source_id)
                source_name = source.display_name if source else rel.source_id
                lines.append(f"  ← {rel.relation_type} {source_name} ({rel.strength:.0%})")
        else:
            lines.append("")
            lines.append("Relationships: none")

    return "\n".join(lines)


# ============================================================================
# FastMCP Server Setup
# ============================================================================

def create_mcp_server():
    """Create and configure the FastMCP server."""
    from fastmcp import FastMCP
    
    mcp = FastMCP(
        "Remind",
        instructions="Generalization-capable memory layer for LLMs with episodic buffers, "
                     "semantic concept graphs, and spreading activation retrieval.",
    )
    
    @mcp.tool()
    async def remember(
        content: str,
        metadata: Optional[str] = None,
        episode_type: Optional[str] = None,
        entities: Optional[str] = None,
    ) -> str:
        """Store an experience or observation in memory.
        
        This is a fast operation - no LLM calls. Entity extraction and type
        classification happen during consolidation.
        
        Auto-consolidation: When the episode threshold (default: 10) is reached,
        consolidation runs automatically after this call.
        
        Use this to log important information that should be remembered across sessions:
        - User preferences and opinions
        - Technical context about projects
        - Corrections or clarifications
        - Patterns and decisions
        
        Args:
            content: The experience/observation to remember (clear, standalone statement)
            metadata: Optional JSON string with additional metadata
            episode_type: Optional explicit type: observation, decision, question, meta, preference
                          (auto-detected during consolidation if not provided)
            entities: Optional comma-separated entity IDs (e.g., "file:src/auth.ts,person:alice")
                      (auto-detected during consolidation if not provided)
        
        Returns:
            Confirmation with episode ID
        """
        return await tool_remember(content, metadata, episode_type, entities)
    
    @mcp.tool()
    async def recall(
        query: str,
        k: int = 5,
        context: Optional[str] = None,
        entity: Optional[str] = None,
    ) -> str:
        """Retrieve relevant memories for a query.
        
        Two modes:
        1. Semantic search (default): Uses embeddings with spreading activation
        2. Entity-based: Retrieves all memories about a specific entity
        
        Args:
            query: What to search for in memory
            k: Number of concepts to retrieve (default: 5)
            context: Optional additional context to improve retrieval
            entity: Optional entity ID to retrieve by (e.g., "file:src/auth.ts")
        
        Returns:
            Formatted memory context for injection into prompts
        """
        return await tool_recall(query, k, context, entity)
    
    @mcp.tool()
    async def consolidate(force: bool = False) -> str:
        """Process pending episodes into generalized concepts.
        
        Consolidation runs in two phases:
        
        Phase 1 - Extraction:
        - Classifies episode types (observation, decision, question, etc.)
        - Extracts entity mentions (files, people, tools, concepts)
        
        Phase 2 - Generalization:
        - Identifies patterns across episodes
        - Creates new generalized concepts
        - Updates existing concepts with new evidence
        - Establishes relations between concepts
        - Flags contradictions
        
        Args:
            force: If True, consolidate even with few pending episodes
        
        Returns:
            Summary of consolidation results
        """
        return await tool_consolidate(force)
    
    @mcp.tool()
    async def inspect(
        concept_id: Optional[str] = None,
        show_episodes: bool = False,
        limit: int = 10,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> str:
        """Inspect concepts or episodes in memory.
        
        Use this to examine what's stored in memory:
        - List all concepts (no concept_id)
        - View a specific concept (with concept_id)
        - View recent episodes (show_episodes=True)
        - Filter episodes by date range (show_episodes=True with start_date/end_date)
        
        Args:
            concept_id: Optional ID of a specific concept to inspect
            show_episodes: If True, show episodes instead of concepts
            limit: Maximum number of items to show
            start_date: Optional ISO format date/datetime (e.g., "2024-01-01" or "2024-01-01T10:00:00") - inclusive start
            end_date: Optional ISO format date/datetime (e.g., "2024-12-31" or "2024-12-31T23:59:59") - inclusive end
        
        Returns:
            Formatted view of concepts or episodes
        
        Examples:
            - inspect(show_episodes=True) - show recent episodes
            - inspect(show_episodes=True, start_date="2024-01-01") - episodes from Jan 1, 2024 onwards
            - inspect(show_episodes=True, start_date="2024-01-01", end_date="2024-01-31") - January 2024 episodes
            - inspect(show_episodes=True, end_date="2024-06-30") - episodes up to June 30, 2024
        """
        return await tool_inspect(concept_id, show_episodes, limit, start_date, end_date)
    
    @mcp.tool()
    async def stats() -> str:
        """Get memory statistics.

        Shows overview of memory contents including:
        - Number of concepts and episodes
        - Consolidation status
        - Relation type distribution

        Returns:
            Formatted statistics summary
        """
        return await tool_stats()

    @mcp.tool()
    async def entities(
        entity_type: Optional[str] = None,
        limit: int = 50,
    ) -> str:
        """List entities (files, functions, people, etc.) in memory.

        Entities are external referents that are mentioned in episodes.
        They help organize memories around specific things like files,
        people, tools, and concepts.

        Use this to discover what entities exist in memory before using
        recall with entity-based lookup.

        Args:
            entity_type: Optional filter by type: file, function, class,
                         module, concept, person, project, tool, other
            limit: Maximum number of entities to show (default: 50)

        Returns:
            List of entities with their mention counts
        """
        return await tool_entities(entity_type, limit)

    @mcp.tool()
    async def inspect_entity(
        entity_id: str,
        show_relations: bool = True,
    ) -> str:
        """Inspect an entity and its relationships.

        Shows detailed information about an entity including:
        - Entity type and display name
        - Number of mentions in episodes
        - Relationships to other entities (if any)

        Use this to explore how entities relate to each other in memory.

        Args:
            entity_id: Entity ID to inspect (e.g., "file:src/auth.ts", "person:alice")
            show_relations: Whether to include relationships (default: True)

        Returns:
            Entity details with relationships
        """
        return await tool_inspect_entity(entity_id, show_relations)

    return mcp


def get_static_directory() -> Optional[Path]:
    """Get the path to static files, handling both dev and installed scenarios."""
    import importlib.resources

    # Try package resources first (when installed)
    try:
        with importlib.resources.as_file(
            importlib.resources.files("remind") / "static"
        ) as static_path:
            if static_path.exists() and static_path.is_dir():
                # Check if it has files (not just an empty dir)
                if any(static_path.iterdir()):
                    return static_path
    except (TypeError, FileNotFoundError, StopIteration):
        pass

    # Development fallback - check relative to this file
    dev_path = Path(__file__).parent / "static"
    if dev_path.exists() and dev_path.is_dir():
        if any(dev_path.iterdir()):
            return dev_path

    return None


def run_server_sse(host: str = "127.0.0.1", port: int = 8765):
    """Run the MCP server with SSE (HTTP) transport and Web UI."""
    import uvicorn
    from fastmcp.server.http import create_sse_app
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route
    from starlette.staticfiles import StaticFiles
    from starlette.responses import RedirectResponse

    from remind.api.routes import api_routes

    mcp = create_mcp_server()

    # Create the SSE app with FastMCP
    sse_app = create_sse_app(
        server=mcp,
        sse_path="/sse",
        message_path="/messages",
    )

    # Check for static files
    static_dir = get_static_directory()
    
    # Create custom ASGI middleware to inject db context
    async def app(scope, receive, send):
        if scope['type'] == 'lifespan':
            # Handle lifespan
            while True:
                message = await receive()
                if message['type'] == 'lifespan.startup':
                    logger.info(f"Remind MCP server starting on {host}:{port}")
                    await send({'type': 'lifespan.startup.complete'})
                elif message['type'] == 'lifespan.shutdown':
                    logger.info("Remind MCP server shutting down")
                    # Clean up session map
                    _session_db_map.clear()
                    await send({'type': 'lifespan.shutdown.complete'})
                    return
        
        elif scope['type'] == 'http':
            path = scope.get('path', '')
            method = scope.get('method', 'GET')
            query_string = scope.get('query_string', b'').decode()
            params = parse_qs(query_string)

            # Handle root redirect to UI
            if path == '/' and method == 'GET':
                db = params.get('db', [''])[0]
                redirect_url = f'/ui/?db={db}' if db else '/ui/'
                await send({
                    'type': 'http.response.start',
                    'status': 302,
                    'headers': [
                        (b'location', redirect_url.encode()),
                        (b'content-type', b'text/plain'),
                    ],
                })
                await send({
                    'type': 'http.response.body',
                    'body': b'',
                })
                return

            # Handle API routes
            if path.startswith('/api/'):
                # Create a Starlette app for API routes
                from starlette.applications import Starlette
                from starlette.routing import Router
                api_app = Router(routes=api_routes)
                await api_app(scope, receive, send)
                return

            # Handle static files for UI
            if path.startswith('/ui'):
                if static_dir:
                    # Serve static files
                    static_app = StaticFiles(directory=str(static_dir), html=True)
                    # Adjust path for static files
                    scope = dict(scope)
                    # Remove /ui prefix for static files lookup
                    if path == '/ui' or path == '/ui/':
                        scope['path'] = '/index.html'
                    else:
                        scope['path'] = path[3:]  # Remove '/ui'
                    try:
                        await static_app(scope, receive, send)
                        return
                    except Exception as e:
                        # If file not found, serve index.html for SPA routing
                        scope['path'] = '/index.html'
                        try:
                            await static_app(scope, receive, send)
                            return
                        except Exception:
                            pass
                # No static files available
                await send({
                    'type': 'http.response.start',
                    'status': 503,
                    'headers': [(b'content-type', b'text/plain')],
                })
                await send({
                    'type': 'http.response.body',
                    'body': b'Web UI not available. Build with: cd web && npm install && npm run build',
                })
                return

            # Extract db from query params
            db_list = params.get('db', [])
            session_list = params.get('session_id', [])
            
            db_path = None
            
            # Case 1: db param provided directly (initial SSE connection)
            if db_list:
                db_path = resolve_db_path(db_list[0])
                logger.info(f"Request with db param: {db_path}")
            
            # Case 2: session_id provided, look up db from session map
            elif session_list:
                session_id = session_list[0]
                db_path = _session_db_map.get(session_id)
                if db_path:
                    logger.debug(f"Found db for session {session_id}: {db_path}")
                else:
                    logger.warning(f"No db found for session {session_id}")
            
            # Case 3: No db or session - check if this is a message POST
            # Try to extract session from the request body or other means
            if not db_path:
                # For MCP SSE endpoint without db param, return error
                if path == '/sse' and method == 'GET':
                    await send({
                        'type': 'http.response.start',
                        'status': 400,
                        'headers': [(b'content-type', b'text/plain')],
                    })
                    await send({
                        'type': 'http.response.body',
                        'body': b'Missing required query parameter: db\n\n'
                               b'Examples:\n'
                               b'  /sse?db=my-project      -> ~/.remind/my-project.db\n'
                               b'  /sse?db=./memory.db     -> ./memory.db (relative)\n'
                               b'  /sse?db=/full/path.db   -> /full/path.db (absolute)\n',
                    })
                    return
                
                # For /messages endpoint, we need the session_id
                # FastMCP typically includes it in query params
                # If we still don't have db_path, check if there's only one db in use
                if len(_session_db_map) == 1:
                    # Only one session/db, use it
                    db_path = list(_session_db_map.values())[0]
                    logger.debug(f"Using only available db: {db_path}")
                elif len(_memory_instances) == 1:
                    # Only one memory instance, use it
                    db_path = list(_memory_instances.keys())[0]
                    logger.debug(f"Using only available memory instance: {db_path}")
                else:
                    # Can't determine which db to use
                    logger.error(f"Cannot determine db for request: {method} {path}")
                    await send({
                        'type': 'http.response.start',
                        'status': 400,
                        'headers': [(b'content-type', b'text/plain')],
                    })
                    await send({
                        'type': 'http.response.body',
                        'body': b'Cannot determine database. Include db parameter or session_id.',
                    })
                    return
            
            # Set context and forward to FastMCP
            token = _current_db.set(db_path)
            try:
                # Pre-initialize memory
                await get_memory_for_db(db_path)
                
                # Intercept HTTP response to capture session ID and map it to db
                if path == '/sse' and method == 'GET':
                    # Wrap send to capture session info from response
                    original_send = send
                    captured_session_id = None
                    
                    async def intercepting_send(message):
                        nonlocal captured_session_id
                        if message['type'] == 'http.response.body':
                            body = message.get('body', b'')
                            if body:
                                # Look for session_id in the response
                                body_str = body.decode('utf-8', errors='ignore')
                                if 'endpoint' in body_str and 'session_id=' in body_str:
                                    # Extract session_id from the endpoint URL
                                    import re
                                    match = re.search(r'session_id=([a-f0-9-]+)', body_str)
                                    if match:
                                        captured_session_id = match.group(1)
                                        _session_db_map[captured_session_id] = db_path
                                        logger.info(f"Mapped session {captured_session_id} to db {db_path}")
                        await original_send(message)
                    
                    await sse_app(scope, receive, intercepting_send)
                else:
                    # Regular request, just forward
                    await sse_app(scope, receive, send)
            finally:
                _current_db.reset(token)
    
    print(f"Starting Remind MCP server (SSE) on {host}:{port}")
    print(f"Database resolution:")
    print(f"  ?db=my-project      → ~/.remind/my-project.db")
    print(f"\nEndpoints:")
    print(f"  MCP SSE:  http://{host}:{port}/sse?db=<name>")
    print(f"  Web UI:   http://{host}:{port}/ui/?db=<name>")
    print(f"  REST API: http://{host}:{port}/api/v1/...")
    if static_dir:
        print(f"\nWeb UI available at: {static_dir}")
    else:
        print(f"\nWeb UI not built. Run: cd web && npm install && npm run build")
    
    uvicorn.run(app, host=host, port=port, log_level="info")


def main():
    """CLI entry point for the MCP server."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Remind MCP Server - Memory system via Model Context Protocol",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Database path resolution:
  my-project        → ~/.remind/my-project.db (central storage)
  ./memory.db       → ./memory.db (relative to cwd)
  /full/path.db     → /full/path.db (absolute)

Examples:
  remind-mcp --port 8765
"""
    )

    # SSE options
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to for SSE mode (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to listen on for SSE mode (default: 8765)"
    )
    
    
    # Provider options
    parser.add_argument(
        "--llm",
        default=None,
        choices=["anthropic", "openai", "azure_openai", "ollama"],
        help="LLM provider for consolidation/reflection"
    )
    parser.add_argument(
        "--embedding",
        default=None,
        choices=["openai", "azure_openai", "ollama"],
        help="Embedding provider for retrieval"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    # Set providers (CLI args > Env vars > Default)
    global DEFAULT_LLM_PROVIDER, DEFAULT_EMBEDDING_PROVIDER
    if args.llm:
        DEFAULT_LLM_PROVIDER = args.llm
    if args.embedding:
        DEFAULT_EMBEDDING_PROVIDER = args.embedding
    
    run_server_sse(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
