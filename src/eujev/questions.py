"""Typed questions that supply their JSON type discriminator automatically."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, TypeAlias

JSONValue: TypeAlias = str | int | float | bool | None | list["JSONValue"] | dict[str, "JSONValue"]


class QuestionType(str, Enum):
    """The three question and answer types supported by System One."""

    CHOICE = "choice"
    NOUL = "noul"
    SCORE = "score"


@dataclass
class ChoiceQuestion:
    """Select one of two to ten named options. A null description uses its name."""

    instructions: JSONValue = None
    criteria: dict[str, JSONValue] | None = None
    type: ClassVar[QuestionType] = QuestionType.CHOICE

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "type": self.type.value,
            "instructions": self.instructions,
            "criteria": self.criteria,
        }


@dataclass
class NoulQuestion:
    """Estimate the probability that a condition is true (between zero and one)."""

    instructions: JSONValue = None
    criteria: dict[str, JSONValue] | None = None
    type: ClassVar[QuestionType] = QuestionType.NOUL

    def to_dict(self) -> dict[str, JSONValue]:
        result: dict[str, JSONValue] = {
            "type": self.type.value,
            "instructions": self.instructions,
        }
        if self.criteria:
            result["criteria"] = self.criteria
        return result


@dataclass
class ScoreQuestion:
    """Estimate a position on an ordered scale of two to ten levels, low to high."""

    instructions: JSONValue = None
    criteria: list[JSONValue] | None = None
    type: ClassVar[QuestionType] = QuestionType.SCORE

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "type": self.type.value,
            "instructions": self.instructions,
            "criteria": self.criteria,
        }


Question: TypeAlias = ChoiceQuestion | NoulQuestion | ScoreQuestion
