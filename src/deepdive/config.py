"""Typed engine settings from config.toml. Secrets: env vars or secrets.env, not the toml."""

import json
import os
import stat
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from deepdive.paths import Paths

_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"
_MASK = "********"
_SECRET_KEYS = ("TYPESAFE_API_KEY", "GITHUB_TOKEN")


class _Section(BaseModel):
    # forbid: a typo'd key in config.toml is an error, not a silently ignored setting
    model_config = ConfigDict(extra="forbid")


class ClassifierConfig(_Section):
    provider: Literal["jev", "claude"] = "jev"
    fallback: Literal["jev", "claude"] = "claude"
    auto_threshold: float = Field(default=0.9, ge=0, le=1)


class SearchConfig(_Section):
    apis: list[str] = ["github", "arxiv", "hn"]
    session_budget: int = Field(default=30, ge=1)  # searches per interactive session
    fetch_max_chars: int = Field(default=20000, ge=1)  # longer pages come back truncated


class ProbeConfig(_Section):
    schedule: str = Field(default="02:00", pattern=_HHMM)
    topic_selection: Literal["all", "active", "pinned", "list"] = "active"
    topics: list[str] = []  # used when topic_selection = "list"
    active_days: int = Field(default=14, ge=1)  # "active" = a session this recent
    max_topics: int = Field(default=5, ge=1)
    searches_per_topic: int = Field(default=10, ge=1)
    fetches_per_topic: int = Field(default=20, ge=1)


class DigestConfig(_Section):
    time: str = Field(default="07:00", pattern=_HHMM)
    path: str | None = None  # unset: Paths.digests, so it follows DEEPDIVE_HOME

    def folder(self, default: Path) -> Path:
        return default if self.path is None else Path(self.path).expanduser()


class DomainConfig(_Section):
    pack: str = "software-engineering"


class MatcherConfig(_Section):
    candidates: int = Field(default=10, ge=1)


class Config(_Section):
    classifier: ClassifierConfig = Field(default_factory=ClassifierConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    probe: ProbeConfig = Field(default_factory=ProbeConfig)
    digest: DigestConfig = Field(default_factory=DigestConfig)
    domain: DomainConfig = Field(default_factory=DomainConfig)
    matcher: MatcherConfig = Field(default_factory=MatcherConfig)

    def to_toml(self) -> str:
        """Render as TOML. JSON scalars and arrays are valid TOML for this config's value types."""
        out: list[str] = []
        for name, values in self.model_dump().items():
            out.append(f"[{name}]")
            out.extend(f"{k} = {json.dumps(v)}" for k, v in values.items() if v is not None)
            out.append("")
        return "\n".join(out)


class ConfigError(ValueError):
    """config.toml is unreadable or holds invalid values; the message says where and why."""


def load_config(path: Path) -> Config:
    """Read `path` into a Config; a missing file means all defaults."""
    if not path.exists():
        return Config()
    try:
        return Config.model_validate(tomllib.loads(path.read_text("utf-8")))
    except tomllib.TOMLDecodeError as err:
        raise ConfigError(f"{path}: not valid TOML: {err}") from err
    except ValidationError as err:
        lines = [f"  {'.'.join(map(str, e['loc']))}: {e['msg']}" for e in err.errors()]
        raise ConfigError(f"{path}: invalid config\n" + "\n".join(lines)) from err


def _read_secrets_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines for the two known keys; blanks, `#` lines and other keys are ignored."""
    if not path.exists():
        return {}
    if path.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ConfigError(f"{path} is readable by other users; run `chmod 600 {path}`")
    out: dict[str, str] = {}
    for line in path.read_text("utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key.strip() in _SECRET_KEYS:
            out[key.strip()] = value.strip()
    return out


@dataclass(frozen=True, repr=False)
class Secrets:
    """API keys from env vars, else <DEEPDIVE_HOME>/secrets.env (launchd jobs don't inherit the
    shell env). repr and str say whether a key is set, never its value."""

    jev_api_key: str | None = None
    github_token: str | None = None

    @classmethod
    def from_env(
        cls, env: Mapping[str, str] | None = None, paths: Paths | None = None
    ) -> "Secrets":
        """Env vars win over secrets.env. A secrets.env open to group or other is refused."""
        env = os.environ if env is None else env
        # shortcut: a plain env file; move to the macOS Keychain if it must be stored encrypted
        file = _read_secrets_file((paths or Paths.from_env(env)).secrets)
        return cls(
            jev_api_key=env.get("TYPESAFE_API_KEY") or file.get("TYPESAFE_API_KEY") or None,
            github_token=env.get("GITHUB_TOKEN") or file.get("GITHUB_TOKEN") or None,
        )

    def masked(self) -> dict[str, str]:
        return {
            "jev_api_key": _MASK if self.jev_api_key else "(not set)",
            "github_token": _MASK if self.github_token else "(not set)",
        }

    def __repr__(self) -> str:
        return "Secrets(" + ", ".join(f"{k}={v}" for k, v in self.masked().items()) + ")"


DEFAULT_CONFIG_TOML = """\
# deepdive config. Every value below is the default; delete or change what you like.
# API keys are not set here: export TYPESAFE_API_KEY and GITHUB_TOKEN in your environment, or put
# KEY=VALUE lines in <DEEPDIVE_HOME>/secrets.env (chmod 600; the env wins).
# Scheduled jobs don't see your shell env, so they need the file.

[classifier]
provider = "jev"            # jev | claude
fallback = "claude"
auto_threshold = 0.9        # act at or above this confidence, else fall back

[search]
apis = ["github", "arxiv", "hn"]
session_budget = 30         # searches per interactive session
fetch_max_chars = 20000     # longer fetched pages are truncated

[probe]
schedule = "02:00"          # HH:MM, 24-hour
topic_selection = "active"  # all | active | pinned | list
topics = []                 # topic titles, used when topic_selection = "list"
active_days = 14            # "active" means a session within this many days
max_topics = 5
searches_per_topic = 10
fetches_per_topic = 20

[digest]
time = "07:00"              # HH:MM, 24-hour
# path = "~/.deepdive/digests/"   # default: <DEEPDIVE_HOME>/digests

[domain]
pack = "software-engineering"

[matcher]
candidates = 10             # past questions the matcher shortlists per new question
"""
