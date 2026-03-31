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
from remind.models import Entity, normalize_entity_name
from remind.config import REMIND_DIR, resolve_db_path, resolve_db_url, _is_db_url, load_config

logger = logging.getLogger(__name__)

# Context variable to track current database path per async context
_current_db: ContextVar[str] = ContextVar('current_db', default='')

# Session ID to database path mapping (for SSE sessions)
_session_db_map: dict[str, str] = {}

# Cache of MemoryInterface instances keyed by database path
_memory_instances: dict[str, MemoryInterface] = {}
_memory_locks: dict[str, asyncio.Lock] = {}
_global_lock = asyncio.Lock()


async def get_memory_for_db(db_path: str) -> MemoryInterface:
    """Get or create a MemoryInterface for the given database URL or path.

    Note: db_path should already be resolved via resolve_db_url() by the caller.
    """

    async with _global_lock:
        if db_path not in _memory_locks:
            _memory_locks[db_path] = asyncio.Lock()
        lock = _memory_locks[db_path]

    async with lock:
        if db_path not in _memory_instances:
            config = load_config()
            logger.info(f"Creating MemoryInterface for database: {db_path}")
            _memory_instances[db_path] = create_memory(
                llm_provider=config.llm_provider,
                embedding_provider=config.embedding_provider,
                db_url=db_path,
                auto_consolidate=config.auto_consolidate,
                consolidation_threshold=config.consolidation_threshold,
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
    topic: Optional[str] = None,
    source_type: Optional[str] = None,
) -> str:
    """Store an experience or observation in memory.
    
    This is a fast operation - no LLM calls. Entity extraction and
    type classification happen during consolidation.
    
    Auto-consolidation triggers when episode threshold (default: 10) is reached.
    """
    from remind.models import EpisodeType
    
    memory = await get_memory()
    
    meta = json.loads(metadata) if metadata else None
    
    ep_type = episode_type or None
    
    # Parse entities if provided (comma-separated)
    entity_list = None
    if entities:
        entity_list = [e.strip() for e in entities.split(",") if e.strip()]
    
    episode_id = await memory.remember(
        content, 
        metadata=meta,
        episode_type=ep_type,
        entities=entity_list,
        topic=topic,
        source_type=source_type,
    )
    
    lines = [f"Remembered as episode {episode_id}"]
    
    if ep_type:
        lines.append(f"  Type: {ep_type.value}")
    if entity_list:
        lines.append(f"  Entities: {', '.join(entity_list)}")
    if topic:
        lines.append(f"  Topic: {topic}")
    if source_type:
        lines.append(f"  Source: {source_type}")
    
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
    query: Optional[str] = None,
    k: int = 3,
    context: Optional[str] = None,
    entity: Optional[str] = None,
    episode_k: Optional[int] = None,
    topic: Optional[str] = None,
) -> str:
    """Retrieve relevant memories for a query."""
    memory = await get_memory()
    return await memory.recall(query=query, k=k, context=context, entity=entity, episode_k=episode_k, topic=topic)


async def tool_list_topics() -> str:
    """List all topics with episode/concept counts and latest activity."""
    memory = await get_memory()
    topics = memory.list_topics()

    if not topics:
        return "No topics found. Use 'create_topic' to add one, or pass 'topic' when remembering."

    lines = ["TOPICS:\n"]
    for t in topics:
        desc = f" — {t['description']}" if t.get("description") else ""
        lines.append(
            f"  [{t['id']}] {t['name']}{desc}: "
            f"{t['episode_count']} episodes, "
            f"{t['concept_count']} concepts, "
            f"latest: {t.get('latest_activity', '')}"
        )
    return "\n".join(lines)


async def tool_create_topic(name: str, description: str = "") -> str:
    """Create a new topic."""
    memory = await get_memory()
    try:
        topic = memory.create_topic(name, description=description)
        return f"Created topic '{topic.id}' ({topic.name})"
    except ValueError as e:
        return f"Error: {e}"


async def tool_update_topic(topic_id: str, name: str = None, description: str = None) -> str:
    """Update an existing topic's name or description."""
    memory = await get_memory()
    updated = memory.update_topic(topic_id, name=name, description=description)
    if not updated:
        return f"Topic '{topic_id}' not found."
    return f"Updated topic '{updated.id}' ({updated.name})"


async def tool_delete_topic(topic_id: str) -> str:
    """Delete a topic (only if no episodes/concepts reference it)."""
    memory = await get_memory()
    try:
        if memory.delete_topic(topic_id):
            return f"Deleted topic '{topic_id}'."
        return f"Topic '{topic_id}' not found."
    except ValueError as e:
        return f"Error: {e}"


async def tool_topic_overview(topic_id: str, k: int = 5) -> str:
    """Get top concepts for a topic without needing a query."""
    memory = await get_memory()
    topic = memory.get_topic(topic_id)
    concepts = memory.get_topic_overview(topic_id, k=k)

    if not concepts:
        return f"No concepts found for topic '{topic_id}'."

    label = topic.name if topic else topic_id
    lines = [f"TOPIC OVERVIEW: {label}\n"]
    if topic and topic.description:
        lines.append(f"  {topic.description}\n")
    for c in concepts:
        updated = c.updated_at.strftime("%Y-%m-%d %H:%M")
        title = f"{c.title} " if c.title else ""
        lines.append(
            f"  [{c.id}] {title}(confidence: {c.confidence:.2f}, "
            f"instances: {c.instance_count}, updated: {updated})"
        )
        lines.append(f"    {c.summary}")
        if c.conditions:
            lines.append(f"    → Applies when: {c.conditions}")
        lines.append("")
    return "\n".join(lines)


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
            ep_type = ep.episode_type
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

    type_str, name = Entity.parse_id(entity_id)
    entity_id = Entity.make_id(type_str, normalize_entity_name(name))
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


async def tool_update_episode(
    episode_id: str,
    content: Optional[str] = None,
    episode_type: Optional[str] = None,
    entities: Optional[str] = None,
    plan_id: Optional[str] = None,
    spec_ids: Optional[str] = None,
    depends_on: Optional[str] = None,
    priority: Optional[str] = None,
) -> str:
    """Update an existing episode."""
    from remind.models import EpisodeType

    memory = await get_memory()

    ep_type = episode_type or None

    # Parse entities
    entity_list = None
    if entities:
        entity_list = [e.strip() for e in entities.split(",") if e.strip()]

    # Build metadata from linkage fields
    meta: dict = {}
    if plan_id:
        meta["plan_id"] = plan_id
    if spec_ids:
        meta["spec_ids"] = [s.strip() for s in spec_ids.split(",") if s.strip()]
    if depends_on:
        meta["depends_on"] = [d.strip() for d in depends_on.split(",") if d.strip()]
    if priority:
        meta["priority"] = priority

    updated = memory.update_episode(
        episode_id,
        content=content,
        episode_type=ep_type,
        entities=entity_list,
        metadata=meta if meta else None,
    )

    if updated:
        lines = [f"Updated episode {episode_id}"]
        if content:
            preview = content[:50] + "..." if len(content) > 50 else content
            lines.append(f"  Content: {preview}")
        if ep_type:
            lines.append(f"  Type: {ep_type.value}")
        if entity_list:
            lines.append(f"  Entities: {', '.join(entity_list)}")
        if plan_id:
            lines.append(f"  Plan: {plan_id}")
        if spec_ids:
            lines.append(f"  Specs: {spec_ids}")
        if depends_on:
            lines.append(f"  Depends on: {depends_on}")
        if priority:
            lines.append(f"  Priority: {priority}")
        if content:
            lines.append("  Note: Episode will be re-consolidated")
        return "\n".join(lines)
    else:
        return f"Episode {episode_id} not found."


async def tool_delete_episode(episode_id: str) -> str:
    """Soft delete an episode from memory."""
    memory = await get_memory()

    if memory.delete_episode(episode_id):
        return f"Deleted episode {episode_id}. Use restore_episode to undelete, or purge_episode to permanently remove."
    else:
        return f"Episode {episode_id} not found."


async def tool_restore_episode(episode_id: str) -> str:
    """Restore a soft-deleted episode."""
    memory = await get_memory()

    if memory.restore_episode(episode_id):
        return f"Restored episode {episode_id}."
    else:
        return f"Episode {episode_id} not found or not deleted."


async def tool_update_concept(
    concept_id: str,
    title: Optional[str] = None,
    summary: Optional[str] = None,
    confidence: Optional[float] = None,
    tags: Optional[str] = None,
    relations: Optional[str] = None,
) -> str:
    """Update an existing concept."""
    memory = await get_memory()

    tag_list = None
    if tags:
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]

    # Parse relations JSON string
    relations_list = None
    if relations:
        import json as _json
        try:
            relations_list = _json.loads(relations)
        except _json.JSONDecodeError:
            return f"Invalid relations JSON: {relations}"

    updated = memory.update_concept(
        concept_id,
        title=title,
        summary=summary,
        confidence=confidence,
        tags=tag_list,
        relations=relations_list,
    )

    if updated:
        lines = [f"Updated concept {concept_id}"]
        if title:
            lines.append(f"  Title: {title}")
        if summary:
            preview = summary[:50] + "..." if len(summary) > 50 else summary
            lines.append(f"  Summary: {preview}")
        if confidence is not None:
            lines.append(f"  Confidence: {confidence:.2f}")
        if tag_list:
            lines.append(f"  Tags: {', '.join(tag_list)}")
        if relations_list is not None:
            lines.append(f"  Relations: {len(relations_list)} set")
        if summary:
            lines.append("  Note: Embedding cleared, will regenerate on next recall")
        return "\n".join(lines)
    else:
        return f"Concept {concept_id} not found."


async def tool_delete_concept(concept_id: str) -> str:
    """Soft delete a concept from memory."""
    memory = await get_memory()

    if memory.delete_concept(concept_id):
        return f"Deleted concept {concept_id}. Use restore_concept to undelete, or purge_concept to permanently remove."
    else:
        return f"Concept {concept_id} not found."


async def tool_restore_concept(concept_id: str) -> str:
    """Restore a soft-deleted concept."""
    memory = await get_memory()

    if memory.restore_concept(concept_id):
        return f"Restored concept {concept_id}."
    else:
        return f"Concept {concept_id} not found or not deleted."


async def tool_task_add(
    content: str,
    entities: Optional[str] = None,
    priority: str = "p1",
    plan_id: Optional[str] = None,
    spec_ids: Optional[str] = None,
    depends_on: Optional[str] = None,
) -> str:
    """Create a new task."""
    from remind.models import EpisodeType

    memory = await get_memory()

    meta = {"status": "todo", "priority": priority}
    if plan_id:
        meta["plan_id"] = plan_id
    if spec_ids:
        meta["spec_ids"] = [s.strip() for s in spec_ids.split(",") if s.strip()]
    if depends_on:
        meta["depends_on"] = [d.strip() for d in depends_on.split(",") if d.strip()]

    entity_list = None
    if entities:
        entity_list = [e.strip() for e in entities.split(",") if e.strip()]

    episode_id = await memory.remember(
        content,
        metadata=meta,
        episode_type=EpisodeType.TASK.value,
        entities=entity_list,
    )

    lines = [f"Created task {episode_id}"]
    lines.append(f"  Priority: {priority}")
    if entity_list:
        lines.append(f"  Entities: {', '.join(entity_list)}")
    if plan_id:
        lines.append(f"  Plan: {plan_id}")
    return "\n".join(lines)


async def tool_task_update_status(
    task_id: str,
    status: str,
    reason: Optional[str] = None,
) -> str:
    """Update a task's status."""
    memory = await get_memory()

    updated = memory.update_task_status(task_id, status, reason=reason)
    if updated:
        msg = f"Task {task_id} -> {status}"
        if reason:
            msg += f" ({reason})"
        return msg
    return f"Task {task_id} not found or invalid status '{status}'."


async def tool_list_tasks(
    status: Optional[str] = None,
    entity: Optional[str] = None,
    plan_id: Optional[str] = None,
    include_done: bool = False,
) -> str:
    """List tasks with optional filters."""
    memory = await get_memory()

    tasks = memory.get_tasks(status=status, entity_id=entity, plan_id=plan_id)
    if not include_done and not status:
        tasks = [t for t in tasks if (t.metadata or {}).get("status") != "done"]

    if not tasks:
        return "No tasks found."

    groups: dict[str, list] = {}
    for t in tasks:
        s = (t.metadata or {}).get("status", "todo")
        groups.setdefault(s, []).append(t)

    lines = []
    for group_status in ["in_progress", "blocked", "todo", "done"]:
        group_tasks = groups.get(group_status, [])
        if not group_tasks:
            continue
        lines.append(f"\n{group_status.upper()} ({len(group_tasks)}):")
        for t in group_tasks:
            meta = t.metadata or {}
            priority = meta.get("priority", "-")
            line = f"  [{t.id}] ({priority}) {t.content}"
            if group_status == "blocked" and meta.get("blocked_reason"):
                line += f" — blocked: {meta['blocked_reason']}"
            if t.entity_ids:
                line += f"\n      entities: {', '.join(t.entity_ids[:3])}"
            lines.append(line)

    return "\n".join(lines)


async def tool_list_specs(
    entity: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
) -> str:
    """List spec episodes."""
    from remind.models import EpisodeType

    memory = await get_memory()
    episodes = memory.get_episodes_by_type(EpisodeType.SPEC.value, limit=1000)

    if entity:
        episodes = [ep for ep in episodes if entity in ep.entity_ids]
    if status:
        episodes = [ep for ep in episodes if (ep.metadata or {}).get("status") == status]

    episodes = episodes[:limit]

    if not episodes:
        return "No specs found."

    lines = [f"Specs ({len(episodes)}):"]
    for ep in episodes:
        meta_status = (ep.metadata or {}).get("status", "-")
        entities_str = ", ".join(ep.entity_ids[:3]) if ep.entity_ids else ""
        lines.append(f"  [{ep.id}] ({meta_status}) {ep.content}")
        if entities_str:
            lines.append(f"      entities: {entities_str}")

    return "\n".join(lines)


async def tool_list_plans(
    entity: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
) -> str:
    """List plan episodes."""
    from remind.models import EpisodeType

    memory = await get_memory()
    episodes = memory.get_episodes_by_type(EpisodeType.PLAN.value, limit=1000)

    if entity:
        episodes = [ep for ep in episodes if entity in ep.entity_ids]
    if status:
        episodes = [ep for ep in episodes if (ep.metadata or {}).get("status") == status]

    episodes = episodes[:limit]

    if not episodes:
        return "No plans found."

    lines = [f"Plans ({len(episodes)}):"]
    for ep in episodes:
        meta_status = (ep.metadata or {}).get("status", "-")
        entities_str = ", ".join(ep.entity_ids[:3]) if ep.entity_ids else ""
        lines.append(f"  [{ep.id}] ({meta_status}) {ep.content}")
        if entities_str:
            lines.append(f"      entities: {entities_str}")

    return "\n".join(lines)


async def tool_ingest(
    content: str,
    source: str = "conversation",
    topic: Optional[str] = None,
) -> str:
    """Ingest raw text for automatic memory curation."""
    memory = await get_memory()

    buf_size_before = memory.ingest_buffer_size
    episode_ids = await memory.ingest(content, source=source, topic=topic)

    if episode_ids:
        lines = [f"Ingested and created {len(episode_ids)} episode(s):"]
        for eid in episode_ids:
            lines.append(f"  {eid}")
        lines.append("Consolidation completed.")
        return "\n".join(lines)

    buf_size = memory.ingest_buffer_size
    if buf_size > 0:
        threshold = memory._ingest_buffer.threshold
        return f"Buffered ({buf_size}/{threshold} chars). Will process when threshold reached."

    if buf_size_before > 0 and buf_size == 0:
        return "Ingested. Triage and consolidation running in background."

    return "Ingested but triage found nothing memory-worthy (low density)."


async def tool_flush_ingest(topic: Optional[str] = None) -> str:
    """Force-flush the ingestion buffer and process contents."""
    memory = await get_memory()

    buf_size = memory.ingest_buffer_size
    if buf_size == 0:
        return "Ingestion buffer is empty, nothing to flush."

    episode_ids = await memory.flush_ingest(topic=topic)

    if episode_ids:
        lines = [f"Flushed buffer ({buf_size} chars) and created {len(episode_ids)} episode(s):"]
        for eid in episode_ids:
            lines.append(f"  {eid}")
        lines.append("Consolidation completed.")
        return "\n".join(lines)

    if memory._ingest_background:
        return f"Flushed buffer ({buf_size} chars). Triage and consolidation running in background."

    return f"Flushed buffer ({buf_size} chars) but triage found nothing memory-worthy."


async def tool_list_deleted(
    item_type: Optional[str] = None,
    limit: int = 20,
) -> str:
    """List soft-deleted episodes and/or concepts."""
    memory = await get_memory()

    lines = []
    show_episodes = item_type in (None, "episodes", "all")
    show_concepts = item_type in (None, "concepts", "all")

    if show_episodes:
        deleted_episodes = memory.get_deleted_episodes(limit=limit)
        if deleted_episodes:
            lines.append(f"Deleted Episodes ({len(deleted_episodes)}):")
            for ep in deleted_episodes:
                deleted_at = ep.deleted_at.strftime('%Y-%m-%d %H:%M') if ep.deleted_at else "?"
                preview = ep.content[:40] + "..." if len(ep.content) > 40 else ep.content
                lines.append(f"  [{ep.id}] {preview} (deleted: {deleted_at})")
        else:
            lines.append("No deleted episodes.")

    if show_concepts:
        if lines:
            lines.append("")
        deleted_concepts = memory.get_deleted_concepts()
        if deleted_concepts:
            lines.append(f"Deleted Concepts ({len(deleted_concepts)}):")
            for c in deleted_concepts[:limit]:
                deleted_at = c.deleted_at.strftime('%Y-%m-%d %H:%M') if c.deleted_at else "?"
                title = c.title or c.summary[:40] + "..." if len(c.summary) > 40 else c.summary
                lines.append(f"  [{c.id}] {title} (deleted: {deleted_at})")
        else:
            lines.append("No deleted concepts.")

    return "\n".join(lines)


# ============================================================================
# FastMCP Server Setup
# ============================================================================

def create_mcp_server(config=None):
    """Create and configure the FastMCP server.
    
    Tools for spec, plan, and task episode types are only registered
    when those types are present in config.episode_types.
    """
    from fastmcp import FastMCP
    
    if config is None:
        config = load_config()
    episode_types = set(config.episode_types)
    
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
        topic: Optional[str] = None,
        source_type: Optional[str] = None,
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
            episode_type: Optional explicit type (e.g., observation, decision, question, meta, preference, spec, plan, task, outcome, fact).
                          Custom types are also accepted if configured. Auto-detected during consolidation if not provided.
            entities: Optional comma-separated entity IDs (e.g., "file:src/auth.ts,person:alice")
                      (auto-detected during consolidation if not provided)
            topic: Primary knowledge area this memory belongs to (e.g., "architecture", "product", "infra").
                   Used to group related memories and scope retrieval.
            source_type: Origin of this memory (e.g., "agent", "slack", "github", "manual").
        
        Returns:
            Confirmation with episode ID
        """
        return await tool_remember(content, metadata, episode_type, entities, topic, source_type)
    
    @mcp.tool()
    async def recall(
        query: Optional[str] = None,
        k: int = 3,
        context: Optional[str] = None,
        entity: Optional[str] = None,
        episode_k: Optional[int] = None,
        topic: Optional[str] = None,
    ) -> str:
        """Retrieve relevant memories for a query.

        Two modes:
        1. Semantic search (default): Uses embeddings with spreading activation
        2. Entity-based: Retrieves all memories about a specific entity

        Provide query for semantic search, or entity for entity-based lookup.
        At least one of query or entity must be provided.

        Args:
            query: What to search for in memory (required for semantic search)
            k: Number of concepts to retrieve (default: 3)
            context: Optional additional context to improve retrieval
            entity: Optional entity ID to retrieve by (e.g., "file:src/auth.ts")
            episode_k: Number of episodes to retrieve via direct vector search (default: 5). Set to 0 to disable.
            topic: Restrict recall to this topic. Cross-topic results are penalized
                   but not excluded. Use list_topics to see available topics.
        
        Returns:
            Formatted memory context for injection into prompts
        """
        return await tool_recall(query, k, context, entity, episode_k=episode_k, topic=topic)
    
    @mcp.tool()
    async def list_topics() -> str:
        """List all topics in memory with episode/concept counts.

        Topics are managed knowledge areas that group related memories. Use this
        to understand the structure of stored knowledge before recalling.

        Returns:
            List of topics with id, name, description, episode count, concept count, latest activity
        """
        return await tool_list_topics()

    @mcp.tool()
    async def create_topic(name: str, description: str = "") -> str:
        """Create a new topic for grouping memories.

        Args:
            name: Display name for the topic (e.g., "Architecture", "Product Design")
            description: What this topic covers

        Returns:
            Confirmation with topic ID
        """
        return await tool_create_topic(name, description)

    @mcp.tool()
    async def update_topic(topic_id: str, name: str = None, description: str = None) -> str:
        """Update an existing topic's name or description.

        Args:
            topic_id: ID of the topic to update
            name: New display name (or null to keep existing)
            description: New description (or null to keep existing)

        Returns:
            Confirmation or error
        """
        return await tool_update_topic(topic_id, name, description)

    @mcp.tool()
    async def delete_topic(topic_id: str) -> str:
        """Delete a topic (only works if no episodes/concepts reference it).

        Args:
            topic_id: ID of the topic to delete

        Returns:
            Confirmation or error
        """
        return await tool_delete_topic(topic_id)

    @mcp.tool()
    async def topic_overview(topic_id: str, k: int = 5) -> str:
        """Get an overview of a topic's top concepts without a specific query.

        Use this to browse/explore what is known about a topic before drilling
        down with a targeted recall query.

        Args:
            topic_id: The topic ID to explore
            k: Number of top concepts to return (default: 5)

        Returns:
            Top concepts for the topic, ordered by confidence and evidence
        """
        return await tool_topic_overview(topic_id, k)

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

    @mcp.tool()
    async def update_episode(
        episode_id: str,
        content: Optional[str] = None,
        episode_type: Optional[str] = None,
        entities: Optional[str] = None,
        plan_id: Optional[str] = None,
        spec_ids: Optional[str] = None,
        depends_on: Optional[str] = None,
        priority: Optional[str] = None,
    ) -> str:
        """Update an existing episode in memory.

        Use this to correct mistakes, add information, reclassify episodes, or link
        tasks to plans and specs after creation.
        Only provided fields are updated; omitted fields keep their current values.

        Note: Updating content resets the episode for re-consolidation.

        Args:
            episode_id: ID of the episode to update (required)
            content: New content text
            episode_type: New type (e.g., observation, decision, question, meta, preference, spec, plan, task, outcome, fact, or any configured custom type)
            entities: New comma-separated entity IDs (e.g., "file:src/auth.ts,person:alice")
            plan_id: Plan episode ID to link this task to
            spec_ids: Comma-separated spec episode IDs to link this task to
            depends_on: Comma-separated task IDs this task depends on
            priority: Priority level: p0, p1, or p2

        Returns:
            Confirmation or error message
        """
        return await tool_update_episode(episode_id, content, episode_type, entities,
                                         plan_id, spec_ids, depends_on, priority)

    @mcp.tool()
    async def delete_episode(episode_id: str) -> str:
        """Soft delete an episode from memory.

        Use this to remove incorrect, outdated, or duplicate episodes.
        The episode is marked as deleted but not permanently removed.

        Use restore_episode to undelete, or list_deleted to see deleted items.

        Args:
            episode_id: ID of the episode to delete (required)

        Returns:
            Confirmation or error message
        """
        return await tool_delete_episode(episode_id)

    @mcp.tool()
    async def restore_episode(episode_id: str) -> str:
        """Restore a previously deleted episode.

        Undeletes an episode that was soft-deleted with delete_episode.

        Args:
            episode_id: ID of the episode to restore (required)

        Returns:
            Confirmation or error message
        """
        return await tool_restore_episode(episode_id)

    @mcp.tool()
    async def update_concept(
        concept_id: str,
        title: Optional[str] = None,
        summary: Optional[str] = None,
        confidence: Optional[float] = None,
        tags: Optional[str] = None,
        relations: Optional[str] = None,
    ) -> str:
        """Update an existing concept.

        Use this to refine or correct generalized knowledge.
        Only provided fields are updated; omitted fields keep their current values.

        Note: Updating summary clears the embedding; it will regenerate on next recall.

        Args:
            concept_id: ID of the concept to update (required)
            title: New short title
            summary: New summary text
            confidence: New confidence score (0.0-1.0)
            tags: New comma-separated tags
            relations: JSON array of relations, e.g. [{"type":"implies","target_id":"abc","strength":0.7}]

        Returns:
            Confirmation or error message
        """
        return await tool_update_concept(concept_id, title, summary, confidence, tags, relations)

    @mcp.tool()
    async def delete_concept(concept_id: str) -> str:
        """Soft delete a concept from memory.

        Use this to remove incorrect or outdated concepts.
        The concept is marked as deleted but not permanently removed.

        Use restore_concept to undelete, or list_deleted to see deleted items.

        Args:
            concept_id: ID of the concept to delete (required)

        Returns:
            Confirmation or error message
        """
        return await tool_delete_concept(concept_id)

    @mcp.tool()
    async def restore_concept(concept_id: str) -> str:
        """Restore a previously deleted concept.

        Undeletes a concept that was soft-deleted with delete_concept.

        Args:
            concept_id: ID of the concept to restore (required)

        Returns:
            Confirmation or error message
        """
        return await tool_restore_concept(concept_id)

    @mcp.tool()
    async def list_deleted(
        item_type: Optional[str] = None,
        limit: int = 20,
    ) -> str:
        """List soft-deleted episodes and concepts.

        Shows items that were deleted but not permanently purged.
        Use restore_episode or restore_concept to undelete them.

        Args:
            item_type: Filter by type: "episodes", "concepts", or None/all for both
            limit: Maximum number of items to show per type (default: 20)

        Returns:
            List of deleted items with their IDs and deletion timestamps
        """
        return await tool_list_deleted(item_type, limit)

    if "task" in episode_types:
        @mcp.tool()
        async def task_add(
            content: str,
            entities: Optional[str] = None,
            priority: str = "p1",
            plan_id: Optional[str] = None,
            spec_ids: Optional[str] = None,
            depends_on: Optional[str] = None,
        ) -> str:
            """Create a new task episode.

            Tasks are discrete units of work with status tracking (todo -> in_progress -> done).
            They can link to plans and specs via IDs.

            Args:
                content: Task description
                entities: Optional comma-separated entity IDs (e.g., "module:auth,file:src/auth.ts")
                priority: Priority level: p0, p1, p2 (default: p1)
                plan_id: Optional plan episode ID this task implements
                spec_ids: Optional comma-separated spec episode IDs this task implements
                depends_on: Optional comma-separated task IDs this depends on

            Returns:
                Confirmation with task ID
            """
            return await tool_task_add(content, entities, priority, plan_id, spec_ids, depends_on)

        @mcp.tool()
        async def task_update_status(
            task_id: str,
            status: str,
            reason: Optional[str] = None,
        ) -> str:
            """Update a task's status.

            Valid statuses: todo, in_progress, done, blocked.
            Timestamps are automatically tracked (started_at, completed_at).

            Args:
                task_id: Episode ID of the task
                status: New status: todo, in_progress, done, blocked
                reason: Optional reason (used when blocking a task)

            Returns:
                Confirmation or error message
            """
            return await tool_task_update_status(task_id, status, reason)

        @mcp.tool()
        async def list_tasks(
            status: Optional[str] = None,
            entity: Optional[str] = None,
            plan_id: Optional[str] = None,
            include_done: bool = False,
        ) -> str:
            """List tasks grouped by status.

            By default excludes completed tasks. Use include_done=True to show all.

            Args:
                status: Filter by status: todo, in_progress, done, blocked
                entity: Filter by entity ID (e.g., "module:auth")
                plan_id: Filter by originating plan episode ID
                include_done: Include completed tasks (default: False)

            Returns:
                Tasks grouped by status
            """
            return await tool_list_tasks(status, entity, plan_id, include_done)

    if "spec" in episode_types:
        @mcp.tool()
        async def list_specs(
            entity: Optional[str] = None,
            status: Optional[str] = None,
            limit: int = 20,
        ) -> str:
            """List spec episodes (requirements, acceptance criteria).

            Specs are prescriptive requirements ("X shall/must be the case").
            They have a lifecycle: draft -> approved -> implemented -> deprecated.

            Args:
                entity: Filter by entity ID (e.g., "module:auth")
                status: Filter by spec status: draft, approved, implemented, deprecated
                limit: Maximum number of specs to show (default: 20)

            Returns:
                List of spec episodes
            """
            return await tool_list_specs(entity, status, limit)

    if "plan" in episode_types:
        @mcp.tool()
        async def list_plans(
            entity: Optional[str] = None,
            status: Optional[str] = None,
            limit: int = 20,
        ) -> str:
            """List plan episodes (implementation plans, roadmaps).

            Plans are sequenced intentions ("we will do X, then Y, then Z").
            They have a lifecycle: draft -> active -> completed -> superseded.

            Args:
                entity: Filter by entity ID (e.g., "module:auth")
                status: Filter by plan status: draft, active, completed, superseded
                limit: Maximum number of plans to show (default: 20)

            Returns:
                List of plan episodes
            """
            return await tool_list_plans(entity, status, limit)

    @mcp.tool()
    async def ingest(
        content: str,
        source: str = "conversation",
        topic: Optional[str] = None,
    ) -> str:
        """Ingest raw text for automatic memory curation.

        Streams raw conversation text into Remind's auto-ingest pipeline.
        Text accumulates in an internal buffer until the threshold (~4000
        chars) is reached, then gets scored for information density and
        distilled into memory-worthy episodes automatically.

        Use this instead of remember() when you want Remind to decide
        what's worth remembering. remember() stores everything as-is;
        ingest() filters and distills.

        Args:
            content: Raw text to ingest (conversation fragments, tool output, etc.)
            source: Source label for metadata tracking (default: "conversation")
            topic: Optional topic ID or name. When set, all extracted episodes
                are assigned to this topic. When omitted, the triage LLM
                infers per-episode topics automatically.

        Returns:
            Status message (buffered, episodes created, or dropped)
        """
        return await tool_ingest(content, source, topic=topic)

    @mcp.tool()
    async def flush_ingest(topic: Optional[str] = None) -> str:
        """Force-flush the ingestion buffer.

        Processes whatever text is in the buffer immediately, regardless
        of whether the character threshold has been reached. Use at
        session end or when you want to ensure all ingested text is processed.

        Args:
            topic: Optional topic ID or name for extracted episodes.
                When set, all episodes are assigned to this topic.
                When omitted, topics are inferred automatically.

        Returns:
            Status message with results
        """
        return await tool_flush_ingest(topic=topic)

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
                raw_db = db_list[0]
                db_path = raw_db if _is_db_url(raw_db) else resolve_db_url(raw_db)
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

    # Set providers via env vars if CLI args provided (so load_config() picks them up)
    if args.llm:
        os.environ["LLM_PROVIDER"] = args.llm
    if args.embedding:
        os.environ["EMBEDDING_PROVIDER"] = args.embedding

    run_server_sse(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
