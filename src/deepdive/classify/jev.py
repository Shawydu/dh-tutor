"""Jev (TypeSafe AI) provider. Every vendor field stays in this module.

Docs, read 2026-11-19 (vendor's own; TypeSafe has no standalone OpenAPI page, so the primitive
pages and quickstart are the reference):
  https://docs.typesafe.ai/introduction/quickstart.md   endpoint, auth, body
  https://docs.typesafe.ai/primitives/choice            choice question and answer
  https://docs.typesafe.ai/primitives/noul.md           yes/no question and answer

Request: POST https://api.typesafe.ai/v1/systemone
  Authorization: Bearer <key>   (env var TYPESAFE_API_KEY), Content-Type: application/json
  {"model": "jev-latest",
   "state": "<text being judged>",
   "questions": {"<id>": {"type": "choice", "instructions": "<question>",
                          "criteria": {"<option>": "<description>", ...}},
                 "<id>": {"type": "noul", "instructions": "<yes/no question>"}}}
Response (200):
  {"model": "jev-1.13.0",
   "answers": {"<id>": {"type": "choice", "choice": "<option>", "confidence": 0.0-1.0,
                        "probabilities": {"<option>": p, ...}},
               "<id>": {"type": "noul", "noul": p_yes}},
   "usage": {"input_tokens": n, "output_tokens": n}}
Mapping: Choice -> type "choice" (criteria maps each option to itself; we hold no richer text);
YesNo -> type "noul", probs {"yes": p, "no": 1-p}. Choice probabilities are used as given.
Not in the docs I could read: HTTP error codes and the error body shape; any non-200 is treated
as unavailable, 5xx gets one retry.

The recorded fixture tests/fixtures/http/jev_systemone.json is hand-written from these docs,
not a real capture (no key was available when V0-07 was built).
"""

import httpx

from deepdive.classify.base import Answer, ClassifierUnavailable, ClassifyResult, Question, YesNo

URL = "https://api.typesafe.ai/v1/systemone"
TIMEOUT_S = 5.0
MODEL = "jev-latest"


class Jev:
    name = "jev"

    def __init__(self, api_key: str | None, transport: httpx.BaseTransport | None = None) -> None:
        self._key = api_key
        self._transport = transport

    @staticmethod
    def _question(question: Question) -> dict[str, object]:
        if isinstance(question, YesNo):
            return {"type": "noul", "instructions": question.prompt}
        return {
            "type": "choice",
            "instructions": question.prompt,
            "criteria": {option: option for option in question.options},
        }

    def _post(self, body: dict[str, object]) -> httpx.Response:
        """POST, one retry on 5xx. Errors are rebuilt without the request, so no header leaks."""
        if not self._key:
            raise ClassifierUnavailable("jev: TYPESAFE_API_KEY is not set")
        headers = {"Authorization": f"Bearer {self._key}"}
        resp: httpx.Response | None = None
        for _ in range(2):
            try:
                with httpx.Client(timeout=TIMEOUT_S, transport=self._transport) as client:
                    resp = client.post(URL, json=body, headers=headers)
            except httpx.HTTPError as err:
                raise ClassifierUnavailable(f"jev: {type(err).__name__}") from None
            if resp.status_code < 500:
                break
        assert resp is not None
        if resp.status_code != 200:
            raise ClassifierUnavailable(f"jev: HTTP {resp.status_code}")
        return resp

    def classify(self, state: str, questions: dict[str, Question]) -> ClassifyResult:
        body: dict[str, object] = {
            "model": MODEL,
            "state": state,
            "questions": {key: self._question(q) for key, q in questions.items()},
        }
        try:
            data = self._post(body).json()
        except ValueError:
            raise ClassifierUnavailable("jev: response was not JSON") from None
        return self.parse(data, questions)

    @staticmethod
    def parse(data: dict[str, object], questions: dict[str, Question]) -> ClassifyResult:
        answers: dict[str, Answer] = {}
        try:
            raw = data["answers"]
            assert isinstance(raw, dict)
            for key, question in questions.items():
                item = raw[key]
                if isinstance(question, YesNo):
                    p = float(item["noul"])
                    probs = {"yes": p, "no": 1 - p}
                else:
                    probs = {o: float(item["probabilities"][o]) for o in question.options}
                if not all(0 <= v <= 1 for v in probs.values()):  # also rejects NaN
                    raise ValueError
                answers[key] = Answer(probs=probs)
        except (KeyError, TypeError, ValueError, AssertionError):
            raise ClassifierUnavailable(
                "jev: response did not match the requested questions"
            ) from None
        return ClassifyResult(answers=answers, provider="jev")
