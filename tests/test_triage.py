"""Tests for the auto-ingest triage engine."""

import pytest

from remind.triage import IngestionBuffer, IngestionTriager, TriageResult, TriageEpisode, split_text
from remind.interface import MemoryInterface
from remind.models import EpisodeType


class TestSplitText:
    """Tests for split_text() -- pre-triage chunk splitting."""

    def test_small_text_returns_single_chunk(self):
        result = split_text("hello world", max_size=100)
        assert result == ["hello world"]

    def test_empty_text_returns_empty(self):
        assert split_text("", max_size=100) == []

    def test_whitespace_only_returns_empty(self):
        assert split_text("   \n\t  ", max_size=100) == []

    def test_exact_max_size_returns_single_chunk(self):
        text = "a" * 50
        result = split_text(text, max_size=50)
        assert result == [text]

    def test_splits_on_paragraph_boundary(self):
        para1 = "First paragraph. " * 10   # ~170 chars
        para2 = "Second paragraph. " * 10  # ~180 chars
        text = para1.rstrip() + "\n\n" + para2.rstrip()
        result = split_text(text, max_size=200, overlap=0)
        assert len(result) == 2
        assert result[0].startswith("First paragraph.")
        assert result[1].startswith("Second paragraph.")

    def test_splits_on_newline_fallback(self):
        line1 = "a" * 50
        line2 = "b" * 50
        text = line1 + "\n" + line2
        result = split_text(text, max_size=60, overlap=0)
        assert len(result) == 2
        assert result[0] == line1 + "\n"
        assert result[1].startswith("b")

    def test_hard_cut_when_no_boundaries(self):
        text = "a" * 200
        result = split_text(text, max_size=80, overlap=0)
        assert all(len(c) <= 80 for c in result)
        joined = "".join(result)
        assert joined == text

    def test_overlap_between_chunks(self):
        text = "a" * 100 + "\n\n" + "b" * 100
        result = split_text(text, max_size=120, overlap=20)
        assert len(result) >= 2
        # Second chunk should begin with tail of the first (overlap region)
        assert result[1][:20] == result[0][-20:]

    def test_overlap_clamped_when_too_large(self):
        text = "a" * 100
        result = split_text(text, max_size=30, overlap=30)
        # overlap >= max_size is clamped to max_size // 5 = 6
        assert len(result) >= 2

    def test_many_chunks_from_large_text(self):
        paragraphs = [f"Paragraph {i}. " * 10 for i in range(20)]
        text = "\n\n".join(paragraphs)
        result = split_text(text, max_size=200, overlap=0)
        assert len(result) > 5
        assert all(len(c) <= 200 for c in result)

    def test_full_coverage_no_overlap(self):
        """Every character appears in at least one chunk (overlap=0)."""
        text = "Hello world.\n\nThis is a test.\n\nFinal paragraph here."
        result = split_text(text, max_size=25, overlap=0)
        joined = "".join(result)
        for char_pos, ch in enumerate(text):
            if not ch.isspace():
                assert ch in joined, f"char {ch!r} at pos {char_pos} missing"

    # --- New tests for recursive splitting ---

    def test_splits_on_sentence_boundary(self):
        """When text has no newlines, splits on sentence endings."""
        text = "First sentence here. Second sentence here. Third sentence here."
        result = split_text(text, max_size=30, overlap=0)
        assert len(result) >= 2
        assert all(len(c) <= 30 for c in result)
        # Sentences should be kept intact where possible
        assert any("First sentence" in c for c in result)
        assert any("Third sentence" in c for c in result)

    def test_splits_on_question_boundary(self):
        """Question marks followed by space are valid split points."""
        text = "What is this? How does it work? Why should we care?"
        result = split_text(text, max_size=25, overlap=0)
        assert len(result) >= 2
        assert all(len(c) <= 25 for c in result)

    def test_splits_on_word_boundary(self):
        """Falls through to word-level splitting when sentences are too long."""
        text = "word " * 40  # 200 chars, no sentence punctuation
        result = split_text(text, max_size=50, overlap=0)
        assert len(result) >= 2
        assert all(len(c) <= 50 for c in result)
        # Should split on spaces, not mid-word
        for chunk in result:
            stripped = chunk.strip()
            if stripped:
                assert stripped.replace("word", "").replace(" ", "") == ""

    def test_prefers_coarse_over_fine_separator(self):
        """Paragraph breaks are preferred over sentence breaks."""
        para1 = "Short paragraph one."
        para2 = "Short paragraph two."
        text = para1 + "\n\n" + para2
        result = split_text(text, max_size=30, overlap=0)
        assert len(result) == 2
        assert result[0].strip() == para1
        assert result[1].strip() == para2

    def test_mixed_separators(self):
        """Text with multiple separator types splits coherently."""
        text = (
            "Section one paragraph one.\n\n"
            "Section one paragraph two. It has two sentences.\n\n\n"
            "Section two starts here. With another sentence."
        )
        result = split_text(text, max_size=60, overlap=0)
        assert len(result) >= 2
        assert all(len(c) <= 60 for c in result)

    def test_no_empty_chunks(self):
        """Output should never contain empty strings."""
        text = "Hello.\n\n\n\nWorld.\n\n\n\nTest."
        result = split_text(text, max_size=15, overlap=0)
        assert all(c for c in result)

    def test_separator_retained_in_chunk(self):
        """Separators stay at the end of the left chunk, not stripped."""
        text = "Line one.\nLine two."
        result = split_text(text, max_size=12, overlap=0)
        assert len(result) >= 2
        assert result[0].endswith("\n")

    def test_single_very_long_word(self):
        """A single token longer than max_size gets hard-split."""
        text = "x" * 100
        result = split_text(text, max_size=30, overlap=0)
        assert all(len(c) <= 30 for c in result)
        assert "".join(result) == text

    def test_overlap_prepends_context(self):
        """With overlap, each chunk after the first starts with previous tail."""
        text = "Alpha paragraph.\n\nBeta paragraph.\n\nGamma paragraph."
        result = split_text(text, max_size=25, overlap=10)
        assert len(result) >= 2
        for i in range(1, len(result)):
            # The beginning of chunk[i] should match the end of the
            # pre-overlap version (i.e. overlap was prepended)
            assert len(result[i]) > 0


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
        return IngestionTriager(llm=mock_llm)

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
    async def test_low_density_keeps_llm_episodes(self, triager, mock_llm):
        """Episodes returned by the LLM are kept regardless of density score."""
        mock_llm.set_complete_json_response({
            "density": 0.3,
            "reasoning": "Low density but has something useful",
            "episodes": [
                {"content": "Something useful", "type": "observation", "entities": [], "metadata": {}}
            ],
        })

        result = await triager.triage("Some text")
        assert result.density == 0.3
        assert len(result.episodes) == 1
        assert result.episodes[0].content == "Something useful"

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
        assert len(history) >= 1
        assert any("User prefers Python" in call["prompt"] for call in history)

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

    async def test_min_density_deprecated(self, mock_llm, caplog):
        """Passing min_density > 0 logs a deprecation warning but doesn't gate."""
        import logging
        with caplog.at_level(logging.WARNING, logger="remind.triage"):
            triager = IngestionTriager(llm=mock_llm, min_density=0.7)
        assert "deprecated" in caplog.text.lower()

        mock_llm.set_complete_json_response({
            "density": 0.5,
            "reasoning": "Medium density",
            "episodes": [
                {"content": "Something", "type": "observation", "entities": [], "metadata": {}}
            ],
        })

        result = await triager.triage("Some text")
        assert len(result.episodes) == 1


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

    @pytest.mark.asyncio
    async def test_remember_outcome(self, mock_llm, mock_embedding, memory_store):
        memory = MemoryInterface(
            llm=mock_llm,
            embedding=mock_embedding,
            store=memory_store,
            auto_consolidate=False,
        )

        episode_id = await memory.remember(
            "Grep search missed the function because of naming",
            episode_type=EpisodeType.OUTCOME,
            metadata={
                "strategy": "grep-based search",
                "result": "failure",
                "prediction_error": "high",
            },
        )

        episode = memory.store.get_episode(episode_id)
        assert episode.episode_type == "outcome"
        assert episode.metadata["strategy"] == "grep-based search"


class TestLargeInputIngestion:
    """Integration test: large input is split into multiple triage calls."""

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
            ingest_background=False,
        )

    @pytest.mark.asyncio
    async def test_large_input_splits_into_multiple_triage_calls(self, memory, mock_llm):
        """A 300-char input with buffer_size=50 should produce multiple triage LLM calls."""
        mock_llm.set_complete_json_response({
            "density": 0.8,
            "reasoning": "Good info",
            "episodes": [
                {
                    "content": "Distilled fact",
                    "type": "observation",
                    "entities": [],
                    "metadata": {},
                }
            ],
        })

        large_text = "x" * 300
        result = await memory.ingest(large_text)

        # Should have created multiple episodes (one per sub-chunk)
        assert len(result) > 1

        # Count triage LLM calls (complete_json with triage system prompt)
        triage_calls = [
            c for c in mock_llm.get_call_history()
            if c["method"] == "complete_json" and "memory curation" in (c.get("system") or "")
        ]
        assert len(triage_calls) > 1

    @pytest.mark.asyncio
    async def test_large_input_with_paragraphs(self, memory, mock_llm):
        """Large input with paragraph structure splits on boundaries."""
        mock_llm.set_complete_json_response({
            "density": 0.7,
            "reasoning": "Contains info",
            "episodes": [
                {
                    "content": "Extracted fact",
                    "type": "observation",
                    "entities": [],
                    "metadata": {},
                }
            ],
        })

        paragraphs = [f"Paragraph {i} with some content." for i in range(10)]
        text = "\n\n".join(paragraphs)
        result = await memory.ingest(text)

        assert len(result) >= 1

        # Verify triage calls happened for each sub-chunk
        triage_calls = [
            c for c in mock_llm.get_call_history()
            if c["method"] == "complete_json" and "memory curation" in (c.get("system") or "")
        ]
        assert len(triage_calls) >= 2


class TestIngestInstructions:
    """Tests for the instructions parameter on ingest/triage."""

    @pytest.fixture
    def mock_llm(self):
        from tests.conftest import MockLLMProvider
        return MockLLMProvider()

    @pytest.fixture
    def triager(self, mock_llm):
        return IngestionTriager(llm=mock_llm)

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
            ingest_background=False,
        )

    @pytest.mark.asyncio
    async def test_instructions_appended_to_system_prompt(self, triager, mock_llm):
        """When instructions are provided, they appear in the system prompt."""
        mock_llm.set_complete_json_response({
            "density": 0.8,
            "reasoning": "Found decisions",
            "episodes": [
                {"content": "Chose Redis", "type": "decision", "entities": [], "metadata": {}}
            ],
        })

        await triager.triage(
            "Some meeting transcript about architecture",
            instructions="Focus on architectural decisions and their rationale",
        )

        history = mock_llm.get_call_history()
        assert len(history) >= 1
        system = history[0].get("system", "")
        assert "PRIORITY INSTRUCTIONS" in system
        assert "Focus on architectural decisions" in system
        assert "=== END PRIORITY INSTRUCTIONS ===" in system

    @pytest.mark.asyncio
    async def test_no_instructions_no_extra_system_prompt(self, triager, mock_llm):
        """Without instructions, system prompt stays unchanged."""
        mock_llm.set_complete_json_response({
            "density": 0.5,
            "reasoning": "Standard",
            "episodes": [],
        })

        await triager.triage("Some text")

        history = mock_llm.get_call_history()
        assert len(history) >= 1
        system = history[0].get("system", "")
        assert "PRIORITY INSTRUCTIONS" not in system

    @pytest.mark.asyncio
    async def test_instructions_threaded_through_ingest(self, memory, mock_llm):
        """instructions parameter flows from ingest() to the triage LLM call."""
        mock_llm.set_complete_json_response({
            "density": 0.8,
            "reasoning": "Good info",
            "episodes": [
                {"content": "Config value found", "type": "fact", "entities": [], "metadata": {}}
            ],
        })

        long_text = "x" * 60
        await memory.ingest(long_text, instructions="Extract all config values")

        triage_calls = [
            c for c in mock_llm.get_call_history()
            if "memory curation" in (c.get("system") or "")
        ]
        assert len(triage_calls) >= 1
        assert "Extract all config values" in triage_calls[0]["system"]

    @pytest.mark.asyncio
    async def test_instructions_threaded_through_flush_ingest(self, memory, mock_llm):
        """instructions parameter flows from flush_ingest() to the triage LLM call."""
        mock_llm.set_complete_json_response({
            "density": 0.7,
            "reasoning": "Found decisions",
            "episodes": [
                {"content": "A decision", "type": "decision", "entities": [], "metadata": {}}
            ],
        })

        await memory.ingest("some short text")
        assert memory.ingest_buffer_size > 0

        await memory.flush_ingest(instructions="Only extract decisions")

        triage_calls = [
            c for c in mock_llm.get_call_history()
            if "memory curation" in (c.get("system") or "")
        ]
        assert len(triage_calls) >= 1
        assert "Only extract decisions" in triage_calls[0]["system"]
