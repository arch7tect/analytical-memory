from __future__ import annotations

import argparse
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
INLINE_LINK = re.compile(r"!?\[[^\]]+\]\((<[^>]+>|[^\s)]+)(?:\s+\"[^\"]*\")?\)")
REFERENCE_LINK = re.compile(r"^ {0,3}\[[^\]]+\]:\s*(<[^>]+>|\S+)", re.MULTILINE)
HEADING = re.compile(r"^ {0,3}#{1,6}\s+(.+?)(?:\s+#+)?\s*$", re.MULTILINE)


def prose(text: str) -> str:
    lines = []
    fence = ""
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            run = marker.group(1)
            if not fence:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence):
                fence = ""
            lines.append("\n")
        else:
            lines.append("\n" if fence else line)
    return "".join(lines)


def anchors(text: str) -> set[str]:
    result: set[str] = set()
    for match in HEADING.finditer(prose(text)):
        heading = match.group(1).lower()
        heading = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", heading)
        base = "".join(
            char for char in heading if char.isalnum() or char in " _-"
        ).replace(" ", "-")
        candidate = base
        suffix = 0
        while candidate in result:
            suffix += 1
            candidate = f"{base}-{suffix}"
        result.add(candidate)
    return result


def markdown_files(root: Path) -> list[Path]:
    paths = set(root.glob("*.md"))
    for directory in ("docs", "plugin/skills", "skills"):
        paths.update((root / directory).rglob("*.md"))
    return sorted(paths)


def check_documents(root: Path) -> list[str]:
    problems = []
    anchor_cache: dict[Path, set[str]] = {}
    for source in markdown_files(root):
        text = prose(source.read_text(encoding="utf-8"))
        text = re.sub(r"(`+).*?\1", lambda m: " " * len(m.group()), text)
        for pattern in (INLINE_LINK, REFERENCE_LINK):
            for match in pattern.finditer(text):
                destination = match.group(1).strip("<>")
                url = urlsplit(destination)
                if url.scheme or url.netloc:
                    continue
                target = (
                    (source.parent / unquote(url.path)).resolve()
                    if url.path
                    else source
                )
                line = text[: match.start()].count("\n") + 1
                location = f"{source.relative_to(root)}:{line}"
                if not target.exists():
                    problems.append(f"{location}: missing target {destination}")
                elif url.fragment and target.suffix.lower() == ".md":
                    if target not in anchor_cache:
                        anchor_cache[target] = anchors(
                            target.read_text(encoding="utf-8")
                        )
                    if unquote(url.fragment) not in anchor_cache[target]:
                        problems.append(f"{location}: missing heading {destination}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check local Markdown links and ATX heading anchors."
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    root = parser.parse_args().root.resolve()
    if not (root / "README.md").is_file():
        parser.error("documentation root must contain README.md")
    problems = check_documents(root)
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print(f"Documentation links OK ({len(markdown_files(root))} Markdown files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
