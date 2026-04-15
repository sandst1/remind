"""Compact tagged-CSV protocol parsing for LLM responses."""

from __future__ import annotations

import csv
import io
import re


ALLOWED_RELATION_TYPES = {
    "implies",
    "contradicts",
    "specializes",
    "generalizes",
    "causes",
    "correlates",
    "part_of",
    "context_of",
    "supersedes",
}

# Row-tag aliases (explicit forms only).
EXTRACT_TAGS = {
    "EPISODE": "EPISODE",
    "ENTITY": "ENTITY",
    "ENTITY_RELATION": "ENTITY_RELATION",
}

RELATION_ONLY_TAGS = {
    "ENTITY_RELATION": "ENTITY_RELATION",
}

CONSOLIDATION_TAGS = {
    "ANALYSIS": "ANALYSIS",
    "UPDATE": "UPDATE",
    "UPDATE_SOURCE": "UPDATE_SOURCE",
    "UPDATE_EXCEPTION": "UPDATE_EXCEPTION",
    "UPDATE_TAG": "UPDATE_TAG",
    "UPDATE_RELATION": "UPDATE_RELATION",
    "NEW_CONCEPT": "NEW_CONCEPT",
    "NEW_SOURCE": "NEW_SOURCE",
    "NEW_EXCEPTION": "NEW_EXCEPTION",
    "NEW_TAG": "NEW_TAG",
    "NEW_RELATION": "NEW_RELATION",
    "CONTRADICTION": "CONTRADICTION",
}

TRIAGE_TAGS = {
    "DENSITY": "DENSITY",
    "TRIAGE_EPISODE": "TRIAGE_EPISODE",
    "TRIAGE_ENTITY": "TRIAGE_ENTITY",
    "TRIAGE_METADATA": "TRIAGE_METADATA",
}


class ProtocolParseError(ValueError):
    """Raised when tagged-CSV content cannot be parsed safely."""


def strip_id_prefix(id_str: str) -> str:
    """Strip ep-/c- prefix from LLM-facing IDs back to raw storage IDs."""
    if id_str.startswith("ep-") or id_str.startswith("c-"):
        return id_str.split("-", 1)[1]
    return id_str


def _strip_code_fence(text: str) -> str:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:csv|text)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    return raw.strip()


def _extract_tagged_block(text: str, begin_tag: str, end_tag: str) -> str:
    raw = _strip_code_fence(text)
    begin_idx = raw.find(begin_tag)
    if begin_idx == -1:
        return raw
    start = begin_idx + len(begin_tag)
    end_idx = raw.find(end_tag, start)
    if end_idx == -1:
        raise ProtocolParseError(f"Missing end tag: {end_tag}")
    return raw[start:end_idx].strip()


def _parse_csv_rows(block: str) -> list[list[str]]:
    rows: list[list[str]] = []
    reader = csv.reader(io.StringIO(block))
    for row in reader:
        if not row:
            continue
        first = (row[0] or "").strip()
        if not first or first.startswith("#"):
            continue
        rows.append([c.strip() for c in row])
    return rows


def _to_opt_str(value: str) -> str | None:
    return value if value != "" else None


def _to_float(value: str | None, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_extraction_single_csv(text: str) -> dict:
    """Parse single-episode extraction result rows."""
    block = _extract_tagged_block(text, "BEGIN EXTRACT_RESULTS", "END EXTRACT_RESULTS")
    rows = _parse_csv_rows(block)
    result = {"type": "observation", "title": None, "entities": [], "entity_relationships": []}

    saw_ep = False
    for row in rows:
        kind = EXTRACT_TAGS.get(row[0], row[0])
        if kind == "EPISODE" and len(row) >= 3:
            saw_ep = True
            result["type"] = row[1] or "observation"
            result["title"] = _to_opt_str(row[2])
        elif kind == "ENTITY" and len(row) >= 3:
            result["entities"].append(
                {
                    "type": row[1] or "other",
                    "name": row[2] or "",
                }
            )
        elif kind == "ENTITY_RELATION" and len(row) >= 7:
            source_id = f"{row[1]}:{row[2]}"
            target_id = f"{row[3]}:{row[4]}"
            relation = row[5]
            if not relation:
                continue
            result["entity_relationships"].append(
                {
                    "source": source_id,
                    "target": target_id,
                    "relationship": relation,
                    "strength": _to_float(row[6] if len(row) > 6 else None, 0.5),
                    "context": _to_opt_str(row[7]) if len(row) > 7 else None,
                }
            )

    if not saw_ep:
        raise ProtocolParseError("Missing EPISODE row in extraction response")
    return result


def parse_extraction_batch_csv(text: str) -> dict:
    """Parse batched extraction result rows."""
    block = _extract_tagged_block(text, "BEGIN EXTRACT_RESULTS", "END EXTRACT_RESULTS")
    rows = _parse_csv_rows(block)
    results: dict[str, dict] = {}

    saw_ep = False
    for row in rows:
        kind = EXTRACT_TAGS.get(row[0], row[0])
        if kind == "EPISODE" and len(row) >= 4:
            saw_ep = True
            ep_id = strip_id_prefix(row[1])
            if not ep_id:
                continue
            results.setdefault(
                ep_id,
                {"type": "observation", "title": None, "entities": [], "entity_relationships": []},
            )
            results[ep_id]["type"] = row[2] or "observation"
            results[ep_id]["title"] = _to_opt_str(row[3])
        elif kind == "ENTITY" and len(row) >= 4:
            ep_id = strip_id_prefix(row[1])
            if not ep_id:
                continue
            results.setdefault(
                ep_id,
                {"type": "observation", "title": None, "entities": [], "entity_relationships": []},
            )
            results[ep_id]["entities"].append(
                {
                    "type": row[2] or "other",
                    "name": row[3] or "",
                }
            )
        elif kind == "ENTITY_RELATION" and len(row) >= 9:
            ep_id = strip_id_prefix(row[1])
            if not ep_id:
                continue
            results.setdefault(
                ep_id,
                {"type": "observation", "title": None, "entities": [], "entity_relationships": []},
            )
            relation = row[6]
            if not relation:
                continue
            results[ep_id]["entity_relationships"].append(
                {
                    "source": f"{row[2]}:{row[3]}",
                    "target": f"{row[4]}:{row[5]}",
                    "relationship": relation,
                    "strength": _to_float(row[7] if len(row) > 7 else None, 0.5),
                    "context": _to_opt_str(row[8]) if len(row) > 8 else None,
                }
            )

    if not saw_ep:
        raise ProtocolParseError("Missing EPISODE rows in batch extraction response")
    return {"results": results}


def parse_relations_only_csv(text: str) -> dict:
    """Parse relationship-only extraction rows."""
    block = _extract_tagged_block(text, "BEGIN RELATION_RESULTS", "END RELATION_RESULTS")
    rows = _parse_csv_rows(block)
    rels: list[dict] = []
    for row in rows:
        kind = RELATION_ONLY_TAGS.get(row[0], row[0])
        if kind != "ENTITY_RELATION" or len(row) < 4:
            continue
        relationship = row[3]
        if not relationship:
            continue
        rels.append(
            {
                "source": row[1],
                "target": row[2],
                "relationship": relationship,
                "strength": _to_float(row[4] if len(row) > 4 else None, 0.5),
                "context": _to_opt_str(row[5]) if len(row) > 5 else None,
            }
        )
    return {"entity_relationships": rels}


def _validate_relation_type(rel_type: str) -> str:
    if rel_type in ALLOWED_RELATION_TYPES:
        return rel_type
    return "correlates"


def parse_consolidation_csv(text: str) -> dict:
    """Parse consolidation operations rows into the existing operations shape."""
    block = _extract_tagged_block(text, "BEGIN CONSOLIDATION_OPS", "END CONSOLIDATION_OPS")
    rows = _parse_csv_rows(block)

    ops = {
        "analysis": "",
        "updates": [],
        "new_concepts": [],
        "new_relations": [],
        "contradictions": [],
    }
    updates_by_id: dict[str, dict] = {}
    new_by_temp_id: dict[str, dict] = {}
    analysis_parts: list[str] = []

    recognized_rows = 0
    for row in rows:
        kind = CONSOLIDATION_TAGS.get(row[0], row[0])
        if kind == "ANALYSIS" and len(row) >= 2:
            recognized_rows += 1
            analysis_parts.append(row[1])
        elif kind == "UPDATE" and len(row) >= 2:
            recognized_rows += 1
            concept_id = strip_id_prefix(row[1])
            if not concept_id:
                continue
            update = updates_by_id.get(concept_id)
            if not update:
                update = {
                    "concept_id": concept_id,
                    "add_exceptions": [],
                    "add_tags": [],
                    "source_episodes": [],
                    "add_relations": [],
                }
                updates_by_id[concept_id] = update
            if len(row) > 2 and row[2]:
                update["new_title"] = row[2]
            if len(row) > 3 and row[3]:
                update["new_summary"] = row[3]
            if len(row) > 4 and row[4]:
                update["confidence_delta"] = _to_float(row[4], 0.0)
            if len(row) > 5 and row[5]:
                update["topic_id"] = row[5]
        elif kind == "UPDATE_SOURCE" and len(row) >= 3:
            recognized_rows += 1
            update = updates_by_id.get(strip_id_prefix(row[1]))
            if update and row[2]:
                update["source_episodes"].append(strip_id_prefix(row[2]))
        elif kind == "UPDATE_EXCEPTION" and len(row) >= 3:
            recognized_rows += 1
            update = updates_by_id.get(strip_id_prefix(row[1]))
            if update and row[2]:
                update["add_exceptions"].append(row[2])
        elif kind == "UPDATE_TAG" and len(row) >= 3:
            recognized_rows += 1
            update = updates_by_id.get(strip_id_prefix(row[1]))
            if update and row[2]:
                update["add_tags"].append(row[2])
        elif kind == "UPDATE_RELATION" and len(row) >= 4:
            recognized_rows += 1
            update = updates_by_id.get(strip_id_prefix(row[1]))
            if not update:
                continue
            update["add_relations"].append(
                {
                    "target_id": strip_id_prefix(row[3]),
                    "type": _validate_relation_type(row[2]),
                    "strength": _to_float(row[4] if len(row) > 4 else None, 0.5),
                    "context": _to_opt_str(row[5]) if len(row) > 5 else None,
                }
            )
        elif kind == "NEW_CONCEPT" and len(row) >= 5:
            recognized_rows += 1
            temp_id = row[1]
            if not temp_id:
                continue
            nc = new_by_temp_id.get(temp_id)
            if not nc:
                nc = {
                    "temp_id": temp_id,
                    "title": None,
                    "summary": "",
                    "confidence": 0.5,
                    "conditions": None,
                    "exceptions": [],
                    "tags": [],
                    "source_episodes": [],
                    "relations": [],
                }
                new_by_temp_id[temp_id] = nc
            nc["title"] = _to_opt_str(row[2]) if len(row) > 2 else nc.get("title")
            if len(row) > 3 and row[3]:
                nc["summary"] = row[3]
            if len(row) > 4 and row[4]:
                nc["confidence"] = _to_float(row[4], 0.5)
            if len(row) > 5 and row[5]:
                nc["conditions"] = row[5]
            if len(row) > 6 and row[6]:
                nc["topic_id"] = row[6]
        elif kind == "NEW_SOURCE" and len(row) >= 3:
            recognized_rows += 1
            nc = new_by_temp_id.get(row[1])
            if nc and row[2]:
                nc["source_episodes"].append(strip_id_prefix(row[2]))
        elif kind == "NEW_EXCEPTION" and len(row) >= 3:
            recognized_rows += 1
            nc = new_by_temp_id.get(row[1])
            if nc and row[2]:
                nc["exceptions"].append(row[2])
        elif kind == "NEW_TAG" and len(row) >= 3:
            recognized_rows += 1
            nc = new_by_temp_id.get(row[1])
            if nc and row[2]:
                nc["tags"].append(row[2])
        elif kind == "NEW_RELATION" and len(row) >= 4:
            recognized_rows += 1
            source_id = strip_id_prefix(row[1])
            rel_type = _validate_relation_type(row[2])
            target_id = strip_id_prefix(row[3])
            if not source_id or not target_id:
                continue
            ops["new_relations"].append(
                {
                    "source_id": source_id,
                    "target_id": target_id,
                    "type": rel_type,
                    "strength": _to_float(row[4] if len(row) > 4 else None, 0.5),
                    "context": _to_opt_str(row[5]) if len(row) > 5 else None,
                }
            )
        elif kind == "CONTRADICTION" and len(row) >= 3:
            recognized_rows += 1
            concept_id = strip_id_prefix(row[1])
            if not concept_id:
                continue
            ops["contradictions"].append(
                {
                    "concept_id": concept_id,
                    "evidence": row[2],
                    "resolution": _to_opt_str(row[3]) if len(row) > 3 else None,
                }
            )

    if recognized_rows == 0:
        raise ProtocolParseError("No recognized consolidation rows")
    ops["analysis"] = "\n".join(analysis_parts).strip()
    ops["updates"] = list(updates_by_id.values())
    ops["new_concepts"] = list(new_by_temp_id.values())
    return ops


def parse_triage_csv(text: str) -> dict:
    """Parse triage rows into existing triage JSON-like structure."""
    block = _extract_tagged_block(text, "BEGIN TRIAGE_RESULTS", "END TRIAGE_RESULTS")
    rows = _parse_csv_rows(block)
    out: dict = {"density": 0.0, "reasoning": "", "episodes": []}
    episodes: list[dict] = []

    saw_dg = False
    for row in rows:
        kind = TRIAGE_TAGS.get(row[0], row[0])
        if kind == "DENSITY" and len(row) >= 2:
            saw_dg = True
            out["density"] = _to_float(row[1], 0.0)
            if len(row) > 2:
                out["reasoning"] = row[2]
        elif kind == "TRIAGE_EPISODE" and len(row) >= 3:
            episodes.append(
                {
                    "type": row[1] or "observation",
                    "content": row[2] or "",
                    "entities": [],
                    "metadata": {},
                }
            )
        elif kind == "TRIAGE_ENTITY" and len(row) >= 3:
            idx = int(row[1]) if row[1].isdigit() else -1
            if 0 <= idx < len(episodes) and row[2]:
                episodes[idx]["entities"].append(row[2])
        elif kind == "TRIAGE_METADATA" and len(row) >= 4:
            idx = int(row[1]) if row[1].isdigit() else -1
            if 0 <= idx < len(episodes) and row[2]:
                episodes[idx]["metadata"][row[2]] = row[3]

    if not saw_dg:
        raise ProtocolParseError("Missing DENSITY row in triage response")
    out["episodes"] = episodes
    return out

