"""Tests for terminal output: the console's encoding, tables and errors."""

import io
import sys
from collections.abc import Callable

import pytest
from support.ai import FakeChat

from thefrontoffice.adapters.inbound.cli import output
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooLoginRequiredError
from thefrontoffice.domain.errors import AIKeyInvalidError, AIQuotaError


def test_rows_are_printed_with_aligned_columns(capsys: pytest.CaptureFixture[str]) -> None:
    output.rows([{"Player": "A", "Pos": "QB"}, {"Player": "Longer Name", "Pos": "RB"}])
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len({len(ln.rstrip()) for ln in lines}) <= 2  # header, rule and rows align


def test_an_empty_roster_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    """Rather than printing nothing, which reads as a hang or a crash."""
    output.rows([])
    assert capsys.readouterr().out.strip()


def test_an_error_the_terminal_can_fix_names_the_fix(capsys: pytest.CaptureFixture[str]) -> None:
    output.print_error(YahooLoginRequiredError(), "NBA (Yahoo)")

    out = capsys.readouterr().out
    assert "NBA (Yahoo)" in out and "just yahoo-login" in out


def test_a_setting_to_fix_is_pointed_at_in_env_not_at_a_page(capsys: pytest.CaptureFixture[str]) -> None:
    """Settings is a page; a terminal has no button to point at, so it names the file instead."""
    output.print_error(AIKeyInvalidError("Gemini", "GOOGLE_API_KEY"))

    out = capsys.readouterr().out
    assert "GOOGLE_API_KEY" in out and ".env" in out and "Settings" not in out


def test_an_error_with_nothing_to_offer_prints_the_message_alone(capsys: pytest.CaptureFixture[str]) -> None:
    output.print_error(AIQuotaError("Gemini"))

    assert len(capsys.readouterr().out.strip().splitlines()) == 1


# ── follow-up questions ─────────────────────────────────────────────────


def _lines(*typed: str) -> Callable[[str], str]:
    """What a person types at each prompt, then an empty line to finish."""
    pending = iter([*typed, ""])
    return lambda _prompt: next(pending)


def test_a_follow_up_is_answered_until_an_empty_line(capsys: pytest.CaptureFixture[str]) -> None:
    chat = FakeChat(reply="Start him.")

    output.follow_up(chat, "report", read=_lines("Who?", "And?"))

    assert chat.sent == ["Who?", "And?"]
    assert "Start him." in capsys.readouterr().out


def test_a_failed_follow_up_keeps_the_errors_remedy(capsys: pytest.CaptureFixture[str]) -> None:
    """As the web chat does: a domain error is already a sentence, and its fix is worth printing."""
    output.follow_up(FakeChat(error=AIKeyInvalidError("Gemini", "GOOGLE_API_KEY")), "report", read=_lines("Who?"))

    assert ".env" in capsys.readouterr().out


def test_an_untranslated_failure_is_not_shown_as_the_vendors_payload(capsys: pytest.CaptureFixture[str]) -> None:
    output.follow_up(FakeChat(error=RuntimeError("{'error': {'code': 500}}")), "report", read=_lines("Who?"))

    out = capsys.readouterr().out
    assert "did not answer" in out and "'code'" not in out


# ── console encoding ────────────────────────────────────────────────────
# The CLI prints emoji and box-drawing characters. On Windows those go out as
# UTF-16 to a real console, but fall back to the locale encoding (cp1252) the
# moment output is redirected to a file or pipe, where they raise
# UnicodeEncodeError and kill the process.

# A sample of the glyphs the UI actually prints.
UI_GLYPHS = "🏀 ⚡ ⏳ ✅ ❌ ⚠️ 📋 🔐 💬 🤖 👋 ═ ─ —"


def test_reconfigure_makes_a_cp1252_stream_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)

    output.configure_console()
    sys.stdout.write(UI_GLYPHS)
    sys.stdout.flush()

    assert raw.getvalue().decode("utf-8").strip() == UI_GLYPHS


def test_stderr_is_reconfigured_too(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(raw, encoding="cp1252", errors="strict"))

    output.configure_console()
    sys.stderr.write(UI_GLYPHS)
    sys.stderr.flush()

    assert raw.getvalue().decode("utf-8") == UI_GLYPHS


def test_streams_without_reconfigure_are_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """pytest's own capture objects have no reconfigure(); must not raise."""

    class Bare:
        def write(self, s: str) -> int:
            return len(s)

    monkeypatch.setattr(sys, "stdout", Bare())
    monkeypatch.setattr(sys, "stderr", Bare())
    output.configure_console()  # must be a no-op, not an AttributeError


def test_already_utf8_stream_is_left_usable(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="utf-8"))
    output.configure_console()
    sys.stdout.write(UI_GLYPHS)
    sys.stdout.flush()
    assert raw.getvalue().decode("utf-8").strip() == UI_GLYPHS
