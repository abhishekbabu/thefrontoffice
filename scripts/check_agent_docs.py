"""Enforce the agent-guidance conventions.

Mirrors the repo_lint rules that keep this structure honest elsewhere:

  * `AGENTS.md` is the source of truth; the sibling `CLAUDE.md` is a symlink to
    it. If it is ever a real file the two drift, and whichever tool reads the
    stale one gets stale rules.
  * Every `AGENTS.md` needs that sibling, or Claude silently sees nothing.
  * `AGENTS.md` stays under 200 lines. Guidance nobody reads is worse than none.
  * Every skill has frontmatter with a name and a description — the description
    is what a model matches against when deciding whether the skill applies.

Run with `just check-agents`.
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAX_AGENTS_LINES = 200
SKILLS_DIR = PROJECT_ROOT / ".agents" / "skills"

SKIP_DIRS = {".git", ".venv", "node_modules", "__pycache__"}


def _walk(root: Path, name: str) -> list[Path]:
    """Every `name` under `root`, including broken symlinks.

    Not `rglob`: it filters entries on `exists()`, so a CLAUDE.md pointing at a
    deleted AGENTS.md — exactly the breakage worth catching — is invisible to it.
    """
    found = []
    for directory, subdirs, files in os.walk(root):
        subdirs[:] = [d for d in subdirs if d not in SKIP_DIRS]
        if name in files:
            found.append(Path(directory) / name)
    return sorted(found)


def _is_unresolved_symlink(path: Path) -> bool:
    """Whether git checked a symlink out as a text file naming its target.

    Git on Windows does this whenever `core.symlinks` is off, which is the
    default without Developer Mode. The repo is still correct — the object is
    mode 120000 — so this is a checkout limitation to report, not a violation to
    fail on.
    """
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError, UnicodeDecodeError:
        return False
    return content == "AGENTS.md" and "\n" not in content


def check_symlinks(root: Path) -> list[str]:
    """CLAUDE.md must be a symlink resolving to its sibling AGENTS.md."""
    problems = []
    for claude in _walk(root, "CLAUDE.md"):
        rel = claude.relative_to(root)
        sibling = claude.with_name("AGENTS.md")
        if not claude.is_symlink():
            if _is_unresolved_symlink(claude):
                print(
                    f"  note: {rel} is a symlink in git but was checked out as a plain file "
                    "(core.symlinks is off — normal on Windows without Developer Mode)."
                )
                continue
            problems.append(f"{rel}: must be a symlink to the sibling AGENTS.md, not a real file")
            continue
        if not sibling.exists():
            problems.append(f"{rel}: symlink has no sibling AGENTS.md to point at")
            continue
        if claude.resolve() != sibling.resolve():
            problems.append(f"{rel}: resolves to {claude.resolve()}, expected {sibling}")
    return problems


def check_siblings(root: Path) -> list[str]:
    """Every AGENTS.md needs a CLAUDE.md beside it, or Claude sees nothing."""
    return [
        f"{agents.relative_to(root)}: needs a sibling CLAUDE.md symlink"
        for agents in _walk(root, "AGENTS.md")
        if not agents.with_name("CLAUDE.md").exists()
    ]


def check_length(root: Path) -> list[str]:
    """Guidance nobody reads is worse than none."""
    problems = []
    for agents in _walk(root, "AGENTS.md"):
        lines = len(agents.read_text(encoding="utf-8").splitlines())
        if lines > MAX_AGENTS_LINES:
            problems.append(f"{agents.relative_to(root)}: {lines} lines, maximum is {MAX_AGENTS_LINES}")
    return problems


def check_skills(root: Path) -> list[str]:
    """Each skill directory needs a SKILL.md with name and description."""
    if not SKILLS_DIR.exists():
        return []

    problems = []
    for directory in sorted(p for p in SKILLS_DIR.iterdir() if p.is_dir()):
        skill = directory / "SKILL.md"
        rel = skill.relative_to(root)
        if not skill.exists():
            problems.append(f"{directory.relative_to(root)}: no SKILL.md")
            continue

        lines = skill.read_text(encoding="utf-8").splitlines()
        if not lines or lines[0].strip() != "---":
            problems.append(f"{rel}: must open with YAML frontmatter")
            continue

        try:
            end = lines.index("---", 1)
        except ValueError:
            problems.append(f"{rel}: frontmatter is not closed")
            continue

        frontmatter = "\n".join(lines[1:end])
        for field in ("name:", "description:"):
            if field not in frontmatter:
                problems.append(f"{rel}: frontmatter is missing `{field}`")
        if f"name: {directory.name}" not in frontmatter:
            problems.append(f"{rel}: frontmatter name must match the directory, `{directory.name}`")
    return problems


def main() -> int:
    problems = (
        check_symlinks(PROJECT_ROOT)
        + check_siblings(PROJECT_ROOT)
        + check_length(PROJECT_ROOT)
        + check_skills(PROJECT_ROOT)
    )
    if problems:
        print("Agent documentation problems:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("Agent documentation OK.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
