from pathlib import Path

from scripts.check_docs import anchors, check_documents


def test_local_links_report_missing_files_and_headings(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        "[Valid](guide.md#setup)\n"
        "[Missing file](missing.md)\n"
        "[Missing heading](guide.md#absent)\n"
        "[Remote](https://example.com/guide)\n"
        "[MCP resource](memory://guide)\n"
        "`[Inline example](ignored.md)`\n"
        "```md\n[Example](ignored.md)\n```\n"
        "# Home\n[Same page](#home)\n[Missing local heading](#absent)\n"
    )
    (tmp_path / "guide.md").write_text("# Guide\n\n## Setup\n")
    assert check_documents(tmp_path) == [
        "README.md:2: missing target missing.md",
        "README.md:3: missing heading guide.md#absent",
        "README.md:12: missing heading #absent",
    ]


def test_reference_links_and_encoded_paths(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        "[Guide](<user guide.md#start-here>)\n"
        "[Encoded](user%20guide.md#start-here)\n"
        "[Reference][guide]\n\n[guide]: <user guide.md#start-here>\n"
    )
    (tmp_path / "user guide.md").write_text("# Start here\n")
    assert check_documents(tmp_path) == []


def test_duplicate_heading_anchors_and_fenced_examples() -> None:
    assert anchors("## `Setup`\n## Setup\n```md\n## Example\n```\n") == {
        "setup",
        "setup-1",
    }
