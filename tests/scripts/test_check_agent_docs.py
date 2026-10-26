"""Tests for the agent-documentation checker.

The conventions it guards are invisible at runtime — a CLAUDE.md that drifted
into a real file keeps working until someone edits one half and wonders why the
other tool ignored it.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

import check_agent_docs as checker  # noqa: E402


def _agents(root: Path, folder: str = "", body: str = "# Rules\n") -> Path:
    directory = root / folder if folder else root
    directory.mkdir(parents=True, exist_ok=True)
    agents = directory / "AGENTS.md"
    agents.write_text(body, encoding="utf-8")
    return agents


def _link(agents: Path) -> Path:
    claude = agents.with_name("CLAUDE.md")
    claude.symlink_to("AGENTS.md")
    return claude


# ── symlinks ────────────────────────────────────────────────────────────


def test_a_correct_symlink_passes(tmp_path: Path) -> None:
    _link(_agents(tmp_path))
    assert checker.check_symlinks(tmp_path) == []


def test_a_real_file_is_rejected(tmp_path: Path) -> None:
    """The whole point: two real files drift, and each tool reads a different one."""
    _agents(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("# different rules\n", encoding="utf-8")
    problems = checker.check_symlinks(tmp_path)
    assert problems and "not a real file" in problems[0]


def test_a_symlink_to_the_wrong_target_is_rejected(tmp_path: Path) -> None:
    _agents(tmp_path)
    (tmp_path / "OTHER.md").write_text("x", encoding="utf-8")
    (tmp_path / "CLAUDE.md").symlink_to("OTHER.md")
    problems = checker.check_symlinks(tmp_path)
    assert problems and "expected" in problems[0]


def test_a_dangling_symlink_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").symlink_to("AGENTS.md")
    problems = checker.check_symlinks(tmp_path)
    assert problems and "no sibling" in problems[0]


def test_the_windows_checkout_form_is_tolerated(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Git without core.symlinks writes the target name into a plain file. The
    repo object is still mode 120000, so this is a checkout limit, not a fault."""
    _agents(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("AGENTS.md", encoding="utf-8")
    assert checker.check_symlinks(tmp_path) == []
    assert "core.symlinks is off" in capsys.readouterr().out


def test_a_file_merely_mentioning_agents_md_is_still_rejected(tmp_path: Path) -> None:
    _agents(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("see AGENTS.md for details\n", encoding="utf-8")
    assert checker.check_symlinks(tmp_path) != []


# ── siblings and length ─────────────────────────────────────────────────


def test_an_agents_file_without_a_sibling_is_rejected(tmp_path: Path) -> None:
    """Without it, Claude silently sees no guidance at all."""
    _agents(tmp_path, "backend")
    problems = checker.check_siblings(tmp_path)
    assert problems and "needs a sibling" in problems[0]


def test_nested_agents_files_are_checked_too(tmp_path: Path) -> None:
    _link(_agents(tmp_path))
    _agents(tmp_path, "deep/nested")
    assert len(checker.check_siblings(tmp_path)) == 1


def test_an_over_long_agents_file_is_rejected(tmp_path: Path) -> None:
    """Guidance nobody reads is worse than none."""
    _link(_agents(tmp_path, body="line\n" * (checker.MAX_AGENTS_LINES + 1)))
    problems = checker.check_length(tmp_path)
    assert problems and str(checker.MAX_AGENTS_LINES) in problems[0]


def test_a_file_at_the_limit_passes(tmp_path: Path) -> None:
    _link(_agents(tmp_path, body="line\n" * checker.MAX_AGENTS_LINES))
    assert checker.check_length(tmp_path) == []


def test_ignored_directories_are_skipped(tmp_path: Path) -> None:
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "AGENTS.md").write_text("x", encoding="utf-8")
    assert checker.check_siblings(tmp_path) == []


# ── the repo itself ─────────────────────────────────────────────────────


def test_this_repo_satisfies_every_convention() -> None:
    root = Path(__file__).resolve().parents[2]
    assert checker.check_symlinks(root) == []
    assert checker.check_siblings(root) == []
    assert checker.check_length(root) == []
    assert checker.check_skills(root) == []


def test_every_skill_is_discoverable_through_the_claude_symlink() -> None:
    """Claude finds skills via .claude/skills -> .agents/skills; a copy would rot."""
    root = Path(__file__).resolve().parents[2]
    link = root / ".claude" / "skills"
    assert link.is_symlink() or link.exists()
    assert link.resolve() == (root / ".agents" / "skills").resolve()
