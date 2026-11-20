"""The classifier interface and its result types (guide 03)."""

from typing import Literal, Protocol

from pydantic import BaseModel, Field


class ClassifierUnavailable(Exception):
    """A provider could not answer (timeout, 5xx, bad output, no key); never carries a secret."""


class Choice(BaseModel):
    kind: Literal["choice"] = "choice"
    prompt: str
    options: list[str] = Field(min_length=2)


class YesNo(BaseModel):
    kind: Literal["yesno"] = "yesno"
    prompt: str

    @property
    def options(self) -> list[str]:
        return ["yes", "no"]


Question = Choice | YesNo


class Answer(BaseModel):
    probs: dict[str, float]  # option -> probability; YesNo uses {"yes": p, "no": 1-p}

    @property
    def top(self) -> tuple[str, float]:
        return max(self.probs.items(), key=lambda kv: kv[1])


class ClassifyResult(BaseModel):
    answers: dict[str, Answer]  # question key -> answer
    provider: str  # "jev" | "claude" | "fake"
    needs_judgement: bool = False  # live session: confidence too low, the guide must decide


class Classifier(Protocol):
    def classify(self, state: str, questions: dict[str, Question]) -> ClassifyResult: ...
