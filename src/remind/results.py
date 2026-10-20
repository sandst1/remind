"""Structured public workflow results."""

from dataclasses import dataclass, field
from typing import Any


def public_model(model: Any) -> dict:
    result = model.to_dict()
    result.pop("embedding", None)
    if getattr(model, "_revision", None):
        result["revision"] = model._revision
    return result


@dataclass
class BatchRememberResult:
    results: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"results": [result.to_dict() for result in self.results]}


@dataclass
class RecallResult:
    text: str
    concepts: list[Any] = field(default_factory=list)
    episodes: list[Any] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    explanation: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"text": self.text,
                "concepts": [{"concept": public_model(item.concept), "score": item.activation,
                              "source": item.source, "hops": item.hops} for item in self.concepts],
                "episodes": [{"episode": public_model(getattr(item, "episode", item)),
                              "score": getattr(item, "score", None)} for item in self.episodes],
                "warnings": self.warnings, "explanation": self.explanation}

    def __str__(self) -> str:
        return self.text
