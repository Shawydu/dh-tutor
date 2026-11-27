import os
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
def home(tmp_path: Path) -> Path:
    """A throwaway DEEPDIVE_HOME with the workspace installed."""
    return make_home(tmp_path)


@pytest.fixture
def session(home: Path, request: pytest.FixtureRequest) -> Iterator[Session]:
    yield Session(home, journey=request.node.name)
