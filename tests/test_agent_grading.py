"""Grader regressions: content support, structural history, and provenance."""

from copy import deepcopy
from datetime import datetime

import pytest

from remind.evals import dataset, grade_agent_state
from remind.models import Concept, Episode, Evidence, Fact
from remind.store import SQLAlchemyMemoryStore


@pytest.fixture
def fixture_state(tmp_path):
    store = SQLAlchemyMemoryStore(f"sqlite:///{tmp_path / 'grade.db'}")
    family = dataset()["families"][0]
    source = "fixture:" + family["id"]
    episode = Episode(content=family["decision"] + ". " + family["outcome"],
                      episode_type="outcome", consolidated=True, source_ref=source)
    store.add_episode(episode)
    concept = Concept(summary=family["decision"], concept_type="pattern", source_episodes=[episode.id])
    store.add_concept(concept)
    evidence = Evidence(concept_id=concept.id, episode_id=episode.id)
    store.add_evidence(evidence)
    old = Fact(statement=family["old"], source_ref=source)
    new = Fact(statement=family["current"], source_ref=source)
    store.add_fact(old)
    store.add_fact(new)
    store.supersede_fact(old.id, new.id)
    sessions = [{"answer": family["current"] + ". " + family["decision"],
                 "transcript": [{"type": "tool_call", "name": "recall"}]}]
    yield store, family, sessions, old, new, episode, evidence
    store.engine.dispose()


def grade(state, **kwargs):
    store, family, sessions, *_ = state
    return grade_agent_state(store, family, "correction_recall", sessions,
                             kwargs.pop("before_final", store.export_data()["records"]), **kwargs)


def test_single_episode_can_supply_both_supported_assertions(fixture_state):
    result = grade(fixture_state)
    assert result["passed"], result
    assert result["checks"]["supported_pattern"]
    assert result["diagnostics"]["support_source_counts"] == [1]
    assert not result["diagnostics"]["capture_granularity"]


def test_old_value_in_history_comment_is_not_a_hard_violation(fixture_state):
    store, family, _, old, new, *_ = fixture_state
    new.statement += ". The service's earlier SQLite claim was corrected."
    store.update_fact(new)
    result = grade(fixture_state)
    assert result["passed"], result
    assert not result["hard_violations"]
    assert result["review_flags"]


def test_original_old_fact_still_active_is_a_real_violation(fixture_state):
    store, family, _, old, *_ = fixture_state
    old.valid_to, old.superseded_by = None, None
    store.update_fact(old)
    initial = [{"id": old.id, "statement": old.statement}]
    result = grade(fixture_state, initial_facts=initial)
    assert not result["passed"]
    assert "Obsolete fact remains active" in result["hard_violations"]
    assert not result["checks"]["history"]


def test_history_link_must_reach_current_fact(fixture_state):
    store, family, _, old, *_ = fixture_state
    unrelated = Fact(statement="Another historical assertion", valid_to=datetime.now())
    store.add_fact(unrelated)
    old.superseded_by = unrelated.id
    store.update_fact(old)
    assert not grade(fixture_state)["checks"]["history"]


def test_description_of_supersession_does_not_create_history(fixture_state):
    store, family, _, old, new, *_ = fixture_state
    old.valid_to, old.superseded_by = None, None
    store.update_fact(old)
    new.statement += ". The earlier claim is retained as superseded history."
    store.update_fact(new)
    assert not grade(fixture_state)["checks"]["history"]


def test_source_episode_without_evidence_link_is_not_supported(fixture_state):
    store, *_, evidence = fixture_state
    store.delete_evidence(evidence.id)
    assert not grade(fixture_state)["checks"]["supported_pattern"]


def test_speaker_field_does_not_substitute_for_source_permalink(fixture_state):
    store, family, _, _, new, *_ = fixture_state
    new.source_ref = None
    new.asserted_by = "fixture:" + family["id"]
    store.update_fact(new)
    assert not grade(fixture_state)["checks"]["source_provenance"]


def test_read_only_change_still_fails(fixture_state):
    before = deepcopy(fixture_state[0].export_data()["records"])
    fixture_state[0].add_episode(Episode(content="Unexpected write"))
    result = grade(fixture_state, before_final=before)
    assert not result["checks"]["read_only"]
    assert "Final read-only session changed durable memory" in result["hard_violations"]


@pytest.mark.asyncio
async def test_live_tool_descriptions_explain_types_and_revisions():
    from remind.mcp_server import create_mcp_server
    tools=await create_mcp_server().get_tools()
    assert 'no automatic type inference' in tools['remember'].description
    assert 'fact_id/cluster_id' in tools['remember_batch'].description
    assert 'expected_revisions' in tools['apply'].description
    assert 'no structural effect' in tools['apply'].description
    assert 'There is no episode:<id> scope' in tools['snapshot'].description


def test_use_and_uses_do_not_change_evidence_support(fixture_state):
    store, family, _, _, _, episode, _ = fixture_state
    episode.content='The service uses PostgreSQL and chooses it for concurrent writers. '+family['outcome']
    store.update_episode(episode)
    result=grade(fixture_state)
    assert result['checks']['supported_pattern'],result
    assert result['grading_version']==3


@pytest.mark.parametrize('wording',['Production and staging configuration should remain separate.',
                                     'Production and staging configuration should be kept separate.'])
def test_supported_policy_paraphrase_is_not_flagged_as_invented(wording):
    from remind.evals import covers
    assert covers(wording,'Keep production and staging configuration separate')
    assert not covers('Delete backups','Keep backups')
