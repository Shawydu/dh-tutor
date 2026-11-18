from pathlib import Path

from deepdive.paths import Paths


def test_from_env_uses_deepdive_home(tmp_path: Path) -> None:
    paths = Paths.from_env({"DEEPDIVE_HOME": str(tmp_path)})
    assert paths.root == tmp_path
    assert paths.db == tmp_path / "deepdive.db"
    assert paths.config == tmp_path / "config.toml"
    assert paths.workspace == tmp_path / "workspace"


def test_from_env_defaults_to_home_dot_deepdive() -> None:
    assert Paths.from_env({}).root == Path("~/.deepdive").expanduser()
    assert Paths.from_env({"DEEPDIVE_HOME": ""}).root == Path("~/.deepdive").expanduser()


def test_ensure_dirs_creates_missing_folders_and_is_repeatable(tmp_path: Path) -> None:
    paths = Paths(tmp_path / "nested" / "home")
    paths.ensure_dirs()
    paths.ensure_dirs()
    for folder in (paths.digests, paths.poc, paths.workspace, paths.logs, paths.cache):
        assert folder.is_dir()
