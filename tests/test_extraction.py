"""Tests for entity and type extraction."""

import pytest
import json

from remind.extraction import (
    EntityExtractor,
    extract_for_remember,
    try_fix_json,
    MAX_CONTENT_LENGTH,
)
from remind.models import EpisodeType, EntityType, Episode, Entity, ExtractionResult


class TestTryFixJson:
    """Tests for the JSON recovery utility."""

    def test_valid_json_returns_as_is(self):
        """Valid JSON should be returned unchanged."""
        data = {"type": "observation", "entities": []}
        result = try_fix_json(json.dumps(data))
        assert result == data

    def test_removes_markdown_code_blocks(self):
        """Should strip ```json code blocks."""
        json_str = '```json\n{"type": "decision"}\n```'
        result = try_fix_json(json_str)
        assert result == {"type": "decision"}

    def test_removes_markdown_code_blocks_no_lang(self):
        """Should strip ``` code blocks without language."""
        json_str = '```\n{"type": "question"}\n```'
        result = try_fix_json(json_str)
        assert result == {"type": "question"}

    def test_extracts_json_from_text(self):
        """Should extract JSON object from surrounding text."""
        text = 'Here is the result: {"type": "question"} Done.'
        result = try_fix_json(text)
        assert result == {"type": "question"}

    def test_fixes_truncated_json_missing_brace(self):
        """Should attempt to close unclosed braces."""
        truncated = '{"type": "observation", "entities": []'
        result = try_fix_json(truncated)
        assert result is not None
        assert result["type"] == "observation"

    def test_fixes_truncated_json_missing_bracket(self):
        """Should attempt to close unclosed brackets."""
        truncated = '{"type": "observation", "entities": ['
        result = try_fix_json(truncated)
        assert result is not None
        assert result["type"] == "observation"

    def test_extracts_type_and_entities_as_last_resort(self):
        """Should extract type/entities from malformed JSON."""
        malformed = '"type": "decision", "entities": []'
        result = try_fix_json(malformed)
        assert result is not None
        assert result["type"] == "decision"

    def test_returns_none_for_completely_invalid(self):
        """Should return None when recovery impossible."""
        result = try_fix_json("this is not json at all without any braces")
        assert result is None


class TestEntityExtractor:
    """Tests for EntityExtractor class."""

    @pytest.mark.asyncio
    async def test_extract_observation(self, mock_llm, memory_store):
        """Test extracting observation type."""
        mock_llm.set_complete_json_response({
            "type": "observation",
            "entities": [
                {"type": "file", "id": "file:auth.py", "name": "auth.py"}
            ]
        })

        extractor = EntityExtractor(mock_llm, memory_store)
        result = await extractor.extract("Found a bug in auth.py")

        assert result.episode_type == "observation"
        assert len(result.entities) == 1
        assert result.entities[0].id == "file:auth.py"

    @pytest.mark.asyncio
    async def test_extract_decision(self, mock_llm, memory_store):
        """Test extracting decision type."""
        mock_llm.set_complete_json_response({
            "type": "decision",
            "entities": []
        })

        extractor = EntityExtractor(mock_llm, memory_store)
        result = await extractor.extract("Decided to use FastAPI")

        assert result.episode_type == "decision"

    @pytest.mark.asyncio
    async def test_extract_question(self, mock_llm, memory_store):
        """Test extracting question type."""
        mock_llm.set_complete_json_response({
            "type": "question",
            "entities": []
        })

        extractor = EntityExtractor(mock_llm, memory_store)
        result = await extractor.extract("Should we use Redis?")

        assert result.episode_type == "question"

    @pytest.mark.asyncio
    async def test_extract_preference(self, mock_llm, memory_store):
        """Test extracting preference type."""
        mock_llm.set_complete_json_response({
            "type": "preference",
            "entities": []
        })

        extractor = EntityExtractor(mock_llm, memory_store)
        result = await extractor.extract("I prefer Python over JavaScript")

        assert result.episode_type == "preference"

    @pytest.mark.asyncio
    async def test_extract_meta(self, mock_llm, memory_store):
        """Test extracting meta type."""
        mock_llm.set_complete_json_response({
            "type": "meta",
            "entities": []
        })

        extractor = EntityExtractor(mock_llm, memory_store)
        result = await extractor.extract("I notice a pattern in my thinking")

        assert result.episode_type == "meta"

    @pytest.mark.asyncio
    async def test_extract_multiple_entities(self, mock_llm, memory_store):
        """Test extracting multiple entities."""
        mock_llm.set_complete_json_response({
            "type": "observation",
            "entities": [
                {"type": "file", "id": "file:main.py", "name": "main.py"},
                {"type": "function", "id": "function:process", "name": "process"},
                {"type": "person", "id": "person:alice", "name": "Alice"},
            ]
        })

        extractor = EntityExtractor(mock_llm, memory_store)
        result = await extractor.extract("Alice modified the process function in main.py")

        assert len(result.entities) == 3
        assert result.entities[0].type == EntityType.FILE
        assert result.entities[1].type == EntityType.FUNCTION
        assert result.entities[2].type == EntityType.PERSON

    @pytest.mark.asyncio
    async def test_extract_all_entity_types(self, mock_llm, memory_store):
        """Test extracting all supported entity types."""
        mock_llm.set_complete_json_response({
            "type": "observation",
            "entities": [
                {"type": "file", "id": "file:test.py", "name": "test.py"},
                {"type": "function", "id": "function:foo", "name": "foo"},
                {"type": "class", "id": "class:Bar", "name": "Bar"},
                {"type": "module", "id": "module:utils", "name": "utils"},
                {"type": "subject", "id": "subject:caching", "name": "caching"},
                {"type": "person", "id": "person:bob", "name": "Bob"},
                {"type": "project", "id": "project:api", "name": "api"},
                {"type": "tool", "id": "tool:redis", "name": "redis"},
            ]
        })

        extractor = EntityExtractor(mock_llm, memory_store)
        result = await extractor.extract("Test content")

        assert len(result.entities) == 8
        types = [e.type for e in result.entities]
        assert EntityType.FILE in types
        assert EntityType.FUNCTION in types
        assert EntityType.CLASS in types
        assert EntityType.MODULE in types
        assert EntityType.SUBJECT in types
        assert EntityType.PERSON in types
        assert EntityType.PROJECT in types
        assert EntityType.TOOL in types

    @pytest.mark.asyncio
    async def test_extract_truncates_long_content(self, mock_llm, memory_store):
        """Test that long content is truncated."""
        mock_llm.set_complete_json_response({
            "type": "observation",
            "entities": []
        })

        extractor = EntityExtractor(mock_llm, memory_store)
        long_content = "x" * (MAX_CONTENT_LENGTH + 500)
        await extractor.extract(long_content)

        # Check that the prompt was truncated
        call = mock_llm.get_call_history()[0]
        assert "[truncated]" in call["prompt"]

    @pytest.mark.asyncio
    async def test_extract_handles_unknown_entity_type(self, mock_llm, memory_store):
        """Test handling of unknown entity types."""
        mock_llm.set_complete_json_response({
            "type": "observation",
            "entities": [
                {"type": "unknown_type", "id": "unknown:foo", "name": "foo"},
            ]
        })

        extractor = EntityExtractor(mock_llm, memory_store)
        result = await extractor.extract("Test content")

        assert len(result.entities) == 1
        assert result.entities[0].type == EntityType.OTHER

    @pytest.mark.asyncio
    async def test_extract_preserves_unknown_episode_type(self, mock_llm, memory_store):
        """Unknown episode types are preserved (custom types are valid)."""
        mock_llm.set_complete_json_response({
            "type": "custom_type",
            "entities": []
        })

        extractor = EntityExtractor(mock_llm, memory_store)
        result = await extractor.extract("Test content")

        assert result.episode_type == "custom_type"

    @pytest.mark.asyncio
    async def test_extract_handles_llm_error(self, mock_llm, memory_store):
        """Test graceful handling of LLM errors."""
        # Make complete_json raise an exception
        async def raise_error(*args, **kwargs):
            raise Exception("LLM service unavailable")
        mock_llm.complete_json = raise_error

        extractor = EntityExtractor(mock_llm, memory_store)
        result = await extractor.extract("Some content")

        # Should return defaults
        assert result.episode_type == "observation"
        assert result.entities == []

    @pytest.mark.asyncio
    async def test_extract_and_store(self, mock_llm, memory_store, sample_episode):
        """Test extraction with storage."""
        mock_llm.set_complete_json_response({
            "type": "preference",
            "entities": [
                {"type": "tool", "id": "tool:python", "name": "Python"}
            ]
        })

        # First add the episode to the store
        memory_store.add_episode(sample_episode)

        extractor = EntityExtractor(mock_llm, memory_store)
        result = await extractor.extract_and_store(sample_episode)

        # Check episode was updated
        updated = memory_store.get_episode(sample_episode.id)
        assert updated.episode_type == "preference"
        assert updated.entities_extracted == True
        assert "tool:python" in updated.entity_ids

        # Check entity was stored
        entity = memory_store.get_entity("tool:python")
        assert entity is not None
        assert entity.display_name == "Python"

    @pytest.mark.asyncio
    async def test_extract_and_store_creates_mentions(self, mock_llm, memory_store):
        """Test that extract_and_store creates mention records."""
        episode = Episode(content="Bob worked on auth.py")
        memory_store.add_episode(episode)

        mock_llm.set_complete_json_response({
            "type": "observation",
            "entities": [
                {"type": "person", "id": "person:bob", "name": "Bob"},
                {"type": "file", "id": "file:auth.py", "name": "auth.py"},
            ]
        })

        extractor = EntityExtractor(mock_llm, memory_store)
        await extractor.extract_and_store(episode)

        # Check mentions were created
        bob_episodes = memory_store.get_episodes_mentioning("person:bob")
        assert len(bob_episodes) == 1
        assert bob_episodes[0].id == episode.id

        auth_episodes = memory_store.get_episodes_mentioning("file:auth.py")
        assert len(auth_episodes) == 1


class TestExtractBatch:
    """Tests for batched extraction."""

    @pytest.mark.asyncio
    async def test_extract_batch_single_episode_delegates_to_extract(self, mock_llm, memory_store):
        """Single-episode batch delegates to extract() directly."""
        mock_llm.set_complete_json_response({
            "type": "observation",
            "entities": [{"type": "file", "id": "file:main.py", "name": "main.py"}],
        })
        ep = Episode(content="Working on main.py")
        extractor = EntityExtractor(mock_llm, memory_store)
        results = await extractor.extract_batch([ep])

        assert ep.id in results
        assert results[ep.id].episode_type == "observation"
        assert len(results[ep.id].entities) == 1

    @pytest.mark.asyncio
    async def test_extract_batch_multiple_episodes(self, mock_llm, memory_store):
        """Multiple episodes batched into one LLM call."""
        ep1 = Episode(content="User likes Python")
        ep2 = Episode(content="Bug found in auth.py")
        ep3 = Episode(content="Decided to use Redis")

        mock_llm.set_complete_json_response({
            "results": {
                ep1.id: {"type": "preference", "title": "Likes Python", "entities": [], "entity_relationships": []},
                ep2.id: {"type": "observation", "title": "Bug in auth", "entities": [{"type": "file", "id": "file:auth.py", "name": "auth.py"}], "entity_relationships": []},
                ep3.id: {"type": "decision", "title": "Use Redis", "entities": [{"type": "tool", "id": "tool:redis", "name": "Redis"}], "entity_relationships": []},
            }
        })

        extractor = EntityExtractor(mock_llm, memory_store)
        results = await extractor.extract_batch([ep1, ep2, ep3])

        assert len(results) == 3
        assert results[ep1.id].episode_type == "preference"
        assert results[ep2.id].episode_type == "observation"
        assert len(results[ep2.id].entities) == 1
        assert results[ep3.id].episode_type == "decision"

        json_calls = [c for c in mock_llm.get_call_history() if c["method"] == "complete_json"]
        assert len(json_calls) == 1

    @pytest.mark.asyncio
    async def test_extract_batch_empty_returns_empty(self, mock_llm, memory_store):
        extractor = EntityExtractor(mock_llm, memory_store)
        results = await extractor.extract_batch([])
        assert results == {}

    @pytest.mark.asyncio
    async def test_extract_batch_partial_results(self, mock_llm, memory_store):
        """Missing episode IDs in the response are omitted from the result."""
        ep1 = Episode(content="Content 1")
        ep2 = Episode(content="Content 2")

        mock_llm.set_complete_json_response({
            "results": {
                ep1.id: {"type": "observation", "entities": []},
            }
        })

        extractor = EntityExtractor(mock_llm, memory_store)
        results = await extractor.extract_batch([ep1, ep2])

        assert ep1.id in results
        assert ep2.id not in results

    @pytest.mark.asyncio
    async def test_extract_batch_llm_failure_returns_empty(self, mock_llm, memory_store):
        """Total LLM failure returns empty dict."""
        async def raise_error(*args, **kwargs):
            raise Exception("LLM unavailable")
        mock_llm.complete_json = raise_error

        ep = Episode(content="Test")
        extractor = EntityExtractor(mock_llm, memory_store)
        results = await extractor.extract_batch([ep, Episode(content="Test 2")])
        assert results == {}

    @pytest.mark.asyncio
    async def test_extract_batch_scales_max_tokens(self, mock_llm, memory_store):
        """max_tokens scales with number of episodes."""
        episodes = [Episode(content=f"Content {i}") for i in range(3)]
        mock_llm.set_complete_json_response({"results": {}})

        extractor = EntityExtractor(mock_llm, memory_store)
        await extractor.extract_batch(episodes)

        call = mock_llm.get_call_history()[0]
        assert call["max_tokens"] == 1024 * 3


class TestStoreExtractionResult:
    """Tests for store_extraction_result."""

    @pytest.mark.asyncio
    async def test_stores_entities_and_updates_episode(self, mock_llm, memory_store):
        ep = Episode(content="Working on auth.py")
        memory_store.add_episode(ep)

        result = ExtractionResult(
            episode_type="observation",
            title="Working on auth",
            entities=[Entity(id="file:auth.py", type=EntityType.FILE, display_name="auth.py")],
        )

        extractor = EntityExtractor(mock_llm, memory_store)
        await extractor.store_extraction_result(ep, result)

        updated = memory_store.get_episode(ep.id)
        assert updated.episode_type == "observation"
        assert updated.entities_extracted is True
        assert "file:auth.py" in updated.entity_ids

        entity = memory_store.get_entity("file:auth.py")
        assert entity is not None

    @pytest.mark.asyncio
    async def test_deduplicates_entities(self, mock_llm, memory_store):
        """When an entity already exists, reuse its ID."""
        existing_entity = Entity(id="file:auth.py", type=EntityType.FILE, display_name="auth.py")
        memory_store.add_entity(existing_entity)

        ep = Episode(content="Still working on auth.py")
        memory_store.add_episode(ep)

        result = ExtractionResult(
            episode_type="observation",
            entities=[Entity(id="file:auth.py_dup", type=EntityType.FILE, display_name="auth.py")],
        )

        extractor = EntityExtractor(mock_llm, memory_store)
        await extractor.store_extraction_result(ep, result)

        updated = memory_store.get_episode(ep.id)
        assert "file:auth.py" in updated.entity_ids

    @pytest.mark.asyncio
    async def test_entity_relation_creates_missing_endpoints(self, mock_llm, memory_store):
        """Relations may name entities the LLM omitted from the entities list; FK stores need rows."""
        from remind.models import EntityRelation

        ep = Episode(content="Political news")
        memory_store.add_episode(ep)

        result = ExtractionResult(
            episode_type="observation",
            entities=[Entity(id="subject:government", type=EntityType.SUBJECT, display_name="Government")],
            entity_relations=[
                EntityRelation(
                    source_id="subject:presidentofrepublic",
                    target_id="subject:government",
                    relation_type="declared permanently unable by",
                    strength=0.9,
                    source_episode_id=ep.id,
                )
            ],
        )

        extractor = EntityExtractor(mock_llm, memory_store)
        await extractor.store_extraction_result(ep, result)

        assert memory_store.get_entity("subject:presidentofrepublic") is not None
        rels = memory_store.get_entity_relations("subject:government")
        assert any(r.source_id == "subject:presidentofrepublic" for r in rels)

    @pytest.mark.asyncio
    async def test_entity_relation_remapped_after_name_dedup(self, mock_llm, memory_store):
        """Relation endpoints use extracted IDs; mentions may dedupe to an existing entity ID."""
        from remind.models import EntityRelation

        memory_store.add_entity(
            Entity(id="subject:government", type=EntityType.SUBJECT, display_name="Government")
        )
        ep = Episode(content="...")
        memory_store.add_episode(ep)

        result = ExtractionResult(
            episode_type="observation",
            entities=[
                Entity(id="subject:government_alt", type=EntityType.SUBJECT, display_name="Government")
            ],
            entity_relations=[
                EntityRelation(
                    source_id="subject:government_alt",
                    target_id="person:alice",
                    relation_type="involves",
                    strength=0.8,
                    source_episode_id=ep.id,
                )
            ],
        )

        extractor = EntityExtractor(mock_llm, memory_store)
        await extractor.store_extraction_result(ep, result)

        rels = memory_store.get_entity_relations("subject:government")
        assert any(r.target_id == "person:alice" for r in rels)

    @pytest.mark.asyncio
    async def test_entity_relation_stub_reuses_existing_entity_by_name(self, mock_llm, memory_store):
        """Relation-only endpoints should not create zero-mention duplicate stubs."""
        from remind.models import EntityRelation

        memory_store.add_entity(
            Entity(id="other:act", type=EntityType.OTHER, display_name="act")
        )
        ep = Episode(content="...")
        memory_store.add_episode(ep)

        result = ExtractionResult(
            episode_type="observation",
            entities=[],
            entity_relations=[
                EntityRelation(
                    source_id="legal_act:act",
                    target_id="subject:procedure",
                    relation_type="governs",
                    strength=0.7,
                    source_episode_id=ep.id,
                )
            ],
        )

        extractor = EntityExtractor(mock_llm, memory_store)
        await extractor.store_extraction_result(ep, result)

        assert memory_store.get_entity("legal_act:act") is None
        rels = memory_store.get_entity_relations("other:act")
        assert any(r.target_id == "subject:procedure" for r in rels)

    @pytest.mark.asyncio
    async def test_entity_label_prefixes_reuse_existing_entity(self, mock_llm, memory_store):
        """Label variants like 'Role: X' should resolve to existing canonical entity."""
        memory_store.add_entity(
            Entity(id="other:chancellor of justice", type=EntityType.OTHER, display_name="chancellor of justice")
        )
        ep = Episode(content="...")
        memory_store.add_episode(ep)

        result = ExtractionResult(
            episode_type="observation",
            entities=[
                Entity(
                    id="other:role: chancellor of justice",
                    type=EntityType.OTHER,
                    display_name="Role: Chancellor of Justice",
                )
            ],
        )

        extractor = EntityExtractor(mock_llm, memory_store)
        await extractor.store_extraction_result(ep, result)

        updated = memory_store.get_episode(ep.id)
        assert updated.entity_ids == ["other:chancellor of justice"]


class TestStoreRelationsResult:
    """Tests for store_relations_result."""

    def test_stores_relations_and_marks_episode(self, mock_llm, memory_store):
        from remind.models import EntityRelation
        ep = Episode(content="Alice manages Bob")
        memory_store.add_episode(ep)

        relations = [
            EntityRelation(
                source_id="person:alice",
                target_id="person:bob",
                relation_type="manages",
                strength=0.9,
                source_episode_id=ep.id,
            )
        ]

        extractor = EntityExtractor(mock_llm, memory_store)
        extractor.store_relations_result(ep, relations)

        updated = memory_store.get_episode(ep.id)
        assert updated.relations_extracted is True


class TestExtractForRemember:
    """Tests for the extract_for_remember helper."""

    @pytest.mark.asyncio
    async def test_extracts_when_enabled(self, mock_llm, memory_store):
        """Test extraction runs when auto_extract is True."""
        mock_llm.set_complete_json_response({
            "type": "decision",
            "entities": []
        })

        episode = Episode(content="Decided to use pytest")
        result = await extract_for_remember(
            mock_llm, memory_store, episode, auto_extract=True
        )

        assert result.episode_type == "decision"
        assert result.entities_extracted == True

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self, mock_llm, memory_store):
        """Test extraction is skipped when auto_extract is False."""
        episode = Episode(content="Some content")
        result = await extract_for_remember(
            mock_llm, memory_store, episode, auto_extract=False
        )

        # Should return unchanged
        assert result.episode_type == "observation"
        assert result.entities_extracted == False
        assert mock_llm.get_call_history() == []

    @pytest.mark.asyncio
    async def test_stores_pending_entities_in_metadata(self, mock_llm, memory_store):
        """Test that extracted entities are stored in metadata for later processing."""
        mock_llm.set_complete_json_response({
            "type": "observation",
            "entities": [
                {"type": "file", "id": "file:test.py", "name": "test.py"}
            ]
        })

        episode = Episode(content="Working on test.py")
        result = await extract_for_remember(
            mock_llm, memory_store, episode, auto_extract=True
        )

        assert "_pending_entities" in result.metadata
        assert len(result.metadata["_pending_entities"]) == 1
        assert result.metadata["_pending_entities"][0]["id"] == "file:test.py"

    @pytest.mark.asyncio
    async def test_handles_extraction_failure_gracefully(self, mock_llm, memory_store):
        """Test that extraction failure doesn't break remember."""
        async def raise_error(*args, **kwargs):
            raise Exception("Extraction failed")
        mock_llm.complete_json = raise_error

        episode = Episode(content="Some content")
        result = await extract_for_remember(
            mock_llm, memory_store, episode, auto_extract=True
        )

        # EntityExtractor.extract() catches errors internally and returns defaults,
        # so extract_for_remember successfully processes the default result
        assert result.episode_type == "observation"
        assert result.entities_extracted == True  # Set to True after processing default result
        assert result.entity_ids == []  # No entities extracted
