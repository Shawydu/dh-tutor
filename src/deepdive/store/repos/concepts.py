from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from deepdive.store.errors import ClaimNotFoundError, ConceptNotFoundError, QuestionNotFoundError
from deepdive.store.ids import new_id
from deepdive.store.models import Concept, ConceptLink
from deepdive.store.repos._common import IdRepo


def concept_name(name: str) -> str:
    """Lowercase, single-spaced, last word singular: "Data  Structures" -> "data structure"."""
    words = name.lower().split()
    if not words:
        return ""
    last = words[-1]
    # shortcut: English plurals by two suffix rules; concept_merge's aliases catch the rest
    if last.endswith("ies") and len(last) > 4:
        last = last[:-3] + "y"
    elif last.endswith("s") and not last.endswith(("ss", "us", "is")) and len(last) > 3:
        last = last[:-1]
    return " ".join([*words[:-1], last])


class ConceptRepo(IdRepo[Concept]):
    """Concepts, their aliases and their tags on questions and claims. Writes run in the caller's
    transaction."""

    table = "concept"
    model = Concept
    not_found = ConceptNotFoundError

    def ensure(self, names: Sequence[str]) -> list[Concept]:
        """The concept for each name (normalised, aliases followed), created when new."""
        found: dict[UUID, Concept] = {}
        for name in dict.fromkeys(filter(None, map(concept_name, names))):
            row = self.conn.execute(
                "SELECT concept_id FROM concept_alias WHERE alias = ?", (name,)
            ).fetchone()
            concept = self.require(row[0]) if row else self._one("WHERE name = ?", (name,))
            if concept is None:
                concept_id = new_id()
                self.conn.execute(
                    "INSERT INTO concept (id, name) VALUES (?, ?)", (concept_id, name)
                )
                concept = self.require(concept_id)
            found[concept.id] = concept
        return list(found.values())

    def tag_question(self, question_id: UUID, names: Sequence[str], at: datetime) -> list[Concept]:
        if not self.conn.execute("SELECT 1 FROM question WHERE id = ?", (question_id,)).fetchone():
            raise QuestionNotFoundError(question_id)
        concepts = self.ensure(names)
        self.conn.executemany(
            "INSERT OR IGNORE INTO question_concept (question_id, concept_id, created_at)"
            " VALUES (?, ?, ?)",
            [(question_id, c.id, at) for c in concepts],
        )
        return concepts

    def tag_claim(self, claim_id: UUID, names: Sequence[str]) -> list[Concept]:
        if not self.conn.execute("SELECT 1 FROM claim WHERE id = ?", (claim_id,)).fetchone():
            raise ClaimNotFoundError(claim_id)
        concepts = self.ensure(names)
        self.conn.executemany(
            "INSERT OR IGNORE INTO claim_concept (claim_id, concept_id) VALUES (?, ?)",
            [(claim_id, c.id) for c in concepts],
        )
        return concepts

    def for_question(self, question_id: UUID) -> list[Concept]:
        """The question's concept tags, by name."""
        return self._many(
            "WHERE id IN (SELECT concept_id FROM question_concept WHERE question_id = ?)"
            " ORDER BY name",
            (question_id,),
        )

    def list_all(self, topic_id: UUID | None = None) -> list[Concept]:
        """Every concept by name, or those tagged on a question or claim of the topic."""
        if topic_id is None:
            return self._many("ORDER BY name")
        return self._many(
            "WHERE id IN (SELECT concept_id FROM question_concept JOIN question q"
            " ON q.id = question_id WHERE q.topic_id = ?"
            " UNION SELECT concept_id FROM claim_concept JOIN claim c"
            " ON c.id = claim_id WHERE c.topic_id = ?) ORDER BY name",
            (topic_id, topic_id),
        )

    def merge(self, keep: UUID, drop: UUID) -> Concept:
        """Move `drop`'s tags, aliases and children to `keep`, alias its name, delete it. The
        knowledge rows must be moved first (KnowledgeStore.merge_concepts)."""
        dropped = self.require(drop)
        self.require(keep)
        for table in ("question_concept", "claim_concept"):
            self.conn.execute(
                f"UPDATE OR IGNORE {table} SET concept_id = ? WHERE concept_id = ?", (keep, drop)
            )
            # a row left on `drop` duplicates one `keep` already has
            self.conn.execute(f"DELETE FROM {table} WHERE concept_id = ?", (drop,))
        self.conn.execute(
            "UPDATE concept_alias SET concept_id = ? WHERE concept_id = ?", (keep, drop)
        )
        self.conn.execute(  # keep was drop's child: it would become its own parent
            "UPDATE concept SET parent_concept_id = NULL WHERE id = ? AND parent_concept_id = ?",
            (keep, drop),
        )
        self.conn.execute(
            "UPDATE concept SET parent_concept_id = ? WHERE parent_concept_id = ?", (keep, drop)
        )
        self.conn.execute("DELETE FROM concept WHERE id = ?", (drop,))
        self.conn.execute(
            "INSERT INTO concept_alias (alias, concept_id) VALUES (?, ?)", (dropped.name, keep)
        )
        return self.require(keep)

    def cross_topic_links(self, since: datetime | None = None) -> list[ConceptLink]:
        """Question pairs in different topics sharing a concept, with a tag made at or after
        `since` (every pair when None; tags from before migration 0010 have no time, never new)."""
        # shortcut: every pair is listed, which grows fast on a popular concept; cap per concept
        # once real digests get long
        rows = self.conn.execute(
            "SELECT qa.question_id, qb.question_id, c.name FROM question_concept qa"
            " JOIN question_concept qb ON qb.concept_id = qa.concept_id"
            " AND qa.question_id < qb.question_id"
            " JOIN question a ON a.id = qa.question_id JOIN question b ON b.id = qb.question_id"
            " JOIN concept c ON c.id = qa.concept_id"
            " WHERE a.topic_id != b.topic_id"
            " AND (? IS NULL OR qa.created_at >= ? OR qb.created_at >= ?)"
            " ORDER BY c.name, qa.question_id, qb.question_id",
            (since, since, since),
        ).fetchall()
        return [ConceptLink(from_id=a, to_id=b, concept=n) for a, b, n in rows]
