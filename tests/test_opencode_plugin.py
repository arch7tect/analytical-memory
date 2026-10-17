from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.build_plugin_bundles import build_bundles
from scripts.configure_opencode import configuration


def test_generic_plugin_connects_both_components_and_preserves_existing_config(
    tmp_path: Path,
) -> None:
    build_bundles(tmp_path / "plugins")
    payload = tmp_path / "plugins" / "generic" / "analytical-memory"
    data = tmp_path / "data"
    document = configuration(payload, data)
    assert document["skills"] == [str(payload / "skills")]
    server = document["mcp"]["servers"]["analytical-memory"]
    assert server["environment"]["ANALYTICAL_MEMORY_PLUGIN_DATA"] == str(data)
    command = server["command"]
    assert command[command.index("--project") + 1] == str(payload)
    assert str(payload / "scripts" / "plugin_runtime.py") in command
    assert command[command.index("--extra") + 1] == "postgres"

    target = tmp_path / "workspace" / "opencode.json"
    args = [
        sys.executable,
        str(payload / "scripts" / "configure_opencode.py"),
        "--output",
        str(target),
        "--data-root",
        str(data),
    ]
    subprocess.run(args, check=True, capture_output=True)
    assert json.loads(target.read_text()) == document
    before = target.read_bytes()
    subprocess.run(args, check=True, capture_output=True)
    assert target.read_bytes() == before

    foreign = tmp_path / "existing" / "opencode.json"
    foreign.parent.mkdir()
    foreign.write_text('{"model":"existing/model","mcp":{"servers":{}}}\n')
    original = foreign.read_bytes()
    conflicting = [*args[:3], str(foreign), *args[4:]]
    assert subprocess.run(conflicting, capture_output=True).returncode == 2
    assert foreign.read_bytes() == original

    jsonc_project = tmp_path / "jsonc-project"
    jsonc_project.mkdir()
    jsonc = jsonc_project / "opencode.jsonc"
    jsonc.write_text('// Keep this comment\n{"model":"existing/model"}\n')
    original = jsonc.read_bytes()
    conflicting = [*args[:3], str(jsonc_project / "opencode.json"), *args[4:]]
    assert subprocess.run(conflicting, capture_output=True).returncode == 2
    assert jsonc.read_bytes() == original
    assert not (jsonc_project / "opencode.json").exists()
