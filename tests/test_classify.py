"""Classifier providers and the fallback policy; HTTP is answered from the fixture."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from deepdive.classify import (
    Answer,
    Choice,
    ClassifierUnavailable,
    ClassifyResult,
    FakeClassifier,
    FallbackClassifier,
    Question,
    YesNo,
    get_classifier,
)
from deepdive.classify.claude_cli import ClaudeCli
from deepdive.classify.jev import Jev
from deepdive.cli import app
from deepdive.config import Config, Secrets

FIXTURE = json.loads((Path(__file__).parent / "fixtures/http/jev_systemone.json").read_text())
KEY = "tsk-super-secret-key"
QUESTIONS: dict[str, Question] = {
    "is_question": YesNo(prompt="Is the text a question?"),
    "scope": Choice(
        prompt="How does the text relate to the topic?", options=["in", "adjacent", "outside"]
    ),
}


def jev_with(handler: Any, key: str | None = KEY) -> Jev:
    return Jev(key, transport=httpx.MockTransport(handler))


def ok(_: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=FIXTURE["response"])


def answer(top: str, p: float) -> Answer:
    return Answer(probs={top: p, "other": 1 - p})


def canned(p: float, provider: str = "fake") -> FakeClassifier:
    return FakeClassifier({k: answer("a", p) for k in QUESTIONS})


def test_jev_parses_recorded_fixture_and_sends_documented_request() -> None:
    """Jev maps the recorded response to Answers and sends the documented body and bearer key."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok(request)

    result = jev_with(handler).classify(FIXTURE["request"]["state"], QUESTIONS)
    assert result.provider == "jev"
    assert result.answers["is_question"].probs == pytest.approx({"yes": 0.97, "no": 0.03})
    assert result.answers["scope"].top == ("in", 0.92)
    body = json.loads(seen[0].content)
    assert body["questions"] == FIXTURE["request"]["questions"]
    assert seen[0].headers["authorization"] == f"Bearer {KEY}"


def test_jev_retries_once_on_5xx() -> None:
    """A single 5xx is retried; a second answer is used."""
    codes = iter([503, 200])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(next(codes), json=FIXTURE["response"])

    assert jev_with(handler).classify("s", QUESTIONS).provider == "jev"


BAD_PROB = {"answers": {**FIXTURE["response"]["answers"], "is_question": {"noul": 1.5}}}


def boom(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectTimeout(f"timed out for {request.headers['authorization']}")


@pytest.mark.parametrize(
    ("handler", "key"),
    [
        (lambda r: httpx.Response(500), KEY),
        (lambda r: httpx.Response(401, text=f"bad key {KEY}"), KEY),
        (lambda r: httpx.Response(200, json={"answers": {}}), KEY),
        (boom, KEY),
        (ok, None),
        (lambda r: httpx.Response(200, text=f"<html>{KEY}"), KEY),
        (lambda r: httpx.Response(200, json=BAD_PROB), KEY),
    ],
    ids=["5xx-twice", "4xx", "malformed", "timeout", "no-key", "not-json", "prob-out-of-range"],
)
def test_jev_failures_are_unavailable_and_never_leak_the_key(handler: Any, key: str | None) -> None:
    """Every failure becomes ClassifierUnavailable and the key is in neither message nor chain."""
    with pytest.raises(ClassifierUnavailable) as info:
        jev_with(handler, key).classify("s", QUESTIONS)
    assert KEY not in repr(info.value)
    assert KEY not in str(info.getrepr())
    assert info.value.__cause__ is None


@pytest.mark.parametrize(
    ("primary", "live", "expect_provider", "needs_judgement"),
    [
        ("error", False, "claude", False),
        ("low", False, "claude", False),
        ("low", True, "jev", True),
        ("high", True, "jev", False),
        ("high", False, "jev", False),
    ],
    ids=["error-headless", "low-headless", "low-live", "high-live", "high-headless"],
)
def test_fallback_policy(
    primary: str, live: bool, expect_provider: str, needs_judgement: bool
) -> None:
    """Error or low confidence goes to Claude headless, or is flagged in a live session."""

    class Primary:
        def classify(self, state: str, questions: dict[str, Question]) -> ClassifyResult:
            if primary == "error":
                raise ClassifierUnavailable("down")
            p = 0.95 if primary == "high" else 0.6
            return ClassifyResult(answers={k: answer("a", p) for k in questions}, provider="jev")

    class Claude:
        def classify(self, state: str, questions: dict[str, Question]) -> ClassifyResult:
            assert not live, "claude_cli must not run in a live session"
            return ClassifyResult(answers={k: answer("a", 1) for k in questions}, provider="claude")

    result = FallbackClassifier(Primary(), None if live else Claude(), 0.9).classify("s", QUESTIONS)
    assert (result.provider, result.needs_judgement) == (expect_provider, needs_judgement)


def test_fallback_live_session_with_primary_down_asks_for_judgement() -> None:
    """With no Jev answer in a live session the result is empty and flagged for the guide."""

    class Down:
        def classify(self, state: str, questions: dict[str, Question]) -> ClassifyResult:
            raise ClassifierUnavailable("down")

    result = FallbackClassifier(Down(), None, 0.9).classify("s", QUESTIONS)
    assert result.answers == {} and result.needs_judgement


def test_fake_answers_by_key_and_raises_on_unknown_question() -> None:
    """The fake returns canned answers and refuses a question it has none for."""
    assert canned(0.8).classify("s", QUESTIONS).provider == "fake"
    with pytest.raises(LookupError, match="is_question"):
        FakeClassifier({}).classify("s", QUESTIONS)


@pytest.mark.parametrize(
    ("live", "provider", "fallback", "expect"),
    [
        (True, "claude", "claude", ("Jev", None)),
        (True, "jev", "claude", ("Jev", None)),
        (False, "jev", "claude", ("Jev", "ClaudeCli")),
        (False, "claude", "jev", ("ClaudeCli", "Jev")),
    ],
    ids=["live-claude", "live-jev", "headless-default", "headless-swapped"],
)
def test_get_classifier_never_wires_claude_cli_in_a_live_session(
    live: bool, provider: str, fallback: str, expect: tuple[str, str | None]
) -> None:
    """Live sessions get Jev only; headless honours the configured provider and fallback."""
    config = Config.model_validate({"classifier": {"provider": provider, "fallback": fallback}})
    clf = get_classifier(config, live_session=live, secrets=Secrets(jev_api_key=KEY))
    names = tuple(type(p).__name__ if p else None for p in (clf._primary, clf._fallback))
    assert names == expect


def test_claude_cli_schema_is_valid_for_a_mixed_question_set() -> None:
    """The schema has one required {choice, confidence} object per question, enums per options."""
    schema: Any = ClaudeCli.schema(QUESTIONS)
    assert schema["required"] == ["is_question", "scope"]
    assert schema["properties"]["is_question"]["properties"]["choice"]["enum"] == ["yes", "no"]
    assert schema["properties"]["scope"]["properties"]["choice"]["enum"] == [
        "in",
        "adjacent",
        "outside",
    ]
    json.dumps(schema)  # serialisable for --json-schema
    prompt = ClaudeCli.prompt("hello", QUESTIONS)
    assert "hello" in prompt and "scope" in prompt


def envelope(out: Any, is_error: bool = False) -> str:
    return json.dumps({"type": "result", "is_error": is_error, "structured_output": out})


def test_claude_cli_normalises_confidence_to_probabilities() -> None:
    """Top option gets the stated confidence; the rest share the remainder."""
    out = {
        "is_question": {"choice": "yes", "confidence": 0.8},
        "scope": {"choice": "in", "confidence": 0.7},
    }
    result = ClaudeCli.parse(envelope(out), QUESTIONS)
    assert result.answers["is_question"].probs == pytest.approx({"yes": 0.8, "no": 0.2})
    assert result.answers["scope"].probs == pytest.approx(
        {"in": 0.7, "adjacent": 0.15, "outside": 0.15}
    )


@pytest.mark.parametrize(
    "stdout",
    [
        "not json",
        envelope({}, is_error=True),
        envelope({"is_question": {"choice": "maybe", "confidence": 0.5}}),
        envelope({"is_question": {"choice": "yes", "confidence": 3}}),
    ],
    ids=["not-json", "is-error", "bad-option", "bad-confidence"],
)
def test_claude_cli_rejects_bad_output(stdout: str) -> None:
    """Unparseable or off-schema output is ClassifierUnavailable, not a crash."""
    with pytest.raises(ClassifierUnavailable):
        ClaudeCli.parse(stdout, QUESTIONS)


def test_classify_try_requires_well_formed_choice() -> None:
    """The CLI rejects a --choice without at least two options."""
    result = CliRunner().invoke(app, ["classify", "try", "x", "--choice", "k:only"])
    assert result.exit_code == 2
