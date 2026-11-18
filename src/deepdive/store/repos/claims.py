import sqlite3
from collections.abc import Sequence
from uuid import UUID

from deepdive.store.db import transaction
from deepdive.store.enums import ClaimStatus, EvidenceStance
from deepdive.store.errors import SourceRequiredError, TopicNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.models import Claim
from deepdive.store.repos import evidence
from deepdive.store.repos._common import check_session, many, one, require


def add(
    conn: sqlite3.Connection,
    topic_id: UUID,
    text: str,
    source_ids: Sequence[UUID],
    *,
    status: ClaimStatus = ClaimStatus.ESTABLISHED,
    stance: EvidenceStance = EvidenceStance.SUPPORTS,
    excerpt_summary: str | None = None,
    session_id: UUID | None = None,
) -> Claim:
    """Add a claim with one evidence row per source, all or nothing.

    The design links claims to sources only through evidence, so a claim that must cite a real
    source (invariant 2) is created together with its first evidence rows.
    """
    if not source_ids:
        raise SourceRequiredError("a claim must cite at least one source")
    with transaction(conn):
        require(conn, "topic", topic_id, TopicNotFoundError)
        check_session(conn, session_id)
        claim_id = new_id()
        conn.execute(
            "INSERT INTO claim (id, topic_id, text, status, session_id) VALUES (?, ?, ?, ?, ?)",
            (claim_id, topic_id, text, status, session_id),
        )
        for source_id in dict.fromkeys(source_ids):
            evidence.insert(conn, claim_id, source_id, stance, excerpt_summary, session_id)
    claim = get(conn, claim_id)
    assert claim is not None
    return claim


def get(conn: sqlite3.Connection, claim_id: UUID) -> Claim | None:
    return one(conn, Claim, "claim", "WHERE id = ?", (claim_id,))


def list_for_topic(conn: sqlite3.Connection, topic_id: UUID) -> list[Claim]:
    return many(conn, Claim, "claim", "WHERE topic_id = ? ORDER BY id", (topic_id,))
