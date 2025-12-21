"""
RealMem MCP Server - Memory system exposed via Model Context Protocol.

Single server instance supporting multiple databases. Each client specifies
its database via URL query parameter:

    http://127.0.0.1:8765/sse?db=/path/to/memory.db

Usage:
    realmem-mcp --port 8765
    realmem-mcp --host 0.0.0.0 --port 8765
"""

import asyncio
import json
import logging
import uuid
from contextvars import ContextVar
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from dotenv import load_dotenv

load_dotenv()

from realmem.interface import create_memory, MemoryInterface

logger = logging.getLogger(__name__)

# Context variable to track current database path per async context
_current_db: ContextVar[str] = ContextVar('current_db', default='')

# Session ID to database path mapping (for SSE sessions)
_session_db_map: dict[str, str] = {}

# Cache of MemoryInterface instances keyed by database path
_memory_instances: dict[str, MemoryInterface] = {}
_memory_locks: dict[str, asyncio.Lock] = {}
_global_lock = asyncio.Lock()

# Default providers - can be overridden via CLI args or env vars
import os
DEFAULT_LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")
DEFAULT_EMBEDDING_PROVIDER = os.environ.get("EMBEDDING_PROVIDER", "openai")


async def get_memory_for_db(db_path: str) -> MemoryInterface:
    """Get or create a MemoryInterface for the given database path."""
    # Normalize path
    db_path = str(Path(db_path).resolve())
    
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
    """Store an experience or observation in memory."""
    from realmem.models import EpisodeType
    
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
    
    episode_id = await memory.remember(
        content, 
        metadata=meta,
        episode_type=ep_type,
        entities=entity_list,
    )
    
    # Get episode to show extraction results
    episode = memory.store.get_episode(episode_id)
    
    stats = memory.get_stats()
    pending = stats.get("unconsolidated_episodes", 0)
    
    lines = [f"Remembered as episode {episode_id}"]
    
    if episode:
        lines.append(f"  Type: {episode.episode_type.value}")
        if episode.entity_ids:
            lines.append(f"  Entities: {', '.join(episode.entity_ids)}")
    
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
            content = ep.content[:70] + "..." if len(ep.content) > 70 else ep.content
            timestamp = ep.timestamp.strftime('%Y-%m-%d %H:%M:%S')
            ep_type = ep.episode_type.value
            lines.append(f"  [{ep.id}] {timestamp} ({ep_type}, {status})")
            lines.append(f"      {content}")
            if ep.entity_ids:
                entities = ", ".join(ep.entity_ids[:3])
                if len(ep.entity_ids) > 3:
                    entities += f" +{len(ep.entity_ids) - 3}"
                lines.append(f"      → entities: {entities}")
        return "\n".join(lines)
    
    if concept_id:
        concept = store.get_concept(concept_id)
        if not concept:
            return f"Concept {concept_id} not found."
        
        lines = [f"Concept: {concept.id}"]
        lines.append(f"  Summary: {concept.summary}")
        lines.append(f"  Confidence: {concept.confidence:.2f}")
        lines.append(f"  Instances: {concept.instance_count}")
        lines.append(f"  Created: {concept.created_at.strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"  Updated: {concept.updated_at.strftime('%Y-%m-%d %H:%M')}")
        
        if concept.conditions:
            lines.append(f"  Conditions: {concept.conditions}")
        if concept.exceptions:
            lines.append(f"  Exceptions: {', '.join(concept.exceptions[:5])}")
        if concept.tags:
            lines.append(f"  Tags: {', '.join(concept.tags)}")
        
        if concept.relations:
            lines.append(f"  Relations ({len(concept.relations)}):")
            for rel in concept.relations[:10]:
                target = store.get_concept(rel.target_id)
                target_summary = target.summary[:50] + "..." if target else "[unknown]"
                lines.append(f"    {rel.type.value} → [{rel.target_id}] {target_summary}")
        
        return "\n".join(lines)
    
    # List all concepts
    concepts = store.get_all_concepts()
    if not concepts:
        return "No concepts in memory. Run consolidate after adding episodes."
    
    lines = [f"All Concepts ({len(concepts)}):"]
    for c in concepts[:limit]:
        summary = c.summary[:60] + "..." if len(c.summary) > 60 else c.summary
        tags = f" [{', '.join(c.tags[:3])}]" if c.tags else ""
        lines.append(f"  [{c.id}] (conf: {c.confidence:.2f}, n={c.instance_count}){tags}")
        lines.append(f"      {summary}")
    
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
        lines.append("Relation Types:")
        for rel_type, count in s['relation_types'].items():
            lines.append(f"  {rel_type}: {count}")
    
    lines.append("")
    lines.append(f"Database: {db_path}")
    
    return "\n".join(lines)


async def tool_reflect(prompt: str) -> str:
    """Let the LLM reason about its own memory."""
    memory = await get_memory()
    return await memory.reflect(prompt)


async def tool_entities(
    entity_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    limit: int = 20,
) -> str:
    """List entities or show episodes mentioning a specific entity."""
    from realmem.models import EntityType
    
    memory = await get_memory()
    store = memory.store
    
    if entity_id:
        # Show specific entity and its mentions
        entity = store.get_entity(entity_id)
        if not entity:
            return f"Entity {entity_id} not found."
        
        episodes = store.get_episodes_mentioning(entity_id, limit=limit)
        
        lines = [f"Entity: {entity.id}"]
        lines.append(f"  Type: {entity.type.value}")
        if entity.display_name:
            lines.append(f"  Name: {entity.display_name}")
        lines.append("")
        
        if episodes:
            lines.append(f"Mentioned in {len(episodes)} episodes:")
            for ep in episodes[:10]:
                content = ep.content[:60] + "..." if len(ep.content) > 60 else ep.content
                lines.append(f"  [{ep.id}] ({ep.episode_type.value}) {content}")
            if len(episodes) > 10:
                lines.append(f"  ... and {len(episodes) - 10} more")
        else:
            lines.append("No episodes mention this entity.")
        
        return "\n".join(lines)
    
    # List all entities
    entity_counts = store.get_entity_mention_counts()
    
    if not entity_counts:
        return "No entities in memory."
    
    # Filter by type if specified
    if entity_type:
        try:
            etype = EntityType(entity_type)
            entity_counts = [(e, c) for e, c in entity_counts if e.type == etype]
        except ValueError:
            valid = ', '.join(t.value for t in EntityType)
            return f"Invalid entity_type: {entity_type}. Valid: {valid}"
    
    lines = [f"Entities ({len(entity_counts)}):"]
    for entity, count in entity_counts[:limit]:
        name = f" ({entity.display_name})" if entity.display_name else ""
        lines.append(f"  {entity.id}{name} - {count} mentions")
    
    if len(entity_counts) > limit:
        lines.append(f"  ... and {len(entity_counts) - limit} more")
    
    return "\n".join(lines)


async def tool_backfill(limit: int = 100) -> str:
    """Backfill entity extraction for existing episodes."""
    memory = await get_memory()
    
    stats = memory.get_stats()
    unextracted = stats.get("unextracted_episodes", 0)
    
    if unextracted == 0:
        return "All episodes already have entity extraction."
    
    result = await memory.backfill_extraction(limit=limit)
    
    lines = [f"Backfill complete:"]
    lines.append(f"  Episodes processed: {result.episodes_processed}")
    lines.append(f"  Entities created: {result.entities_created}")
    
    if result.errors:
        lines.append(f"  Errors: {len(result.errors)}")
    
    remaining = max(0, unextracted - result.episodes_processed)
    if remaining > 0:
        lines.append(f"\n{remaining} episodes still need extraction.")
    
    return "\n".join(lines)


async def tool_decisions(limit: int = 20) -> str:
    """Show decision-type episodes."""
    from realmem.models import EpisodeType
    
    memory = await get_memory()
    episodes = memory.get_episodes_by_type(EpisodeType.DECISION, limit=limit)
    
    if not episodes:
        return "No decisions recorded."
    
    lines = [f"Decisions ({len(episodes)}):"]
    for ep in episodes:
        status = "✓" if ep.consolidated else "pending"
        content = ep.content[:70] + "..." if len(ep.content) > 70 else ep.content
        lines.append(f"  [{ep.id}] ({status}) {content}")
    
    return "\n".join(lines)


async def tool_questions(limit: int = 20) -> str:
    """Show open questions and uncertainties."""
    from realmem.models import EpisodeType
    
    memory = await get_memory()
    episodes = memory.get_episodes_by_type(EpisodeType.QUESTION, limit=limit)
    
    if not episodes:
        return "No questions recorded."
    
    lines = [f"Open Questions ({len(episodes)}):"]
    for ep in episodes:
        status = "✓" if ep.consolidated else "pending"
        content = ep.content[:70] + "..." if len(ep.content) > 70 else ep.content
        lines.append(f"  [{ep.id}] ({status}) {content}")
    
    return "\n".join(lines)


# ============================================================================
# FastMCP Server Setup
# ============================================================================

def create_mcp_server():
    """Create and configure the FastMCP server."""
    from fastmcp import FastMCP
    
    mcp = FastMCP(
        "RealMem",
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
        
        Use this to log important information that should be remembered across sessions:
        - User preferences and opinions
        - Technical context about projects
        - Corrections or clarifications
        - Patterns and decisions
        
        Entity and type extraction is automatic by default. You can also provide explicit values.
        
        Args:
            content: The experience/observation to remember (clear, standalone statement)
            metadata: Optional JSON string with additional metadata
            episode_type: Optional explicit type: observation, decision, question, meta, preference
            entities: Optional comma-separated entity IDs (e.g., "file:src/auth.ts,person:alice")
        
        Returns:
            Confirmation with episode ID, detected type, and entities
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
        
        Consolidation is the "sleep" process where raw experiences are analyzed
        and transformed into abstract, generalized knowledge. The LLM:
        1. Identifies patterns across episodes
        2. Creates new generalized concepts
        3. Updates existing concepts with new evidence
        4. Establishes relations between concepts
        5. Flags contradictions
        
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
    async def reflect(prompt: str) -> str:
        """Let the LLM reason about its own memory.
        
        Use this for meta-cognitive analysis:
        - "What do I know about this user?"
        - "What are the main themes in my memory?"
        - "What gaps exist in my understanding?"
        - "Are there any contradictions?"
        
        Args:
            prompt: The reflection prompt/question
        
        Returns:
            LLM's reflection response based on memory contents
        """
        return await tool_reflect(prompt)
    
    @mcp.tool()
    async def entities(
        entity_id: Optional[str] = None,
        entity_type: Optional[str] = None,
        limit: int = 20,
    ) -> str:
        """List entities or show episodes mentioning a specific entity.
        
        Entities are external referents (files, functions, people, concepts, tools, etc.)
        that are automatically extracted from episodes.
        
        Args:
            entity_id: Optional entity ID to inspect (e.g., "file:src/auth.ts")
            entity_type: Optional filter by type: file, function, class, person, concept, tool, project
            limit: Maximum entities to show
        
        Returns:
            List of entities with mention counts, or details for a specific entity
        """
        return await tool_entities(entity_id, entity_type, limit)
    
    @mcp.tool()
    async def backfill(limit: int = 100) -> str:
        """Backfill entity extraction for existing episodes.
        
        Processes episodes that were added before entity extraction was enabled.
        Extracts episode types and entity mentions using the LLM.
        
        Args:
            limit: Maximum episodes to process (default: 100)
        
        Returns:
            Summary of what was extracted
        """
        return await tool_backfill(limit)
    
    @mcp.tool()
    async def decisions(limit: int = 20) -> str:
        """Show decision-type episodes.
        
        Decisions are episodes classified as choices or decisions that were made.
        Useful for reviewing past choices and their context.
        
        Args:
            limit: Maximum decisions to show
        
        Returns:
            List of decision episodes
        """
        return await tool_decisions(limit)
    
    @mcp.tool()
    async def questions(limit: int = 20) -> str:
        """Show open questions and uncertainties.
        
        Questions are episodes classified as open questions, uncertainties,
        or things that need investigation.
        
        Args:
            limit: Maximum questions to show
        
        Returns:
            List of question episodes
        """
        return await tool_questions(limit)
    
    return mcp


def run_server(host: str = "127.0.0.1", port: int = 8765):
    """Run the MCP server with HTTP transport."""
    import uvicorn
    from fastmcp.server.http import create_sse_app
    
    mcp = create_mcp_server()
    
    # Create the SSE app with FastMCP
    sse_app = create_sse_app(
        server=mcp,
        sse_path="/sse",
        message_path="/messages",
    )
    
    # Create custom ASGI middleware to inject db context
    async def app(scope, receive, send):
        if scope['type'] == 'lifespan':
            # Handle lifespan
            while True:
                message = await receive()
                if message['type'] == 'lifespan.startup':
                    logger.info(f"RealMem MCP server starting on {host}:{port}")
                    await send({'type': 'lifespan.startup.complete'})
                elif message['type'] == 'lifespan.shutdown':
                    logger.info("RealMem MCP server shutting down")
                    # Clean up session map
                    _session_db_map.clear()
                    await send({'type': 'lifespan.shutdown.complete'})
                    return
        
        elif scope['type'] == 'http':
            path = scope.get('path', '')
            method = scope.get('method', 'GET')
            query_string = scope.get('query_string', b'').decode()
            params = parse_qs(query_string)
            
            # Extract db from query params
            db_list = params.get('db', [])
            session_list = params.get('session_id', [])
            
            db_path = None
            
            # Case 1: db param provided directly (initial SSE connection)
            if db_list:
                db_path = str(Path(db_list[0]).resolve())
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
                        'body': b'Missing required query parameter: db\n\nExample: /sse?db=/path/to/memory.db',
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
    
    print(f"Starting RealMem MCP server on {host}:{port}")
    print(f"Connect with: http://{host}:{port}/sse?db=/path/to/memory.db")
    
    uvicorn.run(app, host=host, port=port, log_level="info")


def main():
    """CLI entry point for the MCP server."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="RealMem MCP Server - Memory system via Model Context Protocol"
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to listen on (default: 8765)"
    )
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
    
    run_server(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
