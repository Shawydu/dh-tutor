"""Classification: callers use `get_classifier` and the types in `classify.base`, nothing else."""

from deepdive.classify.base import (
    Answer,
    Choice,
    Classifier,
    ClassifierUnavailable,
    ClassifyResult,
    Question,
    YesNo,
)
from deepdive.classify.claude_cli import ClaudeCli
from deepdive.classify.fake import FakeClassifier
from deepdive.classify.jev import Jev
from deepdive.config import Config, Secrets

__all__ = [
    "Answer",
    "Choice",
    "Classifier",
    "ClassifierUnavailable",
    "ClassifyResult",
    "FakeClassifier",
    "FallbackClassifier",
    "Question",
    "YesNo",
    "get_classifier",
]


class FallbackClassifier:
    """Primary first; on error or low confidence, the fallback, or with none (live) a flag.

    All questions in a call must reach auto_threshold, else the whole call falls back.
    """

    def __init__(
        self, primary: Classifier, fallback: Classifier | None, auto_threshold: float
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._threshold = auto_threshold

    def classify(self, state: str, questions: dict[str, Question]) -> ClassifyResult:
        try:
            result = self._primary.classify(state, questions)
        except ClassifierUnavailable:
            if self._fallback is None:
                return ClassifyResult(answers={}, provider="jev", needs_judgement=True)
            return self._fallback.classify(state, questions)
        if all(a.top[1] >= self._threshold for a in result.answers.values()):
            return result
        if self._fallback is None:
            return result.model_copy(update={"needs_judgement": True})
        return self._fallback.classify(state, questions)


def get_classifier(
    config: Config, live_session: bool, secrets: Secrets | None = None
) -> FallbackClassifier:
    """A live session never gets claude_cli: Jev is primary and there is no fallback."""
    secrets = secrets or Secrets.from_env()

    def build(name: str) -> Classifier:
        return Jev(secrets.jev_api_key) if name == "jev" else ClaudeCli()

    if live_session:
        return FallbackClassifier(Jev(secrets.jev_api_key), None, config.classifier.auto_threshold)
    return FallbackClassifier(
        build(config.classifier.provider),
        build(config.classifier.fallback),
        config.classifier.auto_threshold,
    )
