import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from live.journeys import dive_intake
from live.session import Session

ASK = "When should I use a list comprehension instead of a for loop?"
ASK_AGAIN = "Sorry, remind me: how do I choose between a comprehension and a plain for loop?"
OUTSIDE = "How do I set up a Kubernetes ingress controller with TLS?"


def _row(home: Path, sql: str, *args: str) -> Any:
    with closing(sqlite3.connect(f"file:{home / 'deepdive.db'}?mode=ro", uri=True)) as db:
        return db.execute(sql, args).fetchone()


def _question(home: Path, text: str) -> tuple[str, str]:
    """(id, status) of the question the hook stored for this exact prompt."""
    row = _row(
        home,
        "SELECT id, status FROM question WHERE asker = 'user' AND raw_text = ? ORDER BY id",
        text,
    )
    assert row, f"the hook stored no question for {text!r}"
    return row  # type: ignore[no-any-return]


@pytest.mark.live
def test_repeat_question_links_the_second_ask_to_the_first(home: Path) -> None:
    """A reworded repeat gets a question_edge to the earlier question with repeat=1."""
    session = Session(home, "repeat-question", max_turns=35)
    dive_intake(session)
    session.turn(ASK)
    session.turn(ASK_AGAIN)
    first, again = _question(home, ASK)[0], _question(home, ASK_AGAIN)[0]
    edge = _row(
        home,
        "SELECT relation, repeat FROM question_edge WHERE from_id = ? AND to_id = ?",
        again,
        first,
    )
    assert edge == ("same", 1), edge


@pytest.mark.live
def test_out_of_scope_question_is_parked(home: Path) -> None:
    """A question outside the charter is stored with status parked."""
    session = Session(home, "out-of-scope", max_turns=30)
    dive_intake(session)
    session.turn(OUTSIDE)
    assert _question(home, OUTSIDE)[1] == "parked"
