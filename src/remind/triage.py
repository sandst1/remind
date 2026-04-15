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

## RAW CONVERSATION FRAGMENT
{{chunk}}

Task:
1) Estimate information density in [0.0, 1.0] (for diagnostics only)
2) Extract any memory-worthy episodes from the text

Guidelines:
- Ignore pure filler/chitchat, but capture anything that would be useful if encountered again in a future session
- Do not repeat already-known information unless corrected or refined
- Each episode must be concise and standalone
- Use type=outcome for action-result pairs
- For outcome metadata include strategy, result(success|failure|partial), prediction_error(low|medium|high)
- Use type=fact for concrete details (values, names, dates, versions, config)

Output ONLY rows inside these tags:
BEGIN TRIAGE_RESULTS
DENSITY,<density>,<reasoning>
TRIAGE_EPISODE,<episode_type>,<content>
TRIAGE_ENTITY,<episode_idx>,<entity_id>
TRIAGE_METADATA,<episode_idx>,<metadata_key>,<metadata_value>
END TRIAGE_RESULTS

Rules:
- Exactly one DENSITY row
- TRIAGE_EPISODE row index is implicit 0-based order (first TRIAGE_EPISODE is episode_idx=0)
- Use TRIAGE_ENTITY and TRIAGE_METADATA rows to attach entities/metadata to TRIAGE_EPISODE rows
- Use CSV quoting when needed
- If nothing is worth remembering, output only the DENSITY row (no TRIAGE_EPISODE rows)
- episode_type MUST be one of: {type_enum}
- Do NOT invent or use any other episode type
- For outcome episodes, include TRIAGE_METADATA rows for strategy, result, prediction_error""".format(type_enum=type_enum)


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

# Coarse-to-fine separator hierarchy for prose/conversation text.
# The splitter tries each level in order and only recurses to a finer
# separator when a piece still exceeds max_size.
_SEPARATORS = [
    "\n\n\n",
    "\n\n",
    "\n",
    ". ",
    "? ",
    "! ",
    "; ",
    ", ",
    " ",
    "",
]


def split_text(text: str, max_size: int, overlap: int = DEFAULT_OVERLAP) -> list[str]:
    """Split text into chunks of at most *max_size* characters.

    Uses a recursive strategy: the text is first split on the coarsest
    natural-language boundary that appears (section breaks → paragraphs →
    lines → sentences → words).  Adjacent small pieces are merged back
    together up to *max_size*.  Any merged piece that still exceeds the
    limit is recursively split with the next finer separator.

    Args:
        text: The text to split.
        max_size: Maximum character count per chunk.
        overlap: Characters of overlap between adjacent chunks.

    Returns:
        List of text chunks.  Returns ``[text]`` as-is when it fits in one
        chunk.  Returns ``[]`` for empty input.
    """
    if not text or not text.strip():
        return []

    if len(text) <= max_size:
        return [text]

    if overlap >= max_size:
        overlap = max_size // 5

    chunks = _recursive_split(text, max_size, _SEPARATORS)

    if overlap <= 0 or len(chunks) <= 1:
        return chunks

    return _apply_overlap(chunks, overlap)


def _recursive_split(text: str, max_size: int, separators: list[str]) -> list[str]:
    """Core recursive splitting logic.

    Picks the first (coarsest) separator present in *text*, splits on it,
    merges small adjacent pieces, then recurses on any piece that is still
    too large using the remaining (finer) separators.
    """
    if len(text) <= max_size:
        return [text]

    if not separators:
        return [text]

    sep = separators[0]
    remaining_seps = separators[1:]

    if sep == "":
        return _hard_split(text, max_size)

    if sep not in text:
        return _recursive_split(text, max_size, remaining_seps)

    raw_pieces = _split_keeping_separator(text, sep)

    merged = _merge_pieces(raw_pieces, max_size)

    final: list[str] = []
    for chunk in merged:
        if len(chunk) <= max_size:
            final.append(chunk)
        else:
            final.extend(_recursive_split(chunk, max_size, remaining_seps))

    return final


def _split_keeping_separator(text: str, sep: str) -> list[str]:
    """Split *text* on *sep*, keeping the separator at the end of each piece."""
    parts = text.split(sep)
    pieces: list[str] = []
    for i, part in enumerate(parts):
        if i < len(parts) - 1:
            pieces.append(part + sep)
        elif part:
            pieces.append(part)
    return pieces


def _merge_pieces(pieces: list[str], max_size: int) -> list[str]:
    """Greedily merge adjacent small pieces into chunks up to *max_size*."""
    merged: list[str] = []
    current = ""
    for piece in pieces:
        if not piece:
            continue
        if current and len(current) + len(piece) > max_size:
            merged.append(current)
            current = piece
        else:
            current += piece
    if current:
        merged.append(current)
    return merged


def _hard_split(text: str, max_size: int) -> list[str]:
    """Character-level split as a last resort."""
    return [text[i:i + max_size] for i in range(0, len(text), max_size)]


def _apply_overlap(chunks: list[str], overlap: int) -> list[str]:
    """Re-introduce overlap between adjacent chunks.

    Each chunk (except the first) is prepended with up to *overlap*
    characters from the end of the preceding chunk.
    """
    result = [chunks[0]]
    for i in range(1, len(chunks)):
        prev = chunks[i - 1]
        tail = prev[-overlap:] if len(prev) >= overlap else prev
        result.append(tail + chunks[i])
    return result


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
        self._valid_types: Optional[set[str]] = set(valid_types) if valid_types else None
        if min_density > 0.0:
            logger.warning(
                "min_density is deprecated and ignored. "
                "The LLM now decides directly what to extract."
            )
        if valid_types:
            self._prompt_template = _build_triage_prompt(valid_types)
            self._default_type = valid_types[0]
        else:
            self._prompt_template = TRIAGE_PROMPT_TEMPLATE
            self._default_type = "observation"

    async def triage(
        self,
        chunk: str,
        existing_concepts: str = "",
        instructions: Optional[str] = None,
    ) -> TriageResult:
        """Score density and extract episodes from a text chunk.

        Args:
            chunk: Raw text to triage.
            existing_concepts: Formatted string of relevant existing concepts
                from recall(), used to judge novelty.
            instructions: Optional caller-provided instructions that steer
                what the triage LLM extracts (e.g. "focus on architectural
                decisions"). Appended to the system prompt.

        Returns:
            TriageResult with density score and extracted episodes.
        """
        if not chunk.strip():
            return TriageResult(density=0.0, reasoning="Empty input", raw_chunk=chunk)

        concepts_text = existing_concepts or "(No existing knowledge yet)"

        prompt = self._prompt_template.format(
            existing_concepts=concepts_text,
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

                ep_type = ep.get("type", self._default_type)
                if self._valid_types and ep_type not in self._valid_types:
                    logger.debug(
                        f"Triage LLM returned invalid episode type '{ep_type}', "
                        f"defaulting to '{self._default_type}'"
                    )
                    ep_type = self._default_type
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
            episodes=[TriageEpisode(content=chunk[:2000], episode_type=self._default_type)],
            raw_chunk=chunk,
        )
