"""Deterministic coverage of maintenance and advanced production behavior."""

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from remind.apply import ApplyEngine
from remind.background import (
    _rpc_call_unix_socket,
    ensure_recall_worker,
    get_consolidation_lock_path,
    get_ingest_lock_path,
    get_ingest_queue_dir,
    is_consolidation_running,
    is_ingest_running,
    request_recall_worker,
    spawn_recall_worker,
)
from remind.config import DecayConfig
from remind.doctor import diagnose, diagnose_directory
from remind.interface import MemoryInterface, RememberResult, create_memory
from remind.models import (
    Concept,
    Conflict,
    Entity,
    EntityType,
    Episode,
    Evidence,
    Fact,
    Relation,
    RelationType,
)
from remind.provenance import capture_sources, freshness
from remind.retrieval import MemoryRetriever
from remind.snapshot import SnapshotEngine


def test_apply_validation_covers_every_advanced_required_field(memory_store, mock_embedding):
    engine = ApplyEngine(memory_store, mock_embedding)
    cases = {
        "concept": "concept requires",
        "label": "label requires",
        "unlabel": "unlabel requires",
        "delete": "delete requires",
        "restore": "restore requires",
        "dismiss": "dismiss requires",
        "processed": "processed requires",
        "entity_relation": "entity_relation requires",
        "evidence": "evidence requires",
        "unlink": "unlink requires",
        "reshape": "reshape requires",
        "merge": "merge requires",
        "split": "split requires",
    }
    for op, message in cases.items():
        errors = engine._validate_ops([{"op": op}])
        assert len(errors) == 1
        assert message in errors[0].message


def test_apply_advanced_graph_and_evidence_operations(memory_store, mock_embedding):
    engine = ApplyEngine(memory_store, mock_embedding)
    ep = Episode(id="ep-source", content="source", entity_ids=["person:alice"])
    left = Concept(
        id="left",
        title="Left",
        summary="left summary",
        confidence=0.6,
        entity_ids=["person:alice"],
        source_episodes=[ep.id],
    )
    right = Concept(
        id="right",
        title="Right",
        summary="right summary",
        confidence=0.9,
        entity_ids=["tool:redis"],
    )
    memory_store.add_episode(ep)
    memory_store.add_concept(left)
    memory_store.add_concept(right)

    relation = engine._execute_op_sync(
        0,
        {
            "op": "entity_relation",
            "source": "person:Alice",
            "target": "person:Bob",
            "relation": "manages",
            "strength": "0.8",
            "context": "work",
        },
        {},
    )
    assert relation.success
    stored_relations = memory_store.get_entity_relations_from("person:alice")
    assert stored_relations[0].target_id == "person:bob"
    assert stored_relations[0].strength == 0.8

    evidence = engine._execute_op_sync(
        1,
        {
            "op": "evidence",
            "concept": left.id,
            "episode": ep.id,
            "t": "supports",
            "strength": "0.75",
            "extra": "quoted support",
        },
        {},
    )
    assert evidence.success and evidence.id
    links = memory_store.get_evidence_for_concept(left.id)
    assert links[0].note == "quoted support"

    unlinked = engine._execute_op_sync(
        2, {"op": "unlink", "concept": left.id, "episode": ep.id}, {}
    )
    assert unlinked.success
    assert memory_store.get_evidence_for_concept(left.id) == []

    reshaped = engine._execute_op_sync(
        3, {"op": "reshape", "id": left.id, "t": "principle"}, {}
    )
    assert reshaped.success
    assert memory_store.get_concept(left.id).concept_type == "principle"
    assert "reshaped from" in memory_store.get_concept(left.id).lineage_note
    missing = engine._op_reshape(4, {"id": "missing", "type": "pattern"}, {}, None)
    assert not missing.success

    merged = engine._execute_op_sync(
        5, {"op": "merge", "from": "left,right,missing", "into": "combined"}, {}
    )
    assert merged.success
    combined = memory_store.get_concept("combined")
    assert combined.confidence == 0.9
    assert set(combined.entity_ids) == {"person:alice", "tool:redis"}
    assert {c.id for c in memory_store.get_deleted_concepts()} >= {"left", "right"}
    no_sources = engine._op_merge(
        6, {"from": ["missing"], "into": "never"}, {}, None
    )
    assert not no_sources.success

    memory_store.restore_concept("left")
    split = engine._execute_op_sync(
        7,
        {"op": "split", "id": "combined", "into": "part-a,part-b", "note": "separate"},
        {},
    )
    assert split.success
    assert memory_store.get_concept("part-a").parent_id == "combined"
    assert memory_store.get_concept("part-b").lineage_note == "separate"
    assert "part-a, part-b" in memory_store.get_concept("combined").lineage_note
    assert not engine._op_split(8, {"id": "missing", "into": ["x"]}, {}, None).success
    assert not engine._op_split(9, {"id": "combined", "into": []}, {}, None).success


def test_apply_updates_links_labels_and_missing_targets(memory_store, mock_embedding):
    engine = ApplyEngine(memory_store, mock_embedding)
    ep = Episode(id="ep", content="old")
    c1 = Concept(id="c1", summary="one")
    c2 = Concept(id="c2", summary="two")
    memory_store.add_episode(ep)
    memory_store.add_concept(c1)
    memory_store.add_concept(c2)

    assert engine._execute_op_sync(
        0, {"op": "update", "id": ep.id, "content": "new", "metadata": {"x": 1}}, {}
    ).success
    assert memory_store.get_episode(ep.id).embedding is None
    assert engine._execute_op_sync(
        1, {"op": "update", "id": c1.id, "title": "One", "summary": "changed"}, {}
    ).success
    assert not engine._op_update(2, {"id": "missing"}, {}, None).success

    assert engine._execute_op_sync(
        3, {"op": "link", "from": c1.id, "to": c2.id, "type": "not-a-type"}, {}
    ).success
    assert memory_store.get_concept(c1.id).relations[0].target_id == c2.id

    assert engine._execute_op_sync(
        4, {"op": "label", "id": c1.id, "key": "topic", "value": "testing"}, {}
    ).success
    assert engine._execute_op_sync(
        5, {"op": "unlabel", "id": c1.id, "key": "topic", "value": "testing"}, {}
    ).success
    assert not engine._op_label(
        6, {"id": "missing", "key": "x", "value": "y"}, {}, None
    ).success
    assert not engine._op_unlabel(7, {"id": "missing", "key": "x"}, {}, None).success

    assert not engine._op_delete(8, {"id": "missing"}, {}, None).success
    assert engine._op_delete(9, {"id": c2.id}, {}, None).success
    assert engine._op_restore(10, {"id": c2.id}, {}, None).success
    assert not engine._op_restore(11, {"id": "missing"}, {}, None).success


@pytest.mark.asyncio
async def test_interface_embedding_maintenance_and_dimension_guard(
    memory_store, mock_embedding, monkeypatch
):
    memory = MemoryInterface(mock_embedding, store=memory_store)
    ep = Episode(id="ep", content="episode", embedding=None)
    concept = Concept(id="concept", summary="concept", embedding=None)
    entity = Entity(
        id="tool:redis", type=EntityType.TOOL, display_name="Redis", embedding=None
    )
    fact = Fact(id="fact", statement="fact", embedding=None)
    memory_store.add_episode(ep)
    memory_store.add_concept(concept)
    memory_store.add_entity(entity)
    memory_store.add_fact(fact)

    assert await memory.embed_episodes(batch_size=1) == 1
    monkeypatch.setattr(memory_store, "get_recent_episodes", lambda limit: [])
    assert await memory.embed_episodes() == 0

    plan = await memory.get_reembed_plan()
    assert plan["episodes"] == plan["concepts"] == plan["entities"] == plan["facts"] == 1
    assert plan["target_dimensions"] == mock_embedding.dimensions
    result = await memory.reembed(batch_size=1)
    assert result["episodes_embedded"] == 1
    assert result["concepts_embedded"] == 1
    assert result["entities_embedded"] == 1
    assert result["facts_embedded"] == 1
    assert json.loads(memory_store.get_metadata("embedding_fingerprint"))["dimensions"] == 128

    with pytest.raises(ValueError, match="Select at least one"):
        await memory.get_reembed_plan(False, False, False, False)
    memory_store.set_metadata("embedding_dimensions", "3")
    with pytest.raises(ValueError, match="mixed dimensions"):
        await memory.reembed(
            include_episodes=True,
            include_concepts=False,
            include_entities=False,
            include_facts=False,
        )


@pytest.mark.asyncio
async def test_interface_embed_failure_budget_decay_and_labels(
    memory_store, mock_embedding, monkeypatch
):
    memory = MemoryInterface(
        mock_embedding,
        store=memory_store,
        decay_config=DecayConfig(enabled=True, decay_interval=2, decay_rate=0.1),
    )
    memory_store.add_episode(Episode(id="ep", content="unembedded"))

    async def fail(_texts):
        raise RuntimeError("provider down")

    monkeypatch.setattr(mock_embedding, "embed_batch", fail)
    assert await memory.embed_episodes() == 0

    memory._increment_recall_count()
    assert memory_store.get_metadata("recall_count") == "1"
    decay = MagicMock(return_value=2)
    monkeypatch.setattr(memory_store, "decay_concepts", decay)
    memory._maybe_decay([])
    decay.assert_not_called()
    memory._increment_recall_count()
    memory._maybe_decay([])
    decay.assert_called_once()

    concepts = [
        SimpleNamespace(activation=0.2),
        SimpleNamespace(activation=0.1),
    ]
    episodes = [SimpleNamespace(score=0.15)]
    monkeypatch.setattr(
        memory.retriever,
        "format_for_llm",
        lambda activated, direct_episodes, as_of: "x"
        * (10 * (len(activated) + len(direct_episodes))),
    )
    assert len(memory._format_with_char_budget(concepts, episodes, None, 10)) <= 10

    concept = Concept(id="c", summary="labels")
    memory_store.add_concept(concept)
    assert memory.add_label("concept", "c", "topic", "one")
    assert memory.add_label("concept", "c", "topic", "one")
    assert memory.get_labels("concept", "c") == {"topic": ["one"]}
    assert memory.remove_label("concept", "c", "topic", "missing")
    assert memory.remove_label("concept", "c", "topic")
    assert not memory.remove_label("concept", "c", "topic")
    assert not memory.add_label("episode", "missing", "x", "y")


@pytest.mark.asyncio
async def test_snapshot_operational_scopes_and_query_errors(
    memory_store, mock_embedding, monkeypatch
):
    engine = SnapshotEngine(memory_store, mock_embedding)
    decision = Episode(
        id="decision", content="ship", episode_type="decision", labels={"project": ["r"]}
    )
    question = Episode(id="question", content="when?", episode_type="question")
    entity = Entity(id="tool:redis", type=EntityType.TOOL, display_name="Redis")
    concept = Concept(
        id="orphan",
        summary="orphan",
        concept_type="pattern",
        decay_factor=0.2,
        labels={"project": ["r"]},
    )
    memory_store.add_episode(decision)
    memory_store.add_episode(question)
    memory_store.add_entity(entity)
    memory_store.add_concept(concept)
    memory_store.add_mention(decision.id, entity.id)

    result = await engine.snapshot(
        [
            "concepts:1",
            "episodes:1",
            "entities:tool",
            "decisions:1",
            "questions:1",
            "health",
            "deleted",
        ]
    )
    assert result["concepts"]["count"] == 1
    assert result["episodes"]["count"] == 1
    assert result["entities"]["entities"][0]["id"] == entity.id
    assert result["decisions"]["episodes"][0]["type"] == "decision"
    assert result["questions"]["episodes"][0]["type"] == "question"
    assert result["health"]["healthy"] is False
    assert result["health"]["stale_concepts"] == 1
    assert result["health"]["label_distribution"]["(unlabeled)"] == 1

    no_embedding = SnapshotEngine(memory_store, None)
    assert "No embedding" in (await no_embedding.snapshot(["query:x"]))["query"]["error"]

    async def fail(_text):
        raise RuntimeError("offline")

    monkeypatch.setattr(mock_embedding, "embed", fail)
    assert "offline" in (await engine.snapshot(["query:x"]))["query"]["error"]


def test_provenance_capture_and_freshness(tmp_path, monkeypatch):
    source = tmp_path / "source.py"
    source.write_text("original")
    monkeypatch.setattr(
        "remind.provenance.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout="abc123\n"),
    )
    refs = capture_sources(
        tmp_path,
        ["person:alice", "file:source.py", "file:missing.py", "file:../outside.py"],
    )
    assert refs == [
        {
            "path": "source.py",
            "commit": "abc123",
            "sha256": refs[0]["sha256"],
        }
    ]
    assert freshness(None, refs)[0]["status"] == "unverifiable"
    assert freshness(tmp_path, refs)[0]["status"] == "unchanged"
    source.write_text("changed")
    assert freshness(tmp_path, refs)[0]["status"] == "changed"
    source.unlink()
    assert freshness(tmp_path, refs)[0]["status"] == "missing"
    assert capture_sources(tmp_path, ["person:alice"]) == []


def test_doctor_reports_embeddings_freshness_and_fingerprint(
    memory_store, mock_embedding, tmp_path, monkeypatch
):
    source = tmp_path / "source.py"
    source.write_text("new")
    ep = Episode(
        id="ep",
        content="record",
        metadata={
            "source_refs": [
                {"path": "source.py", "sha256": "wrong", "commit": None}
            ]
        },
    )
    memory_store.add_episode(ep)
    memory_store.set_metadata("embedding_fingerprint", "{}")
    report = diagnose(memory_store, source_root=tmp_path, embedding=mock_embedding)
    kinds = {issue["kind"] for issue in report["issues"]}
    assert {"missing_embeddings", "source_freshness", "incompatible_embeddings"} <= kinds
    assert report["ok"] is True

    assert diagnose_directory(tmp_path / "absent") == {"ok": True, "issues": []}
    monkeypatch.setattr(
        "remind.file_store.FileMemoryStore._read",
        lambda self, files: (_ for _ in ()).throw(ValueError("bad record")),
    )
    invalid = diagnose_directory(tmp_path)
    assert invalid["ok"] is False
    assert invalid["issues"][0]["kind"] == "invalid_record"

    monkeypatch.setattr(memory_store, "export_data", MagicMock(side_effect=ValueError("broken")))
    assert diagnose(memory_store)["issues"][0]["kind"] == "integrity"


def test_background_paths_locks_rpc_and_worker_lifecycle(tmp_path, monkeypatch):
    assert "consolidation" in get_consolidation_lock_path("db", tmp_path).name
    assert "ingest" in get_ingest_lock_path("db", tmp_path).name
    assert "ingest-queue" in get_ingest_queue_dir("db", tmp_path).name
    assert not is_consolidation_running("db", tmp_path)
    assert not is_ingest_running("db", tmp_path)

    sock = MagicMock()
    sock.recv.side_effect = [b'{"ok": true,', b'"pong": true}\n']
    monkeypatch.setattr("remind.background.socket.socket", lambda *args: sock)
    assert _rpc_call_unix_socket(tmp_path / "worker.sock", {"action": "ping"}, 1) == {
        "ok": True,
        "pong": True,
    }
    sock.close.assert_called_once()

    empty_sock = MagicMock()
    empty_sock.recv.return_value = b""
    monkeypatch.setattr("remind.background.socket.socket", lambda *args: empty_sock)
    assert _rpc_call_unix_socket(tmp_path / "worker.sock", {}, 1) is None

    popen = MagicMock()
    monkeypatch.setattr("remind.background.subprocess.Popen", popen)
    monkeypatch.setattr("remind.background.is_recall_running", lambda *args, **kwargs: False)
    stale = tmp_path / "sockets" / "recall.sock"
    monkeypatch.setattr("remind.background.get_recall_socket_path", lambda *args, **kwargs: stale)
    stale.parent.mkdir()
    stale.write_text("stale")
    monkeypatch.setattr("remind.background._ping_recall_socket", lambda path: False)
    assert spawn_recall_worker("db", "deterministic", "key", 1, tmp_path)
    assert not stale.exists()
    command = popen.call_args.args[0]
    assert "--recall-idle-seconds" in command
    assert command[command.index("--recall-idle-seconds") + 1] == "5"
    assert "--remind-dir" in command

    monkeypatch.setattr("remind.background._ping_recall_socket", lambda path: True)
    assert ensure_recall_worker("db", "deterministic", "key", 5, tmp_path) == stale

    response_sock = MagicMock()
    response_sock.recv.return_value = b'{"ok": true}\n'
    monkeypatch.setattr("remind.background.socket.socket", lambda *args: response_sock)
    response = request_recall_worker(
        stale,
        query="cache",
        k=3,
        episode_k=2,
        context="ctx",
        entity="tool:redis",
        labels={"topic": "cache"},
        raw=True,
        max_chars=100,
        min_score=0.2,
        timeout_ms=50,
    )
    assert response == {"ok": True}
    payload = json.loads(response_sock.sendall.call_args.args[0])
    assert payload["action"] == "recall"
    assert payload["labels"] == {"topic": "cache"}


@pytest.mark.asyncio
async def test_retrieve_all_exercises_hybrid_entity_graph_and_reranking(
    memory_store, mock_embedding, monkeypatch
):
    ep = Episode(
        id="ep-cache",
        content="Redis cache policy",
        episode_type="decision",
        entity_ids=["tool:redis"],
        embedding=[1.0] + [0.0] * 127,
    )
    entity = Entity(
        id="tool:redis",
        type=EntityType.TOOL,
        display_name="Redis",
        embedding=[1.0] + [0.0] * 127,
    )
    related = Concept(
        id="related",
        title="Related",
        summary="related cache behavior",
        confidence=0.8,
        embedding=[0.8, 0.2] + [0.0] * 126,
    )
    primary = Concept(
        id="primary",
        title="Redis policy",
        summary="Redis cache policy",
        confidence=0.95,
        source_episodes=[ep.id],
        entity_ids=[entity.id],
        embedding=[1.0] + [0.0] * 127,
        relations=[
            Relation(
                type=RelationType.IMPLIES,
                target_id=related.id,
                strength=1.0,
            )
        ],
    )
    memory_store.add_episode(ep)
    memory_store.add_entity(entity)
    memory_store.add_mention(ep.id, entity.id)
    memory_store.add_concept(primary)
    memory_store.add_concept(related)
    monkeypatch.setattr(
        memory_store,
        "find_by_embedding",
        lambda embedding, k, labels=None: [(primary, 0.95)],
    )
    monkeypatch.setattr(
        memory_store,
        "search_concepts_lexical",
        lambda query, k, labels=None: [(primary, 1.0)],
    )
    for link_type, strength in [
        ("supports", 0.8),
        ("contradicts", 0.1),
        ("exemplifies", 0.4),
        ("qualifies", 0.3),
        ("supersedes", 0.1),
    ]:
        memory_store.add_evidence(
            Evidence(
                episode_id=ep.id,
                concept_id=primary.id,
                link_type=link_type,
                strength=strength,
            )
        )

    mock_embedding.set_embedding("Redis cache", [1.0] + [0.0] * 127)
    reranker = MagicMock()
    reranker.score.side_effect = lambda query, docs: [0.9 - i * 0.1 for i in range(len(docs))]
    retriever = MemoryRetriever(
        embedding=mock_embedding,
        store=memory_store,
        initial_k=5,
        spread_hops=2,
        spread_decay=0.8,
        activation_threshold=0.01,
        hybrid_keyword_weight=0.5,
        lexical_enabled=True,
        reranker=reranker,
    )
    concepts, episodes = await retriever.retrieve_all(
        "Redis cache",
        k=5,
        episode_k=5,
        min_activation=0.01,
        context="production",
        labels=None,
    )
    assert {item.concept.id for item in concepts} >= {"primary", "related"}
    assert episodes and episodes[0].episode.id == ep.id
    assert reranker.score.call_count == 1
    assert retriever._last_trace["vector"]
    assert retriever._last_trace["graph_edges"][0]["to"] == related.id
    assert retriever._last_matched_entities[0].id == entity.id

    direct = await retriever.retrieve_episodes_by_embedding(
        "Redis cache", k=3, query_embedding=[1.0] + [0.0] * 127
    )
    assert direct[0].episode.id == ep.id
    assert retriever._compute_evidence_weight(primary.id) > 1.0
    assert retriever._compute_evidence_weight("missing") == 1.0


@pytest.mark.asyncio
async def test_retrieve_all_lexical_fallback_and_entity_name_edge_cases(
    memory_store, mock_embedding, monkeypatch
):
    ep = Episode(
        id="ep",
        content="unique lexical needle",
        entity_ids=["tool:needle"],
        embedding=[1.0] + [0.0] * 127,
    )
    entity = Entity(id="tool:needle", type=EntityType.TOOL, display_name="Needle")
    concept = Concept(
        id="concept",
        title="Needle",
        summary="unique lexical needle",
        source_episodes=[ep.id],
        embedding=[1.0] + [0.0] * 127,
    )
    memory_store.add_episode(ep)
    memory_store.add_entity(entity)
    memory_store.add_mention(ep.id, entity.id)
    memory_store.add_concept(concept)
    memory_store.set_metadata("embedding_fingerprint", "obsolete")

    retriever = MemoryRetriever(
        embedding=mock_embedding,
        store=memory_store,
        activation_threshold=0.001,
        hybrid_keyword_weight=0.0,
        lexical_enabled=True,
    )
    concepts, episodes = await retriever.retrieve_all(
        "unique lexical needle", k=3, episode_k=3, min_activation=0.0
    )
    assert retriever._last_trace["lexical_only"] is True
    assert concepts[0].concept.id == concept.id
    assert episodes[0].episode.id == ep.id

    assert retriever._entity_name_matches("a to")[0] == []
    monkeypatch.setattr(memory_store, "search_entities_by_words", lambda words, limit: [])
    assert retriever._entity_name_matches("needle tool") == ([], [])
    monkeypatch.setattr(
        memory_store,
        "search_entities_by_words",
        lambda words, limit: [(entity, 1)],
    )
    monkeypatch.setattr(memory_store, "get_episodes_mentioning", lambda *args, **kwargs: [])
    assert retriever._entity_name_matches("needle tool") == ([], [entity])


def test_interface_updates_concept_episode_and_purges_deleted(
    memory_store, mock_embedding
):
    memory = MemoryInterface(mock_embedding, store=memory_store)
    ep = Episode(id="ep-update", content="old", embedding=[1.0])
    concept = Concept(id="concept-update", summary="old", embedding=[1.0])
    memory_store.add_episode(ep)
    memory_store.add_concept(concept)

    from remind.operations import record_revision

    updated_ep = memory.update_episode(
        ep.id,
        content="new",
        metadata={"source": "test"},
        labels={"topic": "coverage"},
        episode_type="decision",
        entities=["person:Alice"],
        expected_revision=record_revision(memory_store, ep.id),
    )
    assert updated_ep.content == "new"
    assert updated_ep.embedding is None
    assert updated_ep.entity_ids == ["person:alice"]
    assert memory.update_episode(
        "missing", expected_revision=record_revision(memory_store, "missing")
    ) is None

    updated_concept = memory.update_concept(
        concept.id,
        summary="new",
        title="Title",
        confidence=2,
        tags=["tag"],
        relations=[
            {"type": "implies", "target_id": "other", "strength": "0.7"},
            {"type": "invalid", "target_id": "fallback"},
        ],
        labels={"topic": ["coverage"]},
        conditions="always",
        exceptions=["never"],
        expected_revision=record_revision(memory_store, concept.id),
    )
    assert updated_concept.confidence == 1.0
    assert updated_concept.relations[1].type == RelationType.RELATED_TO
    assert updated_concept.embedding is None
    assert memory.update_concept(
        "missing", expected_revision=record_revision(memory_store, "missing")
    ) is None

    assert memory.delete_episode(
        ep.id, expected_revision=record_revision(memory_store, ep.id)
    )
    assert memory.delete_concept(
        concept.id, expected_revision=record_revision(memory_store, concept.id)
    )
    revisions = {
        item.id: record_revision(memory_store, item.id)
        for item in [*memory.get_deleted_episodes(), *memory.get_deleted_concepts()]
    }
    assert memory.purge_deleted(revisions) == {
        "episodes_purged": 1,
        "concepts_purged": 1,
    }


def test_remember_result_round_trip_and_status_helpers():
    fact = Fact(id="collision", statement="old")
    result = RememberResult(
        episode_id="episode",
        fact_id="fact",
        cluster_id="cluster",
        cluster_created=True,
        collisions=[fact],
        related_facts=[fact],
        entity_resolutions=["Person: Alice -> person:alice"],
        nearby_episodes=[(Episode(id="near", content="nearby"), 0.8)],
        nearby_concepts=[(Concept(id="near-concept", summary="nearby"), 0.7)],
    )
    restored = RememberResult.from_dict(result.to_dict())
    assert restored.has_collisions() is True
    assert restored.has_related() is True
    assert restored.has_entity_resolutions() is True
    assert restored.has_nearby() is True
    assert restored.collisions[0].id == "collision"


def test_create_memory_resolves_configuration_and_rejects_invalid_inputs(
    tmp_path, monkeypatch
):
    import remind.config as config_module
    import remind.interface as interface_module

    config = config_module.RemindConfig()
    config.embedding_provider = "deterministic"
    config.logging_enabled = True
    monkeypatch.setattr(config_module, "load_config", lambda project_dir=None: config)
    resolved = []
    monkeypatch.setattr(
        config_module,
        "resolve_db_url",
        lambda value, **kwargs: resolved.append((value, kwargs)) or f"resolved:{value}",
    )
    monkeypatch.setattr(config_module, "_is_db_url", lambda value: value.startswith("sqlite:"))
    logging_calls = []
    monkeypatch.setattr(
        interface_module,
        "setup_file_logging",
        lambda db_url, project_dir=None: logging_calls.append((db_url, project_dir)),
    )
    constructed = []

    def fake_interface(**kwargs):
        constructed.append(kwargs)
        return kwargs

    monkeypatch.setattr(interface_module, "MemoryInterface", fake_interface)

    with pytest.raises(ValueError, match="legacy database selector"):
        create_memory(store_url="one", db_url="two")
    with pytest.raises(ValueError, match="Unknown embedding provider"):
        create_memory(embedding_provider="unknown", db_url="sqlite:///memory.db")

    explicit = create_memory(
        db_url="sqlite:///memory.db",
        project_dir=tmp_path,
        hybrid_keyword_weight="0.7",
        source_root=tmp_path,
    )
    assert explicit["db_url"] == "sqlite:///memory.db"
    assert explicit["hybrid_keyword_weight"] == 0.7
    assert explicit["source_root"] == tmp_path
    assert logging_calls[-1] == ("sqlite:///memory.db", tmp_path)

    config.db_url = "sqlite:///configured.db"
    assert create_memory()["db_url"] == config.db_url
    config.db_url = None
    assert create_memory(db_path=None)["db_url"] == "resolved:None"
    assert create_memory(db_path="sqlite:///direct.db")["db_url"] == "sqlite:///direct.db"
    absolute = str(tmp_path / "absolute.db")
    assert create_memory(db_path=absolute)["db_url"] == f"resolved:{absolute}"
    assert create_memory(db_path="named.db")["db_url"] == "resolved:named.db"
    assert constructed


def test_background_lock_contention_and_startup_polling(tmp_path, monkeypatch):
    from filelock import FileLock

    consolidation = get_consolidation_lock_path("db", tmp_path)
    ingest = get_ingest_lock_path("db", tmp_path)
    consolidation.parent.mkdir(parents=True, exist_ok=True)
    first = FileLock(str(consolidation))
    second = FileLock(str(ingest))
    first.acquire()
    second.acquire()
    try:
        assert is_consolidation_running("db", tmp_path)
        assert is_ingest_running("db", tmp_path)
    finally:
        first.release()
        second.release()

    socket_path = tmp_path / "worker.sock"
    pings = iter([False, False, True])
    monkeypatch.setattr(
        "remind.background._ping_recall_socket", lambda path: next(pings)
    )
    monkeypatch.setattr("remind.background.spawn_recall_worker", lambda **kwargs: True)
    monkeypatch.setattr("remind.background.get_recall_socket_path", lambda *a, **k: socket_path)
    monkeypatch.setattr("remind.background.time.sleep", lambda seconds: None)
    assert (
        ensure_recall_worker(
            "db", "deterministic", "key", 5, tmp_path, startup_timeout_seconds=1
        )
        == socket_path
    )

    monkeypatch.setattr("remind.background._ping_recall_socket", lambda path: False)
    monkeypatch.setattr("remind.background.spawn_recall_worker", lambda **kwargs: False)
    monkeypatch.setattr("remind.background.is_recall_running", lambda *a, **k: False)
    assert ensure_recall_worker("db", "deterministic", "key", 5, tmp_path) is None


def test_retrieval_formats_matched_entity_episode_groups(memory_store, mock_embedding):
    entity = Entity(id="tool:redis", type=EntityType.TOOL, display_name="Redis")
    memory_store.add_entity(entity)
    for index, episode_type in enumerate(
        ["fact", "decision", "question", "preference", "observation", "outcome", "meta"]
    ):
        episode = Episode(
            id=f"ep-{index}",
            content=f"{episode_type} content",
            episode_type=episode_type,
            entity_ids=[entity.id],
        )
        memory_store.add_episode(episode)
        memory_store.add_mention(episode.id, entity.id)
    retriever = MemoryRetriever(mock_embedding, memory_store)
    rendered = retriever.format_for_llm([], matched_entities=[entity])
    assert "MATCHED ENTITIES" in rendered
    assert "[tool:redis] Redis" in rendered
    assert "[DECISIONS]" in rendered


@pytest.mark.asyncio
async def test_snapshot_query_success(memory_store, mock_embedding):
    concept = Concept(
        id="query-concept",
        title="Query result",
        summary="semantic result",
        embedding=[1.0] + [0.0] * 127,
    )
    memory_store.add_concept(concept)
    mock_embedding.set_embedding("semantic", [1.0] + [0.0] * 127)
    result = await SnapshotEngine(memory_store, mock_embedding).snapshot(["query:semantic"])
    assert result["query"]["query"] == "semantic"
    assert result["query"]["concepts"][0]["id"] == concept.id
