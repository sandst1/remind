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
    Episode, Concept, Evidence, Fact, Conflict, Relation, RelationType,
    EpisodeType, EntityType, Entity, EntityRelation,
    canonicalize_entity_name, strip_entity_label_prefix, normalize_labels,
    EVIDENCE_SUPPORTS,
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
    code: Optional[str] = None
    subject_id: Optional[str] = None
    current_revision: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            "line": self.line,
            "op_index": self.op_index,
            "op_type": self.op_type,
            "message": self.message,
            "code": self.code,
            "subject_id": self.subject_id,
            "current_revision": self.current_revision,
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
    subject_type: Optional[str] = None  # For the change feed; not surfaced via to_dict
    
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
    warnings: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "ops_executed": self.ops_executed,
            "errors": [e.to_dict() for e in self.errors],
            "results": [r.to_dict() for r in self.results],
            "warnings": self.warnings,
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
        elif op_type in ("resolve", "dismiss", "evidence", "reshape", "merge", "split"):
            op["note"] = trailing_string
    
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
        from remind.operations import resolve_id
        return resolve_id(self.store, value) if isinstance(value, str) else value
    
    async def apply(
        self,
        changeset: Union[str, list[dict]],
        dry_run: bool = False,
        expected_revisions: Optional[dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
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
        
        from remind.operations import receipt, save_receipt, check_revisions, record_revision, RevisionConflict
        request = {"operation": "apply", "ops": ops, "expected_revisions": expected_revisions}
        cached = receipt(self.store, idempotency_key, request)
        if cached is not None:
            return ApplyResult(success=cached["success"], ops_executed=cached["ops_executed"],
                               results=[OpResult(**r) for r in cached["results"]], warnings=cached.get("warnings", []))
        # Validate all ops first
        errors = self._validate_ops(ops)
        if errors:
            return ApplyResult(success=False, errors=errors)
        
        if dry_run:
            return ApplyResult(success=True, ops_executed=len(ops))
        
        # Pre-compute embeddings for ops that need them
        # This must happen before the transaction since embedding is async
        warnings = []
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
                            warnings.append(f"Missing embedding for op {i}: {e}")
                elif op_type == "concept":
                    summary = op.get("summary", "") or op.get("content", "")
                    if summary:
                        try:
                            embeddings_cache[i] = await self.embedding.embed(summary)
                        except Exception as e:
                            logger.warning(f"Failed to embed concept for op {i}: {e}")
                            warnings.append(f"Missing embedding for op {i}: {e}")
        
        fingerprint = None
        if embeddings_cache:
            dims = len(next(iter(embeddings_cache.values())))
            fingerprint = json.dumps({"provider": self.embedding.name, "dimensions": dims, "input_version": 1}, sort_keys=True)
            existing = self.store.get_metadata("embedding_fingerprint")
            old_dims = self.store.get_metadata("embedding_dimensions")
            if (existing and existing != fingerprint) or (old_dims and int(old_dims) != dims):
                warnings.append("Embedding model changed; run re-embed --all. Writes stored without embeddings.")
                embeddings_cache.clear()
        # Pre-initialize vector dimensions *outside* the transaction.
        # _ensure_vec_dimensions() runs DDL (CREATE VIRTUAL TABLE) via a
        # separate fresh connection.  Calling it inside engine.begin() would
        # require conn.commit() mid-transaction, which SQLAlchemy 2.x forbids
        # inside a context-manager transaction and raises
        # "Can't operate on closed transaction inside context manager".
        if embeddings_cache:
            first_emb = next(iter(embeddings_cache.values()))
            if getattr(self.store, '_vec_dimensions', None) != len(first_emb):
                self.store._ensure_vec_dimensions(first_emb)  # conn=None → fresh connection + DDL
        
        # Execute in transaction (sync operations only)
        results = []
        refs: dict[str, str] = {}  # Local reference names -> IDs
        
        try:
            with self.store.transaction():
                cached = receipt(self.store, idempotency_key, request)
                if cached is not None:
                    return ApplyResult(success=cached["success"], ops_executed=cached["ops_executed"],
                                       results=[OpResult(**r) for r in cached["results"]], warnings=cached.get("warnings", []))
                if embeddings_cache:
                    self.store.set_metadata("embedding_fingerprint", fingerprint)
                check_revisions(self.store, expected_revisions or {})
                created = set()
                for i, op in enumerate(ops):
                    fields = {"update": ["id"], "label": ["id"], "unlabel": ["id"],
                              "delete": ["id"], "restore": ["id"], "processed": ["ids"],
                              "supersede": ["old"], "resolve": ["id"], "dismiss": ["id"],
                              "link": ["from"], "unlink": ["from"], "concept": ["from"],
                              "reshape": ["id"], "merge": ["from", "into"], "split": ["id"]}.get(op["op"], [])
                    for field in fields:
                        values = op.get(field, [])
                        if isinstance(values, str):
                            values = values.split(",")
                        for value in values:
                            identifier = self._resolve_ref(value, refs)
                            if identifier not in created and record_revision(self.store, identifier) is not None:
                                if identifier not in (expected_revisions or {}):
                                    raise RevisionConflict(identifier, record_revision(self.store, identifier))
                    result = self._execute_op_sync(i, op, refs, embeddings_cache.get(i))
                    results.append(result)
                    if result.id and result.op_type in {"remember", "concept", "conflict", "evidence"}:
                        created.add(result.id)
                    
                    # Store ref if declared
                    if result.success and result.ref and result.id:
                        refs[result.ref] = result.id
                    
                    if not result.success:
                        raise RuntimeError(f"Op {i} failed: {result.error}")
                save_receipt(self.store, idempotency_key, request, ApplyResult(
                    success=True, ops_executed=len(results), results=results, warnings=warnings).to_dict())
        
        except Exception as e:
            # Transaction rolled back. A failing op is appended to results
            # before it raises, so the culprit is the last result when that
            # result is a failure -- not len(results), which is the op after.
            failed_index = (
                len(results) - 1 if results and not results[-1].success else len(results)
            )
            return ApplyResult(
                success=False,
                ops_executed=len(results),
                results=results,
                errors=[OpError(
                    line=None,
                    op_index=failed_index,
                    op_type=ops[failed_index]["op"] if failed_index < len(ops) else "",
                    message=str(e),
                    code="revision_conflict" if isinstance(e, RevisionConflict) else "operation_failed",
                    subject_id=e.subject_id if isinstance(e, RevisionConflict) else None,
                    current_revision=e.current_revision if isinstance(e, RevisionConflict) else None,
                )],
            )
        
        return ApplyResult(
            success=True,
            ops_executed=len(results),
            results=results,
            warnings=warnings,
        )
    
    def _validate_ops(self, ops: list[dict]) -> list[OpError]:
        """Validate operations without executing them."""
        errors = []
        refs_declared: set[str] = set()
        
        valid_ops = {
            "remember", "supersede", "conflict", "resolve", "dismiss",
            "concept", "update", "link", "label", "unlabel",
            "delete", "restore", "processed", "entity_relation",
            "evidence", "unlink",
            "reshape", "merge", "split",
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
            
            elif op_type == "label":
                if not op.get("id") or not op.get("key") or op.get("value") is None:
                    errors.append(OpError(
                        line=None, op_index=i, op_type=op_type,
                        message="label requires 'id', 'key', and 'value'",
                    ))

            elif op_type == "unlabel":
                if not op.get("id") or not op.get("key"):
                    errors.append(OpError(
                        line=None, op_index=i, op_type=op_type,
                        message="unlabel requires 'id' and 'key'",
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
            
            elif op_type == "evidence":
                if not op.get("concept") or not op.get("episode"):
                    errors.append(OpError(
                        line=None, op_index=i, op_type=op_type,
                        message="evidence requires 'concept' and 'episode'",
                    ))
            
            elif op_type == "unlink":
                if not op.get("concept") or not op.get("episode"):
                    errors.append(OpError(
                        line=None, op_index=i, op_type=op_type,
                        message="unlink requires 'concept' and 'episode'",
                    ))
            
            elif op_type == "reshape":
                if not op.get("id"):
                    errors.append(OpError(
                        line=None, op_index=i, op_type=op_type,
                        message="reshape requires 'id'",
                    ))
            
            elif op_type == "merge":
                if not op.get("from") or not op.get("into"):
                    errors.append(OpError(
                        line=None, op_index=i, op_type=op_type,
                        message="merge requires 'from' and 'into'",
                    ))
            
            elif op_type == "split":
                if not op.get("id") or not op.get("into"):
                    errors.append(OpError(
                        line=None, op_index=i, op_type=op_type,
                        message="split requires 'id' and 'into'",
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
                result = self._op_remember(index, op, refs, ref_name, embedding)
            elif op_type == "supersede":
                result = self._op_supersede(index, op, refs, ref_name)
            elif op_type == "conflict":
                result = self._op_conflict(index, op, refs, ref_name)
            elif op_type == "resolve":
                result = self._op_resolve(index, op, refs, ref_name)
            elif op_type == "dismiss":
                result = self._op_dismiss(index, op, refs, ref_name)
            elif op_type == "concept":
                result = self._op_concept(index, op, refs, ref_name, embedding)
            elif op_type == "update":
                result = self._op_update(index, op, refs, ref_name)
            elif op_type == "link":
                result = self._op_link(index, op, refs, ref_name)
            elif op_type == "label":
                result = self._op_label(index, op, refs, ref_name)
            elif op_type == "unlabel":
                result = self._op_unlabel(index, op, refs, ref_name)
            elif op_type == "delete":
                result = self._op_delete(index, op, refs, ref_name)
            elif op_type == "restore":
                result = self._op_restore(index, op, refs, ref_name)
            elif op_type == "processed":
                result = self._op_processed(index, op, refs, ref_name)
            elif op_type == "entity_relation":
                result = self._op_entity_relation(index, op, refs, ref_name)
            elif op_type == "evidence":
                result = self._op_evidence(index, op, refs, ref_name)
            elif op_type == "unlink":
                result = self._op_unlink(index, op, refs, ref_name)
            elif op_type == "reshape":
                result = self._op_reshape(index, op, refs, ref_name)
            elif op_type == "merge":
                result = self._op_merge(index, op, refs, ref_name)
            elif op_type == "split":
                result = self._op_split(index, op, refs, ref_name)
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

        if result.success:
            resolved_op = dict(op)
            if result.op_type == "processed":
                values = op.get("ids", [])
                values = values.split(",") if isinstance(values, str) else values
                resolved_op["ids"] = [self._resolve_ref(value, refs) for value in values]
            self._emit_op_event(resolved_op, result)
        return result

    # Maps op_type -> (event kind, default subject_type). Ops not listed
    # here (link, entity_relation, evidence, unlink, reshape, merge, split)
    # don't yet write to the change feed.
    _EVENT_KIND_MAP = {
        "remember": ("remembered", "episode"),
        "supersede": ("superseded", "fact"),
        "conflict": ("conflict_opened", "conflict"),
        "resolve": ("conflict_resolved", "conflict"),
        "dismiss": ("conflict_dismissed", "conflict"),
        "concept": ("concept_created", "concept"),
        "update": ("updated", "concept"),
        "label": ("labeled", "episode"),
        "unlabel": ("unlabeled", "episode"),
        "delete": ("deleted", "episode"),
        "restore": ("restored", "episode"),
    }

    def _emit_op_event(self, op: dict, result: OpResult) -> None:
        """Append change-feed events for a successfully executed op.

        Best-effort: failures here are logged, not raised, so an events
        backend hiccup never breaks the underlying write it's describing.
        """
        if result.op_type == "processed":
            ids_raw = op.get("ids", [])
            if isinstance(ids_raw, str):
                ids_raw = [ids_raw]
            for episode_id in ids_raw:
                self.store.emit_event("processed", "episode", episode_id)
            return

        mapping = self._EVENT_KIND_MAP.get(result.op_type)
        if not mapping or not result.id:
            from uuid import uuid4
            self.store.emit_event("updated", "operation", str(uuid4()), payload={"operation": op})
            return
        kind, default_subject_type = mapping
        subject_type = result.subject_type or default_subject_type
        self.store.emit_event(kind, subject_type, result.id)
    
    def _op_remember(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str],
        embedding: Optional[list[float]] = None,
    ) -> OpResult:
        """Execute a remember operation."""
        content = op.get("content", "")
        episode_type = op.get("t") or op.get("type", "observation")
        entities_raw = op.get("e") or op.get("entities", [])
        if isinstance(entities_raw, str):
            # JSON path: split comma-separated string just like compact format does
            entities_raw = [e.strip() for e in entities_raw.split(",") if e.strip()]
        elif isinstance(entities_raw, list):
            # Expand any comma-joined strings within list elements
            expanded: list[str] = []
            for item in entities_raw:
                if isinstance(item, str) and "," in item:
                    expanded.extend(e.strip() for e in item.split(",") if e.strip())
                else:
                    expanded.append(item)
            entities_raw = expanded
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
            labels=normalize_labels(op.get("labels")),
            metadata=op.get("metadata") or {},
            source_type=op.get("source_type"),
            confidence=max(0., min(1., float(op.get("confidence", 1.)))),
        )
        
        episode_id = self.store.add_episode(episode)
        if episode_type == "fact":
            self.store.emit_event("remembered", "episode", episode_id)
        
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
            subject_type="fact" if fact_id else "episode",
        )
    
    def _op_supersede(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Execute a supersede operation.

        In addition to closing the old fact's validity window, upserts a
        resolved Conflict row so the replacement is visible in recall conflict
        history, snapshot, and the UI — even when the agent skips the formal
        conflict → resolve workflow.
        """
        old_id = self._resolve_ref(op.get("old", ""), refs)
        new_id = self._resolve_ref(op.get("new", ""), refs)
        resolved_by = op.get("by") or op.get("resolved_by")
        resolution_note = op.get("note") or op.get("resolution_note")

        self.store.supersede_fact(old_id, new_id)

        # Upsert a resolved Conflict row for provenance
        now = datetime.now()
        existing = self.store.find_open_conflict_for_facts(old_id, new_id)
        if existing:
            existing.status = "resolved"
            existing.winning_fact_id = new_id
            existing.resolved_at = now
            existing.resolved_by = resolved_by
            if resolution_note:
                existing.resolution_note = resolution_note
            self.store.update_conflict(existing)
        else:
            old_fact = self.store.get_fact(old_id)
            concept_ids = [old_fact.cluster_id] if old_fact and old_fact.cluster_id else []
            conflict = Conflict(
                kind="fact",
                fact_a_id=old_id,
                fact_b_id=new_id,
                concept_ids=concept_ids,
                description=f"Superseded: {old_id} replaced by {new_id}",
                severity="low",
                status="resolved",
                created_at=now,
                resolved_at=now,
                resolved_by=resolved_by,
                resolution_note=resolution_note,
                winning_fact_id=new_id,
            )
            self.store.add_conflict(conflict)

        return OpResult(
            op_index=index,
            op_type="supersede",
            success=True,
            ref=ref_name,
        )
    
    def _op_conflict(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Execute a conflict (open) operation.

        Accepts fact_a/fact_b or the shorter a/b aliases. concept_ids can be
        passed as a comma-separated string or a list; concept_id (singular) is
        also accepted for convenience and normalised to a one-element list.
        """
        fact_a = self._resolve_ref(op.get("fact_a") or op.get("a", ""), refs)
        fact_b = self._resolve_ref(op.get("fact_b") or op.get("b", ""), refs)
        note = op.get("note") or op.get("description", "")
        severity = op.get("severity", "medium")

        raw_cids = op.get("concept_ids") or op.get("concept_id")
        if isinstance(raw_cids, str):
            concept_ids = [c.strip() for c in raw_cids.split(",") if c.strip()]
        elif isinstance(raw_cids, list):
            concept_ids = raw_cids
        else:
            concept_ids = []

        kind = op.get("kind", "fact")
        if kind == "fact":
            left, right = self.store.get_fact(fact_a), self.store.get_fact(fact_b)
            if left is None or right is None:
                raise ValueError("Fact conflicts require two existing fact IDs")
            concept_ids = sorted(set(concept_ids) | {f.cluster_id for f in (left, right) if f.cluster_id})
        elif kind == "concept":
            concept_ids = concept_ids or [fact_a, fact_b]
            if not concept_ids or any(self.store.get_concept(identifier) is None for identifier in concept_ids):
                raise ValueError("Concept conflicts require existing concept IDs")
            fact_a = fact_b = None
        else:
            raise ValueError("Conflict kind must be fact or concept")

        conflict = Conflict(
            kind=kind,
            fact_a_id=fact_a,
            fact_b_id=fact_b,
            concept_ids=concept_ids,
            description=note,
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
        if conflict.kind == "fact" and winner_id not in {conflict.fact_a_id, conflict.fact_b_id}:
            raise ValueError("Winner must be one of the conflicting facts")
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
        conflict.winning_fact_id = (winner_id or None) if conflict.kind == "fact" else None
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
        self.store.emit_event("remembered", "episode", decision.id)
        for concept_id in conflict.concept_ids:
            concept = self.store.get_concept(concept_id)
            if concept and concept.concept_type in {"fact_cluster", "fact"}:
                concept.specifics = [f.statement for f in self.store.get_facts(cluster_id=concept_id, active_only=True)]
                concept.conflicts = []
                self.store.update_concept(concept)
        
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
            labels=normalize_labels(op.get("labels")),
            confidence=float(op.get("confidence", 0.5)),
            entity_ids=sorted({entity for episode in self.store.get_episodes_batch(from_episodes)
                               for entity in episode.entity_ids}),
        )
        
        self.store.add_concept(concept)
        from remind.models import Evidence
        for episode_id in from_episodes:
            self.store.add_evidence(Evidence(episode_id=episode_id, concept_id=concept.id))
        
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
        episode = self.store.get_episode(target_id)
        if episode:
            if "content" in op:
                episode.content = op["content"]
                episode.embedding = None
            if "metadata" in op:
                episode.metadata = op["metadata"]
            episode.updated_at = datetime.now()
            self.store.update_episode(episode)
        else:
            concept = self.store.get_concept(target_id)
            if not concept:
                return OpResult(
                    op_index=index, op_type="update", success=False,
                    error=f"Target not found: {target_id}",
                )
            if "title" in op:
                concept.title = op["title"]
            if "summary" in op:
                concept.summary = op["summary"]
                concept.embedding = None
            concept.updated_at = datetime.now()
            self.store.update_concept(concept)
        
        return OpResult(
            op_index=index,
            op_type="update",
            success=True,
            id=target_id,
            ref=ref_name,
            subject_type="episode" if episode else "concept",
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
    
    def _resolve_label_target(
        self, target_id: str
    ) -> tuple[Optional[Any], Optional[str], str]:
        """Resolve a label/unlabel target to a labelable object.

        Facts carry no labels of their own, but a `remember` op that creates
        one exposes the *fact* id as its ref (supersede needs it), so a fact
        id is redirected to the episode that asserted it.

        Returns (object, subject_type, resolved_id); object is None if the
        target could not be resolved.
        """
        episode = self.store.get_episode(target_id)
        if episode:
            return episode, "episode", target_id

        concept = self.store.get_concept(target_id)
        if concept:
            return concept, "concept", target_id

        fact = self.store.get_fact(target_id)
        if fact and fact.source_episode_id:
            episode = self.store.get_episode(fact.source_episode_id)
            if episode:
                return episode, "episode", fact.source_episode_id

        return None, None, target_id

    def _op_label(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Add a key=value label to an episode or concept, leaving existing labels intact."""
        target_id = self._resolve_ref(op.get("id", ""), refs)
        key = str(op.get("key", "")).strip()
        value = str(op.get("value", "")).strip()

        obj, subject_type, resolved_id = self._resolve_label_target(target_id)
        if not obj:
            return OpResult(
                op_index=index, op_type="label", success=False,
                error=f"Target not found: {target_id}",
            )

        values = obj.labels.setdefault(key, [])
        if value not in values:
            values.append(value)
        obj.updated_at = datetime.now()
        if subject_type == "episode":
            self.store.update_episode(obj)
        else:
            self.store.update_concept(obj)

        return OpResult(
            op_index=index,
            op_type="label",
            success=True,
            id=resolved_id,
            ref=ref_name,
            subject_type=subject_type,
        )

    def _op_unlabel(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Remove a label from an episode or concept.

        Removes all values for 'key' unless 'value' narrows it to one.
        """
        target_id = self._resolve_ref(op.get("id", ""), refs)
        key = str(op.get("key", "")).strip()
        value = op.get("value")

        obj, subject_type, resolved_id = self._resolve_label_target(target_id)
        if not obj:
            return OpResult(
                op_index=index, op_type="unlabel", success=False,
                error=f"Target not found: {target_id}",
            )

        if key in obj.labels:
            if value is None:
                obj.labels.pop(key, None)
            else:
                remaining = [v for v in obj.labels[key] if v != value]
                if remaining:
                    obj.labels[key] = remaining
                else:
                    obj.labels.pop(key, None)

        obj.updated_at = datetime.now()
        if subject_type == "episode":
            self.store.update_episode(obj)
        else:
            self.store.update_concept(obj)

        return OpResult(
            op_index=index,
            op_type="unlabel",
            success=True,
            id=resolved_id,
            ref=ref_name,
            subject_type=subject_type,
        )
    
    def _op_delete(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Execute a delete operation."""
        target_id = self._resolve_ref(op.get("id", ""), refs)
        
        # Try episode first, then concept.
        deleted_episode = self.store.delete_episode(target_id)
        deleted_concept = False if deleted_episode else self.store.delete_concept(target_id)
        if not deleted_episode and not deleted_concept:
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
            subject_type="episode" if deleted_episode else "concept",
        )
    
    def _op_restore(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Execute a restore operation."""
        target_id = self._resolve_ref(op.get("id", ""), refs)
        
        # Try episode first, then concept.
        restored_episode = self.store.restore_episode(target_id)
        restored_concept = False if restored_episode else self.store.restore_concept(target_id)
        if not restored_episode and not restored_concept:
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
            subject_type="episode" if restored_episode else "concept",
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
    
    def _op_evidence(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Execute an evidence operation to link an episode to a concept."""
        concept_id = self._resolve_ref(op.get("concept", ""), refs)
        episode_id = self._resolve_ref(op.get("episode", ""), refs)
        link_type = op.get("type") or op.get("t", EVIDENCE_SUPPORTS)
        strength = float(op.get("strength", 0.5))
        note = op.get("note")
        
        # Trailing string becomes note if not set
        if not note:
            for key, value in op.items():
                if key not in ("op", "concept", "episode", "type", "t", "strength", "as"):
                    note = str(value)
                    break
        
        evidence = Evidence(
            episode_id=episode_id,
            concept_id=concept_id,
            link_type=link_type,
            strength=strength,
            note=note,
        )
        
        evidence_id = self.store.add_evidence(evidence)
        
        return OpResult(
            op_index=index,
            op_type="evidence",
            success=True,
            id=evidence_id,
            ref=ref_name,
        )
    
    def _op_unlink(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Execute an unlink operation to remove evidence links between an episode and concept."""
        concept_id = self._resolve_ref(op.get("concept", ""), refs)
        episode_id = self._resolve_ref(op.get("episode", ""), refs)
        
        # Find and delete all evidence links between this episode and concept
        evidence_links = self.store.get_evidence_for_concept(concept_id)
        deleted_count = 0
        for ev in evidence_links:
            if ev.episode_id == episode_id:
                self.store.delete_evidence(ev.id)
                deleted_count += 1
        
        return OpResult(
            op_index=index,
            op_type="unlink",
            success=True,
            ref=ref_name,
        )
    
    def _op_reshape(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Change a concept's type while preserving its identity and history."""
        concept_id = self._resolve_ref(op.get("id", ""), refs)
        new_type = op.get("type") or op.get("t")
        note = op.get("note")
        
        concept = self.store.get_concept(concept_id)
        if not concept:
            return OpResult(
                op_index=index, op_type="reshape", success=False,
                error=f"Concept not found: {concept_id}",
            )
        
        old_type = concept.concept_type
        concept.concept_type = new_type or old_type
        concept.lineage_note = note or f"reshaped from {old_type}"
        concept.updated_at = datetime.now()
        
        self.store.update_concept(concept)
        
        return OpResult(
            op_index=index,
            op_type="reshape",
            success=True,
            id=concept_id,
            ref=ref_name,
        )
    
    def _op_merge(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Merge multiple concepts into a new one."""
        from_ids_raw = op.get("from", [])
        if isinstance(from_ids_raw, str):
            from_ids_raw = [f.strip() for f in from_ids_raw.split(",")]
        from_ids = [self._resolve_ref(fid, refs) for fid in from_ids_raw]
        
        into_id = self._resolve_ref(op.get("into", ""), refs)
        note = op.get("note")
        
        # Get source concepts
        source_concepts = []
        for cid in from_ids:
            c = self.store.get_concept(cid)
            if c:
                source_concepts.append(c)
        
        if not source_concepts:
            return OpResult(
                op_index=index, op_type="merge", success=False,
                error="No source concepts found",
            )
        
        # Create merged concept if it doesn't exist
        merged = self.store.get_concept(into_id)
        if not merged:
            # Combine data from source concepts
            merged = Concept(
                id=into_id,
                title=source_concepts[0].title,
                summary=" | ".join(c.summary for c in source_concepts if c.summary),
                confidence=max(c.confidence for c in source_concepts),
                concept_type=source_concepts[0].concept_type,
                parent_id=source_concepts[0].id,
                lineage_note=note or f"merged from {', '.join(from_ids)}",
            )
            
            # Combine entity_ids
            all_entities: set[str] = set()
            for c in source_concepts:
                all_entities.update(c.entity_ids or [])
            merged.entity_ids = list(all_entities)
            
            # Combine source_episodes
            all_episodes: set[str] = set()
            for c in source_concepts:
                all_episodes.update(c.source_episodes or [])
            merged.source_episodes = list(all_episodes)
            
            self.store.add_concept(merged)
        else:
            merged.lineage_note = note or f"merged from {', '.join(from_ids)}"
            merged.updated_at = datetime.now()
            self.store.update_concept(merged)
        
        # Soft-delete source concepts
        for c in source_concepts:
            c.deleted_at = datetime.now()
            c.lineage_note = f"merged into {into_id}"
            self.store.update_concept(c)
        
        return OpResult(
            op_index=index,
            op_type="merge",
            success=True,
            id=into_id,
            ref=ref_name,
        )
    
    def _op_split(
        self, index: int, op: dict, refs: dict[str, str], ref_name: Optional[str]
    ) -> OpResult:
        """Split a concept into multiple new concepts."""
        source_id = self._resolve_ref(op.get("id", ""), refs)
        into_ids_raw = op.get("into", [])
        if isinstance(into_ids_raw, str):
            into_ids_raw = [i.strip() for i in into_ids_raw.split(",")]
        into_ids = [self._resolve_ref(iid, refs) for iid in into_ids_raw]
        
        note = op.get("note")
        
        source = self.store.get_concept(source_id)
        if not source:
            return OpResult(
                op_index=index, op_type="split", success=False,
                error=f"Source concept not found: {source_id}",
            )
        
        if not into_ids:
            return OpResult(
                op_index=index, op_type="split", success=False,
                error="No target IDs specified for split",
            )
        
        created_ids = []
        for new_id in into_ids:
            new_concept = self.store.get_concept(new_id)
            if not new_concept:
                # Create new concept derived from source
                new_concept = Concept(
                    id=new_id,
                    title=f"{source.title or source.id} (split)",
                    summary=source.summary,
                    confidence=source.confidence,
                    concept_type=source.concept_type,
                    parent_id=source_id,
                    lineage_note=note or f"split from {source_id}",
                    entity_ids=list(source.entity_ids or []),
                )
                self.store.add_concept(new_concept)
                created_ids.append(new_id)
        
        # Mark source as split
        source.lineage_note = f"split into {', '.join(into_ids)}"
        source.updated_at = datetime.now()
        self.store.update_concept(source)
        
        return OpResult(
            op_index=index,
            op_type="split",
            success=True,
            id=",".join(created_ids) if created_ids else source_id,
            ref=ref_name,
        )
