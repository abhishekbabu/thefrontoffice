"""Terminal output helpers."""

import contextlib
import sys
from collections.abc import Callable

from thefrontoffice.adapters.inbound.conversation import Conversation
from thefrontoffice.adapters.inbound.remedies import remedy
from thefrontoffice.domain.errors import FrontOfficeError
from thefrontoffice.domain.ports import ChatSession


def configure_console() -> None:
    """Make stdout/stderr able to carry the UI's emoji and box-drawing glyphs.

    Python writes to a Windows *console* as UTF-16 and handles them fine, but as
    soon as output is redirected to a file or pipe it falls back to the locale
    encoding — cp1252 on most Windows installs — where every one of those
    characters raises UnicodeEncodeError and takes the process down.

    Reconfiguring to UTF-8 fixes redirection; errors="replace" means a terminal
    that genuinely cannot represent a glyph degrades to a placeholder instead of
    crashing. No-op where the streams are already UTF-8, or replaced entirely
    (pytest's capture, for instance, offers no reconfigure()).
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        # Already detached, or not reconfigurable — the UI is still usable.
        with contextlib.suppress(ValueError, OSError):
            reconfigure(encoding="utf-8", errors="replace")


def header(text: str) -> None:
    width = 60
    print("\n" + "═" * width)
    print(f"  {text}")
    print("═" * width)


def rows(rows: list[dict[str, str]]) -> None:
    """Table rows, each column as wide as its widest value."""
    if not rows:
        print("  (no players found)")
        return
    columns = list(rows[0])
    widths = {c: max(len(c), max(len(str(r.get(c, ""))) for r in rows)) for c in columns}
    print("  " + "  ".join(c.ljust(widths[c]) for c in columns))
    print("  " + "  ".join("─" * widths[c] for c in columns))
    for row in rows:
        print("  " + "  ".join(str(row.get(c, "")).ljust(widths[c]) for c in columns))


def follow_up(chat: ChatSession, noun: str, *, read: Callable[[str], str] = input) -> None:
    """Questions about what was just shown, asked in the open chat until an empty line.

    Args:
        read: what prompts for a line; the terminal's own `input` but in a test.
    """
    conversation = Conversation(chat)
    print("\n  " + "─" * 60)
    print(f"  💬 Interactive Mode: Ask follow-up questions about this {noun}.")
    print("     Type your question or press Enter to continue.")
    print("  " + "─" * 60)

    while True:
        try:
            user_input = read("\n  Query > ").strip()
            if not user_input or user_input.lower() in ("/quit", "/exit", "q"):
                break

            print("  ⏳ Thinking...")
            print(f"\n  🤖 {conversation.ask(user_input)}")
        except KeyboardInterrupt, EOFError:
            break
        except FrontOfficeError as e:
            print_error(e)
            break


def print_error(error: FrontOfficeError, prefix: str = "") -> None:
    """Render a failure, plus the terminal's way of fixing it if there is one."""
    label = f"{prefix}: " if prefix else ""
    print(f"  ❌ {label}{error}")
    fix = remedy(error)
    if fix and fix.command:
        print(f"     {fix.command}")
