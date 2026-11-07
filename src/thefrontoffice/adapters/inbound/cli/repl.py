"""The interactive loop.

Competition-neutral: the registry decides which competitions are available, and a platform
is only contacted when a command actually needs it.
"""

import contextlib
import sys
import textwrap
from datetime import datetime

from thefrontoffice import bootstrap
from thefrontoffice.adapters.inbound.cli import commands
from thefrontoffice.adapters.inbound.cli.output import configure_console, header, print_error
from thefrontoffice.adapters.inbound.cli.session import Session
from thefrontoffice.bootstrap import Wiring
from thefrontoffice.config.logging import setup_logging
from thefrontoffice.config.telemetry import setup_telemetry
from thefrontoffice.domain.errors import FrontOfficeError

# Graceful fallback on systems without readline
with contextlib.suppress(ImportError):
    import readline  # noqa: F401 — enables up/down arrow history in input()


def parse_command(raw: str) -> tuple[str, list[str]]:
    """Split a REPL line into a command and its positional arguments.

    The command token is case-insensitive, but positional arguments are not:
    `/trade Give LeBron, Get Tatum` must reach the AI with its casing intact,
    since player-name lookups against the platform depend on it.
    """
    parts = raw.split()
    if not parts:
        return ("", [])

    cmd = parts[0].lower()
    args = [a for a in parts[1:] if not a.startswith("--")]
    return (cmd, args)


class QuitRequested(Exception):
    """Raised by `dispatch` when the user asks to exit."""


def dispatch(session: Session, cmd: str, args: list[str]) -> None:
    """Route one parsed command to its handler.

    Raises:
        QuitRequested: the user asked to exit.
    """
    if cmd == "/scout":
        commands.scout(session, args)
    elif cmd == "/week":
        commands.week(session, args)
    elif cmd in ("/roster", "/rosters", "/my-roster"):
        commands.roster(session, args)
    elif cmd == "/leagues":
        commands.leagues(session)
    elif cmd == "/trade":
        commands.trade(session, args)
    elif cmd == "/help":
        commands.print_help(session)
    elif cmd in ("/quit", "/exit", "/q"):
        raise QuitRequested
    else:
        print(f"  ❓ Unknown command: {cmd}. Type /help for available commands.")


def main() -> None:
    """Start a REPL over whichever competitions are configured: `just run`."""
    configure_console()
    setup_logging()
    # After setup_logging, so the bridge attaches to a root logger that already
    # has its level and its console handler.
    setup_telemetry("front-office-cli")
    run(bootstrap.wiring())


def run(wiring: Wiring) -> None:
    """The REPL over `wiring`, until the user quits."""
    header("🏆 The Front Office — Fantasy Intelligence")
    # The reader's own clock, said so: a banner is for the person at the terminal.
    print(f"  {datetime.now().astimezone().strftime('%A, %B %d %Y  •  %I:%M %p')}")

    session = Session(wiring)
    if not session.entries:
        print("\n  ⚠️  No competitions configured. Set one of these in .env:")
        for entry in wiring.registry.entries:
            print(f"       {entry.label}: {entry.requires}")
        sys.exit(1)

    print(f"\n  ✅ Configured: {', '.join(e.label for e in session.entries)}")
    unconfigured = [e for e in wiring.registry.entries if e not in session.entries]
    if unconfigured:
        print(
            textwrap.fill(
                "  Also available: " + "; ".join(f"{e.label} (set {e.requires})" for e in unconfigured),
                width=78,
                subsequent_indent="    ",
            )
        )
    commands.print_help(session)

    while True:
        try:
            raw = input("  ⚡ ").strip()
        except KeyboardInterrupt, EOFError:
            print("\n")
            header("Goodbye 👋")
            break

        if not raw:
            continue

        cmd, args = parse_command(raw)

        try:
            dispatch(session, cmd, args)
        except FrontOfficeError as e:
            # Safety net — handlers render their own errors, but a session must
            # never die because one command raised.
            print_error(e)
        except QuitRequested:
            header("Goodbye 👋")
            break

    header("Done ✅")


if __name__ == "__main__":
    main()
