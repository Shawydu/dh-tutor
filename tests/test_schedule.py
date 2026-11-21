import os
import plistlib
from pathlib import Path

import pytest

from deepdive.config import Config, Secrets
from deepdive.paths import Paths
from deepdive.schedule import Scheduler, SchedulerError

DOMAIN = f"gui/{os.getuid()}"


class FakeLaunchctl:
    """Stands in for launchctl: records calls and tracks which labels are loaded."""

    def __init__(self, bootstrap_rc: int = 0) -> None:
        self.calls: list[list[str]] = []
        self.loaded: set[str] = set()
        self.bootstrap_rc = bootstrap_rc

    def __call__(self, args: list[str]) -> int:
        self.calls.append(args)
        verb, target = args[0], args[-1]
        label = Path(target).stem if target.endswith(".plist") else target.rsplit("/", 1)[-1]
        if verb == "bootstrap" and self.bootstrap_rc == 0:
            self.loaded.add(label)
        elif verb == "bootout":
            self.loaded.discard(label)
        elif verb == "print":
            return 0 if label in self.loaded else 113
        return self.bootstrap_rc if verb == "bootstrap" else 0


@pytest.fixture
def launchctl() -> FakeLaunchctl:
    return FakeLaunchctl()


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    (tmp_path / "dd").mkdir()
    (tmp_path / "dd" / "pyproject.toml").write_text("")
    return tmp_path / "dd"


KEYS = Secrets(jev_api_key="k", github_token="t")


def make(
    tmp_path: Path, checkout: Path, launchctl: FakeLaunchctl, secrets: Secrets = KEYS
) -> Scheduler:
    config = Config.model_validate({"probe": {"schedule": "02:30"}, "digest": {"time": "07:05"}})
    return Scheduler(
        Paths(tmp_path / "home"),
        config,
        tmp_path / "agents",
        checkout,
        "/bin/uv",
        secrets,
        launchctl,
    )


@pytest.fixture
def scheduler(tmp_path: Path, checkout: Path, launchctl: FakeLaunchctl) -> Scheduler:
    return make(tmp_path, checkout, launchctl)


@pytest.mark.parametrize(
    ("index", "hour", "minute", "command"),
    [(0, 2, 30, ["probe", "run"]), (1, 7, 5, ["digest", "build"])],
    ids=["probe", "digest"],
)
def test_render_plist(
    scheduler: Scheduler, checkout: Path, index: int, hour: int, minute: int, command: list[str]
) -> None:
    """Each plist runs its command via uv at the configured time and logs to scheduler.log."""
    plist = plistlib.loads(scheduler.render(scheduler.jobs[index]))
    assert plist["ProgramArguments"] == [
        "/bin/uv", "--directory", str(checkout), "run", "deepdive", *command
    ]  # fmt: skip
    assert plist["StartCalendarInterval"] == {"Hour": hour, "Minute": minute}
    assert plist["StandardOutPath"] == plist["StandardErrorPath"]
    assert plist["StandardOutPath"].endswith("home/logs/scheduler.log")
    assert plist["EnvironmentVariables"]["DEEPDIVE_HOME"].endswith("home")


def test_install_twice_status_then_remove(
    scheduler: Scheduler, tmp_path: Path, launchctl: FakeLaunchctl
) -> None:
    """Install twice boots out then bootstraps; status reads the plists; remove unloads."""
    scheduler.install()
    scheduler.install()
    verbs = [c[0] for c in launchctl.calls]
    assert verbs == ["bootout", "bootstrap"] * 4
    assert launchctl.calls[1] == [
        "bootstrap",
        DOMAIN,
        str(tmp_path / "agents/com.deepdive.probe.plist"),
    ]
    assert len(list((tmp_path / "agents").iterdir())) == 2
    assert scheduler.status() == [
        "com.deepdive.probe at 02:30: loaded",
        "com.deepdive.digest at 07:05: loaded",
    ]
    scheduler.remove()
    assert launchctl.loaded == set()
    assert list((tmp_path / "agents").iterdir()) == []
    assert scheduler.status() == [
        "com.deepdive.probe: not installed",
        "com.deepdive.digest: not installed",
    ]


def test_install_fails_when_bootstrap_fails(tmp_path: Path, checkout: Path) -> None:
    """A launchctl bootstrap failure surfaces as SchedulerError."""
    with pytest.raises(SchedulerError, match="bootstrap failed"):
        make(tmp_path, checkout, FakeLaunchctl(bootstrap_rc=5)).install()


def test_install_rejects_a_non_checkout(tmp_path: Path, launchctl: FakeLaunchctl) -> None:
    """Without pyproject.toml the checkout path is wrong, so nothing is installed."""
    with pytest.raises(SchedulerError, match="pyproject.toml"):
        make(tmp_path, tmp_path, launchctl).install()
    assert launchctl.calls == []


def test_install_warns_when_claude_is_missing(
    scheduler: Scheduler, monkeypatch: pytest.MonkeyPatch
) -> None:
    """install returns a warning, not an error, when claude is not on PATH."""
    monkeypatch.setenv("PATH", "/nonexistent")
    assert len(scheduler.install()) == 1


@pytest.mark.parametrize(
    ("secrets", "missing"),
    [(Secrets(github_token="t"), "TYPESAFE_API_KEY"), (Secrets(jev_api_key="k"), "GITHUB_TOKEN")],
    ids=["jev", "github"],
)
def test_install_warns_on_a_missing_key(
    tmp_path: Path,
    checkout: Path,
    launchctl: FakeLaunchctl,
    monkeypatch: pytest.MonkeyPatch,
    secrets: Secrets,
    missing: str,
) -> None:
    """install warns once for each key that is in neither the env nor secrets.env."""
    monkeypatch.setenv("PATH", os.defpath)
    warnings = make(tmp_path, checkout, launchctl, secrets).install()
    assert [w.split()[0] for w in warnings if "not set" in w] == [missing]
