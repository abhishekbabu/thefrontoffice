"""Tests for console encoding setup.

The CLI prints emoji and box-drawing characters. On Windows those go out as
UTF-16 to a real console, but fall back to the locale encoding (cp1252) the
moment output is redirected to a file or pipe — where they raise
UnicodeEncodeError and kill the process.
"""

import io
import sys

import pytest

from thefrontoffice.adapters.inbound.cli.repl import _configure_console

# A sample of the glyphs the UI actually prints.
UI_GLYPHS = "🏀 ⚡ ⏳ ✅ ❌ ⚠️ 📋 🔐 💬 🤖 👋 ═ ─ —"


def test_reconfigure_makes_a_cp1252_stream_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = io.BytesIO()
    stream = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", stream)

    _configure_console()
    print(UI_GLYPHS)
    sys.stdout.flush()

    assert raw.getvalue().decode("utf-8").strip() == UI_GLYPHS


def test_stderr_is_reconfigured_too(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stderr", io.TextIOWrapper(raw, encoding="cp1252", errors="strict"))

    _configure_console()
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
    _configure_console()  # must be a no-op, not an AttributeError


def test_already_utf8_stream_is_left_usable(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", io.TextIOWrapper(raw, encoding="utf-8"))
    _configure_console()
    print(UI_GLYPHS)
    sys.stdout.flush()
    assert raw.getvalue().decode("utf-8").strip() == UI_GLYPHS
