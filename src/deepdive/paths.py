"""Every filesystem location the engine uses, rooted at DEEPDIVE_HOME (default ~/.deepdive)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HOME = "~/.deepdive"


@dataclass(frozen=True)
class Paths:
    root: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Paths":
        """Root at $DEEPDIVE_HOME, or ~/.deepdive when it is unset or empty."""
        env = os.environ if env is None else env
        return cls(Path(env.get("DEEPDIVE_HOME") or DEFAULT_HOME).expanduser())

    @property
    def db(self) -> Path:
        return self.root / "deepdive.db"

    @property
    def config(self) -> Path:
        return self.root / "config.toml"

    @property
    def secrets(self) -> Path:
        return self.root / "secrets.env"

    @property
    def digests(self) -> Path:
        return self.root / "digests"

    @property
    def recaps(self) -> Path:
        return self.root / "recaps"

    @property
    def workspace(self) -> Path:
        return self.root / "workspace"

    @property
    def probe_lock(self) -> Path:
        return self.root / "probe.lock"

    @property
    def logs(self) -> Path:
        return self.root / "logs"

    @property
    def cache(self) -> Path:
        return self.root / "cache"

    def ensure_dirs(self) -> None:
        """Create the root and every folder under it that is missing."""
        for folder in (
            self.root,
            self.digests,
            self.recaps,
            self.workspace,
            self.logs,
            self.cache,
        ):
            folder.mkdir(parents=True, exist_ok=True)
