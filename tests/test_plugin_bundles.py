from pathlib import Path

from scripts.build_plugin_bundles import build_bundles

SKILLS = {"analytical-memory", "analytical-memory-inspect"}


def _skills_root(output: Path, host: str) -> Path:
    if host == "openai":
        return output / host / "plugins" / "analytical-memory" / "skills"
    return output / host / "analytical-memory" / "skills"


def test_plugin_skills_are_shared_with_openai_metadata_only_for_codex(
    tmp_path: Path,
) -> None:
    build_bundles(tmp_path)

    for host in ("claude", "kimi", "openai"):
        skills_root = _skills_root(tmp_path, host)
        assert {path.name for path in skills_root.iterdir()} == SKILLS
        for skill_name in SKILLS:
            skill = skills_root / skill_name
            assert (skill / "SKILL.md").is_file()
            assert (skill / "agents" / "openai.yaml").is_file() is (host == "openai")
