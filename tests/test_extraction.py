"""Tests for entity and type extraction."""

import pytest
import json

from remind.extraction import (
    EntityExtractor,
    extract_for_remember,
    try_fix_json,
    MAX_CONTENT_LENGTH,
)
from remind.models import EpisodeType, EntityType, Episode


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

        assert result.episode_type == EpisodeType.OBSERVATION
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

        assert result.episode_type == EpisodeType.DECISION

    @pytest.mark.asyncio
    async def test_extract_question(self, mock_llm, memory_store):
        """Test extracting question type."""
        mock_llm.set_complete_json_response({
            "type": "question",
            "entities": []
        })

        extractor = EntityExtractor(mock_llm, memory_store)
        result = await extractor.extract("Should we use Redis?")

        assert result.episode_type == EpisodeType.QUESTION

    @pytest.mark.asyncio
    async def test_extract_preference(self, mock_llm, memory_store):
        """Test extracting preference type."""
        mock_llm.set_complete_json_response({
            "type": "preference",
            "entities": []
        })

        extractor = EntityExtractor(mock_llm, memory_store)
        result = await extractor.extract("I prefer Python over JavaScript")

        assert result.episode_type == EpisodeType.PREFERENCE

    @pytest.mark.asyncio
    async def test_extract_meta(self, mock_llm, memory_store):
        """Test extracting meta type."""
        mock_llm.set_complete_json_response({
            "type": "meta",
            "entities": []
        })

        extractor = EntityExtractor(mock_llm, memory_store)
        result = await extractor.extract("I notice a pattern in my thinking")

        assert result.episode_type == EpisodeType.META

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
    async def test_extract_handles_unknown_episode_type(self, mock_llm, memory_store):
        """Test handling of unknown episode types."""
        mock_llm.set_complete_json_response({
            "type": "unknown_episode_type",
            "entities": []
        })

        extractor = EntityExtractor(mock_llm, memory_store)
        result = await extractor.extract("Test content")

        # Should default to observation
        assert result.episode_type == EpisodeType.OBSERVATION

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
        assert result.episode_type == EpisodeType.OBSERVATION
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
        assert updated.episode_type == EpisodeType.PREFERENCE
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

        assert result.episode_type == EpisodeType.DECISION
        assert result.entities_extracted == True

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self, mock_llm, memory_store):
        """Test extraction is skipped when auto_extract is False."""
        episode = Episode(content="Some content")
        result = await extract_for_remember(
            mock_llm, memory_store, episode, auto_extract=False
        )

        # Should return unchanged
        assert result.episode_type == EpisodeType.OBSERVATION
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
        assert result.episode_type == EpisodeType.OBSERVATION
        assert result.entities_extracted == True  # Set to True after processing default result
        assert result.entity_ids == []  # No entities extracted
