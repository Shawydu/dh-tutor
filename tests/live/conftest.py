import os
import re
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from live.session import Session, make_home


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    if os.environ.get("DEEPDIVE_LIVE"):
        return
    skip = pytest.mark.skip(reason="set DEEPDIVE_LIVE=1")
    for item in items:
        if "tests/live/" in item.nodeid:
            item.add_marker(skip)


@pytest.fixture
def home(tmp_path: Path) -> Iterator[Path]:
    """A throwaway DEEPDIVE_HOME with the workspace installed; its Claude project goes after."""
    home = make_home(tmp_path)
    yield home
    # Claude Code names the project folder after the resolved cwd, non-alphanumerics as "-"
    encoded = re.sub(r"[^A-Za-z0-9]", "-", str((home / "workspace").resolve()))
    shutil.rmtree(Path.home() / ".claude" / "projects" / encoded, ignore_errors=True)


@pytest.fixture
def session(home: Path, request: pytest.FixtureRequest) -> Iterator[Session]:
    yield Session(home, journey=request.node.name)
