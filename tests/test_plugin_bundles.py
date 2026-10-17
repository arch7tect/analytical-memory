import json
from pathlib import Path

from scripts.build_plugin_bundles import HOSTS, build_bundles
from scripts.check_docs import check_documents

SKILLS = {"analytical-memory", "analytical-memory-inspect"}


def _skills_root(output: Path, host: str) -> Path:
    if host == "openai":
        return output / host / "plugins" / "analytical-memory" / "skills"
    return output / host / "analytical-memory" / "skills"


def test_plugin_skills_are_shared_with_openai_metadata_only_for_codex(
    tmp_path: Path,
) -> None:
    build_bundles(tmp_path)
    kimi_root = tmp_path / "kimi" / "analytical-memory"
    kimi_manifest = json.loads((kimi_root / "kimi.plugin.json").read_text())
    for server in kimi_manifest["mcpServers"].values():
        # Kimi ignores plugin servers whose cwd lacks its required ./ prefix.
        assert server["cwd"].startswith("./")
        assert (kimi_root / server["cwd"]).resolve().is_relative_to(kimi_root.resolve())

    for host in HOSTS:
        skills_root = _skills_root(tmp_path, host)
        assert check_documents(skills_root.parent) == []
        assert check_documents(tmp_path / host) == []
        assert (skills_root.parent / "docs" / "plugin-installation.md").is_file()
        assert {path.name for path in skills_root.iterdir()} == SKILLS
        for skill_name in SKILLS:
            skill = skills_root / skill_name
            assert (skill / "SKILL.md").is_file()
            assert (skill / "agents" / "openai.yaml").is_file() is (host == "openai")
