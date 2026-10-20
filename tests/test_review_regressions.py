"""Regression cases found while reviewing the 0.14 storage and API contracts."""

from copy import deepcopy
from datetime import datetime

import pytest

from remind.file_store import FileMemoryStore
from remind.interface import MemoryInterface
from remind.models import Concept, Episode, Entity, EntityType, Fact, Relation, RelationType
from remind.operations import record_revision, resolve_id, RevisionConflict
from remind.providers.deterministic import DeterministicEmbedding
from remind.scope import FilteredStore
from remind.store import SQLAlchemyMemoryStore


@pytest.fixture(params=["files", "sqlite"])
def store(request, tmp_path):
    result = (FileMemoryStore(tmp_path / "memory") if request.param == "files"
              else SQLAlchemyMemoryStore(f"sqlite:///{tmp_path / 'memory.db'}"))
    yield result
    result.engine.dispose()


def test_history_filters_all_episode_candidate_channels_before_final_limit(store):
    entity = Entity(id="subject:history", type=EntityType.SUBJECT)
    store.add_entity(entity)
    old = Episode(content="history token", created_at=datetime(2020, 1, 1),
                  embedding=[.8, .6], entity_ids=[entity.id], labels={"scope": ["A"]})
    store.add_episode(old)
    store.add_mention(old.id, entity.id)
    # More ineligible results than the original search budget, with better ranks.
    for index in range(12):
        future = Episode(content="history token " * 10,
                         created_at=datetime(2030, 1, 1), embedding=[1., 0.],
                         entity_ids=[entity.id], labels={"scope": ["A"]})
        store.add_episode(future)
        store.add_mention(future.id, entity.id)
    view = FilteredStore(store, {"scope": "A"}, datetime(2021, 1, 1))
    assert [e.id for e, _ in view.find_episodes_by_embedding([1., 0.], k=1)] == [old.id]
    assert [e.id for e, _ in view.search_episodes_lexical("history token", k=1)] == [old.id]
    assert [e.id for e in view.find_episodes_by_entities([entity.id], limit=1)] == [old.id]
    assert [e.id for e in view.get_episodes_mentioning(entity.id, limit=1)] == [old.id]
    assert view.find_episodes_by_embedding([1., 0.], k=0) == []
    assert view.get_episode(old.id)
    assert len(view.get_episodes_batch([e.id for e in store.get_all_episodes()])) == 1


def test_entity_expansion_cannot_cross_label_boundary(store):
    entity = Entity(id="subject:shared", type=EntityType.SUBJECT)
    store.add_entity(entity)
    for scope in ("A", "B"):
        episode = Episode(content=f"Private {scope}", entity_ids=[entity.id], labels={"scope": [scope]})
        store.add_episode(episode)
        store.add_mention(episode.id, entity.id)
    view = FilteredStore(store, {"scope": "A"})
    assert [e.content for e in view.find_episodes_by_entities([entity.id])] == ["Private A"]


def test_labeled_pattern_keeps_examples_and_removes_out_of_scope_provenance(store):
    allowed = Episode(content="Allowed", entity_ids=[], labels={"scope": ["A"]})
    private = Episode(content="Private", labels={"scope": ["B"]})
    store.add_episode(allowed)
    store.add_episode(private)
    hidden = Concept(summary="Private relation", labels={"scope": ["B"]})
    store.add_concept(hidden)
    pattern = Concept(summary="Retry failures", concept_type="pattern", specifics=["Retry after 1 second"],
                      labels={"scope": ["A"]}, source_episodes=[allowed.id, private.id],
                      relations=[Relation(type=RelationType.IMPLIES, target_id=hidden.id)])
    store.add_concept(pattern)
    result = FilteredStore(store, {"scope": "A"}).get_concept(pattern.id)
    assert result.specifics == pattern.specifics
    assert result.source_episodes == [allowed.id]
    assert not result.relations
    # Cleaning the request view must not modify stored knowledge.
    assert store.get_concept(pattern.id).source_episodes == [allowed.id, private.id]


def test_historical_concept_search_does_not_starve_eligible_results(store):
    old = Concept(summary="history token", created_at=datetime(2020, 1, 1), embedding=[.8, .6])
    store.add_concept(old)
    for _ in range(12):
        store.add_concept(Concept(summary="history token " * 10,
                                  created_at=datetime(2030, 1, 1), embedding=[1., 0.]))
    view = FilteredStore(store, {}, datetime(2021, 1, 1))
    assert [c.id for c, _ in view.find_by_embedding([1., 0.], k=1)] == [old.id]
    assert [c.id for c, _ in view.search_concepts_lexical("history token", k=1)] == [old.id]


def test_historical_fact_cluster_keeps_old_specifics(store):
    cluster = Concept(summary="Cache facts", concept_type="fact_cluster")
    store.add_concept(cluster)
    for year, statement in ((2020, "TTL was 100"), (2030, "TTL is 300")):
        episode = Episode(content=statement, episode_type="fact", created_at=datetime(year, 1, 1),
                          labels={"scope": ["A"]})
        store.add_episode(episode)
        store.add_fact(Fact(statement=statement, cluster_id=cluster.id, source_episode_id=episode.id,
                            valid_from=datetime(year, 1, 1),
                            valid_to=datetime(2030, 1, 1) if year == 2020 else None))
    historical = FilteredStore(store, {"scope": "A"}, datetime(2021, 1, 1)).get_concept(cluster.id)
    assert historical.specifics == ["TTL was 100"]


@pytest.mark.asyncio
async def test_public_historical_recall_excludes_future_observations(store):
    memory = MemoryInterface(DeterministicEmbedding(), store=store, hybrid_keyword_weight=.3)
    for year in (2020, 2030):
        store.add_episode(Episode(content=f"chronology release {year}", created_at=datetime(year, 1, 1)))
    before = store.export_data()
    result = await memory.recall("chronology", as_of="2021-01-01", explain=True)
    assert "2030" not in result.text
    assert "2020" in result.text
    assert store.export_data() == before


@pytest.mark.parametrize("replace", [True, False])
def test_import_rejects_duplicate_input_and_preserves_existing_state(store, replace):
    store.add_episode(Episode(content="Keep me"))
    before = store.export_data()
    invalid = deepcopy(before)
    invalid["records"]["episodes"].append(deepcopy(invalid["records"]["episodes"][0]))
    with pytest.raises(ValueError, match="duplicate"):
        store.import_data(invalid, replace=replace)
    assert store.export_data() == before


@pytest.mark.parametrize("malformation", ["unknown", "not-array", "missing-id", "unknown-field", "dangling"])
def test_import_validation_failure_is_atomic(store, malformation):
    store.add_episode(Episode(content="Keep me"))
    before = store.export_data()
    invalid = deepcopy(before)
    records = invalid["records"]
    if malformation == "unknown":
        records["secrets"] = []
    elif malformation == "not-array":
        records["episodes"] = {}
    elif malformation == "missing-id":
        del records["episodes"][0]["id"]
    elif malformation == "unknown-field":
        records["episodes"][0]["unexpected"] = True
    else:
        records["mentions"].append({"episode_id": "absent", "entity_id": "absent"})
    with pytest.raises(ValueError):
        store.import_data(invalid, replace=True)
    assert store.export_data() == before


def test_import_validation_runs_with_write_transaction_held(store, monkeypatch):
    import remind.serialization as serialization
    original = serialization.validate_records
    observed = []
    def checked(records):
        observed.append(getattr(store._local, "tx_conn", None) is not None)
        return original(records)
    monkeypatch.setattr(serialization, "validate_records", checked)
    store.import_data(store.export_data())
    assert observed and all(observed)


def test_opaque_prefix_resolution_and_missing_revision(store):
    store.add_episode(Episode(id="abcd-1111", content="one"))
    store.add_episode(Episode(id="abcd-2222", content="two"))
    assert resolve_id(store, "ep:abcd-1") == "abcd-1111"
    assert resolve_id(store, "abc") == "abc"
    assert resolve_id(store, "nothing") == "nothing"
    with pytest.raises(ValueError, match="Ambiguous"):
        resolve_id(store, "abcd")
    memory = MemoryInterface(DeterministicEmbedding(), store=store)
    assert memory.update_episode("missing", content="edit") is None
    with pytest.raises(RevisionConflict):
        memory.update_episode("abcd-1111", content="edit")
    assert record_revision(store, "abcd-1111")


@pytest.mark.parametrize("kind", ["episode", "concept", "fact"])
def test_clearing_embedding_removes_stale_vector_index_entry(store, kind):
    # Start with the direct store API, including the first embedded write.
    item = {"episode": Episode(content="Original", embedding=[1., 0.]),
            "concept": Concept(summary="Original", embedding=[1., 0.]),
            "fact": Fact(statement="Original", embedding=[1., 0.])}[kind]
    # SQL callers initialize native index DDL before a transaction on non-SQLite backends.
    store._ensure_vec_dimensions(item.embedding)
    getattr(store, "add_" + kind)(item)
    item.embedding = None
    getattr(store, "update_" + kind)(item)
    if kind == "fact":
        results = store.find_facts_by_embedding([1., 0.])
    else:
        search = store.find_by_embedding if kind == "concept" else store.find_episodes_by_embedding
        results = search([1., 0.])
    assert results == []


def test_first_embedded_write_and_rollback_leave_store_usable(store):
    with pytest.raises(RuntimeError, match="abort"):
        with store.transaction():
            store.add_episode(Episode(content="Rolled back", embedding=[1., 0.]))
            raise RuntimeError("abort")
    assert store._vec_dimensions is None
    assert not store.get_all_episodes()
    # The rollback must not leave Python state claiming rolled-back tables exist.
    with store.transaction():
        episode = Episode(content="Committed", embedding=[1., 0.])
        store.add_episode(episode)
    assert store.find_episodes_by_embedding([1., 0.])[0][0].id == episode.id


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["label", "unlabel"])
async def test_fact_alias_label_edit_requires_source_episode_revision(store, operation):
    from remind.apply import ApplyEngine
    memory = MemoryInterface(DeterministicEmbedding(), store=store)
    captured = await memory.remember("TTL is 100", episode_type="fact", labels={"env": "prod"})
    fact_revision = record_revision(store, captured.fact_id)
    episode_revision = record_revision(store, captured.episode_id)
    memory.update_episode(captured.episode_id, metadata={"reviewed": True}, expected_revision=episode_revision)
    engine = ApplyEngine(store)
    op = {"op": operation, "id": captured.fact_id, "key": "env", "value": "dev"}
    before = store.export_data()
    missing = await engine.apply([op], expected_revisions={captured.fact_id: fact_revision})
    assert not missing.success
    assert missing.errors[0].subject_id == captured.episode_id
    stale = await engine.apply([op], expected_revisions={captured.episode_id: episode_revision})
    assert not stale.success
    assert store.export_data() == before
    current = await engine.apply([op], expected_revisions={
        captured.episode_id: record_revision(store, captured.episode_id)})
    assert current.success, current.to_dict()


def test_expanded_candidate_budget_can_exceed_native_knn_limit(store):
    episode = Episode(content="Eligible", embedding=[1., 0.])
    concept = Concept(summary="Eligible", embedding=[1., 0.])
    store._ensure_vec_dimensions(episode.embedding)
    store.add_episode(episode)
    store.add_concept(concept)
    assert [e.id for e, _ in store.find_episodes_by_embedding([1., 0.], k=3000)] == [episode.id]
    assert [c.id for c, _ in store.find_by_embedding([1., 0.], k=3000)] == [concept.id]
