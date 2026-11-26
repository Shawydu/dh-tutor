"""Run one topic's probe as a headless `claude -p` (guide 02 "The headless probe").

Same lockdown as the interactive workspace: the only tools are the engine's. Runs on the
subscription, so no `--bare`. The agenda goes in the prompt because the agent cannot read files.
"""

import json
import re
import subprocess
import tempfile
from dataclasses import astuple
from pathlib import Path
from uuid import UUID

from deepdive.adapters.claude_code.install import LOCKED, REPO, WEB, _json, _persona
from deepdive.config import ConfigError, Secrets
from deepdive.paths import Paths
from deepdive.probe.agenda import AgendaEntry
from deepdive.probe.runner import AgentResult

TIMEOUT_S = 1800


class ClaudeProbe:
    def __init__(self, paths: Paths, repo: Path = REPO, timeout: int = TIMEOUT_S) -> None:
        self.paths = paths
        self.repo = repo
        self.timeout = timeout

    def prompt(self, run_id: UUID, topic_id: UUID, agenda: list[AgendaEntry]) -> str:
        lines = [_persona("_shared"), _persona("probe"), "# This run", ""]
        lines += [f"probe_run_id: {run_id}", f"topic_id: {topic_id}", "", "Agenda:"]
        for n, item in enumerate(agenda, start=1):
            ref = (
                f"question_id {item.question_id}"
                if item.question_id
                else f"agenda_item_id {item.agenda_item_id}"
            )
            lines.append(f"{n}. [{item.kind}] {ref}: {item.question}")
            lines.append(f"   - search: query {item.query!r}, optional {item.keywords!r}")
        return "\n".join(lines)

    def mcp_config(self, run_id: UUID, topic_id: UUID) -> str:
        args = ["run", "--project", str(self.repo), "deepdive", "mcp", "serve"]
        args += ["--probe-run", str(run_id), "--topic", str(topic_id)]
        env = {
            "DEEPDIVE_HOME": str(self.paths.root),
            # expanded by Claude Code from its own env; the value never lands in the file
            "TYPESAFE_API_KEY": "${TYPESAFE_API_KEY:-}",
            "GITHUB_TOKEN": "${GITHUB_TOKEN:-}",
        }
        return _json({"mcpServers": {"deepdive": {"command": "uv", "args": args, "env": env}}})

    def command(self, prompt: str, mcp_config: Path) -> list[str]:
        return [
            "claude", "-p", prompt,
            "--strict-mcp-config", "--mcp-config", str(mcp_config),
            "--allowedTools", "mcp__deepdive__*",
            "--disallowedTools", ",".join(WEB + LOCKED),
            "--permission-mode", "dontAsk",
            "--output-format", "json",
        ]  # fmt: skip

    def run(self, run_id: UUID, topic_id: UUID, agenda: list[AgendaEntry]) -> AgentResult:
        self.paths.workspace.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / "probe-mcp.json"
            config.write_text(self.mcp_config(run_id, topic_id))
            cmd = self.command(self.prompt(run_id, topic_id, agenda), config)
            try:
                done = subprocess.run(
                    cmd, cwd=self.paths.workspace, capture_output=True, text=True, errors="replace",
                    timeout=self.timeout, check=False,
                )  # fmt: skip
            except (subprocess.TimeoutExpired, OSError) as err:
                return AgentResult(False, f"claude did not run to the end: {type(err).__name__}")
        try:
            envelope = json.loads(done.stdout)
        except ValueError:
            envelope = None
        if done.returncode == 0 and isinstance(envelope, dict) and not envelope.get("is_error"):
            return AgentResult(True, str(envelope.get("result", "")))
        if isinstance(envelope, dict) and envelope.get("is_error"):
            raw = str(envelope.get("result", ""))
        else:
            raw = done.stderr or done.stdout
        reason = self._clean(raw)[-500:].strip()  # redact before cutting: no half secret survives
        return AgentResult(False, f"claude failed (exit {done.returncode}): {reason}")

    def _clean(self, text: str) -> str:
        """One line, with the configured secret values blanked."""
        try:
            keys = Secrets.from_env(paths=self.paths)
        except ConfigError:  # refused secrets.env: the run's own Secrets load failed first anyway
            keys = Secrets()
        # shortcut: exact match only, an escaped or encoded secret slips through; widen if seen
        for value in astuple(keys):
            if value:
                text = text.replace(value, "***")
        return re.sub(r"\s+", " ", text).strip()
