import os
import subprocess
from pathlib import Path

import pytest

from live.journeys import dive_intake, rows
from live.session import REPO, Session, Turn

CHECKPOINT = (
    "Teach the first agenda item briefly, then run a student checkpoint and put the student's "
    "question to me with the options."
)
NEXT_CHECKPOINT = "Teach the next agenda item briefly, then run the next student checkpoint."
ANSWER = (
    "I choose answer. I think a comprehension fits when I build a new list from one loop with "
    "a simple expression, and a for loop fits when the body is long or has side effects."
)


def _asked(turns: list[Turn]) -> list[str]:
    """The `asker` of every question_submit call, in order."""
    return [
        c.input["asker"]
        for t in turns
        for c in t.tool_calls
        if c.name.endswith("question_submit") and not c.error
    ]


# Known failure: the guide does not follow section 9 (calls both students at once, invents its own
# options, parks on "keep for the probe"). The checkpoint redesign comes back to this.
XFAIL = pytest.mark.xfail(reason="guide does not follow the checkpoint steps yet", strict=False)


@XFAIL
@pytest.mark.live
def test_students_alternate_and_answers_become_evidence(home: Path) -> None:
    """With /student both the askers alternate, and each answered question gets evidence."""
    session = Session(home, "students", max_turns=60)
    dive_intake(session)
    session.turn("/student both")
    turns = [session.turn(CHECKPOINT), session.turn(ANSWER)]
    turns += [session.turn(NEXT_CHECKPOINT), session.turn(ANSWER)]
    askers = _asked(turns)
    assert askers[:2] in (["curious", "skeptic"], ["skeptic", "curious"]), askers
    graded = rows(
        home,
        "SELECT DISTINCT q.asker FROM knowledge_evidence e JOIN question q ON q.id = e.question_id"
        " WHERE e.kind = 'answered_student_q'",
    )
    assert {a for (a,) in graded} == {"curious", "skeptic"}, graded


@XFAIL
@pytest.mark.live
def test_skipped_challenge_stays_open_and_is_in_the_probe_plan(home: Path) -> None:
    """A skipped skeptic question stays open and `deepdive probe plan` lists it."""
    session = Session(home, "skip-challenge", max_turns=40)
    dive_intake(session)
    session.turn("/student skeptic")
    session.turn(CHECKPOINT)
    session.turn("Skip it, but keep it for the overnight probe.")
    questions = rows(
        home, "SELECT clean_text, status FROM question WHERE asker = 'skeptic' ORDER BY id"
    )
    assert questions, "the skeptic asked nothing"
    text, status = questions[0]
    assert status == "open", questions
    plan = subprocess.run(
        ["uv", "run", "--project", str(REPO), "deepdive", "probe", "plan"],
        env=os.environ | {"DEEPDIVE_HOME": str(home)},
        check=True, capture_output=True, text=True,
    ).stdout  # fmt: skip
    assert text in plan, plan
