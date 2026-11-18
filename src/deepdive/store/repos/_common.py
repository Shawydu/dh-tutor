"""Helpers shared by the repos: typed row fetching and existence checks."""

import sqlite3
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from deepdive.store.errors import NotFoundError, SessionNotFoundError

type Params = Sequence[Any]


def _select(model: type[BaseModel], table: str, tail: str) -> str:
    cols = ", ".join(f'"{table}"."{name}"' for name in model.model_fields)
    return f'SELECT {cols} FROM "{table}" {tail}'


def many[M: BaseModel](
    conn: sqlite3.Connection, model: type[M], table: str, tail: str = "", params: Params = ()
) -> list[M]:
    """`SELECT <model fields> FROM table <tail>` as models; `tail` is WHERE/JOIN/ORDER BY/LIMIT."""
    rows = conn.execute(_select(model, table, tail), params).fetchall()
    return [model.model_validate(dict(zip(model.model_fields, row, strict=True))) for row in rows]


def one[M: BaseModel](
    conn: sqlite3.Connection, model: type[M], table: str, tail: str, params: Params = ()
) -> M | None:
    found = many(conn, model, table, f"{tail} LIMIT 1", params)
    return found[0] if found else None


def require(conn: sqlite3.Connection, table: str, id_: UUID, error: type[NotFoundError]) -> None:
    if conn.execute(f'SELECT 1 FROM "{table}" WHERE id = ?', (id_,)).fetchone() is None:
        raise error(id_)


def check_session(conn: sqlite3.Connection, session_id: UUID | None) -> None:
    """A writer's `session_id` is optional, but when given it must be a real session."""
    if session_id is not None:
        require(conn, "session", session_id, SessionNotFoundError)
