"""Domain packs: field-specific sources, allowlist, tiers and depth, from packaged TOML."""

import tomllib
from importlib import resources
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

_Host = Annotated[str, Field(pattern=r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")]  # bare hostname only


class DomainPack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    providers: list[str] = Field(min_length=1)
    default_depth: Literal["overview", "standard", "deep"]
    fetch_allowlist: list[_Host] = Field(min_length=1)
    source_tiers: dict[str, Annotated[int, Field(ge=1)]] = Field(min_length=1)


class DomainPackError(ValueError):
    """The requested pack is missing or invalid."""


def load_pack(name: str) -> DomainPack:
    """Load a packaged pack by its config name, e.g. "software-engineering"."""
    resource = resources.files("deepdive.domain_packs") / f"{name.replace('-', '_')}.toml"
    if not resource.is_file():
        raise DomainPackError(f"unknown domain pack {name!r}")
    try:
        pack = DomainPack.model_validate(tomllib.loads(resource.read_text("utf-8")))
    except (tomllib.TOMLDecodeError, ValidationError) as err:
        raise DomainPackError(f"domain pack {name!r} is invalid: {err}") from err
    if pack.name != name:
        raise DomainPackError(f"domain pack file for {name!r} declares name {pack.name!r}")
    return pack
