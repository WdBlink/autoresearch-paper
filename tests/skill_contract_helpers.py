from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILLS_ROOT = REPO_ROOT / "skills"


def parse_frontmatter(text: str) -> tuple[dict[str, object], str]:
    match = re.match(r"\A---\n(.*?)\n---\n?(.*)\Z", text, re.DOTALL)
    if not match:
        raise AssertionError("SKILL.md must contain YAML frontmatter")
    metadata = yaml.safe_load(match.group(1))
    if not isinstance(metadata, dict):
        raise AssertionError("SKILL.md frontmatter must be a mapping")
    return metadata, match.group(2)


def load_skill(name: str) -> tuple[dict[str, object], str]:
    return parse_frontmatter((SKILLS_ROOT / name / "SKILL.md").read_text())


def local_markdown_links(skill_dir: Path, body: str) -> list[Path]:
    targets = []
    for raw in re.findall(r"\[[^]]+\]\(([^)]+)\)", body):
        if raw.startswith(("http://", "https://", "#")):
            continue
        targets.append((skill_dir / raw.split("#", 1)[0]).resolve())
    return targets


def assert_compact_skill(testcase, name: str) -> str:
    path = SKILLS_ROOT / name / "SKILL.md"
    metadata, body = load_skill(name)
    testcase.assertEqual(set(metadata), {"name", "description"})
    testcase.assertEqual(metadata["name"], name)
    testcase.assertTrue(str(metadata["description"]).startswith("Use when"))
    testcase.assertNotIn("TO" + "DO", path.read_text())
    testcase.assertLessEqual(len(path.read_text().splitlines()), 220)
    testcase.assertLessEqual(len(path.read_text().split()), 1400)
    for target in local_markdown_links(path.parent, body):
        testcase.assertTrue(target.is_relative_to(path.parent.resolve()))
        testcase.assertTrue(target.exists(), str(target))
    return body
