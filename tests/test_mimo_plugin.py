from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from scripts import configure_mimo
from scripts.build_plugin_bundles import build_bundles


@pytest.fixture
def payload(tmp_path: Path) -> Path:
    build_bundles(tmp_path / "plugins")
    return tmp_path / "plugins" / "generic" / "analytical-memory"


def test_mimo_bundle_configures_both_components_and_is_repeatable(
    tmp_path: Path, payload: Path
) -> None:
    workspace = tmp_path / "workspace"
    data = tmp_path / "data"
    command = [
        sys.executable,
        str(payload / "scripts" / "configure_mimo.py"),
        "--workspace",
        str(workspace),
        "--data-root",
        str(data),
    ]
    subprocess.run(command, check=True, capture_output=True)
    output = workspace / ".mimocode" / "mimocode.jsonc"
    document = json.loads(output.read_text())
    assert document["skills"] == {"paths": [str(payload / "skills")]}
    server = document["mcp"]["analytical-memory"]
    assert server["timeout"] == 600_000
    assert server["environment"]["ANALYTICAL_MEMORY_PLUGIN_DATA"] == str(data)
    assert str(payload / "scripts" / "plugin_runtime.py") in server["command"]
    assert server["command"][server["command"].index("--project") + 1] == str(payload)
    assert server["command"][server["command"].index("--extra") + 1] == "postgres"
    before = output.read_bytes()
    subprocess.run(command, check=True, capture_output=True)
    assert output.read_bytes() == before


@pytest.mark.parametrize(
    "location",
    [
        ".mimocode/mimocode.jsonc",
        ".mimocode/mimocode.json",
        "mimocode.jsonc",
        "mimocode.json",
    ],
)
def test_mimo_preserves_existing_configuration(
    tmp_path: Path, payload: Path, location: str
) -> None:
    workspace = tmp_path / "workspace"
    existing = workspace / location
    existing.parent.mkdir(parents=True)
    original = '// Keep settings and comments\n{"model":"existing/model"}\n'
    existing.write_text(original)
    with pytest.raises(ValueError, match="preserved|another config"):
        configure_mimo.configure(workspace, configure_mimo.configuration(payload))
    assert existing.read_text() == original


def test_mimo_does_not_write_through_config_symlink(
    tmp_path: Path, payload: Path
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (workspace / ".mimocode").symlink_to(foreign, target_is_directory=True)
    with pytest.raises(ValueError, match="linked"):
        configure_mimo.configure(workspace, configure_mimo.configuration(payload))
    assert list(foreign.iterdir()) == []


def test_mimo_check_reports_only_bounded_host_status(
    tmp_path: Path, payload: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config: dict[str, Any] = configure_mimo.configuration(payload)
    skills = [
        {
            "name": name,
            "location": str(payload / "skills" / name / "SKILL.md"),
            "content": "irrelevant skill body " * 10_000,
        }
        for name in configure_mimo.SKILLS
    ]
    status = "●  ✓ analytical-memory \x1b[90mconnected opencode:/project/config\n"

    def output(cli: str, workspace: Path, *args: str) -> str:
        assert cli == "mimo"
        if args == ("debug", "config"):
            return json.dumps(config)
        if args == ("debug", "skill"):
            return json.dumps(skills)
        assert args == ("mcp", "list")
        return status

    monkeypatch.setattr(configure_mimo, "host_output", output)
    result = configure_mimo.check_host("mimo", tmp_path, payload)
    assert result["mcp"] == "connected"
    assert result["skills"] == dict.fromkeys(configure_mimo.SKILLS, "available")
    assert len(json.dumps(result)) < 350
    status = "● analytical-memory disconnected\n● other connected\n"
    with pytest.raises(ValueError, match="connected"):
        configure_mimo.check_host("mimo", tmp_path, payload)
    status = "● ✓ analytical-memory connected\n"
    skills[0]["location"] = str(tmp_path / "old-plugin" / "SKILL.md")
    with pytest.raises(ValueError, match="another installation"):
        configure_mimo.check_host("mimo", tmp_path, payload)
    skills[0]["location"] = str(
        payload / "skills" / configure_mimo.SKILLS[0] / "SKILL.md"
    )
    config["mcp"]["analytical-memory"]["command"] = ["old-runtime"]
    with pytest.raises(ValueError, match="launch command"):
        configure_mimo.check_host("mimo", tmp_path, payload)
