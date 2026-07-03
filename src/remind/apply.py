"""
Apply engine for batch memory operations.

Processes changesets (either JSON or compact line format) transactionally.
All operations succeed together or none do (all-or-nothing).
"""

import json
import logging
import re
import shlex
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, Union
from uuid import uuid4

from remind.models import (
    Episode, Concept, Fact, Conflict, Topic, Relation, RelationType,
    EpisodeType, EntityType, Entity, EntityRelation,
    slugify, canonicalize_entity_name, strip_entity_label_prefix,
)
from remind.store import MemoryStore
from remind.providers.base import EmbeddingProvider
from remind.facts import create_fact_from_episode

logger = logging.getLogger(__name__)


@dataclass
class OpError:
    """Error from validating or executing an operation."""
    
    line: Optional[int]  # Line number (1-based) for compact format
    op_index: int  # Index in the ops array (0-based)
    op_type: str
    message: str
    
    def to_dict(self) -> dict:
        return {
            "line": self.line,
            "op_index": self.op_index,
            "op_type": self.op_type,
            "message": self.message,
        }


@dataclass
class OpResult:
    """Result of executing a single operation."""
    
    op_index: int
    op_type: str
    success: bool
    id: Optional[str] = None  # Created ID
    ref: Optional[str] = None  # Local ref name if declared with `as`
    error: Optional[str] = None
    collisions: list[dict] = field(default_factory=list)  # For remember ops
    
    def to_dict(self) -> dict:
        d = {
            "op_index": self.op_index,
            "op_type": self.op_type,
            "success": self.success,
        }
        if self.id:
            d["id"] = self.id
        if self.ref:
            d["ref"] = self.ref
        if self.error:
            d["error"] = self.error
        if self.collisions:
            d["collisions"] = self.collisions
        return d


@dataclass
class ApplyResult:
    """Result of applying a changeset."""
    
    success: bool
    ops_executed: int = 0
    errors: list[OpError] = field(default_factory=list)
    results: list[OpResult] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "ops_executed": self.ops_executed,
            "errors": [e.to_dict() for e in self.errors],
            "results": [r.to_dict() for r in self.results],
        }


def parse_compact_line(line: str, line_num: int) -> tuple[Optional[dict], Optional[OpError]]:
    """Parse a single line in compact format into an op dict.
    
    Format: op_name key=value key=value "trailing string"
    
    Examples:
        remember as=f1 t=fact e=concept:caching "Cache TTL is 600 seconds"
        supersede old=fact:a91c2 new=$f1
        resolve id=conflict:7 winner=fact:b3d01 "confirmed by bob"
    """
    line = line.strip()
    if not line or line.startswith("#"):
        return None, None
    
    try:
        tokens = shlex.split(line)
    except ValueError as e:
        return None, OpError(
            line=line_num,
            op_index=-1,
            op_type="",
            message=f"Parse error: {e}",
        )
    
    if not tokens:
        return None, None
    
    op_type = tokens[0].lower()
    op: dict[str, Any] = {"op": op_type}
    
    # Track trailing quoted string (content/note)
    trailing_string = None
    
    for token in tokens[1:]:
        if "=" in token:
            key, _, value = token.partition("=")
            key = key.lower()
            
            # Handle comma-separated lists
            if "," in value and key in ("e", "entities", "from", "ids"):
                value = [v.strip() for v in value.split(",")]
            
            # Map short keys to full names
            key_map = {
                "t": "t",  # type
                "e": "e",  # entities
                "as": "as",
                "by": "by",
                "ref": "ref",
            }
            op[key_map.get(key, key)] = value
        else:
            # Trailing string (unescaped)
            trailing_string = token.replace("\\n", "\n")
    
    # Assign trailing string based on op type
    if trailing_string:
        if op_type in ("remember", "concept"):
            op["content"] = trailing_string
        elif op_type in ("resolve", "dismiss"):
            op["note"] = trailing_string
        elif op_type == "topic":
            op["name"] = trailing_string
    
    return op, None


def parse_changeset(text: str) -> tuple[list[dict], list[OpError]]:
    """Parse a changeset from either JSON or compact format.
    
    Auto-detects format based on first non-whitespace character.
    Returns (ops, errors).
    """
    text = text.strip()
    if not text:
        return [], []
    
    # Auto-detect format
    if text[0] in "[{":
        # JSON format
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                data = [data]
            return data, []
        except json.JSONDecodeError as e:
            return [], [OpError(
                line=None,
                op_index=-1,
                op_type="",
                message=f"JSON parse error: {e}",
            )]
    
    # Compact line format
    ops = []
    errors = []
    for i, line in enumerate(text.split("\n"), start=1):
        op, err = parse_compact_line(line, i)
        if err:
            errors.append(err)
        elif op:
            ops.append(op)
    
    return ops, errors


class ApplyEngine:
    """Engine for executing apply changesets."""
    
    def __init__(
        self,
        store: MemoryStore,
        embedding: Optional[EmbeddingProvider] = None,
        fact_cluster_jaccard_threshold: float = 0.5,
    ):
        self.store = store
        self.embedding = embedding
        self.fact_cluster_jaccard_threshold = fact_cluster_jaccard_threshold
    
    def _resolve_entity_id(self, raw_entity_id: str) -> str:
        """Resolve a raw entity ID to a canonical one."""
        type_str, name = Entity.parse_id(raw_entity_id)
        canonical_name = canonicalize_entity_name(name)
        existing = self.store.find_entity_by_name(canonical_name)
        if existing:
            return existing.id

        normalized_id = Entity.make_id(type_str, canonical_name)
        if not self.store.get_entity(normalized_id):
            try:
                etype = EntityType(type_str)
            except ValueError:
                etype = EntityType.OTHER
            display_name = strip_entity_label_prefix(name) or canonical_name
            entity = Entity(id=normalized_id, type=etype, display_name=display_name)
            self.store.add_entity(entity)
        return normalized_id
    
    def _resolve_ref(self, value: str, refs: dict[str, str]) -> str:
        """Resolve a $ref or return value as-is."""
        if isinstance(value, str) and value.startswith("$"):
            ref_name = value[1:]
            if ref_name not in refs:
                raise ValueError(f"Unknown reference: {value}")
            return refs[ref_name]
        return value
    
    async def apply(
        self,
        changeset: Union[str, list[dict]],
        dry_run: bool = False,
    ) -> ApplyResult:
        """Apply a changeset transactionally.
        
        Args:
            changeset: Either raw text (JSON or compact) or pre-parsed ops
            dry_run: If True, validate only without executing
        
        Returns:
            ApplyResult with success status, executed ops, and any errors
        """
        # Parse if needed
        if isinstance(changeset, str):
            ops, parse_errors = parse_changeset(changeset)
            if parse_errors:
                return ApplyResult(success=False, errors=parse_errors)
        else:
            ops = changeset
        
        if not ops:
            return ApplyResult(success=True)
        
        # Validate all ops first
        errors = self._validate_ops(ops)
        if errors:
            return ApplyResult(success=False, errors=errors)
        
        if dry_run:
            return ApplyResult(success=True, ops_executed=len(ops))
        
        # Pre-compute embeddings for ops that need them
        # This must happen before the transaction since embedding is async
        embeddings_cache: dict[int, list[float]] = {}
        if self.embedding:
            for i, op in enumerate(ops):
                op_type = op.get("op", "").lower()
                if op_type == "remember":
                    content = op.get("content", "")
                    if content:
                        try:
                            embeddings_cache[i] = await self.embedding.embed(content)
                        except Exception as e:
                            logger.warning(f"Failed to embed content for op {i}: {e}")
                elif op_type == "concept":
                    summary = op.get("summary", "") or op.get("content", "")
                    if summary:
                        try:
                            embeddings_cache[i] = await self.embedding.embed(summary)
                        except Exception as e:
                            logger.warning(f"Failed to embed concept for op {i}: {e}")
        
        # Execute in transaction (sync operations only)
        results = []
        refs: dict[str, str] = {}  # Local reference names -> IDs
        
        try:
            with self.store.transaction():
                for i, op in enumerate(ops):
                    result = self._execute_op_sync(i, op, refs, embeddings_cache.get(i))
                    results.append(result)
                    
                    # Store ref if declared
                    if result.success and result.ref and result.id:
                        refs[result.ref] = result.id
                    
                    if not result.success:
                        raise RuntimeError(f"Op {i} failed: {result.error}")
        
        except Exception as e:
            # Transaction rolled back
            return ApplyResult(
                success=False,
                ops_executed=len(results),
                results=results,
                errors=[OpError(
                    line=None,
                    op_index=len(results),
                    op_type=ops[len(results)]["op"] if len(results) < len(ops) else "",
                    message=str(e),
                )],
            )
        
        return ApplyResult(
            success=True,
            ops_executed=len(results),
            results=results,
        )
    
    def _validate_ops(self, ops: list[dict]) -> list[OpError]:
        """Validate operations without executing them."""
        errors = []
        refs_declared: set[str] = set()
        
        valid_ops = {
            "remember", "supersede", "conflict", "resolve", "dismiss",
            "concept", "update", "link", "topic", "set_topic",
            "delete", "restore", "processed", "entity_relation",
        }
        
        for i, op in enumerate(ops):
            op_type = op.get("op", "").lower()
            
            if not op_type:
                errors.append(OpError(
                    line=None, op_index=i, op_type="",
                    message="Missing 'op' field",
                ))
                continue
            
            if op_type not in valid_ops:
                errors.append(OpError(
                    line=None, op_index=i, op_type=op_type,
                    message=f"Unknown operation: {op_type}",
                ))
                continue
            
            # Track ref declarations
            if "as" in op:
                ref_name = op["as"]
                if ref_name in refs_declared:
                    errors.append(OpError(
                        line=None, op_index=i, op_type=op_type,
                        message=f"Duplicate ref declaration: {ref_name}",
                    ))
                refs_declared.add(ref_name)
            
            # Validate ref usages
            for key, value in op.items():
                if isinstance(value, str) and value.startswith("$"):
                    ref_name = value[1:]
                    if ref_name not in refs_declared:
                        errors.append(OpError(
                            line=None, op_index=i, op_type=op_type,
                            message=f"Reference used before declaration: {value}",
                        ))
            
            # Op-specific validation
            if op_type == "remember":
                if not op.get("content"):
                    errors.append(OpError(
                        line=None, op_index=i, op_type=op_type,
                        message="remember requires 'content'",
                    ))
            
            elif op_type == "supersede":
                if not op.get("old") or not op.get("new"):
                    errors.append(OpError(
                        line=None, op_index=i, op_type=op_type,
                        message="supersede requires 'old' and 'new'",
                    ))
            
            elif op_type == "resolve":
                if not op.get("id") or not op.get("winner"):
                    errors.append(OpError(
                        line=None, op_index=i, op_type=op_type,
                        message="resolve requires 'id' and 'winner'",
                    ))
            
            elif op_type == "concept":
                if not op.get("title") and not op.get("summary"):
                    errors.append(OpError(
                        line=None, op_index=i, op_type=op_type,
                        message="concept requires 'title' or 'summary'",
                    ))
            
            elif op_type == "topic":
                if not op.get("name"):
                    errors.append(OpError(
                        line=None, op_index=i, op_type=op_type,
                        message="topic requires 'name'",
                    ))
            
            elif op_type in ("delete", "restore", "dismiss"):
                if not op.get("id"):
                    errors.append(OpError(
                        line=None, op_index=i, op_type=op_type,
                        message=f"{op_type} requires 'id'",
                    ))
            
            elif op_type == "processed":
                if not op.get("ids"):
                    errors.append(OpError(
                        line=None, op_index=i, op_type=op_type,
                        message="processed requires 'ids'",
                    ))
            
            elif op_type == "entity_relation":
                if not op.get("source") or not op.get("target") or not op.get("relation"):
                    errors.append(OpError(
                        line=None, op_index=i, op_type=op_type,
                        message="entity_relation requires 'source', 'target', and 'relation'",
                    ))
        
        return errors
    
    def _execute_op_sync(
        self,
        index: int,
        op: dict,
        refs: dict[str, str],
        embedding: Optional[list[float]] = None,
    ) -> OpResult:
        """Execute a single operation synchronously (embeddings pre-computed)."""
        op_type = op.get("op", "").lower()
        ref_name = op.get("as")
        
        try:
            if op_type == "remember":
                return self._op_remember(index, op, refs, ref_name, embedding)
            elif op_type == "supersede":
                return self._op_supersede(index, op, refs, ref_name)
            elif op_type == "conflict":
                return self._op_conflict(index, op, refs, ref_name)
            elif op_type == "resolve":
                return self._op_resolve(index, op, refs, ref_name)
            elif op_type == "dismiss":
                return self._op_dismiss(index, op, refs, ref_name)
            elif op_type == "concept":
                return self._op_concept(index, op, refs, ref_name, embedding)
            elif op_type == "update":
                return self._op_update(index, op, refs, ref_name)
            elif op_type == "link":
                return self._op_link(index, op, refs, ref_name)
            elif op_type == "topic":
                return self._op_topic(index, op, refs, ref_name)
            elif op_type == "set_topic":
                return self._op_set_topic(index, op, refs, ref_name)
            elif op_type == "delete":
                return self._op_delete(index, op, refs, ref_name)
            elif op_type == "restore":
                return self._op_restore(index, op, refs, ref_name)
            elif op_type == "processed":
                return self._op_processed(index, op, refs, ref_name)
            elif op_type == "entity_relation":
                return self._op_entity_relation(index, op, refs, ref_name)
            else:
                return OpResult(
                    op_index=index, op_type=op_type, success=False,
                    error=f"Unknown operation: {op_type}",
                )
        except Exception as e:
            return OpResult(
                op_index=index, op_type=op_type, success=False,
                error=str(e),
            )
    
    def _op_remember(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str],
        embedding: Optional[list[float]] = None,
    ) -> OpResult:
        """Execute a remember operation."""
        content = op.get("content", "")
        episode_type = op.get("t") or op.get("type", "observation")
        entities_raw = op.get("e") or op.get("entities", [])
        if isinstance(entities_raw, str):
            entities_raw = [entities_raw]
        asserted_by = op.get("by") or op.get("asserted_by")
        source_ref = op.get("ref") or op.get("source_ref")
        
        # Resolve entity IDs
        entity_ids = [self._resolve_entity_id(e) for e in entities_raw]
        
        # Create episode with pre-computed embedding
        episode = Episode(
            content=content,
            episode_type=episode_type,
            asserted_by=asserted_by,
            source_ref=source_ref,
            entity_ids=entity_ids,
            embedding=embedding,
        )
        
        episode_id = self.store.add_episode(episode)
        
        # Add entity mentions
        for entity_id in entity_ids:
            self.store.add_mention(episode_id, entity_id)
        
        collisions = []
        fact_id = None
        
        # For fact type, create Fact row
        if episode_type == "fact":
            from remind.facts import create_fact_from_episode
            fact_result = create_fact_from_episode(
                self.store,
                episode,
                embedding=embedding,
                jaccard_threshold=self.fact_cluster_jaccard_threshold,
            )
            fact_id = fact_result.fact_id
            collisions = [
                {"id": f.id, "statement": f.statement}
                for f in fact_result.collisions
            ]
        
        return OpResult(
            op_index=index,
            op_type="remember",
            success=True,
            id=fact_id or episode_id,
            ref=ref_name,
            collisions=collisions,
        )
    
    def _op_supersede(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Execute a supersede operation."""
        old_id = self._resolve_ref(op.get("old", ""), refs)
        new_id = self._resolve_ref(op.get("new", ""), refs)
        
        self.store.supersede_fact(old_id, new_id)
        
        return OpResult(
            op_index=index,
            op_type="supersede",
            success=True,
            ref=ref_name,
        )
    
    def _op_conflict(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Execute a conflict (open) operation."""
        fact_a = self._resolve_ref(op.get("fact_a", ""), refs)
        fact_b = self._resolve_ref(op.get("fact_b", ""), refs)
        concept_id = op.get("concept_id")
        description = op.get("description", "")
        severity = op.get("severity", "medium")
        
        conflict = Conflict(
            kind="fact",
            fact_a_id=fact_a,
            fact_b_id=fact_b,
            concept_id=concept_id,
            description=description,
            severity=severity,
            status="open",
        )
        self.store.add_conflict(conflict)
        
        return OpResult(
            op_index=index,
            op_type="conflict",
            success=True,
            id=conflict.id,
            ref=ref_name,
        )
    
    def _op_resolve(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Execute a resolve operation."""
        conflict_id = self._resolve_ref(op.get("id", ""), refs)
        winner_id = self._resolve_ref(op.get("winner", ""), refs)
        note = op.get("note", "")
        resolved_by = op.get("by") or op.get("resolved_by")
        
        conflict = self.store.get_conflict(conflict_id)
        if not conflict:
            return OpResult(
                op_index=index, op_type="resolve", success=False,
                error=f"Conflict not found: {conflict_id}",
            )
        
        if conflict.status != "open":
            return OpResult(
                op_index=index, op_type="resolve", success=False,
                error=f"Conflict is not open: {conflict.status}",
            )
        
        # Supersede the loser
        loser_id = (
            conflict.fact_b_id
            if winner_id == conflict.fact_a_id
            else conflict.fact_a_id
        )
        if loser_id:
            self.store.supersede_fact(loser_id, winner_id)
        
        # Update conflict
        conflict.status = "resolved"
        conflict.resolved_at = datetime.now()
        conflict.resolved_by = resolved_by
        conflict.resolution_note = note
        conflict.winning_fact_id = winner_id
        self.store.update_conflict(conflict)
        
        # Record decision episode
        winner = self.store.get_fact(winner_id)
        decision_content = f"Resolved conflict: chose '{winner.statement if winner else winner_id}'"
        if note:
            decision_content += f" ({note})"
        
        decision = Episode(
            content=decision_content,
            episode_type="decision",
            asserted_by=resolved_by,
        )
        self.store.add_episode(decision)
        
        return OpResult(
            op_index=index,
            op_type="resolve",
            success=True,
            id=conflict_id,
            ref=ref_name,
        )
    
    def _op_dismiss(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Execute a dismiss operation."""
        conflict_id = self._resolve_ref(op.get("id", ""), refs)
        note = op.get("note", "")
        dismissed_by = op.get("by") or op.get("dismissed_by")
        
        conflict = self.store.get_conflict(conflict_id)
        if not conflict:
            return OpResult(
                op_index=index, op_type="dismiss", success=False,
                error=f"Conflict not found: {conflict_id}",
            )
        
        if conflict.status != "open":
            return OpResult(
                op_index=index, op_type="dismiss", success=False,
                error=f"Conflict is not open: {conflict.status}",
            )
        
        conflict.status = "dismissed"
        conflict.resolved_at = datetime.now()
        conflict.resolved_by = dismissed_by
        conflict.resolution_note = note
        self.store.update_conflict(conflict)
        
        return OpResult(
            op_index=index,
            op_type="dismiss",
            success=True,
            id=conflict_id,
            ref=ref_name,
        )
    
    def _op_concept(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str],
        embedding: Optional[list[float]] = None,
    ) -> OpResult:
        """Execute a concept creation operation."""
        title = op.get("title", "")
        summary = op.get("summary", "") or op.get("content", "")
        from_episodes = op.get("from", [])
        if isinstance(from_episodes, str):
            from_episodes = [from_episodes]
        from_episodes = [self._resolve_ref(e, refs) for e in from_episodes]
        
        relations_raw = op.get("relations", [])
        
        concept = Concept(
            title=title,
            summary=summary,
            concept_type="pattern",
            source_episodes=from_episodes,
            embedding=embedding,
        )
        
        self.store.add_concept(concept)
        
        # Add relations
        for rel in relations_raw:
            rel_type_str = rel.get("type", "related_to")
            try:
                rel_type = RelationType(rel_type_str)
            except ValueError:
                rel_type = RelationType.RELATED_TO
            
            target_id = self._resolve_ref(rel.get("to", ""), refs)
            relation = Relation(type=rel_type, target_id=target_id)
            self.store.add_relation(concept.id, relation)
        
        # Mark source episodes as processed
        for ep_id in from_episodes:
            episode = self.store.get_episode(ep_id)
            if episode:
                episode.consolidated = True
                episode.consolidated_at = datetime.now()
                self.store.update_episode(episode)
        
        return OpResult(
            op_index=index,
            op_type="concept",
            success=True,
            id=concept.id,
            ref=ref_name,
        )
    
    def _op_update(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Execute an update operation."""
        target_id = self._resolve_ref(op.get("id", ""), refs)
        
        # Determine target type and update
        if self.store.get_episode(target_id):
            episode = self.store.get_episode(target_id)
            if "content" in op:
                episode.content = op["content"]
                episode.embedding = None
            if "metadata" in op:
                episode.metadata = op["metadata"]
            episode.updated_at = datetime.now()
            self.store.update_episode(episode)
        elif self.store.get_concept(target_id):
            concept = self.store.get_concept(target_id)
            if "title" in op:
                concept.title = op["title"]
            if "summary" in op:
                concept.summary = op["summary"]
                concept.embedding = None
            concept.updated_at = datetime.now()
            self.store.update_concept(concept)
        else:
            return OpResult(
                op_index=index, op_type="update", success=False,
                error=f"Target not found: {target_id}",
            )
        
        return OpResult(
            op_index=index,
            op_type="update",
            success=True,
            id=target_id,
            ref=ref_name,
        )
    
    def _op_link(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Execute a link (relation) operation."""
        from_id = self._resolve_ref(op.get("from", ""), refs)
        to_id = self._resolve_ref(op.get("to", ""), refs)
        rel_type_str = op.get("type", "related_to")
        
        try:
            rel_type = RelationType(rel_type_str)
        except ValueError:
            rel_type = RelationType.RELATED_TO
        
        relation = Relation(type=rel_type, target_id=to_id)
        self.store.add_relation(from_id, relation)
        
        return OpResult(
            op_index=index,
            op_type="link",
            success=True,
            ref=ref_name,
        )
    
    def _op_topic(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Execute a topic creation operation."""
        name = op.get("name", "")
        topic_id = op.get("id") or slugify(name)
        description = op.get("description", "")
        
        topic = Topic(id=topic_id, name=name, description=description)
        self.store.create_topic(topic)
        
        return OpResult(
            op_index=index,
            op_type="topic",
            success=True,
            id=topic_id,
            ref=ref_name,
        )
    
    def _op_set_topic(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Execute a set_topic operation."""
        target_id = self._resolve_ref(op.get("id", ""), refs)
        topic_id = op.get("topic")
        
        # Try episode first, then concept
        episode = self.store.get_episode(target_id)
        if episode:
            episode.topic_id = topic_id
            episode.updated_at = datetime.now()
            self.store.update_episode(episode)
        else:
            concept = self.store.get_concept(target_id)
            if concept:
                concept.topic_id = topic_id
                concept.updated_at = datetime.now()
                self.store.update_concept(concept)
            else:
                return OpResult(
                    op_index=index, op_type="set_topic", success=False,
                    error=f"Target not found: {target_id}",
                )
        
        return OpResult(
            op_index=index,
            op_type="set_topic",
            success=True,
            id=target_id,
            ref=ref_name,
        )
    
    def _op_delete(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Execute a delete operation."""
        target_id = self._resolve_ref(op.get("id", ""), refs)
        
        # Try episode first, then concept
        episode = self.store.get_episode(target_id)
        if episode:
            episode.deleted = True
            episode.deleted_at = datetime.now()
            self.store.update_episode(episode)
        else:
            concept = self.store.get_concept(target_id)
            if concept:
                concept.deleted = True
                concept.deleted_at = datetime.now()
                self.store.update_concept(concept)
            else:
                return OpResult(
                    op_index=index, op_type="delete", success=False,
                    error=f"Target not found: {target_id}",
                )
        
        return OpResult(
            op_index=index,
            op_type="delete",
            success=True,
            id=target_id,
            ref=ref_name,
        )
    
    def _op_restore(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Execute a restore operation."""
        target_id = self._resolve_ref(op.get("id", ""), refs)
        
        # Try episode first, then concept
        episode = self.store.get_episode(target_id, include_deleted=True)
        if episode and episode.deleted:
            episode.deleted = False
            episode.deleted_at = None
            self.store.update_episode(episode)
        else:
            concept = self.store.get_concept(target_id, include_deleted=True)
            if concept and concept.deleted:
                concept.deleted = False
                concept.deleted_at = None
                self.store.update_concept(concept)
            else:
                return OpResult(
                    op_index=index, op_type="restore", success=False,
                    error=f"Deleted item not found: {target_id}",
                )
        
        return OpResult(
            op_index=index,
            op_type="restore",
            success=True,
            id=target_id,
            ref=ref_name,
        )
    
    def _op_processed(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Execute a processed operation (mark episodes as reviewed)."""
        ids_raw = op.get("ids", [])
        if isinstance(ids_raw, str):
            ids_raw = [ids_raw]
        
        ids = [self._resolve_ref(i, refs) for i in ids_raw]
        
        for episode_id in ids:
            episode = self.store.get_episode(episode_id)
            if episode:
                episode.consolidated = True
                episode.consolidated_at = datetime.now()
                self.store.update_episode(episode)
        
        return OpResult(
            op_index=index,
            op_type="processed",
            success=True,
            ref=ref_name,
        )
    
    def _op_entity_relation(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Execute an entity_relation operation to create a relationship between entities."""
        source_raw = op.get("source", "")
        target_raw = op.get("target", "")
        relation_type = op.get("relation", "")
        strength = float(op.get("strength", 0.5))
        context = op.get("context")
        
        source_id = self._resolve_entity_id(source_raw)
        target_id = self._resolve_entity_id(target_raw)
        
        relation = EntityRelation(
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            strength=strength,
            context=context,
        )
        
        self.store.add_entity_relation(relation)
        
        return OpResult(
            op_index=index,
            op_type="entity_relation",
            success=True,
            ref=ref_name,
        )
