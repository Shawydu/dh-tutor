import sqlite3
from uuid import UUID

from deepdive.store.enums import EvidenceStance
from deepdive.store.errors import ClaimNotFoundError, SourceNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.models import Evidence
from deepdive.store.repos._common import check_session, many, one, require


def insert(
    conn: sqlite3.Connection,
    claim_id: UUID,
    source_id: UUID,
    stance: EvidenceStance,
    excerpt_summary: str | None,
    session_id: UUID | None = None,
) -> UUID:
    """Check claim and source, then write the row. `claims.add` calls this in its own
    transaction, so it must not open one."""
    require(conn, "claim", claim_id, ClaimNotFoundError)
    require(conn, "source", source_id, SourceNotFoundError)
    check_session(conn, session_id)
    evidence_id = new_id()
    conn.execute(
        "INSERT INTO evidence (id, claim_id, source_id, stance, excerpt_summary, session_id)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (evidence_id, claim_id, source_id, stance, excerpt_summary, session_id),
    )
    return evidence_id


def add(
    conn: sqlite3.Connection,
    claim_id: UUID,
    source_id: UUID,
    stance: EvidenceStance,
    excerpt_summary: str | None = None,
    session_id: UUID | None = None,
) -> Evidence:
    """Attach a source to an existing claim, for or against it."""
    evidence = get(conn, insert(conn, claim_id, source_id, stance, excerpt_summary, session_id))
    assert evidence is not None
    return evidence


def get(conn: sqlite3.Connection, evidence_id: UUID) -> Evidence | None:
    return one(conn, Evidence, "evidence", "WHERE id = ?", (evidence_id,))


def list_for_claim(conn: sqlite3.Connection, claim_id: UUID) -> list[Evidence]:
    return many(conn, Evidence, "evidence", "WHERE claim_id = ? ORDER BY id", (claim_id,))


def list_for_topic(conn: sqlite3.Connection, topic_id: UUID) -> list[Evidence]:
    return many(
        conn,
        Evidence,
        "evidence",
        "JOIN claim ON claim.id = evidence.claim_id WHERE claim.topic_id = ? ORDER BY evidence.id",
        (topic_id,),
    )
