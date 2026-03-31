"""REST API routes for Remind web UI."""

import json
import logging
from pathlib import Path
from typing import Optional

from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route

from remind.models import Entity, EpisodeType, TaskStatus, normalize_entity_name
from remind.config import load_config

logger = logging.getLogger(__name__)


def _normalize_entity_param(raw: str) -> str:
    """Normalize an entity ID from a URL path or query parameter."""
    from urllib.parse import unquote
    entity_id = unquote(raw)
    type_str, name = Entity.parse_id(entity_id)
    return Entity.make_id(type_str, normalize_entity_name(name))

# Import config and memory instance cache
from remind.config import resolve_db_url, _is_db_url, REMIND_DIR
from remind.mcp_server import get_memory_for_db, resolve_db_alias


async def _get_memory_from_request(request: Request):
    """Get MemoryInterface from request's db query param."""
    db_name = request.query_params.get("db")
    if not db_name:
        return None, JSONResponse(
            {"error": "Missing required 'db' query parameter"},
            status_code=400,
        )

    try:
        db_url = resolve_db_alias(db_name)
        if db_url is None:
            db_url = db_name if _is_db_url(db_name) else resolve_db_url(db_name)
        memory = await get_memory_for_db(db_url)
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
        topic_id = request.query_params.get("topic")

        all_concepts = memory.store.get_all_concepts()

        if topic_id:
            all_concepts = [c for c in all_concepts if c.topic_id == topic_id]

        if search:
            search_lower = search.lower()
            all_concepts = [
                c for c in all_concepts
                if search_lower in c.summary.lower()
                or (c.title and search_lower in c.title.lower())
                or any(search_lower in tag.lower() for tag in c.tags)
            ]

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
                    "content": episode.content[:150],
                    "type": episode.episode_type,
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


async def update_concept(request: Request) -> JSONResponse:
    """Update an existing concept."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    concept_id = request.path_params.get("id")

    try:
        body = await request.json()
        title = body.get("title")
        summary = body.get("summary")
        confidence = body.get("confidence")
        conditions = body.get("conditions")
        exceptions = body.get("exceptions")
        tags = body.get("tags")
        relations = body.get("relations")

        updated = memory.update_concept(
            concept_id,
            title=title,
            summary=summary,
            confidence=confidence,
            conditions=conditions,
            exceptions=exceptions,
            tags=tags,
            relations=relations,
        )

        if not updated:
            return JSONResponse({"error": "Concept not found"}, status_code=404)

        return JSONResponse({"success": True, "concept": updated.to_dict()})
    except Exception as e:
        logger.exception("Failed to update concept")
        return JSONResponse({"error": str(e)}, status_code=500)


async def delete_concept(request: Request) -> JSONResponse:
    """Soft delete a concept."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    concept_id = request.path_params.get("id")

    try:
        if memory.delete_concept(concept_id):
            return JSONResponse({"success": True})
        return JSONResponse({"error": "Concept not found"}, status_code=404)
    except Exception as e:
        logger.exception("Failed to delete concept")
        return JSONResponse({"error": str(e)}, status_code=500)


async def restore_concept(request: Request) -> JSONResponse:
    """Restore a soft-deleted concept."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    concept_id = request.path_params.get("id")

    try:
        if memory.restore_concept(concept_id):
            return JSONResponse({"success": True})
        return JSONResponse({"error": "Concept not found or not deleted"}, status_code=404)
    except Exception as e:
        logger.exception("Failed to restore concept")
        return JSONResponse({"error": str(e)}, status_code=500)


async def purge_concept(request: Request) -> JSONResponse:
    """Permanently delete a concept."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    concept_id = request.path_params.get("id")

    try:
        if memory.purge_concept(concept_id):
            return JSONResponse({"success": True})
        return JSONResponse({"error": "Concept not found"}, status_code=404)
    except Exception as e:
        logger.exception("Failed to purge concept")
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_deleted_concepts(request: Request) -> JSONResponse:
    """Get soft-deleted concepts."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    try:
        deleted = memory.get_deleted_concepts()
        return JSONResponse({
            "concepts": [c.to_dict() for c in deleted],
            "total": len(deleted),
        })
    except Exception as e:
        logger.exception("Failed to get deleted concepts")
        return JSONResponse({"error": str(e)}, status_code=500)


async def purge_all_deleted(request: Request) -> JSONResponse:
    """Permanently delete all soft-deleted items."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    try:
        deleted_episodes = memory.get_deleted_episodes(limit=10000)
        deleted_concepts = memory.get_deleted_concepts()

        ep_count = 0
        c_count = 0

        for ep in deleted_episodes:
            if memory.purge_episode(ep.id):
                ep_count += 1

        for c in deleted_concepts:
            if memory.purge_concept(c.id):
                c_count += 1

        return JSONResponse({
            "success": True,
            "episodes_purged": ep_count,
            "concepts_purged": c_count,
        })
    except Exception as e:
        logger.exception("Failed to purge all deleted")
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
        topic_filter = request.query_params.get("topic")

        if episode_type:
            all_episodes = memory.store.get_episodes_by_type(episode_type, limit=1000)
        elif start_date or end_date:
            all_episodes = memory.store.get_episodes_by_date_range(
                start_date=start_date,
                end_date=end_date,
                limit=1000,
            )
        else:
            all_episodes = memory.store.get_recent_episodes(limit=1000)

        if consolidated is not None:
            is_consolidated = consolidated.lower() == "true"
            all_episodes = [e for e in all_episodes if e.consolidated == is_consolidated]

        if topic_filter:
            all_episodes = [e for e in all_episodes if e.topic_id == topic_filter]

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


async def update_episode(request: Request) -> JSONResponse:
    """Update an existing episode."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    episode_id = request.path_params.get("id")

    try:
        body = await request.json()
        content = body.get("content")
        episode_type = body.get("episode_type")
        entities = body.get("entities")
        metadata = body.get("metadata")

        if metadata is not None and not isinstance(metadata, dict):
            return JSONResponse({"error": "metadata must be an object"}, status_code=400)

        updated = memory.update_episode(
            episode_id,
            content=content,
            episode_type=episode_type or None,
            entities=entities,
            metadata=metadata,
        )

        if not updated:
            return JSONResponse({"error": "Episode not found"}, status_code=404)

        return JSONResponse({"success": True, "episode": updated.to_dict()})
    except Exception as e:
        logger.exception("Failed to update episode")
        return JSONResponse({"error": str(e)}, status_code=500)


async def delete_episode(request: Request) -> JSONResponse:
    """Soft delete an episode."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    episode_id = request.path_params.get("id")

    try:
        if memory.delete_episode(episode_id):
            return JSONResponse({"success": True})
        return JSONResponse({"error": "Episode not found"}, status_code=404)
    except Exception as e:
        logger.exception("Failed to delete episode")
        return JSONResponse({"error": str(e)}, status_code=500)


async def restore_episode(request: Request) -> JSONResponse:
    """Restore a soft-deleted episode."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    episode_id = request.path_params.get("id")

    try:
        if memory.restore_episode(episode_id):
            return JSONResponse({"success": True})
        return JSONResponse({"error": "Episode not found or not deleted"}, status_code=404)
    except Exception as e:
        logger.exception("Failed to restore episode")
        return JSONResponse({"error": str(e)}, status_code=500)


async def purge_episode(request: Request) -> JSONResponse:
    """Permanently delete an episode."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    episode_id = request.path_params.get("id")

    try:
        if memory.purge_episode(episode_id):
            return JSONResponse({"success": True})
        return JSONResponse({"error": "Episode not found"}, status_code=404)
    except Exception as e:
        logger.exception("Failed to purge episode")
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_deleted_episodes(request: Request) -> JSONResponse:
    """Get soft-deleted episodes."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    try:
        limit = int(request.query_params.get("limit", 50))
        deleted = memory.get_deleted_episodes(limit=limit)
        return JSONResponse({
            "episodes": [e.to_dict() for e in deleted],
            "total": len(deleted),
        })
    except Exception as e:
        logger.exception("Failed to get deleted episodes")
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

    entity_id = _normalize_entity_param(request.path_params.get("id", ""))

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

    entity_id = _normalize_entity_param(request.path_params.get("id", ""))
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

    entity_id = _normalize_entity_param(request.path_params.get("id", ""))
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
                        "content": episode.content[:200],
                        "type": episode.episode_type,
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
        query = body.get("query") or None
        k = body.get("k", 3)
        entity = body.get("entity") or None
        topic = body.get("topic") or None

        if not query and not entity:
            return JSONResponse(
                {"error": "Either 'query' or 'entity' must be provided"},
                status_code=400,
            )

        result = await memory.recall(query=query, k=k, entity=entity, raw=True, topic=topic)

        if entity:
            return JSONResponse({
                "episodes": [e.to_dict() for e in result],
                "formatted": memory.retriever.format_entity_context(entity, result),
            })

        topic_names = memory._get_topic_names()
        formatted = memory.retriever.format_for_llm(
            result,
            group_by_topic=topic is None,
            topic_names=topic_names,
        )

        return JSONResponse({
            "concepts": [
                {
                    "concept": r.concept.to_dict(),
                    "activation": r.activation,
                    "source": r.source,
                    "hops": r.hops,
                }
                for r in result
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
# Config
# =============================================================================


async def get_config(request: Request) -> JSONResponse:
    """Return relevant configuration for the web UI.

    Uses CWD as project_dir so project-local .remind/remind.config.json
    is picked up when the server is started from a project directory.
    """
    try:
        config = load_config(project_dir=Path.cwd())
        return JSONResponse({
            "episode_types": config.episode_types,
        })
    except Exception as e:
        logger.exception("Failed to get config")
        return JSONResponse({"error": str(e)}, status_code=500)


# =============================================================================
# Tasks
# =============================================================================


async def get_tasks(request: Request) -> JSONResponse:
    """Get tasks with optional status/entity/plan filters."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    try:
        status = request.query_params.get("status")
        entity_id = request.query_params.get("entity")
        plan_id = request.query_params.get("plan_id")
        include_done = request.query_params.get("include_done", "false").lower() == "true"
        limit = int(request.query_params.get("limit", 50))

        tasks = memory.get_tasks(
            status=status,
            entity_id=entity_id,
            plan_id=plan_id,
            limit=1000,
        )

        if not include_done:
            tasks = [t for t in tasks if (t.metadata or {}).get("status") != "done"]

        total = len(tasks)
        tasks = tasks[:limit]

        return JSONResponse({
            "tasks": [t.to_dict() for t in tasks],
            "total": total,
        })
    except Exception as e:
        logger.exception("Failed to get tasks")
        return JSONResponse({"error": str(e)}, status_code=500)


async def update_task_status(request: Request) -> JSONResponse:
    """Update a task's status."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    task_id = request.path_params.get("id")

    try:
        body = await request.json()
        status = body.get("status")
        reason = body.get("reason")

        if not status:
            return JSONResponse({"error": "Missing 'status' in request body"}, status_code=400)

        updated = memory.update_task_status(task_id, status, reason=reason)
        if not updated:
            return JSONResponse({"error": "Task not found or invalid status"}, status_code=404)

        return JSONResponse({"success": True, "task": updated.to_dict()})
    except Exception as e:
        logger.exception("Failed to update task status")
        return JSONResponse({"error": str(e)}, status_code=500)


async def add_task(request: Request) -> JSONResponse:
    """Create a new task episode."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    try:
        body = await request.json()
        content = body.get("content")
        if not content:
            return JSONResponse({"error": "Missing 'content' in request body"}, status_code=400)

        entities = body.get("entities", [])
        priority = body.get("priority", "p1")
        plan_id = body.get("plan_id")
        spec_ids = body.get("spec_ids", [])
        depends_on = body.get("depends_on", [])

        metadata = {"status": "todo", "priority": priority}
        if plan_id:
            metadata["plan_id"] = plan_id
        if spec_ids:
            metadata["spec_ids"] = spec_ids
        if depends_on:
            metadata["depends_on"] = depends_on

        episode_id = await memory.remember(
            content=content,
            episode_type=EpisodeType.TASK.value,
            entities=entities or None,
            metadata=metadata,
        )

        episode = memory.store.get_episode(episode_id)
        if not episode:
            return JSONResponse(
                {"error": "Task was created but could not be loaded"},
                status_code=500,
            )

        return JSONResponse({"success": True, "task": episode.to_dict()}, status_code=201)
    except Exception as e:
        logger.exception("Failed to add task")
        return JSONResponse({"error": str(e)}, status_code=500)


# =============================================================================
# Specs & Plans
# =============================================================================


async def get_specs(request: Request) -> JSONResponse:
    """Get spec episodes."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    try:
        limit = int(request.query_params.get("limit", 50))
        entity_id = request.query_params.get("entity")
        status = request.query_params.get("status")

        specs = memory.store.get_episodes_by_type(EpisodeType.SPEC.value, limit=1000)

        if entity_id:
            norm_eid = _normalize_entity_param(entity_id)
            specs = [s for s in specs if norm_eid in s.entity_ids]
        if status:
            specs = [s for s in specs if (s.metadata or {}).get("spec_status") == status]

        total = len(specs)
        specs = specs[:limit]

        return JSONResponse({
            "specs": [s.to_dict() for s in specs],
            "total": total,
        })
    except Exception as e:
        logger.exception("Failed to get specs")
        return JSONResponse({"error": str(e)}, status_code=500)


async def get_plans(request: Request) -> JSONResponse:
    """Get plan episodes."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error

    try:
        limit = int(request.query_params.get("limit", 50))
        entity_id = request.query_params.get("entity")
        status = request.query_params.get("status")

        plans = memory.store.get_episodes_by_type(EpisodeType.PLAN.value, limit=1000)

        if entity_id:
            norm_eid = _normalize_entity_param(entity_id)
            plans = [p for p in plans if norm_eid in p.entity_ids]
        if status:
            plans = [p for p in plans if (p.metadata or {}).get("plan_status") == status]

        total = len(plans)
        plans = plans[:limit]

        return JSONResponse({
            "plans": [p.to_dict() for p in plans],
            "total": total,
        })
    except Exception as e:
        logger.exception("Failed to get plans")
        return JSONResponse({"error": str(e)}, status_code=500)


# =============================================================================
# Topics
# =============================================================================


async def api_get_topics(request: Request) -> JSONResponse:
    """List all topics with stats."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error
    try:
        topics = memory.list_topics()
        return JSONResponse({"topics": topics, "total": len(topics)})
    except Exception as e:
        logger.exception("Failed to get topics")
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_create_topic(request: Request) -> JSONResponse:
    """Create a new topic."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error
    try:
        body = await request.json()
        name = body.get("name", "").strip()
        if not name:
            return JSONResponse({"error": "name is required"}, status_code=400)
        description = body.get("description", "")
        topic = memory.create_topic(name, description=description)
        return JSONResponse(topic.to_dict(), status_code=201)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    except Exception as e:
        logger.exception("Failed to create topic")
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_get_topic_detail(request: Request) -> JSONResponse:
    """Get a single topic by ID with stats."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error
    topic_id = request.path_params.get("id")
    try:
        topic = memory.get_topic(topic_id)
        if not topic:
            return JSONResponse({"error": "Topic not found"}, status_code=404)
        stats = memory.list_topics()
        topic_stat = next((t for t in stats if t["id"] == topic_id), None)
        result = topic.to_dict()
        if topic_stat:
            result["episode_count"] = topic_stat["episode_count"]
            result["concept_count"] = topic_stat["concept_count"]
            result["latest_activity"] = topic_stat.get("latest_activity")
        return JSONResponse(result)
    except Exception as e:
        logger.exception("Failed to get topic detail")
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_update_topic(request: Request) -> JSONResponse:
    """Update a topic."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error
    topic_id = request.path_params.get("id")
    try:
        body = await request.json()
        name = body.get("name")
        description = body.get("description")
        updated = memory.update_topic(topic_id, name=name, description=description)
        if not updated:
            return JSONResponse({"error": "Topic not found"}, status_code=404)
        return JSONResponse(updated.to_dict())
    except Exception as e:
        logger.exception("Failed to update topic")
        return JSONResponse({"error": str(e)}, status_code=500)


async def api_delete_topic(request: Request) -> JSONResponse:
    """Delete a topic (only if not in use)."""
    memory, error = await _get_memory_from_request(request)
    if error:
        return error
    topic_id = request.path_params.get("id")
    try:
        if memory.delete_topic(topic_id):
            return JSONResponse({"deleted": True})
        return JSONResponse({"error": "Topic not found"}, status_code=404)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    except Exception as e:
        logger.exception("Failed to delete topic")
        return JSONResponse({"error": str(e)}, status_code=500)


# =============================================================================
# Route definitions
# =============================================================================


api_routes = [
    Route("/api/v1/stats", get_stats, methods=["GET"]),
    # Concepts
    Route("/api/v1/concepts", get_concepts, methods=["GET"]),
    Route("/api/v1/concepts/deleted", get_deleted_concepts, methods=["GET"]),
    Route("/api/v1/concepts/{id}", get_concept_detail, methods=["GET"]),
    Route("/api/v1/concepts/{id}", update_concept, methods=["PUT", "PATCH"]),
    Route("/api/v1/concepts/{id}", delete_concept, methods=["DELETE"]),
    Route("/api/v1/concepts/{id}/restore", restore_concept, methods=["POST"]),
    Route("/api/v1/concepts/{id}/purge", purge_concept, methods=["DELETE"]),
    # Episodes
    Route("/api/v1/episodes", get_episodes, methods=["GET"]),
    Route("/api/v1/episodes/deleted", get_deleted_episodes, methods=["GET"]),
    Route("/api/v1/episodes/{id}", get_episode_detail, methods=["GET"]),
    Route("/api/v1/episodes/{id}", update_episode, methods=["PUT", "PATCH"]),
    Route("/api/v1/episodes/{id}", delete_episode, methods=["DELETE"]),
    Route("/api/v1/episodes/{id}/restore", restore_episode, methods=["POST"]),
    Route("/api/v1/episodes/{id}/purge", purge_episode, methods=["DELETE"]),
    # Entities
    Route("/api/v1/entities", get_entities, methods=["GET"]),
    Route("/api/v1/entities/{id:path}/episodes", get_entity_episodes, methods=["GET"]),
    Route("/api/v1/entities/{id:path}/concepts", get_entity_concepts, methods=["GET"]),
    Route("/api/v1/entities/{id:path}", get_entity_detail, methods=["GET"]),
    # Graph
    Route("/api/v1/graph", get_graph, methods=["GET"]),
    Route("/api/v1/entity-graph", get_entity_graph, methods=["GET"]),
    # Query/Chat
    Route("/api/v1/query", execute_query, methods=["POST"]),
    Route("/api/v1/chat", stream_chat, methods=["POST"]),
    # Databases
    Route("/api/v1/databases", list_databases, methods=["GET"]),
    # Config
    Route("/api/v1/config", get_config, methods=["GET"]),
    # Tasks
    Route("/api/v1/tasks", get_tasks, methods=["GET"]),
    Route("/api/v1/tasks", add_task, methods=["POST"]),
    Route("/api/v1/tasks/{id}/status", update_task_status, methods=["PUT", "PATCH"]),
    # Specs & Plans
    Route("/api/v1/specs", get_specs, methods=["GET"]),
    Route("/api/v1/plans", get_plans, methods=["GET"]),
    # Topics
    Route("/api/v1/topics", api_get_topics, methods=["GET"]),
    Route("/api/v1/topics", api_create_topic, methods=["POST"]),
    Route("/api/v1/topics/{id}", api_get_topic_detail, methods=["GET"]),
    Route("/api/v1/topics/{id}", api_update_topic, methods=["PUT", "PATCH"]),
    Route("/api/v1/topics/{id}", api_delete_topic, methods=["DELETE"]),
    # Bulk operations
    Route("/api/v1/deleted/purge-all", purge_all_deleted, methods=["DELETE"]),
]
