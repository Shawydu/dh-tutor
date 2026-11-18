from datetime import UTC, datetime

from typer.testing import CliRunner

import deepdive
from deepdive import clock
from deepdive.cli import app

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert result.output.strip() == "0.1.0"


def test_clock_is_utc_and_overridable() -> None:
    assert deepdive.__name__ == "deepdive"
    assert clock.now().tzinfo is UTC
    pinned = datetime(2026, 1, 1, tzinfo=UTC)
    clock.set_now(pinned)
    try:
        assert clock.now() == pinned
    finally:
        clock.set_now(None)
    assert clock.now() != pinned


def test_now_iso_is_the_database_timestamp_format(frozen_clock: datetime) -> None:
    assert clock.now_iso() == "2026-01-01T12:00:00Z"
