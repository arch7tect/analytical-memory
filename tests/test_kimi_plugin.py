import json
import subprocess
from pathlib import Path

import pytest

from scripts.build_plugin_bundles import build_bundles
from scripts.install_kimi import install, installation_lock


@pytest.fixture
def payload(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    build_bundles(tmp_path / "bundles")
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, "0.39.1\n"),
    )
    return tmp_path / "bundles" / "kimi" / "analytical-memory"


def test_install_preserves_other_plugins_and_prior_payloads(
    payload: Path, tmp_path: Path
) -> None:
    home = tmp_path / "home"
    registry = home / "plugins" / "installed.json"
    registry.parent.mkdir(parents=True)
    other = {"id": "other", "root": "/existing", "enabled": False, "custom": {"x": 1}}
    original = json.dumps({"version": 1, "plugins": [other], "custom": True})
    registry.write_text(original)
    (payload / ".venv").mkdir()
    (payload / ".venv" / "do-not-copy").write_text("runtime")
    first = install(payload, home)
    root = Path(first["root"])
    assert not (root / ".venv").exists()
    assert (root / "scripts" / "install_kimi.py").is_file()
    document = json.loads(registry.read_text())
    assert document["plugins"][0] == other
    assert document["custom"] is True
    assert next(registry.parent.glob("installed.before-*.json")).read_text() == original
    assert install(payload, home)["registration"] == "unchanged"
    before = registry.read_bytes()
    (payload / "README.md").write_text("updated bundle")
    second = install(payload, home)
    assert second["root"] != first["root"]
    assert (root / "README.md").read_text() != "updated bundle"
    assert before in [
        p.read_bytes() for p in registry.parent.glob("installed.before-*.json")
    ]
    assert len(json.loads(registry.read_text())["plugins"]) == 2


@pytest.mark.parametrize(
    "contents",
    ["bad json", "[]", '{"version":2,"plugins":[]}', '{"version":1,"plugins":[null]}'],
)
def test_install_rejects_invalid_registry_without_replacing_it(
    payload: Path, tmp_path: Path, contents: str
) -> None:
    home = tmp_path / "home"
    registry = home / "plugins" / "installed.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(contents)
    with pytest.raises(ValueError):
        install(payload, home)
    assert registry.read_text() == contents
    with installation_lock(registry.parent / ".analytical-memory-install.lock"):
        pass


def test_install_rejects_other_host_versions(
    payload: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a, 0, "0.40.0\n"),
    )
    with pytest.raises(ValueError, match="verified only"):
        install(payload, tmp_path / "home")
    assert not (tmp_path / "home").exists()


def test_failed_runtime_preparation_does_not_register(
    payload: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        if command[0] == "uv":
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0, "0.39.1\n")

    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(subprocess.CalledProcessError):
        install(payload, tmp_path / "home")
    assert not (tmp_path / "home" / "plugins" / "installed.json").exists()


def test_install_rejects_symlinks_and_nested_home(
    payload: Path, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="outside"):
        install(payload, payload / "home")
    (payload / "linked").symlink_to(tmp_path / "other")
    with pytest.raises(ValueError, match="symlink"):
        install(payload, tmp_path / "home")


@pytest.mark.parametrize("value", [None, 42, {}, "relative/path", "~/plugin"])
def test_invalid_existing_root_is_rejected(
    payload: Path, tmp_path: Path, value: object
) -> None:
    home = tmp_path / "home"
    registry = home / "plugins" / "installed.json"
    registry.parent.mkdir(parents=True)
    original = json.dumps(
        {"version": 1, "plugins": [{"id": "analytical-memory", "root": value}]}
    )
    registry.write_text(original)
    with pytest.raises(ValueError, match="absolute path string"):
        install(payload, home)
    assert registry.read_text() == original


def test_existing_lock_file_does_not_block_recovery(tmp_path: Path) -> None:
    lock = tmp_path / "lock"
    lock.write_text("left by an interrupted installer")
    with (
        installation_lock(lock),
        pytest.raises(ValueError, match="another.*installer"),
        installation_lock(lock),
    ):
        pass
    with installation_lock(lock):
        pass


def test_current_kimi_version_is_supported(
    payload: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, "2.0.2\n")
    )
    assert install(payload, tmp_path / "home")["registration"] == "installed"
