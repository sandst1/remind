"""
Auto-ingest triage engine.

Implements buffered intake with information density scoring for automatic
memory curation. This is the "input selection" subsystem -- a separate,
cheaper process that handles attention/curation so the main agent doesn't
have to compete its filtering decisions with the actual task.

Pipeline: raw text → buffer → density scoring + extraction (LLM) → episodes
"""

from dataclasses import dataclass, field
from typing import Optional
import json
import logging

from remind.providers.base import LLMProvider

logger = logging.getLogger(__name__)


TRIAGE_SYSTEM_PROMPT = """You are a memory curation system. You receive raw conversation fragments and decide what's worth remembering long-term.

You produce two outputs:
1. An information density score (0.0-1.0)
2. Distilled, memory-worthy episodes extracted from the text

Be aggressive about compression. Strip conversational filler, hedging, and step-by-step narration. Each episode should be a single clear assertion that stands on its own."""


_DEFAULT_TRIAGE_TYPES = "observation|decision|preference|question|meta|outcome|fact"


def _build_triage_prompt(valid_types: list[str]) -> str:
    type_enum = "|".join(valid_types)
    return """## EXISTING RELEVANT KNOWLEDGE
{{existing_concepts}}

## RAW CONVERSATION FRAGMENT
{{chunk}}

Score the INFORMATION DENSITY of this text from 0.0 to 1.0:
- 0.0: Pure boilerplate, greetings, acknowledgments, routine narration
- 0.3: Some context but nothing specific or actionable
- 0.5: Contains some facts or context worth noting
- 0.7: Contains decisions, preferences, or important facts
- 1.0: Dense with critical decisions, corrections, or surprising outcomes

Information already captured in EXISTING RELEVANT KNOWLEDGE does NOT count toward density unless it adds new nuance, corrections, or context.

If density >= {{min_density}}, extract memory-worthy episodes as TIGHT, DISTILLED statements. Do NOT copy conversation verbatim. Compress and rewrite into information-dense factual statements. Strip conversational filler, hedging, and step-by-step narration. Each episode should be a single clear assertion that stands on its own.

Good: "Token expiry check in verify_credentials uses <= instead of <, causing tokens to be accepted one second past expiry"
Bad:  "The assistant looked at the auth bug and found that the issue is in verify_credentials where the token expiry check uses <= instead of <"

Additionally, detect ACTION-RESULT pairs: when a strategy, tool, or approach was tried and produced a result. Extract these as "outcome" type episodes with metadata fields: strategy (what was tried), result (success/failure/partial), prediction_error (low/medium/high - how surprising was the outcome).

Use "fact" type for specific factual assertions: concrete values, configuration details, names, dates, version numbers, or technical details that would be lost if generalized. Facts are high-value and should not be paraphrased into vague summaries.

Output JSON:
{{{{
  "density": 0.7,
  "reasoning": "Brief explanation of density score",
  "episodes": [
    {{{{
      "content": "tight, distilled factual statement",
      "type": "{type_enum}",
      "entities": ["type:name"],
      "metadata": {{{{}}}}
    }}}}
  ]
}}}}

For outcome episodes, include metadata like:
{{{{
  "strategy": "what approach was used",
  "result": "success|failure|partial",
  "prediction_error": "low|medium|high"
}}}}

Episodes array should be empty if {{min_density}}.""".format(type_enum=type_enum)


TRIAGE_PROMPT_TEMPLATE = _build_triage_prompt(_DEFAULT_TRIAGE_TYPES.split("|"))


@dataclass
class TriageEpisode:
    """A single episode extracted by triage."""
    content: str
    episode_type: str = "observation"
    entities: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass
class TriageResult:
    """Result of triaging a text chunk."""
    density: float
    reasoning: str
    episodes: list[TriageEpisode] = field(default_factory=list)
    raw_chunk: str = ""


DEFAULT_OVERLAP = 200


def split_text(text: str, max_size: int, overlap: int = DEFAULT_OVERLAP) -> list[str]:
    """Split text into chunks of at most max_size characters.

    Splits on paragraph boundaries (\\n\\n) when possible, falling back to
    line breaks (\\n), then hard-cutting as a last resort. Adjacent chunks
    share an overlap region so context isn't lost at boundaries.

    Args:
        text: The text to split.
        max_size: Maximum character count per chunk.
        overlap: Characters of overlap between adjacent chunks.

    Returns:
        List of text chunks. Returns [text] as-is if it fits in one chunk.
        Returns [] for empty input.
    """
    if not text or not text.strip():
        return []

    if len(text) <= max_size:
        return [text]

    if overlap >= max_size:
        overlap = max_size // 5

    chunks: list[str] = []
    start = 0

    while start < len(text):
        end = start + max_size

        if end >= len(text):
            chunks.append(text[start:])
            break

        # Try to find a paragraph boundary to split on
        split_at = _find_split_point(text, start, end)
        chunks.append(text[start:split_at])

        # Advance past the split point, minus overlap
        start = max(start + 1, split_at - overlap)

    return chunks


def _find_split_point(text: str, start: int, end: int) -> int:
    """Find the best place to split within text[start:end].

    Searches backwards from end for paragraph breaks, then line breaks,
    then falls back to a hard cut at end.
    """
    # Search the last 25% of the window for a good split point
    search_start = start + (end - start) * 3 // 4

    # Prefer paragraph boundary (\n\n)
    pos = text.rfind("\n\n", search_start, end)
    if pos != -1:
        return pos + 2  # after the double newline

    # Fall back to line boundary (\n)
    pos = text.rfind("\n", search_start, end)
    if pos != -1:
        return pos + 1

    # Hard cut
    return end


class IngestionBuffer:
    """Character-threshold buffer for raw text accumulation.

    Accumulates text via add() until the buffer exceeds the character
    threshold, then returns the flushed chunk. flush() forces a flush
    regardless of size.
    """

    def __init__(self, threshold: int = 4000):
        self.threshold = threshold
        self._buffer: list[str] = []
        self._char_count: int = 0

    def add(self, text: str) -> Optional[str]:
        """Add text to the buffer. Returns flushed chunk if threshold reached."""
        self._buffer.append(text)
        self._char_count += len(text)

        if self._char_count >= self.threshold:
            return self._flush()
        return None

    def flush(self) -> Optional[str]:
        """Force flush the buffer. Returns None if buffer is empty."""
        if not self._buffer:
            return None
        return self._flush()

    def _flush(self) -> str:
        chunk = "\n".join(self._buffer)
        self._buffer = []
        self._char_count = 0
        return chunk

    @property
    def size(self) -> int:
        return self._char_count

    @property
    def is_empty(self) -> bool:
        return self._char_count == 0


class IngestionTriager:
    """Scores information density and extracts distilled episodes from raw text.

    Uses a single LLM call to both score density and extract episodes.
    Chunks below the density threshold produce no episodes. Includes
    existing concept context (via recall) to avoid redundant extraction.
    """

    def __init__(
        self,
        llm: LLMProvider,
        min_density: float = 0.4,
        valid_types: Optional[list[str]] = None,
    ):
        self.llm = llm
        self.min_density = min_density
        if valid_types:
            self._prompt_template = _build_triage_prompt(valid_types)
        else:
            self._prompt_template = TRIAGE_PROMPT_TEMPLATE

    async def triage(
        self,
        chunk: str,
        existing_concepts: str = "",
    ) -> TriageResult:
        """Score density and extract episodes from a text chunk.

        Args:
            chunk: Raw text to triage.
            existing_concepts: Formatted string of relevant existing concepts
                from recall(), used to judge novelty.

        Returns:
            TriageResult with density score and extracted episodes.
        """
        if not chunk.strip():
            return TriageResult(density=0.0, reasoning="Empty input", raw_chunk=chunk)

        concepts_text = existing_concepts or "(No existing knowledge yet)"

        prompt = self._prompt_template.format(
            existing_concepts=concepts_text,
            chunk=chunk,
            min_density=self.min_density,
        )

        logger.debug(
            "Triage LLM request:\n"
            f"  provider: {self.llm.name}\n"
            f"  system: {TRIAGE_SYSTEM_PROMPT[:120]}...\n"
            f"  chunk_length: {len(chunk)}\n"
            f"  prompt (first 500 chars): {prompt[:500]}"
        )

        try:
            response = await self.llm.complete_json(
                prompt=prompt,
                system=TRIAGE_SYSTEM_PROMPT,
                temperature=0.3,
            )
        except Exception as e:
            logger.warning(f"Triage LLM call failed: {e}. Falling back to raw storage.")
            return self._fallback_result(chunk, str(e))

        logger.debug(f"Triage LLM response: {json.dumps(response, indent=2)}")

        return self._parse_response(response, chunk)

    def _parse_response(self, response: dict, chunk: str) -> TriageResult:
        """Parse LLM JSON response into a TriageResult."""
        try:
            density = float(response.get("density", 0.0))
            reasoning = response.get("reasoning", "")
            raw_episodes = response.get("episodes", [])

            episodes = []
            for ep in raw_episodes:
                if not isinstance(ep, dict):
                    continue
                content = ep.get("content", "").strip()
                if not content:
                    continue

                ep_type = ep.get("type", "observation")
                entities = ep.get("entities", [])
                if not isinstance(entities, list):
                    entities = []
                metadata = ep.get("metadata", {})
                if not isinstance(metadata, dict):
                    metadata = {}

                episodes.append(TriageEpisode(
                    content=content,
                    episode_type=ep_type,
                    entities=[str(e) for e in entities],
                    metadata=metadata,
                ))

            if density < self.min_density:
                episodes = []

            return TriageResult(
                density=density,
                reasoning=reasoning,
                episodes=episodes,
                raw_chunk=chunk,
            )

        except (TypeError, ValueError, KeyError) as e:
            logger.warning(f"Failed to parse triage response: {e}")
            return self._fallback_result(chunk, f"Parse error: {e}")

    def _fallback_result(self, chunk: str, reason: str) -> TriageResult:
        """Create a fallback result that stores the raw chunk as-is."""
        return TriageResult(
            density=0.5,
            reasoning=f"Fallback: {reason}",
            episodes=[TriageEpisode(content=chunk[:2000])],
            raw_chunk=chunk,
        )
