import pytest
from pydantic import ValidationError

from deepdive.config import Config
from deepdive.domain_packs import DomainPack, DomainPackError, load_pack


def test_software_engineering_pack_loads_and_matches_config_default() -> None:
    pack = load_pack(Config().domain.pack)
    assert pack.name == "software-engineering"
    assert pack.providers == ["github", "arxiv", "hn"]
    assert pack.default_depth == "standard"
    assert pack.fetch_allowlist == [
        "github.com",
        "raw.githubusercontent.com",
        "arxiv.org",
        "export.arxiv.org",
        "news.ycombinator.com",
        "hn.algolia.com",
    ]
    assert pack.source_tiers["poc"] < pack.source_tiers["paper"] < pack.source_tiers["discussion"]


def test_unknown_pack_is_a_clear_error() -> None:
    with pytest.raises(DomainPackError, match="unknown domain pack 'kids-science'"):
        load_pack("kids-science")


@pytest.mark.parametrize(
    "change",
    [
        {"providers": []},
        {"default_depth": "bottomless"},
        {"fetch_allowlist": ["https://github.com/"]},
        {"source_tiers": {"paper": 0}},
        {"surprise": 1},
    ],
)
def test_pack_model_rejects_invalid_values(change: dict[str, object]) -> None:
    valid: dict[str, object] = load_pack("software-engineering").model_dump() | change
    with pytest.raises(ValidationError):
        DomainPack.model_validate(valid)
