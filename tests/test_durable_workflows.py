"""Public workflow regressions for durable memory and concurrent curation."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from remind.apply import ApplyEngine
from remind.file_store import FileMemoryStore
from remind.interface import MemoryInterface
from remind.models import Concept, Episode, Evidence, Relation, RelationType
from remind.operations import RevisionConflict, record_revision
from remind.providers.deterministic import DeterministicEmbedding
from remind.store import SQLAlchemyMemoryStore


@pytest.fixture(params=["files", "sqlite"])
def durable_memory(request, tmp_path):
    store = FileMemoryStore(tmp_path / "memory") if request.param == "files" else SQLAlchemyMemoryStore(f"sqlite:///{tmp_path / 'memory.db'}")
    yield MemoryInterface(DeterministicEmbedding(), store=store, hybrid_keyword_weight=.3)
    store.engine.dispose()


@pytest.mark.asyncio
async def test_capture_roundtrip_fact_evidence_and_deletions(durable_memory, tmp_path):
    m = durable_memory
    captured = await m.remember_batch([
        {"content": "Cache TTL is 300 seconds", "episode_type": "fact", "entities": ["concept:cache"], "labels": {"env": "prod"}},
        {"content": "Retries fixed deployment", "labels": {"env": "prod"}},
    ])
    fact, observation = captured.results
    assert fact.fact_id
    assert m.store.get_episode(fact.episode_id).labels == {"env": ["prod"]}
    concept = Concept(summary="Retry transient errors", source_episodes=[observation.episode_id])
    m.store.add_concept(concept)
    m.store.add_evidence(Evidence(episode_id=observation.episode_id, concept_id=concept.id))
    m.delete_episode(observation.episode_id, expected_revision=record_revision(m.store, observation.episode_id))
    snapshot = m.export_memory()
    restored = SQLAlchemyMemoryStore(f"sqlite:///{tmp_path / 'restored.db'}")
    try:
        restored.import_data(snapshot)
        assert restored.get_fact(fact.fact_id).statement == "Cache TTL is 300 seconds"
        assert restored.get_episode(observation.episode_id, include_deleted=True).deleted_at
        assert len(restored.get_evidence_for_concept(concept.id)) == 1
        assert restored.export_data()["records"] == snapshot["records"]
    finally:
        restored.engine.dispose()


@pytest.mark.asyncio
async def test_failed_capture_has_no_partial_episode_or_event(durable_memory):
    m = durable_memory
    before = m.export_memory()["records"]
    with patch.object(m.store, "emit_event", side_effect=RuntimeError("disk full")):
        with pytest.raises(RuntimeError, match="disk full"):
            await m.remember("Do not partially commit this", embed=False)
    assert m.export_memory()["records"] == before


@pytest.mark.asyncio
async def test_retry_and_revision_conflict(durable_memory):
    m = durable_memory
    first = await m.remember("Retries are safe", idempotency_key="capture-1")
    second = await m.remember("Retries are safe", idempotency_key="capture-1")
    assert first.to_dict() == second.to_dict()
    assert len(m.store.get_all_episodes()) == 1
    with pytest.raises(ValueError, match="different request"):
        await m.remember("Changed request", idempotency_key="capture-1")
    old = record_revision(m.store, first.episode_id)
    m.update_episode(first.episode_id, content="Updated safely", expected_revision=old)
    with pytest.raises(RevisionConflict):
        m.update_episode(first.episode_id, content="Stale overwrite", expected_revision=old)
    assert m.store.get_episode(first.episode_id).content == "Updated safely"


@pytest.mark.asyncio
async def test_curation_and_strict_graph_filter(durable_memory):
    m = durable_memory
    capture = await m.remember("Retry transient deployment failures", labels={"scope": "A"})
    rev = record_revision(m.store, capture.episode_id)
    engine = ApplyEngine(m.store, m.embedding)
    curated = await engine.apply([{"op": "concept", "from": [capture.episode_id],
        "content": "Retry transient deployment failures", "title": "Retry failures"}],
        expected_revisions={capture.episode_id: rev})
    assert curated.success, curated.to_dict()
    assert m.store.get_episode(capture.episode_id).consolidated
    vector = await m.embedding.embed("shared")
    other = Concept(summary="FORBIDDEN unrelated private data", confidence=1, embedding=vector, labels={"scope": ["B"]})
    seed = Concept(summary="shared", confidence=1, embedding=vector, labels={"scope": ["A"]},
                   relations=[Relation(type=RelationType.IMPLIES, target_id=other.id, strength=1)])
    m.store.add_concept(other)
    m.store.add_concept(seed)
    result = await m.recall("shared", labels={"scope": "A"}, explain=True)
    assert "FORBIDDEN" not in result.text
    assert all(c.concept.labels.get("scope") == ["A"] for c in result.concepts)


@pytest.mark.asyncio
async def test_recall_is_read_only_and_unknown_entity_not_created(durable_memory):
    m = durable_memory
    await m.remember("Read-only recall")
    before = m.export_memory(mode="backup")
    await m.recall("Read-only recall")
    await m.recall(entity="person:unknown")
    assert m.export_memory(mode="backup") == before


@pytest.mark.asyncio
async def test_file_restart_external_change_and_cache_rebuild(tmp_path):
    directory = tmp_path / "memory"
    store = FileMemoryStore(directory)
    m = MemoryInterface(DeterministicEmbedding(), store=store)
    item = await m.remember("Durable across restart", episode_type="fact", entities=["concept:durability"])
    store.engine.dispose()
    reopened = FileMemoryStore(directory)
    assert reopened.get_fact(item.fact_id)
    path = next((directory / "episodes").glob("*.json"))
    document = json.loads(path.read_text())
    document["record"]["content"] = "Externally edited memory"
    path.write_text(json.dumps(document))
    assert reopened.get_episode(item.episode_id).content == "Externally edited memory"
    assert reopened.get_episode(item.episode_id).embedding is None
    reopened.engine.dispose()
    import shutil
    shutil.rmtree(tmp_path / "cache")
    rebuilt = FileMemoryStore(directory)
    assert rebuilt.get_fact(item.fact_id)
    rebuilt.engine.dispose()


@pytest.mark.asyncio
async def test_file_migration_and_recovery_refuses_external_edit(tmp_path):
    legacy = tmp_path / "remind.db"
    sql = SQLAlchemyMemoryStore(f"sqlite:///{legacy}")
    ep = Episode(content="Legacy knowledge")
    sql.add_episode(ep)
    sql.engine.dispose()
    store = FileMemoryStore(tmp_path / "memory", legacy_db=legacy)
    assert store.get_episode(ep.id).content == ep.content
    assert (store.runtime / "legacy-backup.db").exists()
    from remind.serialization import revision
    path = next((store.directory / "episodes").glob("*.json"))
    name = path.relative_to(store.directory).as_posix()
    before = path.read_text()
    (store.runtime / "journal.json").write_text(json.dumps({"committed": True, "changes": {
        name: {"before": revision(before), "after": before.replace("Legacy knowledge", "Committed knowledge")}}}))
    store._recover()
    assert "Committed knowledge" in path.read_text()
    (store.runtime / "journal.json").write_text(json.dumps({"committed": True, "changes": {
        name: {"before": revision(before), "after": before}}}))
    path.write_text("external edit")
    with pytest.raises(ValueError, match="external edit"):
        store._recover()
    store.engine.dispose()


@pytest.mark.asyncio
async def test_source_freshness_and_lexical_fallback(tmp_path):
    source = tmp_path / "design.txt"
    source.write_text("Use exponential backoff for retries")
    store = FileMemoryStore(tmp_path / "memory")
    provider = DeterministicEmbedding()
    memory = MemoryInterface(provider, store=store, source_root=tmp_path, hybrid_keyword_weight=.3)
    await memory.remember("Use exponential backoff for retries", entities=["file:design.txt"])
    source.write_text("Use jitter with exponential backoff")
    with patch.object(provider, "embed", side_effect=RuntimeError("model unavailable")):
        recalled = await memory.recall("exponential backoff", explain=True)
    assert "exponential backoff" in recalled.text
    assert any("changed" in warning for warning in recalled.warnings)
    assert recalled.explanation["lexical_only"]
    from remind.doctor import diagnose
    assert any(issue["kind"] == "source_freshness" for issue in diagnose(store, tmp_path)["issues"])
    store.engine.dispose()


def test_event_cursor_detects_external_change(tmp_path):
    store = FileMemoryStore(tmp_path / "memory")
    episode = Episode(content="Original")
    store.add_episode(episode)
    first = store.poll_events()
    path = next((store.directory / "episodes").glob("*.json"))
    value = json.loads(path.read_text())
    value["record"]["content"] = "Edited outside the process"
    path.write_text(json.dumps(value))
    assert store.poll_events(first["next_cursor"])["reset_required"]
    store.engine.dispose()


def test_sparse_labels_filter_before_vector_and_lexical_limits(tmp_path):
    store = SQLAlchemyMemoryStore(f"sqlite:///{tmp_path / 'sparse.db'}")
    for index in range(300):
        store.add_concept(Concept(summary="alpha beta", embedding=[1., 0.], confidence=1))
    wanted = Concept(summary="alpha", embedding=[.5, .866], confidence=1, labels={"scope": ["wanted"]})
    store.add_concept(wanted)
    assert store.find_by_embedding([1., 0.], k=1, labels={"scope": "wanted"})[0][0].id == wanted.id
    assert store.search_concepts_lexical("alpha beta", k=1, labels={"scope": "wanted"})[0][0].id == wanted.id
    page, count = store.page_records("concepts", search="alpha", labels={"scope": "wanted"}, limit=1)
    assert count == 1 and page[0].id == wanted.id
    assert page[0]._revision == record_revision(store, wanted.id)
    store.engine.dispose()


@pytest.mark.asyncio
async def test_bulk_purge_checks_every_revision_before_writing(durable_memory):
    from remind.snapshot import SnapshotEngine
    m = durable_memory
    captured = await m.remember_batch([{"content": "first"}, {"content": "second"}])
    for item in captured.results:
        m.delete_episode(item.episode_id, expected_revision=record_revision(m.store, item.episode_id))
    snapshot = await SnapshotEngine(m.store, m.embedding).snapshot(["deleted"])
    revisions = {e["id"]: e["revision"] for e in snapshot["deleted"]["episodes"]}
    stale = dict(revisions)
    stale[captured.results[-1].episode_id] = "stale"
    with pytest.raises(RevisionConflict):
        m.purge_deleted(stale)
    assert len(m.store.get_deleted_episodes(limit=None)) == 2
    assert m.purge_deleted(revisions) == {"episodes_purged": 2, "concepts_purged": 0}
    assert not m.store.get_deleted_episodes(limit=None)


@pytest.mark.asyncio
async def test_lexical_fallback_never_queries_incompatible_vectors(durable_memory):
    m = durable_memory
    item = await m.remember("ZX915 cache configuration requires a 300 second timeout")
    async def unavailable(_):
        raise RuntimeError("embedding service unavailable")
    with patch.object(m.embedding, "embed", unavailable), \
         patch.object(SQLAlchemyMemoryStore, "find_by_embedding", side_effect=AssertionError("vector search attempted")), \
         patch.object(SQLAlchemyMemoryStore, "find_episodes_by_embedding", side_effect=AssertionError("vector search attempted")), \
         patch.object(SQLAlchemyMemoryStore, "find_entities_by_embedding", side_effect=AssertionError("vector search attempted")):
        result = await m.recall("ZX915 cache configuration", explain=True)
    assert item.episode_id in json.dumps(result.to_dict())
    assert result.explanation["lexical_only"]
    assert any("lexical" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_reembed_a_cold_portable_clone(durable_memory):
    m = durable_memory
    item = await m.remember("Portable knowledge needs newly built vectors", embed=False)
    assert not m.store.get_episode(item.episode_id).embedding
    before = m.export_memory()
    await m.reembed()
    assert m.store.get_episode(item.episode_id).embedding
    assert m.export_memory() == before
