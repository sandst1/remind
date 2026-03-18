"""Tests for the auto-ingest triage engine."""

import pytest

from remind.triage import IngestionBuffer, IngestionTriager, TriageResult, TriageEpisode
from remind.interface import MemoryInterface
from remind.models import EpisodeType


class TestIngestionBuffer:
    """Tests for IngestionBuffer -- character-threshold buffering."""

    def test_add_below_threshold(self):
        buf = IngestionBuffer(threshold=100)
        result = buf.add("hello")
        assert result is None
        assert buf.size == 5
        assert not buf.is_empty

    def test_add_reaches_threshold(self):
        buf = IngestionBuffer(threshold=20)
        buf.add("twelve chars.")  # 13 chars
        result = buf.add("more text here")  # 14 chars, total 27 > 20
        assert result is not None
        assert "twelve chars." in result
        assert "more text here" in result
        assert buf.size == 0
        assert buf.is_empty

    def test_flush_returns_content(self):
        buf = IngestionBuffer(threshold=1000)
        buf.add("first chunk")
        buf.add("second chunk")
        result = buf.flush()
        assert result is not None
        assert "first chunk" in result
        assert "second chunk" in result
        assert buf.is_empty

    def test_flush_empty_returns_none(self):
        buf = IngestionBuffer(threshold=100)
        assert buf.flush() is None

    def test_buffer_resets_after_flush(self):
        buf = IngestionBuffer(threshold=10)
        buf.add("abcdefghijk")  # triggers threshold
        assert buf.is_empty
        assert buf.size == 0
        # Can add again after flush
        result = buf.add("new")
        assert result is None
        assert buf.size == 3

    def test_multiple_flush_cycles(self):
        buf = IngestionBuffer(threshold=10)
        # First cycle
        chunk1 = buf.add("a" * 15)
        assert chunk1 is not None
        # Second cycle
        buf.add("bb")
        buf.add("cc")
        chunk2 = buf.flush()
        assert chunk2 is not None
        assert "bb" in chunk2
        assert "cc" in chunk2

    def test_exact_threshold(self):
        buf = IngestionBuffer(threshold=5)
        result = buf.add("12345")  # exactly 5 chars
        assert result is not None

    def test_size_property(self):
        buf = IngestionBuffer(threshold=100)
        assert buf.size == 0
        buf.add("hello")
        assert buf.size == 5
        buf.add("world")
        assert buf.size == 10


class TestIngestionTriager:
    """Tests for IngestionTriager -- density scoring + episode extraction."""

    @pytest.fixture
    def mock_llm(self):
        from tests.conftest import MockLLMProvider
        return MockLLMProvider()

    @pytest.fixture
    def triager(self, mock_llm):
        return IngestionTriager(llm=mock_llm, min_density=0.4)

    @pytest.mark.asyncio
    async def test_high_density_extracts_episodes(self, triager, mock_llm):
        mock_llm.set_complete_json_response({
            "density": 0.8,
            "reasoning": "Contains specific bug diagnosis",
            "episodes": [
                {
                    "content": "Token expiry check uses <= instead of <",
                    "type": "observation",
                    "entities": ["function:verify_credentials"],
                    "metadata": {},
                }
            ],
        })

        result = await triager.triage("Some conversation about a bug...")
        assert result.density == 0.8
        assert len(result.episodes) == 1
        assert result.episodes[0].content == "Token expiry check uses <= instead of <"
        assert result.episodes[0].episode_type == "observation"

    @pytest.mark.asyncio
    async def test_low_density_drops_episodes(self, triager, mock_llm):
        mock_llm.set_complete_json_response({
            "density": 0.2,
            "reasoning": "Just greetings and boilerplate",
            "episodes": [],
        })

        result = await triager.triage("Hi! How are you? I'm good, thanks.")
        assert result.density == 0.2
        assert len(result.episodes) == 0

    @pytest.mark.asyncio
    async def test_density_below_threshold_clears_episodes(self, triager, mock_llm):
        """Even if LLM returns episodes, they're dropped if density < threshold."""
        mock_llm.set_complete_json_response({
            "density": 0.3,
            "reasoning": "Low density",
            "episodes": [
                {"content": "Something", "type": "observation", "entities": [], "metadata": {}}
            ],
        })

        result = await triager.triage("Some text")
        assert result.density == 0.3
        assert len(result.episodes) == 0

    @pytest.mark.asyncio
    async def test_outcome_episode_extraction(self, triager, mock_llm):
        mock_llm.set_complete_json_response({
            "density": 0.7,
            "reasoning": "Contains action-result pair",
            "episodes": [
                {
                    "content": "Grep search for auth missed main implementation",
                    "type": "outcome",
                    "entities": ["function:verify_credentials"],
                    "metadata": {
                        "strategy": "grep-based search for 'auth'",
                        "result": "partial",
                        "prediction_error": "high",
                    },
                }
            ],
        })

        result = await triager.triage("Agent tried grep...")
        assert len(result.episodes) == 1
        ep = result.episodes[0]
        assert ep.episode_type == "outcome"
        assert ep.metadata["strategy"] == "grep-based search for 'auth'"
        assert ep.metadata["result"] == "partial"
        assert ep.metadata["prediction_error"] == "high"

    @pytest.mark.asyncio
    async def test_empty_input(self, triager):
        result = await triager.triage("")
        assert result.density == 0.0
        assert len(result.episodes) == 0

    @pytest.mark.asyncio
    async def test_whitespace_input(self, triager):
        result = await triager.triage("   \n  \t  ")
        assert result.density == 0.0
        assert len(result.episodes) == 0

    @pytest.mark.asyncio
    async def test_llm_failure_fallback(self, triager, mock_llm):
        """LLM failure should produce a fallback result."""
        async def failing_complete_json(*args, **kwargs):
            raise RuntimeError("API error")
        mock_llm.complete_json = failing_complete_json

        result = await triager.triage("Important text about a critical bug")
        assert result.density == 0.5
        assert len(result.episodes) == 1
        assert "Important text" in result.episodes[0].content

    @pytest.mark.asyncio
    async def test_existing_concepts_passed_to_prompt(self, triager, mock_llm):
        mock_llm.set_complete_json_response({
            "density": 0.5,
            "reasoning": "Some new info",
            "episodes": [
                {"content": "New fact", "type": "observation", "entities": [], "metadata": {}}
            ],
        })

        await triager.triage(
            "Some conversation",
            existing_concepts="- User prefers Python\n- User works on distributed systems",
        )

        # Verify the prompt included the concepts
        history = mock_llm.get_call_history()
        assert len(history) == 1
        assert "User prefers Python" in history[0]["prompt"]

    @pytest.mark.asyncio
    async def test_malformed_episode_skipped(self, triager, mock_llm):
        mock_llm.set_complete_json_response({
            "density": 0.7,
            "reasoning": "Mixed quality",
            "episodes": [
                {"content": "Valid episode", "type": "observation", "entities": [], "metadata": {}},
                {"content": "", "type": "observation"},  # empty content, should be skipped
                "not a dict",  # not a dict, should be skipped
                {"content": "Another valid", "type": "decision", "entities": [], "metadata": {}},
            ],
        })

        result = await triager.triage("Some text")
        assert len(result.episodes) == 2
        assert result.episodes[0].content == "Valid episode"
        assert result.episodes[1].content == "Another valid"

    @pytest.mark.asyncio
    async def test_custom_min_density(self, mock_llm):
        triager = IngestionTriager(llm=mock_llm, min_density=0.7)
        mock_llm.set_complete_json_response({
            "density": 0.5,
            "reasoning": "Medium density",
            "episodes": [
                {"content": "Something", "type": "observation", "entities": [], "metadata": {}}
            ],
        })

        result = await triager.triage("Some text")
        assert len(result.episodes) == 0  # 0.5 < 0.7 threshold


class TestIngestionIntegration:
    """Integration tests for ingest() and flush_ingest() on MemoryInterface."""

    @pytest.fixture
    def mock_llm(self):
        from tests.conftest import MockLLMProvider
        return MockLLMProvider()

    @pytest.fixture
    def mock_embedding(self):
        from tests.conftest import MockEmbeddingProvider
        return MockEmbeddingProvider(dimensions=128)

    @pytest.fixture
    def memory(self, mock_llm, mock_embedding, memory_store):
        return MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            store=memory_store,
            consolidation_threshold=5,
            auto_consolidate=False,
            ingest_buffer_size=50,
            ingest_min_density=0.4,
            ingest_background=False,
        )

    @pytest.mark.asyncio
    async def test_ingest_buffers_below_threshold(self, memory):
        result = await memory.ingest("short text")
        assert result == []
        assert memory.ingest_buffer_size > 0

    @pytest.mark.asyncio
    async def test_ingest_processes_at_threshold(self, memory, mock_llm):
        mock_llm.set_complete_json_response({
            "density": 0.8,
            "reasoning": "Good info",
            "episodes": [
                {
                    "content": "Distilled fact from conversation",
                    "type": "observation",
                    "entities": [],
                    "metadata": {},
                }
            ],
        })

        # Also need consolidation response for immediate consolidation
        long_text = "x" * 60  # exceeds 50 char threshold
        result = await memory.ingest(long_text)
        assert len(result) >= 1

        # Verify episode was stored
        episode = memory.store.get_episode(result[0])
        assert episode is not None
        assert episode.content == "Distilled fact from conversation"

    @pytest.mark.asyncio
    async def test_flush_ingest_processes_buffer(self, memory, mock_llm):
        mock_llm.set_complete_json_response({
            "density": 0.7,
            "reasoning": "Contains useful info",
            "episodes": [
                {
                    "content": "Extracted from flush",
                    "type": "decision",
                    "entities": ["tool:redis"],
                    "metadata": {},
                }
            ],
        })

        await memory.ingest("some short text")
        assert memory.ingest_buffer_size > 0

        result = await memory.flush_ingest()
        assert len(result) >= 1
        assert memory.ingest_buffer_size == 0

    @pytest.mark.asyncio
    async def test_flush_ingest_empty_buffer(self, memory):
        result = await memory.flush_ingest()
        assert result == []

    @pytest.mark.asyncio
    async def test_ingest_metadata_includes_source(self, memory, mock_llm):
        mock_llm.set_complete_json_response({
            "density": 0.8,
            "reasoning": "Good info",
            "episodes": [
                {"content": "A fact", "type": "observation", "entities": [], "metadata": {}}
            ],
        })

        long_text = "y" * 60
        result = await memory.ingest(long_text, source="transcript")
        assert len(result) >= 1

        episode = memory.store.get_episode(result[0])
        assert episode.metadata.get("source") == "transcript"
        assert "triage_density" in episode.metadata

    @pytest.mark.asyncio
    async def test_ingest_outcome_episode(self, memory, mock_llm):
        """Verify that outcome-typed episodes from triage are stored with correct type and metadata.

        The mock LLM returns the same response for all complete_json calls, so
        consolidation's extraction phase will also see this response. We just
        verify the episode was created with the right type *before* consolidation
        re-classifies it. Check metadata instead (which consolidation preserves).
        """
        mock_llm.set_complete_json_response({
            "density": 0.7,
            "reasoning": "Action-result pair detected",
            "episodes": [
                {
                    "content": "Grep missed auth implementation",
                    "type": "outcome",
                    "entities": [],
                    "metadata": {
                        "strategy": "grep search",
                        "result": "failure",
                        "prediction_error": "high",
                    },
                }
            ],
        })

        long_text = "z" * 60
        result = await memory.ingest(long_text)
        assert len(result) >= 1

        episode = memory.store.get_episode(result[0])
        assert episode.metadata["strategy"] == "grep search"
        assert episode.metadata["result"] == "failure"
        assert episode.metadata["prediction_error"] == "high"


class TestOutcomeEpisodeType:
    """Tests for the OUTCOME episode type."""

    def test_outcome_enum_exists(self):
        assert EpisodeType.OUTCOME.value == "outcome"

    def test_outcome_from_string(self):
        assert EpisodeType("outcome") == EpisodeType.OUTCOME

    def test_remember_outcome(self, mock_llm, mock_embedding, memory_store):
        memory = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            store=memory_store,
            auto_consolidate=False,
        )

        episode_id = memory.remember(
            "Grep search missed the function because of naming",
            episode_type=EpisodeType.OUTCOME,
            metadata={
                "strategy": "grep-based search",
                "result": "failure",
                "prediction_error": "high",
            },
        )

        episode = memory.store.get_episode(episode_id)
        assert episode.episode_type == EpisodeType.OUTCOME
        assert episode.metadata["strategy"] == "grep-based search"
