from pathlib import Path

import pytest
from replay import ReplayError, assert_dive_intake_state, replay
from test_ledger_server import Ledger

from deepdive.ledger.server import create_server
from deepdive.paths import Paths

FIXTURE = Path(__file__).parent / "fixtures" / "sessions" / "dive-intake.jsonl"


@pytest.fixture
def ledger(tmp_path: Path) -> Ledger:
    paths = Paths(tmp_path / "home")
    return Ledger(create_server(paths), paths)


def test_dive_intake_replays_to_the_recorded_end_state(ledger: Ledger) -> None:
    """The recorded dive-intake calls, replayed with remapped ids, end in the journey's state."""
    replay(FIXTURE, ledger)
    assert_dive_intake_state(ledger.paths.db)


def test_changed_tool_contract_fails_replay_naming_fixture_and_step(
    ledger: Ledger, tmp_path: Path
) -> None:
    """A recorded call whose argument the tool no longer accepts fails with fixture and step."""
    stale = tmp_path / "stale.jsonl"
    stale.write_text(FIXTURE.read_text().replace('"title"', '"name"'))
    with pytest.raises(ReplayError, match=r"stale\.jsonl step 1 \(topic_create\)"):
        replay(stale, ledger)
