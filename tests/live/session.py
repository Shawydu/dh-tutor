"""Drive a scripted learner through a real `claude -p` session in a throwaway DEEPDIVE_HOME."""

import json
import os
import sqlite3
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from deepdive.config import Secrets
from deepdive.paths import Paths

REPO = Path(__file__).resolve().parents[2]
TURN_TIMEOUT_S = 600


class JourneyError(AssertionError):
    pass


@dataclass
class ToolCall:
    name: str
    input: dict[str, Any]
    result: str = ""
    error: bool = False


@dataclass
class Hook:
    name: str
    exit_code: int
    output: str


@dataclass
class Turn:
    session_id: str = ""
    num_turns: int = 0
    subtype: str = ""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    hooks: list[Hook] = field(default_factory=list)


def parse_stream(path: Path) -> Turn:
    """Fold one `--output-format stream-json --include-hook-events` stream into a Turn."""
    turn = Turn()
    calls: dict[str, ToolCall] = {}
    texts: list[str] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        kind, sub = event.get("type"), event.get("subtype")
        turn.session_id = event.get("session_id") or turn.session_id
        if sub == "hook_response":
            turn.hooks.append(Hook(event["hook_name"], event["exit_code"], event["output"]))
        elif kind == "result":
            turn.subtype, turn.num_turns = sub or "", event.get("num_turns", 0)
        elif kind in ("assistant", "user") and isinstance(event["message"]["content"], list):
            for block in event["message"]["content"]:
                if block["type"] == "tool_use":
                    calls[block["id"]] = call = ToolCall(block["name"], block["input"])
                    turn.tool_calls.append(call)
                elif block["type"] == "text":
                    texts.append(block["text"])
                elif block["type"] == "tool_result" and block["tool_use_id"] in calls:
                    body, call = block["content"], calls[block["tool_use_id"]]
                    call.error = block.get("is_error", False)
                    call.result = (
                        body
                        if isinstance(body, str)
                        else "".join(b.get("text", "") for b in body)  # MCP text blocks
                    )
    turn.text = "\n".join(texts)
    return turn


def make_home(root: Path) -> Path:
    """A fresh DEEPDIVE_HOME with the workspace installed; DEEPDIVE_LIVE_SNAPSHOT seeds its db."""
    home = root / "home"
    home.mkdir()
    snapshot = os.environ.get("DEEPDIVE_LIVE_SNAPSHOT")
    if snapshot:
        src = sqlite3.connect(f"file:{Path(snapshot).resolve()}?mode=ro", uri=True)
        dst = sqlite3.connect(Paths(home).db)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
    subprocess.run(
        ["uv", "run", "--project", str(REPO), "deepdive", "init"],
        env=os.environ | {"DEEPDIVE_HOME": str(home)},
        check=True, capture_output=True, text=True,
    )  # fmt: skip
    return home


class Session:
    """One journey: `turn(text)` runs `claude -p` (then `--resume`) in the workspace."""

    def __init__(
        self, home: Path, journey: str, model: str | None = None, max_turns: int = 40
    ) -> None:
        self.home, self.journey, self.cap, self.left = home, journey, max_turns, max_turns
        self.model = model or os.environ.get("DEEPDIVE_LIVE_MODEL", "haiku")
        self.workspace = Paths(home).workspace
        self.session_id = ""
        self.count = 0
        # Secrets come from the real home: the throwaway home has no secrets.env.
        keys = Secrets.from_env()
        self.secrets = {
            k: v
            for k, v in {
                "TYPESAFE_API_KEY": keys.jev_api_key,
                "GITHUB_TOKEN": keys.github_token,
            }.items()
            if v
        }

    def _command(self, text: str) -> list[str]:
        settings = json.loads((self.workspace / ".claude" / "settings.json").read_text())
        # shortcut: a temp workspace is untrusted so Claude ignores its allow list; pass it by hand
        allowed = ",".join(settings["permissions"]["allow"])
        cmd = [
            "claude", "-p", text, "--model", self.model, "--max-turns", str(self.left),
            "--output-format", "stream-json", "--verbose", "--include-hook-events",
            "--setting-sources", "project", "--strict-mcp-config", "--mcp-config", ".mcp.json",
            "--allowedTools", allowed, "--permission-mode", "dontAsk",
        ]  # fmt: skip
        return cmd + (["--resume", self.session_id] if self.session_id else [])

    def turn(self, text: str) -> Turn:
        if self.left <= 0:
            raise JourneyError(f"journey {self.journey!r} used its cap of {self.cap} agent turns")
        try:
            done = subprocess.run(
                self._command(text), cwd=self.workspace, capture_output=True, text=True,
                errors="replace", timeout=TURN_TIMEOUT_S, check=False,
                env=os.environ | {"DEEPDIVE_HOME": str(self.home)} | self.secrets,
            )  # fmt: skip
        except subprocess.TimeoutExpired:
            raise JourneyError(
                f"journey {self.journey!r}: turn ran past {TURN_TIMEOUT_S}s"
            ) from None
        leaked = [k for k, v in self.secrets.items() if v in done.stdout + done.stderr]
        if leaked:  # checked before anything is saved or printed
            raise JourneyError(f"journey {self.journey!r}: secret value in claude output: {leaked}")
        self.count += 1
        raw = self.home.parent / f"turn{self.count}.jsonl"
        raw.write_text(done.stdout)
        try:
            result = parse_stream(raw)
        except (ValueError, KeyError) as e:
            raise JourneyError(f"unparseable stream {raw} ({e!r}): {done.stderr[-300:]}") from None
        if result.subtype == "error_max_turns":
            raise JourneyError(f"journey {self.journey!r} hit its cap of {self.cap} agent turns")
        if done.returncode != 0:
            raise JourneyError(f"claude exited {done.returncode}: {done.stderr[-500:]}")
        self.session_id = result.session_id or self.session_id
        self.left -= result.num_turns  # num_turns counts this call only, also under --resume
        return result
