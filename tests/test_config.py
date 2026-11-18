import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from deepdive.cli import app
from deepdive.config import (
    DEFAULT_CONFIG_TOML,
    Config,
    ConfigError,
    Secrets,
    load_config,
)

runner = CliRunner()
KEY = "sk-super-secret-value-123"


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(text, "utf-8")
    return path


def test_defaults_when_no_file(tmp_path: Path) -> None:
    config = load_config(tmp_path / "missing.toml")
    assert config == Config()
    assert config.classifier.provider == "jev"
    assert config.classifier.fallback == "claude"
    assert config.classifier.auto_threshold == 0.9
    assert config.search.apis == ["github", "arxiv", "hn"]
    assert (config.probe.schedule, config.probe.topic_selection) == ("02:00", "pinned")
    assert (config.probe.max_topics, config.probe.searches_per_topic) == (5, 10)
    assert config.digest.time == "07:00"
    assert config.domain.pack == "software-engineering"
    assert config.poc.sandbox == "devcontainer"
    assert config.matcher.candidates == 10


def test_overrides_from_file_keep_other_defaults(tmp_path: Path) -> None:
    path = write(tmp_path, '[probe]\nmax_topics = 2\ntopic_selection = "list"\ntopics = ["a"]\n')
    config = load_config(path)
    assert config.probe.max_topics == 2
    assert config.probe.topics == ["a"]
    assert config.probe.searches_per_topic == 10
    assert config.classifier == Config().classifier


def test_commented_default_file_matches_defaults(tmp_path: Path) -> None:
    assert load_config(write(tmp_path, DEFAULT_CONFIG_TOML)) == Config()


@pytest.mark.parametrize(
    ("toml", "where"),
    [
        ("[classifier]\nauto_threshold = 1.5\n", "classifier.auto_threshold"),
        ('[classifier]\nprovider = "gpt"\n', "classifier.provider"),
        ('[probe]\nschedule = "25:00"\n', "probe.schedule"),
        ("[probe]\nmax_topics = 0\n", "probe.max_topics"),
        ("[probe]\nmax_topic = 3\n", "probe.max_topic"),  # typo'd key
        ("[nope]\nx = 1\n", "nope"),
        ('[matcher]\ncandidates = "ten"\n', "matcher.candidates"),
    ],
)
def test_invalid_values_rejected_with_clear_message(tmp_path: Path, toml: str, where: str) -> None:
    path = write(tmp_path, toml)
    with pytest.raises(ConfigError) as err:
        load_config(path)
    assert str(path) in str(err.value)
    assert where in str(err.value)


def test_invalid_toml_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(write(tmp_path, "[probe\n"))


def test_secrets_come_from_env_and_never_appear_in_repr_or_str() -> None:
    secrets = Secrets.from_env({"JEV_API_KEY": KEY, "GITHUB_TOKEN": "ghp_other_secret"})
    assert secrets.jev_api_key == KEY
    for text in (repr(secrets), str(secrets), f"{secrets}", repr([secrets])):
        assert KEY not in text
        assert "ghp_other_secret" not in text
    assert Secrets.from_env({}) == Secrets()
    assert "(not set)" in repr(Secrets())


def test_secrets_cannot_be_set_from_the_toml(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(write(tmp_path, f'[classifier]\njev_api_key = "{KEY}"\n'))


def test_cli_config_init_creates_folders_and_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("DEEPDIVE_HOME", str(home))
    result = runner.invoke(app, ["config", "init"])
    assert result.exit_code == 0
    assert (home / "config.toml").read_text("utf-8") == DEFAULT_CONFIG_TOML
    assert (home / "digests").is_dir() and (home / "logs").is_dir()


def test_cli_config_init_never_overwrites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPDIVE_HOME", str(tmp_path))
    (tmp_path / "config.toml").write_text("[matcher]\ncandidates = 3\n", "utf-8")
    result = runner.invoke(app, ["config", "init"])
    assert result.exit_code == 0
    assert "already exists" in result.output
    assert (tmp_path / "config.toml").read_text("utf-8") == "[matcher]\ncandidates = 3\n"


def test_cli_config_show_prints_effective_config_and_masks_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPDIVE_HOME", str(tmp_path))
    monkeypatch.setenv("JEV_API_KEY", KEY)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    (tmp_path / "config.toml").write_text("[matcher]\ncandidates = 3\n", "utf-8")
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert KEY not in result.output
    assert 'jev_api_key = "********"' in result.output
    assert 'github_token = "(not set)"' in result.output
    shown = tomllib.loads(result.output)
    assert shown["matcher"] == {"candidates": 3}
    assert shown["classifier"]["auto_threshold"] == 0.9


def test_cli_config_show_without_file_shows_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPDIVE_HOME", str(tmp_path))
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "showing defaults" in result.output
    assert not (tmp_path / "config.toml").exists()


def test_cli_config_show_reports_invalid_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DEEPDIVE_HOME", str(tmp_path))
    (tmp_path / "config.toml").write_text("[probe]\nmax_topics = 0\n", "utf-8")
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 1
    assert "probe.max_topics" in result.output
