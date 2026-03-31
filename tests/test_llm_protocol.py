"""Tests for tagged-CSV LLM protocol parsers."""

import pytest

from remind.llm_protocol import (
    ProtocolParseError,
    parse_consolidation_csv,
    parse_extraction_batch_csv,
    parse_extraction_single_csv,
    parse_triage_csv,
    strip_id_prefix,
)


def test_strip_id_prefix():
    assert strip_id_prefix("ep-abc123") == "abc123"
    assert strip_id_prefix("c-abc123") == "abc123"
    assert strip_id_prefix("NEW_0") == "NEW_0"
    assert strip_id_prefix("abc123") == "abc123"
    assert strip_id_prefix("") == ""
    assert strip_id_prefix("ep-c-nested") == "c-nested"


def test_parse_extraction_single_csv():
    text = """BEGIN EXTRACT_RESULTS
EPISODE,observation,"Found auth issue"
ENTITY,file,auth.py
ENTITY_RELATION,file,auth.py,file,utils.py,imports,0.8,
END EXTRACT_RESULTS"""
    parsed = parse_extraction_single_csv(text)
    assert parsed["type"] == "observation"
    assert parsed["title"] == "Found auth issue"
    assert parsed["entities"][0]["type"] == "file"
    assert parsed["entity_relationships"][0]["relationship"] == "imports"


def test_parse_extraction_batch_csv_strips_ep_prefix():
    """LLM returns ep-prefixed IDs; parser strips them to raw IDs."""
    text = """BEGIN EXTRACT_RESULTS
EPISODE,ep-abc123,decision,"Use Redis"
ENTITY,ep-abc123,tool,Redis
EPISODE,ep-def456,observation,"Bug in auth.py"
ENTITY,ep-def456,file,auth.py
END EXTRACT_RESULTS"""
    parsed = parse_extraction_batch_csv(text)
    assert "abc123" in parsed["results"]
    assert "def456" in parsed["results"]
    assert parsed["results"]["abc123"]["type"] == "decision"
    assert parsed["results"]["def456"]["entities"][0]["name"] == "auth.py"


def test_parse_extraction_batch_csv_unprefixed_ids():
    """Backward compat: raw IDs without prefix still work."""
    text = """BEGIN EXTRACT_RESULTS
EPISODE,ep1,decision,"Use Redis"
ENTITY,ep1,tool,Redis
EPISODE,ep2,observation,"Bug in auth.py"
ENTITY,ep2,file,auth.py
END EXTRACT_RESULTS"""
    parsed = parse_extraction_batch_csv(text)
    assert "ep1" in parsed["results"]
    assert parsed["results"]["ep1"]["type"] == "decision"
    assert parsed["results"]["ep2"]["entities"][0]["name"] == "auth.py"


def test_parse_consolidation_csv_strips_prefixes():
    """LLM returns c-/ep-prefixed IDs; parser strips them to raw IDs."""
    text = """BEGIN CONSOLIDATION_OPS
ANALYSIS,"Observed recurring preference"
UPDATE,c-exist1,"Updated title","Updated summary",0.1,
UPDATE_SOURCE,c-exist1,ep-aaa111
UPDATE_RELATION,c-exist1,implies,c-exist2,0.9,
NEW_CONCEPT,NEW_0,"Python preference","User prefers Python",0.7,,"architecture"
NEW_SOURCE,NEW_0,ep-bbb222
NEW_TAG,NEW_0,python
NEW_RELATION,NEW_0,implies,c-exist1,0.8,
CONTRADICTION,c-exist2,"Episode contradicts old rule",
END CONSOLIDATION_OPS"""
    parsed = parse_consolidation_csv(text)
    assert parsed["analysis"] == "Observed recurring preference"
    update = parsed["updates"][0]
    assert update["concept_id"] == "exist1"
    assert update["source_episodes"] == ["aaa111"]
    assert update["add_relations"][0]["target_id"] == "exist2"
    nc = parsed["new_concepts"][0]
    assert nc["temp_id"] == "NEW_0"
    assert nc["source_episodes"] == ["bbb222"]
    assert parsed["new_relations"][0]["source_id"] == "NEW_0"
    assert parsed["new_relations"][0]["target_id"] == "exist1"
    assert parsed["contradictions"][0]["concept_id"] == "exist2"


def test_parse_consolidation_csv_unprefixed_ids():
    """Backward compat: raw IDs without prefix still work."""
    text = """BEGIN CONSOLIDATION_OPS
ANALYSIS,"Observed recurring preference"
NEW_CONCEPT,NEW_0,"Python preference","User prefers Python",0.7,,"architecture"
NEW_SOURCE,NEW_0,ep1
NEW_TAG,NEW_0,python
NEW_RELATION,NEW_0,implies,c1,0.8,
CONTRADICTION,c1,"Episode contradicts old rule",
END CONSOLIDATION_OPS"""
    parsed = parse_consolidation_csv(text)
    assert parsed["new_concepts"][0]["source_episodes"] == ["ep1"]
    assert parsed["new_relations"][0]["target_id"] == "c1"
    assert parsed["contradictions"][0]["concept_id"] == "c1"


def test_parse_triage_csv():
    text = """BEGIN TRIAGE_RESULTS
DENSITY,0.8,"Dense chunk"
TRIAGE_EPISODE,outcome,"Grep strategy failed on auth search"
TRIAGE_ENTITY,0,function:verify_credentials
TRIAGE_METADATA,0,strategy,grep search
TRIAGE_METADATA,0,result,failure
END TRIAGE_RESULTS"""
    parsed = parse_triage_csv(text)
    assert parsed["density"] == pytest.approx(0.8)
    assert parsed["episodes"][0]["type"] == "outcome"
    assert parsed["episodes"][0]["entities"] == ["function:verify_credentials"]
    assert parsed["episodes"][0]["metadata"]["result"] == "failure"


def test_parse_raises_on_invalid_text():
    with pytest.raises(ProtocolParseError):
        parse_extraction_single_csv("not csv at all")
