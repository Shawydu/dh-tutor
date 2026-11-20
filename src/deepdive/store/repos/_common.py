"""The base class the repos share: typed row fetching and existence checks."""

import sqlite3
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from pydantic import BaseModel

from deepdive.store.errors import NotFoundError, SessionNotFoundError

type Params = Sequence[Any]


class Repo[M: BaseModel]:
    """One table and its row model; a subclass sets `table` and `model`. A type parameter can't
    appear in a ClassVar, so `model` is a plain class attribute."""

    table: str
    model: type[M]

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def _many(self, tail: str = "", params: Params = ()) -> list[M]:
        """`SELECT <model fields> FROM table <tail>` as models; `tail` is WHERE/JOIN/ORDER BY."""
        cols = ", ".join(f'"{self.table}"."{name}"' for name in self.model.model_fields)
        rows = self.conn.execute(f'SELECT {cols} FROM "{self.table}" {tail}', params).fetchall()
        fields = self.model.model_fields
        return [self.model.model_validate(dict(zip(fields, row, strict=True))) for row in rows]

    def _one(self, tail: str, params: Params = ()) -> M | None:
        found = self._many(f"{tail} LIMIT 1", params)
        return found[0] if found else None

    def _check_session(self, session_id: UUID | None) -> None:
        """A writer's `session_id` is optional, but when given it must be a real session."""
        # raw query, not SessionRepo: sessions.py imports this module
        sql = "SELECT 1 FROM session WHERE id = ?"
        if session_id is not None and self.conn.execute(sql, (session_id,)).fetchone() is None:
            raise SessionNotFoundError(session_id)


class IdRepo[M: BaseModel](Repo[M]):
    """A repo whose table has an `id` primary key; a subclass also sets `not_found`."""

    not_found: type[NotFoundError]

    def get(self, id_: UUID) -> M | None:
        return self._one("WHERE id = ?", (id_,))

    def exists(self, id_: UUID) -> bool:
        sql = f'SELECT 1 FROM "{self.table}" WHERE id = ?'
        return self.conn.execute(sql, (id_,)).fetchone() is not None

    def require(self, id_: UUID) -> M:
        """The row, or `not_found` raised."""
        found = self.get(id_)
        if found is None:
            raise self.not_found(id_)
        return found
