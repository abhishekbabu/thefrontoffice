"""Terminal output helpers."""

from thefrontoffice.domain.errors import FrontOfficeError
from thefrontoffice.domain.ports import ChatSession


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


def follow_up(chat: ChatSession, noun: str) -> None:
    """Questions about what was just shown, asked in the open chat until an empty line."""
    print("\n  " + "─" * 60)
    print(f"  💬 Interactive Mode: Ask follow-up questions about this {noun}.")
    print("     Type your question or press Enter to continue.")
    print("  " + "─" * 60)

    while True:
        try:
            user_input = input("\n  Query > ").strip()
            if not user_input or user_input.lower() in ("/quit", "/exit", "q"):
                break

            print("  ⏳ Thinking...")
            response = chat.send_message(user_input)
            print(f"\n  🤖 {response.text}")
        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"  ❌ Error: {e}")
            break


# What a terminal can do about a condition the domain only describes. The web
# adapter offers a button for the same codes; neither belongs in the error.
CLI_REMEDIES = {
    "yahoo_login_required": "Run `just yahoo-login` to authorize.",
    "yahoo_not_approved": "Apply at https://sports.yahoo.com/developer/access/, then `just yahoo-login --force`.",
}


def print_error(error: FrontOfficeError, prefix: str = "") -> None:
    """Render a failure, plus the terminal's way of fixing it if there is one."""
    label = f"{prefix}: " if prefix else ""
    print(f"  ❌ {label}{error}")
    remedy = CLI_REMEDIES.get(error.code)
    if remedy:
        print(f"     {remedy}")
