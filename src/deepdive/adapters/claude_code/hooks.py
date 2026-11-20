"""The Claude Code hook commands: `deepdive hook user-prompt` and `deepdive hook session-start`.

A hook must never block the user's message: any failure or timeout yields no output and is logged
(error class only, never prompt text).
"""

import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from deepdive import clock
from deepdive.classify import Classifier, get_classifier
from deepdive.config import load_config
from deepdive.matcher.matcher import Matcher
from deepdive.paths import Paths
from deepdive.store.db import Database
from deepdive.store.enums import QuestionAsker
from deepdive.store.repos import Store

TIMEOUT = 8.0  # seconds; Claude Code's own limit for the hook is set a little higher
RECENT = 5
FALLBACK = "Matcher unavailable. If this message is a question, call question_record."


def _context(text: str) -> str:
    return json.dumps(
        {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit", "additionalContext": text}}
    )


class Hooks:
    def __init__(self, paths: Paths, classifier: Classifier | None = None) -> None:
        self.paths = paths
        self.classifier = classifier  # tests pass a fake, like create_server

    def user_prompt(self, raw: str) -> str:
        """The hook's stdout for a UserPromptSubmit payload; empty when there is nothing to add."""
        attached: list[bool] = []
        out = self._guarded("user-prompt", lambda: self._user_prompt(raw, attached))
        # the matcher failed for a live session: tell the guide so it records the question itself
        return out or (_context(FALLBACK) if attached else "")

    def session_start(self, raw: str) -> str:
        """The plain-text brief for a SessionStart payload."""
        try:
            agent_id = str(UUID(json.loads(raw)["session_id"]))
        except Exception as exc:
            self._log("session-start", type(exc).__name__)
            return ""
        line = f"agent_session_id: {agent_id}"
        return self._guarded("session-start", lambda: f"{self._brief()}\n{line}") or line

    def _user_prompt(self, raw: str, attached: list[bool]) -> str:
        payload = json.loads(raw)
        prompt: str = payload["prompt"]
        if not prompt.strip() or prompt.lstrip().startswith(
            "/"
        ):  # a slash command is not a question
            return ""
        self.paths.ensure_dirs()
        with Database(self.paths.db) as db:
            db.migrate()  # a fresh home has no tables until the MCP server has run
            store = Store(db)
            link = store.agent_sessions.get(UUID(payload["session_id"]))
            session = store.sessions.get(link.session_id) if link else None
            if session is None or session.ended_at is not None:
                return ""
            attached.append(True)
            config = load_config(self.paths.config)
            classifier = self.classifier or get_classifier(config, live_session=True)
            result = Matcher(store, classifier, config).match(
                prompt, session.topic_id, QuestionAsker.USER, session.id
            )
        context = result.render_context()
        return json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context,
                }
            }
        )

    def _brief(self) -> str:
        self.paths.ensure_dirs()
        with Database(self.paths.db) as db:
            db.migrate()
            topics = Store(db).topics.overview()
        if not topics:
            return "deepdive: no topics yet. Start one with /dive <topic>."
        epoch = datetime.min.replace(tzinfo=UTC)
        recent = sorted(topics, key=lambda t: t.last_session_at or epoch, reverse=True)[:RECENT]
        lines = ["deepdive: recent topics"]
        for t in recent:
            when = t.last_session_at.date().isoformat() if t.last_session_at else "no sessions"
            lines.append(f"- {t.title} ({t.status}, last session {when})")
        lines.append(f"Continue the most recent with: /resume {recent[0].title}")
        return "\n".join(lines)

    def _guarded(self, name: str, work: Callable[[], str]) -> str:
        """Run `work` in a daemon thread for at most TIMEOUT seconds; "" on error or timeout."""
        out: list[str] = []

        def target() -> None:
            try:
                out.append(work())
            except Exception as exc:
                self._log(name, type(exc).__name__)

        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        # shortcut: a timed-out match may still commit late, so a guide that also records makes a
        # rare duplicate question; upgrade (cancel or dedupe) if duplicates show up.
        thread.join(TIMEOUT)
        if thread.is_alive():
            self._log(name, "timeout")
        return out[0] if out else ""

    def _log(self, name: str, what: str) -> None:
        try:
            self.paths.ensure_dirs()
            with (self.paths.logs / "hooks.log").open("a", encoding="utf-8") as log:
                log.write(f"{clock.now_iso()} {name} {what}\n")
        except OSError:
            pass  # a hook that cannot log must still not block the message
