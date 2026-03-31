"""Tests for tagged-CSV LLM protocol parsers."""

import pytest

from remind.llm_protocol import (
    ProtocolParseError,
    parse_consolidation_csv,
    parse_extraction_batch_csv,
    parse_extraction_single_csv,
    parse_triage_csv,
)


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


def test_parse_extraction_batch_csv():
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


def test_parse_consolidation_csv():
    text = """BEGIN CONSOLIDATION_OPS
ANALYSIS,"Observed recurring preference"
NEW_CONCEPT,NEW_0,"Python preference","User prefers Python",0.7,,"architecture"
NEW_SOURCE,NEW_0,ep1
NEW_TAG,NEW_0,python
NEW_RELATION,NEW_0,implies,c1,0.8,
CONTRADICTION,c1,"Episode contradicts old rule",
END CONSOLIDATION_OPS"""
    parsed = parse_consolidation_csv(text)
    assert parsed["analysis"] == "Observed recurring preference"
    assert len(parsed["new_concepts"]) == 1
    assert parsed["new_concepts"][0]["temp_id"] == "NEW_0"
    assert parsed["new_relations"][0]["type"] == "implies"
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
