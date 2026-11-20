"""Deterministic classifier for tests: canned answers by question key."""

from deepdive.classify.base import Answer, ClassifyResult, Question


class FakeClassifier:
    def __init__(self, answers: dict[str, Answer]) -> None:
        self._answers = answers

    def classify(self, state: str, questions: dict[str, Question]) -> ClassifyResult:
        missing = [key for key in questions if key not in self._answers]
        if missing:
            raise LookupError(f"no canned answer for question(s): {', '.join(missing)}")
        return ClassifyResult(answers={k: self._answers[k] for k in questions}, provider="fake")
