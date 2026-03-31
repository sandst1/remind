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

from remind.llm_protocol import ProtocolParseError, parse_triage_csv
from remind.providers.base import LLMProvider

logger = logging.getLogger(__name__)


TRIAGE_SYSTEM_PROMPT = """You are a memory curation system. You receive raw conversation fragments and decide what's worth remembering long-term.

You produce two outputs:
1. An information density estimate (0.0-1.0) for diagnostics
2. Distilled, memory-worthy episodes extracted from the text

Be aggressive about compression. Strip conversational filler, hedging, and step-by-step narration. Each episode should be a single clear assertion that stands on its own.

Err on the side of capturing information. If something might be useful in a future session, extract it. Only skip content that is purely conversational filler with zero informational value."""


_DEFAULT_TRIAGE_TYPES = "observation|decision|preference|question|meta|outcome|fact"


def _build_triage_prompt(valid_types: list[str]) -> str:
    type_enum = "|".join(valid_types)
    return """## EXISTING RELEVANT KNOWLEDGE
{{existing_concepts}}

## EXISTING TOPICS
{{existing_topics}}

## RAW CONVERSATION FRAGMENT
{{chunk}}

Task:
1) Estimate information density in [0.0, 1.0] (for diagnostics only)
2) Extract any memory-worthy episodes from the text
3) Assign each episode to a topic

Guidelines:
- Ignore pure filler/chitchat, but capture anything that would be useful if encountered again in a future session
- Do not repeat already-known information unless corrected or refined
- Each episode must be concise and standalone
- Use type=outcome for action-result pairs
- For outcome metadata include strategy, result(success|failure|partial), prediction_error(low|medium|high)
- Use type=fact for concrete details (values, names, dates, versions, config)
- Assign each episode to a topic: use an existing topic ID when content fits, or suggest a new short topic name

Output ONLY rows inside these tags:
BEGIN TRIAGE_RESULTS
DENSITY,<density>,<reasoning>
TRIAGE_EPISODE,<episode_type>,<content>
TRIAGE_ENTITY,<episode_idx>,<entity_id>
TRIAGE_METADATA,<episode_idx>,<metadata_key>,<metadata_value>
TRIAGE_TOPIC,<episode_idx>,<topic_id_or_name>
END TRIAGE_RESULTS

Rules:
- Exactly one DENSITY row
- TRIAGE_EPISODE row index is implicit 0-based order (first TRIAGE_EPISODE is episode_idx=0)
- Use TRIAGE_ENTITY and TRIAGE_METADATA rows to attach entities/metadata to TRIAGE_EPISODE rows
- Use TRIAGE_TOPIC to assign a topic to each episode (one per episode)
- For existing topics, use the topic ID from the EXISTING TOPICS list
- For new topics, use a short descriptive name (will be auto-created)
- Use CSV quoting when needed
- If nothing is worth remembering, output only the DENSITY row (no TRIAGE_EPISODE rows)
- episode_type must be one of: {type_enum}
- For outcome episodes, include TRIAGE_METADATA rows for strategy, result, prediction_error""".format(type_enum=type_enum)


TRIAGE_PROMPT_TEMPLATE = _build_triage_prompt(_DEFAULT_TRIAGE_TYPES.split("|"))


@dataclass
class TriageEpisode:
    """A single episode extracted by triage."""
    content: str
    episode_type: str = "observation"
    entities: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    topic_id: Optional[str] = None
    topic_name: Optional[str] = None


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
    The LLM decides what's worth remembering -- no numeric threshold is
    applied. Includes existing concept context (via recall) to avoid
    redundant extraction.
    """

    def __init__(
        self,
        llm: LLMProvider,
        min_density: float = 0.0,
        valid_types: Optional[list[str]] = None,
    ):
        self.llm = llm
        if min_density > 0.0:
            logger.warning(
                "min_density is deprecated and ignored. "
                "The LLM now decides directly what to extract."
            )
        if valid_types:
            self._prompt_template = _build_triage_prompt(valid_types)
        else:
            self._prompt_template = TRIAGE_PROMPT_TEMPLATE

    async def triage(
        self,
        chunk: str,
        existing_concepts: str = "",
        existing_topics: str = "",
        instructions: Optional[str] = None,
    ) -> TriageResult:
        """Score density and extract episodes from a text chunk.

        Args:
            chunk: Raw text to triage.
            existing_concepts: Formatted string of relevant existing concepts
                from recall(), used to judge novelty.
            existing_topics: Formatted string of existing topics (id: name)
                for the LLM to assign episodes to.
            instructions: Optional caller-provided instructions that steer
                what the triage LLM extracts (e.g. "focus on architectural
                decisions"). Appended to the system prompt.

        Returns:
            TriageResult with density score and extracted episodes.
        """
        if not chunk.strip():
            return TriageResult(density=0.0, reasoning="Empty input", raw_chunk=chunk)

        concepts_text = existing_concepts or "(No existing knowledge yet)"
        topics_text = existing_topics or "(No topics yet -- suggest new topic names as needed)"

        prompt = self._prompt_template.format(
            existing_concepts=concepts_text,
            existing_topics=topics_text,
            chunk=chunk,
        )

        system_prompt = TRIAGE_SYSTEM_PROMPT
        if instructions:
            system_prompt += (
                "\n\n=== PRIORITY INSTRUCTIONS ===\n"
                "THE FOLLOWING ARE THE MOST IMPORTANT INSTRUCTIONS. "
                "They OVERRIDE and take precedence over ALL other extraction behavior.\n\n"
                f"{instructions}\n"
                "=== END PRIORITY INSTRUCTIONS ==="
            )

        logger.debug(
            "Triage LLM request:\n"
            f"  provider: {self.llm.name}\n"
            f"  system: {system_prompt[:120]}...\n"
            f"  chunk_length: {len(chunk)}\n"
            f"  instructions: {instructions!r}\n"
            f"  prompt (first 500 chars): {prompt[:500]}"
        )

        try:
            raw_response = await self.llm.complete_structured_text(
                prompt=prompt,
                system=system_prompt,
                temperature=0.3,
            )
            logger.debug(f"Triage structured response length: {len(raw_response)}")
            response = parse_triage_csv(raw_response)
        except (ProtocolParseError, ValueError, KeyError, IndexError) as parse_err:
            logger.warning(f"Triage CSV parse failed: {parse_err}. Trying JSON fallback.")
            try:
                response = await self.llm.complete_json(
                    prompt=prompt,
                    system=system_prompt + "\n\nRespond with valid JSON only.",
                    temperature=0.3,
                )
            except Exception as e:
                logger.warning(f"Triage JSON fallback failed: {e}. Falling back to raw storage.")
                return self._fallback_result(chunk, str(e))
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

                topic_id = ep.get("topic_id") or ep.get("topic") or None
                topic_name = ep.get("topic_name") or None

                episodes.append(TriageEpisode(
                    content=content,
                    episode_type=ep_type,
                    entities=[str(e) for e in entities],
                    metadata=metadata,
                    topic_id=str(topic_id) if topic_id else None,
                    topic_name=str(topic_name) if topic_name else None,
                ))

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
