# Guide 03 — The classifier, Jev and the fallback

## The interface

```python
# src/deepdive/classify/base.py
from typing import Protocol, Literal
from pydantic import BaseModel

class Choice(BaseModel):
    kind: Literal["choice"] = "choice"
    prompt: str
    options: list[str]

class YesNo(BaseModel):
    kind: Literal["yesno"] = "yesno"
    prompt: str
    @property
    def options(self) -> list[str]: ...    # ["yes", "no"]

Question = Choice | YesNo

class Answer(BaseModel):
    probs: dict[str, float]        # option -> probability; YesNo uses {"yes": p, "no": 1-p}
    @property
    def top(self) -> tuple[str, float]: ...

class ClassifyResult(BaseModel):
    answers: dict[str, Answer]     # question key -> answer
    provider: str                  # "jev" | "claude" | "fake"
    needs_judgement: bool = False  # live session only: the guide must decide

class Classifier(Protocol):
    def classify(self, state: str, questions: dict[str, Question]) -> ClassifyResult: ...
```

`state` is the text the decision is about. `questions` is a dict of named questions, all answered in one call.

## Where it's used

| Caller | State | Questions |
| --- | --- | --- |
| Question matcher | new question + charter + candidate questions with answer summaries | `is_question` (yes/no), `rel_<candidate_id>` (7-way choice) per candidate, `scope` (in / adjacent / outside) |
| Probe relevance | finding summary + topic's open questions | `relevant` (yes/no), `effect` (answers / supports / weakens / new thread), `target` (choice of question or claim ids) |
| Grading | rubric + your answer | `grade` (wrong / partial / correct / insightful) |

## Providers

- **`tests/fakes.py`** — `FakeClassifier`, deterministic, driven by a dict of canned answers. Test-only; lives outside the package.
- **`jev.py`** — calls Jev over HTTPS with `httpx`. The request and response shapes are vendor-defined; a real request and response is recorded under `tests/fixtures/http/`; re-record it when the vendor changes its API. Map our `Choice` and `YesNo` onto Jev's own question types, and keep every vendor field inside this module.
- **`claude_cli.py`** — runs `claude -p` with `--output-format json --json-schema <schema>` and reads `structured_output`. Slower; used where no live Claude session exists (probe, batch). In a live session the guide is the fallback (see guide 02).

## Fallback policy

```
result = jev.classify(...)               # timeout ~5 s
if error or timeout        -> fallback
if top probability < auto_threshold
                           -> live session: pass to guide as needs_judgement
                           -> headless: claude_cli.classify(...)
```

`auto_threshold` comes from config (default 0.9). Every question in a call must reach it, else the whole call falls back. A live session never calls `claude_cli`: with Jev down it returns an empty result with `needs_judgement=True`. Record the provider and confidence on every stored decision (`question_edge.classifier`, `knowledge_evidence.grader`), so you can tune the threshold later from real data.

## Tuning

Tune `classifier.auto_threshold` on your own questions. A labelled set of question pairs with an accuracy and calibration report per provider is planned, not built.

## Background on Jev

Jev is TypeSafe AI's decision model. It returns typed answers with probabilities instead of generated text and is offered through TypeSafe and OpenRouter. Published accuracy and speed numbers are mostly the vendor's own, which is why the threshold is tuned on your data.

- https://www.cometapi.com/en/models/typesafe-ai/jev
- https://aimlapi.com/blog/what-is-jev
- https://benchlm.ai/blog/posts/what-is-jev
