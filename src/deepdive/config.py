"""Typed engine settings from config.toml. Secrets come from env vars only, never the file."""

import json
import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

_HHMM = r"^([01]\d|2[0-3]):[0-5]\d$"
_MASK = "********"


class _Section(BaseModel):
    # forbid: a typo'd key in config.toml is an error, not a silently ignored setting
    model_config = ConfigDict(extra="forbid")


class ClassifierConfig(_Section):
    provider: Literal["jev", "claude"] = "jev"
    fallback: Literal["jev", "claude"] = "claude"
    auto_threshold: float = Field(default=0.9, ge=0, le=1)


class EmbeddingsConfig(_Section):
    model: str = "TBD"  # local model, picked by testing (task L-01)


class SearchConfig(_Section):
    apis: list[str] = ["github", "arxiv", "hn"]
    session_budget: int = Field(default=30, ge=1)  # searches per interactive session
    fetch_max_chars: int = Field(default=20000, ge=1)  # longer pages come back truncated


class ProbeConfig(_Section):
    schedule: str = Field(default="02:00", pattern=_HHMM)
    topic_selection: Literal["all", "active", "pinned", "list"] = "pinned"
    topics: list[str] = []  # used when topic_selection = "list"
    active_days: int = Field(default=14, ge=1)  # "active" = a session this recent
    max_topics: int = Field(default=5, ge=1)
    searches_per_topic: int = Field(default=10, ge=1)


class DigestConfig(_Section):
    time: str = Field(default="07:00", pattern=_HHMM)
    path: str = "~/.deepdive/digests/"


class DomainConfig(_Section):
    pack: str = "software-engineering"


class PocConfig(_Section):
    workspace: str = "~/.deepdive/poc/"
    sandbox: Literal["devcontainer"] = "devcontainer"  # Docker Compose under a devcontainer


class MatcherConfig(_Section):
    candidates: int = Field(default=10, ge=1)


class Config(_Section):
    classifier: ClassifierConfig = Field(default_factory=ClassifierConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    search: SearchConfig = Field(default_factory=SearchConfig)
    probe: ProbeConfig = Field(default_factory=ProbeConfig)
    digest: DigestConfig = Field(default_factory=DigestConfig)
    domain: DomainConfig = Field(default_factory=DomainConfig)
    poc: PocConfig = Field(default_factory=PocConfig)
    matcher: MatcherConfig = Field(default_factory=MatcherConfig)

    def to_toml(self) -> str:
        """Render as TOML. JSON scalars and arrays are valid TOML for this config's value types."""
        out: list[str] = []
        for name, values in self.model_dump().items():
            out.append(f"[{name}]")
            out.extend(f"{key} = {json.dumps(value)}" for key, value in values.items())
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


@dataclass(frozen=True, repr=False)
class Secrets:
    """API keys from env vars only. repr and str say whether a key is set, never its value."""

    jev_api_key: str | None = None
    github_token: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Secrets":
        env = os.environ if env is None else env
        return cls(
            jev_api_key=env.get("TYPESAFE_API_KEY") or None,
            github_token=env.get("GITHUB_TOKEN") or None,
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
# API keys are not set here: export TYPESAFE_API_KEY and GITHUB_TOKEN in your environment.

[classifier]
provider = "jev"            # jev | claude
fallback = "claude"
auto_threshold = 0.9        # act at or above this confidence, else fall back

[embeddings]
model = "TBD"               # local model, picked by testing

[search]
apis = ["github", "arxiv", "hn"]
session_budget = 30         # searches per interactive session
fetch_max_chars = 20000     # longer fetched pages are truncated

[probe]
schedule = "02:00"          # HH:MM, 24-hour
topic_selection = "pinned"  # all | active | pinned | list
topics = []                 # topic titles, used when topic_selection = "list"
active_days = 14            # "active" means a session within this many days
max_topics = 5
searches_per_topic = 10

[digest]
time = "07:00"              # HH:MM, 24-hour
path = "~/.deepdive/digests/"

[domain]
pack = "software-engineering"

[poc]
workspace = "~/.deepdive/poc/"
sandbox = "devcontainer"    # Docker Compose under a devcontainer

[matcher]
candidates = 10             # past questions the matcher shortlists per new question
"""
