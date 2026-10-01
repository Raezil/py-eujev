"""Request and response models for POST /v1/systemone."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from ._constants import DEFAULT_MODEL
from .questions import JSONValue, Question


@dataclass
class DecisionRequest:
    """A decision payload. The service validates input counts and constraints.

    State normally contains a nonempty string, JSON object, or array. An empty
    model selects DEFAULT_MODEL when serialized, without changing this object.
    """

    state: JSONValue
    questions: dict[str, Question]
    model: str = ""

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "model": self.model or DEFAULT_MODEL,
            "state": self.state,
            "questions": {name: question.to_dict() for name, question in self.questions.items()},
        }


@dataclass
class Answer:
    """An answer. Numeric None values mean absent; zero is a valid result.

    Unknown type strings are retained to allow forward-compatible responses.
    Compare type with QuestionType.CHOICE, NOUL, or SCORE before using a field.
    """

    type: str = ""
    choice: str = ""
    noul: float | None = None
    score: float | None = None
    confidence: float | None = None
    probabilities: dict[str, float] | None = None
    legend: dict[str, str] | None = None

    def to_dict(self) -> dict[str, JSONValue]:
        result: dict[str, JSONValue] = {"type": self.type}
        if self.choice:
            result["choice"] = self.choice
        for name in ("noul", "score", "confidence"):
            value = getattr(self, name)
            if value is not None:
                result[name] = value
        if self.probabilities:
            result["probabilities"] = dict(self.probabilities)
        if self.legend:
            result["legend"] = dict(self.legend)
        return result


@dataclass
class Usage:
    """Tokens counted by the service."""

    input_tokens: int = 0
    output_tokens: int = 0

    def to_dict(self) -> dict[str, JSONValue]:
        return {"input_tokens": self.input_tokens, "output_tokens": self.output_tokens}


@dataclass
class Metadata:
    """Server processing details. cost_eur remains an exact decimal string."""

    request_id: str = ""
    mode: str = ""
    latency_ms: int = 0
    cost_eur: str = ""

    def to_dict(self) -> dict[str, JSONValue]:
        result: dict[str, JSONValue] = {
            "request_id": self.request_id,
            "mode": self.mode,
            "latency_ms": self.latency_ms,
        }
        if self.cost_eur:
            result["cost_eur"] = self.cost_eur
        return result


@dataclass
class DecisionResponse:
    """Named model answers and request accounting."""

    model: str = ""
    answers: dict[str, Answer] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)
    meta: Metadata = field(default_factory=Metadata)

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "model": self.model,
            "answers": {name: answer.to_dict() for name, answer in self.answers.items()},
            "usage": self.usage.to_dict(),
            "meta": self.meta.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> DecisionResponse:
        """Decode known fields, rejecting incorrect types and ignoring new fields.

        Missing or null fields use the Go SDK's zero values. A null top-level
        response is invalid. Raises TypeError or ValueError for invalid data.
        """
        if not isinstance(payload, dict):
            raise TypeError("expected a decision response object")
        answers = _object(payload.get("answers"), "answers")
        usage = _object(payload.get("usage"), "usage")
        meta = _object(payload.get("meta"), "meta")
        return cls(
            model=_string(payload.get("model"), "model"),
            answers={name: _answer(value, name) for name, value in answers.items()},
            usage=Usage(
                input_tokens=_integer(usage.get("input_tokens"), "usage.input_tokens"),
                output_tokens=_integer(usage.get("output_tokens"), "usage.output_tokens"),
            ),
            meta=Metadata(
                request_id=_string(meta.get("request_id"), "meta.request_id"),
                mode=_string(meta.get("mode"), "meta.mode"),
                latency_ms=_integer(meta.get("latency_ms"), "meta.latency_ms"),
                cost_eur=_string(meta.get("cost_eur"), "meta.cost_eur"),
            ),
        )


def _object(value: Any, path: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise TypeError(f"{path} must be an object")
    return value


def _string(value: Any, path: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError(f"{path} must be a string")
    return value


def _integer(value: Any, path: str) -> int:
    if value is None:
        return 0
    if type(value) is not int or not -(2**63) <= value < 2**63:
        raise TypeError(f"{path} must be a signed 64-bit integer")
    return value


def _number(value: Any, path: str) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float):
        raise TypeError(f"{path} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{path} must be finite")
    return result


def _answer(value: Any, name: str) -> Answer:
    path = f"answers.{name}"
    data = _object(value, path)
    probabilities = data.get("probabilities")
    legend = data.get("legend")
    return Answer(
        type=_string(data.get("type"), f"{path}.type"),
        choice=_string(data.get("choice"), f"{path}.choice"),
        noul=_number(data.get("noul"), f"{path}.noul"),
        score=_number(data.get("score"), f"{path}.score"),
        confidence=_number(data.get("confidence"), f"{path}.confidence"),
        probabilities=(
            {
                key: _number(number, f"{path}.probabilities.{key}") or 0.0
                for key, number in _object(probabilities, f"{path}.probabilities").items()
            }
            if probabilities is not None
            else None
        ),
        legend=(
            {
                key: _string(label, f"{path}.legend.{key}")
                for key, label in _object(legend, f"{path}.legend").items()
            }
            if legend is not None
            else None
        ),
    )
