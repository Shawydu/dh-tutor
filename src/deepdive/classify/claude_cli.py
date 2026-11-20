"""Headless Claude provider: `claude -p ... --json-schema`, reading `structured_output`.

Slow; for runs with no live Claude session (probe, batch). Runs on the user's subscription, so
no `--bare` (guide 02). Each answer is {"choice": <option>, "confidence": 0-1}; the top option
gets the stated confidence and the others share the remainder.
"""

import json
import subprocess
import tempfile

from deepdive.classify.base import Answer, ClassifierUnavailable, ClassifyResult, Question

TIMEOUT_S = 180
_NO_TOOLS = "WebSearch,WebFetch,Bash,Edit,Write,Read,Glob,Grep,NotebookEdit"


class ClaudeCli:
    name = "claude"

    @staticmethod
    def schema(questions: dict[str, Question]) -> dict[str, object]:
        def one(q: Question) -> dict[str, object]:
            return {
                "type": "object",
                "properties": {
                    "choice": {"type": "string", "enum": q.options},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                },
                "required": ["choice", "confidence"],
                "additionalProperties": False,
            }

        return {
            "type": "object",
            "properties": {key: one(q) for key, q in questions.items()},
            "required": list(questions),
            "additionalProperties": False,
        }

    @staticmethod
    def prompt(state: str, questions: dict[str, Question]) -> str:
        lines = [
            "Answer every question about the text between the markers. For each, pick one "
            "option and give your confidence (0 to 1) that it is right.",
            "<state>",
            state,
            "</state>",
        ]
        for key, q in questions.items():
            lines.append(f"- {key}: {q.prompt} Options: {', '.join(q.options)}")
        return "\n".join(lines)

    @staticmethod
    def parse(stdout: str, questions: dict[str, Question]) -> ClassifyResult:
        try:
            envelope = json.loads(stdout)
            if envelope.get("is_error"):
                raise ValueError
            out = envelope["structured_output"]
            answers: dict[str, Answer] = {}
            for key, q in questions.items():
                choice, conf = out[key]["choice"], float(out[key]["confidence"])
                if choice not in q.options or not 0 <= conf <= 1:
                    raise ValueError
                rest = (1 - conf) / max(len(q.options) - 1, 1)
                answers[key] = Answer(probs={o: conf if o == choice else rest for o in q.options})
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ClassifierUnavailable("claude: output did not match the schema") from None
        return ClassifyResult(answers=answers, provider="claude")

    def classify(self, state: str, questions: dict[str, Question]) -> ClassifyResult:
        cmd = [
            "claude", "-p", self.prompt(state, questions),
            "--output-format", "json",
            "--json-schema", json.dumps(self.schema(questions)),
            "--disallowedTools", _NO_TOOLS,
            "--permission-mode", "dontAsk",
            "--strict-mcp-config",  # no --mcp-config given: load no MCP servers
        ]  # fmt: skip
        try:
            # neutral cwd: no project CLAUDE.md, hooks or .mcp.json get picked up
            with tempfile.TemporaryDirectory() as cwd:
                done = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=TIMEOUT_S, cwd=cwd
                )
        except (OSError, subprocess.TimeoutExpired) as err:
            raise ClassifierUnavailable(f"claude: {type(err).__name__}") from None
        if done.returncode != 0:
            raise ClassifierUnavailable(f"claude: exit code {done.returncode}")
        return self.parse(done.stdout, questions)
