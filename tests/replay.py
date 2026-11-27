"""Replay a recorded stream's engine tool calls through the in-process MCP server, offline."""

import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from live.session import parse_stream
from test_ledger_server import Ledger

PREFIX = "mcp__deepdive__"
NEEDS_WEB = {"search", "fetch"}  # skipped: they need the network; dive-intake records none
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


class ReplayError(AssertionError):
    pass


def assert_dive_intake_state(db_path: Path) -> None:
    """End state of the journey; shared by the live test and the offline replay."""
    with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as db:
        assert db.execute("SELECT count(*) FROM topic").fetchone() == (1,)
        assert db.execute("SELECT count(*) FROM session WHERE ended_at IS NULL").fetchone() == (1,)
        latest = db.execute("SELECT search_terms FROM charter ORDER BY version DESC").fetchone()
    assert latest and latest[0] != "[]", latest  # charters are versioned; the guide may revise


def _pair(old: Any, new: Any, ids: dict[str, str]) -> None:
    """Map each recorded UUID to the one at the same key/position in the replayed result."""
    if isinstance(old, dict) and isinstance(new, dict):
        for key in old.keys() & new.keys():
            _pair(old[key], new[key], ids)
    elif isinstance(old, list) and isinstance(new, list):
        for a, b in zip(old, new, strict=False):
            _pair(a, b, ids)
    elif isinstance(old, str) and isinstance(new, str) and UUID.fullmatch(old):
        ids[old] = new


def replay(fixture: Path, ledger: Ledger) -> None:
    """Run the fixture's recorded deepdive calls in order; a failure says to re-record."""
    ids: dict[str, str] = {}
    calls = [c for c in parse_stream(fixture).tool_calls if c.name.startswith(PREFIX)]
    for step, call in enumerate(calls):
        name = call.name.removeprefix(PREFIX)
        if call.error or name in NEEDS_WEB:
            continue
        recorded = json.dumps(call.input)
        # every id an agent passes came from an earlier result
        if missing := set(UUID.findall(recorded)) - ids.keys():
            raise ReplayError(f"{fixture.name} step {step} ({name}): unmapped ids {missing}")
        args = json.loads(UUID.sub(lambda m: ids[m.group()], recorded))
        try:
            result = ledger.call(name, **args)
            _pair(json.loads(call.result), result, ids)
        except Exception as e:
            raise ReplayError(
                f"{fixture.name} step {step} ({name}) failed: {e}. "
                "The tool contract changed; re-record the journey (docs/journeys/README.md)."
            ) from e
