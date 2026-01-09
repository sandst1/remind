"""REST API routes for Remind web UI."""

import json
import logging
from pathlib import Path
from typing import Optional

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from remind.models import EpisodeType

logger = logging.getLogger(__name__)

# Import from mcp_server - we share the same memory instance cache
from remind.mcp_server import (
    resolve_db_path,
    get_memory_for_db,
    REMIND_DIR,
)


async def _get_memory_from_request(request: Request):
    """Get MemoryInterface from request's db query param."""
    db_name = request.query_params.get("db")
    if not db_name:
        return None, JSONResponse(
            {"error": "Missing required 'db' query parameter"},
            status_code=400,
        )

    try:
        db_path = resolve_db_path(db_name)
        memory = await get_memory_for_db(db_path)
        return memory, None
    except ValueError as e:
        return None, JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        logger.exception("Failed to get memory interface")
        return None, JSONResponse({"error": str(e)}, status_code=500)


# =============================================================================
# Stats
# =============================================================================


async def get_stats(request: Request) -> JSONResponse:
    """Get memory statistics."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    try:
        stats = memory.store.get_stats()
        return JSONResponse(stats)
    except Exception as e:
        logger.exception("Failed to get stats")
        return JSONResponse({"error": str(e)}, status_code=500)


# =============================================================================
# Concepts
# =============================================================================


async def get_concepts(request: Request) -> JSONResponse:
    """Get paginated list of concepts."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    try:
        offset = int(request.query_params.get("offset", 0))
        limit = int(request.query_params.get("limit", 50))
        search = request.query_params.get("search", "")

        all_concepts = memory.store.get_all_concepts()

        # Simple search filter
        if search:
            search_lower = search.lower()
            all_concepts = [
                c for c in all_concepts
                if search_lower in c.summary.lower()
                or (c.title and search_lower in c.title.lower())
                or any(search_lower in tag.lower() for tag in c.tags)
            ]

        # Sort alphabetically by title (or summary if no title)
        all_concepts.sort(key=lambda c: (c.title or c.summary).lower())

        total = len(all_concepts)
        concepts = all_concepts[offset : offset + limit]

        return JSONResponse({
            "concepts": [c.to_dict() for c in concepts],
            "total": total,
        })
    except Exception as e:
        logger.exception("Failed to get concepts")
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_concept_detail(request: Request) -> JSONResponse:
    """Get a single concept by ID."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    concept_id = request.path_params.get("id")

    try:
        concept = memory.store.get_concept(concept_id)
        if not concept:
            return JSONResponse({"error": "Concept not found"}, status_code=404)

        result = concept.to_dict()

        # Add source episode data with content summaries
        source_episodes_data = []
        for ep_id in concept.source_episodes[:10]:  # Limit to 10
            episode = memory.store.get_episode(ep_id)
            if episode:
                source_episodes_data.append({
                    "id": episode.id,
                    "title": episode.title,
                    "content": episode.content[:150],  # Truncated preview
                    "type": episode.episode_type.value,
                })
        result["source_episodes_data"] = source_episodes_data

        # Add target summaries for relations and filter out invalid ones
        concept_map = {c.id: c for c in memory.store.get_all_concepts()}
        valid_relations = []
        for rel in result.get("relations", []):
            target = concept_map.get(rel["target_id"])
            if target:
                rel["target_summary"] = target.summary[:100]
                valid_relations.append(rel)
            # Skip relations to non-existent concepts (data integrity issue)
        result["relations"] = valid_relations

        return JSONResponse(result)
    except Exception as e:
        logger.exception("Failed to get concept")
        return JSONResponse({"error": str(e)}, status_code=500)


# =============================================================================
# Episodes
# =============================================================================


async def get_episodes(request: Request) -> JSONResponse:
    """Get paginated list of episodes with filters."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    try:
        offset = int(request.query_params.get("offset", 0))
        limit = int(request.query_params.get("limit", 50))
        episode_type = request.query_params.get("type")
        consolidated = request.query_params.get("consolidated")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")
        search = request.query_params.get("search", "")

        # Get episodes based on filters
        if episode_type:
            try:
                ep_type = EpisodeType(episode_type)
                all_episodes = memory.store.get_episodes_by_type(ep_type, limit=1000)
            except ValueError:
                return JSONResponse(
                    {"error": f"Invalid episode type: {episode_type}"},
                    status_code=400,
                )
        elif start_date or end_date:
            all_episodes = memory.store.get_episodes_by_date_range(
                start_date=start_date,
                end_date=end_date,
                limit=1000,
            )
        else:
            all_episodes = memory.store.get_recent_episodes(limit=1000)

        # Filter by consolidated status
        if consolidated is not None:
            is_consolidated = consolidated.lower() == "true"
            all_episodes = [e for e in all_episodes if e.consolidated == is_consolidated]

        # Filter by search term (fulltext search on content)
        if search:
            search_lower = search.lower()
            all_episodes = [
                e for e in all_episodes
                if search_lower in e.content.lower()
            ]

        total = len(all_episodes)
        episodes = all_episodes[offset : offset + limit]

        return JSONResponse({
            "episodes": [e.to_dict() for e in episodes],
            "total": total,
        })
    except Exception as e:
        logger.exception("Failed to get episodes")
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_episode_detail(request: Request) -> JSONResponse:
    """Get a single episode by ID."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    episode_id = request.path_params.get("id")

    try:
        episode = memory.store.get_episode(episode_id)
        if not episode:
            return JSONResponse({"error": "Episode not found"}, status_code=404)

        return JSONResponse(episode.to_dict())
    except Exception as e:
        logger.exception("Failed to get episode")
        return JSONResponse({"error": str(e)}, status_code=500)


# =============================================================================
# Entities
# =============================================================================


async def get_entities(request: Request) -> JSONResponse:
    """Get all entities with mention counts."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    try:
        # get_entity_mention_counts returns list[tuple[Entity, int]]
        entity_counts = memory.store.get_entity_mention_counts()

        entities_data = []
        for entity, count in entity_counts:
            data = entity.to_dict()
            data["mention_count"] = count
            entities_data.append(data)

        return JSONResponse({
            "entities": entities_data,
            "total": len(entities_data),
        })
    except Exception as e:
        logger.exception("Failed to get entities")
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_entity_detail(request: Request) -> JSONResponse:
    """Get a single entity by ID with relationships."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    # Entity IDs may be URL-encoded (they contain colons)
    from urllib.parse import unquote
    entity_id = unquote(request.path_params.get("id", ""))

    try:
        entity = memory.store.get_entity(entity_id)
        if not entity:
            return JSONResponse({"error": "Entity not found"}, status_code=404)

        # Find mention count for this entity
        entity_counts = memory.store.get_entity_mention_counts()
        mention_count = 0
        for ent, count in entity_counts:
            if ent.id == entity_id:
                mention_count = count
                break

        data = entity.to_dict()
        data["mention_count"] = mention_count

        # Get entity relations
        relations = memory.store.get_entity_relations(entity_id)
        enriched_relations = []
        for rel in relations:
            rel_dict = rel.to_dict()
            # Determine direction and enrich with related entity info
            if rel.source_id == entity_id:
                rel_dict["direction"] = "outgoing"
                related_entity = memory.store.get_entity(rel.target_id)
                rel_dict["related_entity"] = related_entity.to_dict() if related_entity else None
            else:
                rel_dict["direction"] = "incoming"
                related_entity = memory.store.get_entity(rel.source_id)
                rel_dict["related_entity"] = related_entity.to_dict() if related_entity else None
            enriched_relations.append(rel_dict)

        data["relations"] = enriched_relations

        return JSONResponse(data)
    except Exception as e:
        logger.exception("Failed to get entity")
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_entity_episodes(request: Request) -> JSONResponse:
    """Get episodes mentioning a specific entity."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    from urllib.parse import unquote
    entity_id = unquote(request.path_params.get("id", ""))
    limit = int(request.query_params.get("limit", 50))

    try:
        episodes = memory.store.get_episodes_mentioning(entity_id, limit=limit)
        return JSONResponse({
            "episodes": [e.to_dict() for e in episodes],
        })
    except Exception as e:
        logger.exception("Failed to get entity episodes")
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_entity_concepts(request: Request) -> JSONResponse:
    """Get concepts derived from episodes mentioning a specific entity."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    from urllib.parse import unquote
    entity_id = unquote(request.path_params.get("id", ""))
    limit = int(request.query_params.get("limit", 50))

    try:
        concepts = memory.store.get_concepts_for_entity(entity_id, limit=limit)
        return JSONResponse({
            "concepts": [c.to_dict() for c in concepts],
        })
    except Exception as e:
        logger.exception("Failed to get entity concepts")
        return JSONResponse({"error": str(e)}, status_code=500)


# =============================================================================
# Graph
# =============================================================================


async def get_graph(request: Request) -> JSONResponse:
    """Get full graph data for D3 visualization."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    try:
        all_concepts = memory.store.get_all_concepts()

        # Build concept ID to concept map for quick lookup
        concept_map = {c.id: c for c in all_concepts}

        nodes = []
        links = []

        for concept in all_concepts:
            # Get source episodes content
            source_episodes_data = []
            for ep_id in concept.source_episodes[:5]:  # Limit to 5
                episode = memory.store.get_episode(ep_id)
                if episode:
                    source_episodes_data.append({
                        "id": episode.id,
                        "title": episode.title,
                        "content": episode.content[:200],  # Truncate
                        "type": episode.episode_type.value,
                    })

            # Build relations with target summaries
            relations_data = []
            for rel in concept.relations:
                target = concept_map.get(rel.target_id)
                relations_data.append({
                    "type": rel.type.value,
                    "target_id": rel.target_id,
                    "target_summary": target.summary[:100] if target else None,
                    "strength": rel.strength,
                    "context": rel.context,
                })

            # Parse conditions as list
            conditions = []
            if concept.conditions:
                # Split by common delimiters
                if "\n" in concept.conditions:
                    conditions = [c.strip() for c in concept.conditions.split("\n") if c.strip()]
                else:
                    conditions = [concept.conditions]

            nodes.append({
                "id": concept.id,
                "title": concept.title,
                "summary": concept.summary,
                "confidence": concept.confidence,
                "instance_count": concept.instance_count,
                "conditions": conditions,
                "exceptions": concept.exceptions,
                "tags": concept.tags,
                "source_episodes": source_episodes_data,
                "relations": relations_data,
            })

            # Create links for D3
            for rel in concept.relations:
                # Only include links where target exists
                if rel.target_id in concept_map:
                    links.append({
                        "source": concept.id,
                        "target": rel.target_id,
                        "type": rel.type.value,
                        "strength": rel.strength,
                        "context": rel.context,
                    })

        return JSONResponse({
            "nodes": nodes,
            "links": links,
        })
    except Exception as e:
        logger.exception("Failed to get graph")
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_entity_graph(request: Request) -> JSONResponse:
    """Get entity network graph data for D3 visualization."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    try:
        # Get all entities with mention counts
        entity_counts = memory.store.get_entity_mention_counts()

        # Build entity map for quick lookup
        entity_map = {ent.id: ent for ent, _ in entity_counts}

        nodes = []
        links = []

        # Collect all entity relations (dedupe by source, target, type)
        all_relations = set()  # (source, target, type) tuples

        for entity, mention_count in entity_counts:
            # Get relations for this entity
            relations = memory.store.get_entity_relations(entity.id)

            for rel in relations:
                # Only include if both entities exist
                if rel.source_id in entity_map and rel.target_id in entity_map:
                    key = (rel.source_id, rel.target_id, rel.relation_type)
                    if key not in all_relations:
                        all_relations.add(key)
                        links.append({
                            "source": rel.source_id,
                            "target": rel.target_id,
                            "type": rel.relation_type,
                            "strength": rel.strength,
                            "context": rel.context,
                        })

        # Only include entities that have relations
        entities_with_relations = set()
        for link in links:
            entities_with_relations.add(link["source"])
            entities_with_relations.add(link["target"])

        for entity, mention_count in entity_counts:
            if entity.id in entities_with_relations:
                nodes.append({
                    "id": entity.id,
                    "type": entity.type.value,
                    "display_name": entity.display_name,
                    "mention_count": mention_count,
                })

        return JSONResponse({
            "nodes": nodes,
            "links": links,
        })
    except Exception as e:
        logger.exception("Failed to get entity graph")
        return JSONResponse({"error": str(e)}, status_code=500)


# =============================================================================
# Query
# =============================================================================


async def execute_query(request: Request) -> JSONResponse:
    """Execute a recall query using the LLM retriever."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    try:
        body = await request.json()
        query = body.get("query", "")
        k = body.get("k", 5)

        if not query:
            return JSONResponse({"error": "Missing 'query' in request body"}, status_code=400)

        # Use the memory interface's recall method with raw=True to get ActivatedConcept objects
        results = await memory.recall(query, k=k, raw=True)

        # Get the formatted output for LLM context
        formatted = memory.retriever.format_for_llm(results)

        return JSONResponse({
            "concepts": [
                {
                    "concept": r.concept.to_dict(),
                    "activation": r.activation,
                    "source": r.source,
                    "hops": r.hops,
                }
                for r in results
            ],
            "formatted": formatted,
        })
    except Exception as e:
        logger.exception("Failed to execute query")
        return JSONResponse({"error": str(e)}, status_code=500)


# =============================================================================
# Chat
# =============================================================================

CHAT_SYSTEM_PROMPT = """You are a helpful assistant with access to the user's memory system.
Answer questions based on the provided memory context.
Be concise and direct. If the memory doesn't contain relevant information, say so.
Do not make up information that isn't in the provided context."""


async def stream_chat(request: Request):
    """Stream a chat response using the LLM with memory context."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    try:
        body = await request.json()
        messages = body.get("messages", [])
        context = body.get("context", "")

        if not messages:
            return JSONResponse(
                {"error": "Missing 'messages' in request body"},
                status_code=400,
            )

        # Build the system prompt with memory context
        system_prompt = CHAT_SYSTEM_PROMPT
        if context:
            system_prompt += f"\n\n{context}"

        # Convert messages to the format expected by the LLM provider
        chat_messages = [
            {"role": msg["role"], "content": msg["content"]}
            for msg in messages
        ]

        async def generate():
            try:
                async for chunk in memory.llm.complete_stream(
                    messages=chat_messages,
                    system=system_prompt,
                    temperature=0.7,
                    max_tokens=2048,
                ):
                    # Send as SSE format
                    yield f"data: {json.dumps({'chunk': chunk})}\n\n"
                # Signal completion
                yield f"data: {json.dumps({'done': True})}\n\n"
            except Exception as e:
                logger.exception("Error during chat streaming")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    except Exception as e:
        logger.exception("Failed to start chat stream")
        return JSONResponse({"error": str(e)}, status_code=500)


# =============================================================================
# Databases
# =============================================================================


async def list_databases(request: Request) -> JSONResponse:
    """List available databases in ~/.remind/."""
    try:
        databases = []

        if REMIND_DIR.exists():
            for db_file in sorted(REMIND_DIR.glob("*.db")):
                name = db_file.stem
                databases.append({
                    "name": name,
                    "path": str(db_file),
                })

        return JSONResponse({"databases": databases})
    except Exception as e:
        logger.exception("Failed to list databases")
        return JSONResponse({"error": str(e)}, status_code=500)


# =============================================================================
# Route definitions
# =============================================================================


api_routes = [
    Route("/api/v1/stats", get_stats, methods=["GET"]),
    Route("/api/v1/concepts", get_concepts, methods=["GET"]),
    Route("/api/v1/concepts/{id}", get_concept_detail, methods=["GET"]),
    Route("/api/v1/episodes", get_episodes, methods=["GET"]),
    Route("/api/v1/episodes/{id}", get_episode_detail, methods=["GET"]),
    Route("/api/v1/entities", get_entities, methods=["GET"]),
    Route("/api/v1/entities/{id:path}/episodes", get_entity_episodes, methods=["GET"]),
    Route("/api/v1/entities/{id:path}/concepts", get_entity_concepts, methods=["GET"]),
    Route("/api/v1/entities/{id:path}", get_entity_detail, methods=["GET"]),
    Route("/api/v1/graph", get_graph, methods=["GET"]),
    Route("/api/v1/entity-graph", get_entity_graph, methods=["GET"]),
    Route("/api/v1/query", execute_query, methods=["POST"]),
    Route("/api/v1/chat", stream_chat, methods=["POST"]),
    Route("/api/v1/databases", list_databases, methods=["GET"]),
]
