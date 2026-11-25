"""Daily probe and digest as launchd agents (macOS)."""

import os
import plistlib
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from deepdive.config import Config, Secrets
from deepdive.paths import Paths

_DEFAULT_PATH = "/usr/bin:/bin"
Launchctl = Callable[[list[str]], int]  # the process boundary; tests pass a fake


def _launchctl(args: list[str]) -> int:
    return subprocess.run(["launchctl", *args], capture_output=True, check=False).returncode


@dataclass(frozen=True)
class Job:
    label: str
    hhmm: str
    command: list[str]  # deepdive subcommand, e.g. ["probe", "run"]


class SchedulerError(RuntimeError):
    """The jobs cannot be installed; the message says why."""


class Scheduler:
    def __init__(
        self,
        paths: Paths,
        config: Config,
        agents_dir: Path,
        checkout: Path,
        uv: str,
        secrets: Secrets,
        launchctl: Launchctl = _launchctl,
    ) -> None:
        self._paths, self._agents_dir, self._launchctl = paths, agents_dir, launchctl
        self._checkout, self._uv, self._secrets = checkout, uv, secrets
        self._domain = f"gui/{os.getuid()}"
        self.jobs = [
            Job("com.deepdive.probe", config.probe.schedule, ["probe", "run"]),
            Job("com.deepdive.digest", config.digest.time, ["digest", "build"]),
        ]

    def _plist_path(self, job: Job) -> Path:
        return self._agents_dir / f"{job.label}.plist"

    def render(self, job: Job) -> bytes:
        """The plist for one job; both jobs append stdout and stderr to logs/scheduler.log."""
        hour, minute = (int(part) for part in job.hhmm.split(":"))
        log = str(self._paths.logs / "scheduler.log")
        return plistlib.dumps(
            {
                "Label": job.label,
                "ProgramArguments": [
                    # -i: hold an idle-sleep assertion only while the probe runs
                    # shortcut: keyed on the command name; a Job field if another job needs it
                    *(["/usr/bin/caffeinate", "-i"] if job.command[0] == "probe" else []),
                    self._uv,
                    "--directory",
                    str(self._checkout),
                    "run",
                    "deepdive",
                    *job.command,
                ],
                "StartCalendarInterval": {"Hour": hour, "Minute": minute},
                "EnvironmentVariables": {
                    "DEEPDIVE_HOME": str(self._paths.root),
                    "PATH": os.environ.get("PATH", _DEFAULT_PATH),
                },
                "StandardOutPath": log,
                "StandardErrorPath": log,
            }
        )

    def install(self) -> list[str]:
        """Write and (re)load both plists; running it again replaces them. Returns warnings."""
        if not (self._checkout / "pyproject.toml").exists():
            raise SchedulerError(
                f"{self._checkout} is not the deepdive checkout (no pyproject.toml)"
            )
        self._paths.ensure_dirs()
        self._agents_dir.mkdir(parents=True, exist_ok=True)
        for job in self.jobs:
            path = self._plist_path(job)
            self._launchctl(
                ["bootout", self._domain, str(path)]
            )  # fails harmlessly when not loaded
            path.write_bytes(self.render(job))
            if self._launchctl(["bootstrap", self._domain, str(path)]) != 0:
                raise SchedulerError(f"launchctl bootstrap failed for {path}")
        warnings = []
        if self._secrets.jev_api_key is None:
            warnings.append(
                f"TYPESAFE_API_KEY not set (env or {self._paths.secrets}); "
                "the probe falls back to the slower claude classifier"
            )
        if self._secrets.github_token is None:
            warnings.append(
                f"GITHUB_TOKEN not set (env or {self._paths.secrets}); "
                "GitHub search is limited to 10 requests a minute"
            )
        path_env = os.environ.get("PATH", _DEFAULT_PATH)
        if shutil.which("claude", path=path_env) is None:
            warnings.append("claude is not on the PATH saved in the plists; the probe will fail")
        return warnings

    def remove(self) -> None:
        """Boot both jobs out of launchd, then delete the plists that exist."""
        for job in self.jobs:
            self._launchctl(["bootout", f"{self._domain}/{job.label}"])
            self._plist_path(job).unlink(missing_ok=True)

    def status(self) -> list[str]:
        """One line per job: the time in the installed plist, and whether launchd has it."""
        lines = []
        for job in self.jobs:
            path = self._plist_path(job)
            if not path.exists():
                lines.append(f"{job.label}: not installed")
                continue
            when = plistlib.loads(path.read_bytes())["StartCalendarInterval"]
            loaded = self._launchctl(["print", f"{self._domain}/{job.label}"]) == 0
            lines.append(
                f"{job.label} at {when['Hour']:02d}:{when['Minute']:02d}: "
                + ("loaded" if loaded else "installed, not loaded")
            )
        return lines
