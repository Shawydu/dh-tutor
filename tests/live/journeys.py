"""Scripted learner turns shared by the live journeys."""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from live.session import Session, Turn

TOPIC = "/dive Python list comprehensions"
CONTEXT = "I know basic Python loops. I want to read other people's code more easily."
CHARTER = (
    "Just curiosity. Core question: when to use one instead of a for loop. Skip generators for "
    "now. Search term: Python. Done when I can rewrite a loop as a comprehension. "
    "That charter looks good, please save it."
)


def dive_intake(session: Session) -> list[Turn]:
    """Run the three scoping turns that end with a saved charter."""
    turns = [session.turn(text) for text in (TOPIC, CONTEXT, CHARTER)]
    # Later journeys build on intake; fail here so a stalled intake isn't misread as their bug.
    assert row(session.home, "SELECT 1 FROM charter"), "intake saved no charter"
    return turns


def row(home: Path, sql: str, *args: str) -> Any:
    """First row of a read-only query on the journey's database."""
    with closing(sqlite3.connect(f"file:{home / 'deepdive.db'}?mode=ro", uri=True)) as db:
        return db.execute(sql, args).fetchone()


def rows(home: Path, sql: str, *args: str) -> list[Any]:
    """Every row of a read-only query on the journey's database."""
    with closing(sqlite3.connect(f"file:{home / 'deepdive.db'}?mode=ro", uri=True)) as db:
        return db.execute(sql, args).fetchall()
