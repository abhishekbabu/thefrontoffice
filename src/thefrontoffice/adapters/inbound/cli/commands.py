"""One function per slash command."""

from thefrontoffice.adapters.inbound.cli.output import _interactive_followup, _print_header, _print_rows, print_error
from thefrontoffice.adapters.inbound.cli.render import render_scout_report, render_trade_verdict
from thefrontoffice.adapters.inbound.cli.session import Session
from thefrontoffice.bootstrap import CompetitionEntry, find, scout_engine, trade_engine
from thefrontoffice.domain.errors import FrontOfficeError
from thefrontoffice.domain.ports import TradeProvider


def _print_help(entries: list[CompetitionEntry]) -> None:
    """Print the commands that will actually work here.

    Anything needing a model is omitted without one, the same way the web UI
    omits it — listing a command that can only refuse is worse than a shorter
    list, and the absence needs no explaining because nothing is missing.
    """
    from thefrontoffice.bootstrap import ai_available

    keys = " | ".join(e.competition for e in entries) or "none configured"
    tradeable = " | ".join(e.competition for e in entries if e.supports_trades) or "none"
    rows = [
        ("/leagues", "Every league you are in, per competition"),
        ("/roster [competition]", "Your squad"),
    ]
    if ai_available():
        rows.append((f"/scout [{keys}]", "Analyze a week. No competition runs every configured one"))
        if tradeable != "none":
            rows.append((f"/trade [{tradeable}] <txt>", "Evaluate a trade in plain language"))
    rows += [
        ("/help", "Show this message"),
        ("/quit", "Exit"),
    ]

    print()
    print("  Available commands:")
    print("  ─────────────────────────────────────")
    width = max(len(c) for c, _ in rows)
    for command, description in rows:
        print(f"  {command.ljust(width)}   {description}")
    print()


def _match_competition(entries: list[CompetitionEntry], token: str) -> CompetitionEntry | None:
    """The entry in `entries` a user's competition token names, if any.

    Matched within the list passed in rather than through the registry: the
    caller's list is the authority on what is available, and consulting the
    registry first lets the two disagree.
    """
    key = token.lower().lstrip("/")
    return next((entry for entry in entries if entry.competition == key), None)


def _resolve_competitions(args: list[str], entries: list[CompetitionEntry]) -> list[CompetitionEntry]:
    """Which competitions a command should run for.

    No argument means every configured competition; a named one means just that,
    provided it is configured.
    """
    if not args:
        return entries

    if (chosen := _match_competition(entries, args[0])) is not None:
        return [chosen]

    known = find(args[0])
    if known is None:
        print(f"  ❓ Unknown competition: {args[0]}")
    else:
        print(f"  ⚠️  {known.label} is not configured. Set {known.requires} in .env.")
    return []


def _cmd_scout(session: Session, entries: list[CompetitionEntry], args: list[str]) -> None:
    """Run a scouting report for each requested competition and league."""
    for entry in _resolve_competitions(args, entries):
        try:
            provider = session.provider(entry)
            refs = provider.list_leagues()
        except FrontOfficeError as e:
            print_error(e, entry.label)
            continue

        if not refs:
            print(f"  ⚠️  No {entry.label} leagues found for this season.")
            continue

        engine = scout_engine(provider)
        for ref in refs:
            _print_header(f"{entry.label} — {ref.name}")
            if ref.detail:
                print(f"  {ref.detail}")
            print("  ⏳ Gathering league state and building the report...")
            try:
                report, chat = engine.start_analysis(ref.league_id)
            except FrontOfficeError as e:
                print_error(e)
                continue
            print("\n" + render_scout_report(report))
            _interactive_followup(chat, "report")


def _cmd_roster(session: Session, entries: list[CompetitionEntry], args: list[str]) -> None:
    """Show the user's roster for each requested competition."""
    for entry in _resolve_competitions(args, entries):
        try:
            provider = session.provider(entry)
            for ref in provider.list_leagues():
                _print_header(f"{entry.label} — {ref.name}")
                _print_rows([card.columns for card in provider.roster(ref.league_id)])
        except FrontOfficeError as e:
            print_error(e, entry.label)


def _cmd_leagues(session: Session, entries: list[CompetitionEntry]) -> None:
    """List every league across configured competitions."""
    for entry in entries:
        _print_header(entry.label)
        try:
            refs = session.provider(entry).list_leagues()
        except FrontOfficeError as e:
            print_error(e)
            continue
        if not refs:
            print("  (none this season)")
        for ref in refs:
            print(f"  • {ref.name}" + (f"  —  {ref.detail}" if ref.detail else ""))


def _trade_competition(tradeable: list[CompetitionEntry], args: list[str]) -> tuple[CompetitionEntry | None, list[str]]:
    """Split an optional leading competition off the trade description.

    A trade names players on one platform, so running the same text against
    every competition is meaningless. With one trade-capable competition there is nothing to
    disambiguate; with several the competition must be given rather than guessed.
    """
    if args and (chosen := _match_competition(tradeable, args[0])) is not None:
        return chosen, args[1:]

    # A competition that exists but is not in `tradeable` has to be named as such.
    # Falling through would fold the competition token into the trade description and
    # price the trade against whichever competition happened to be the only tradeable
    # one — silently, because a description is free text.
    if args and (known := find(args[0])) is not None:
        if known.supports_trades:
            print(f"  ⚠️  {known.label} is not configured. Set {known.requires} in .env.")
        else:
            print(f"  ⚠️  {known.label} does not support trade evaluation.")
        return None, args

    if len(tradeable) == 1:
        return tradeable[0], args

    keys = " | ".join(e.competition for e in tradeable)
    print(f"  ⚠️  Several competitions support trades. Name one: /trade [{keys}] <description>")
    return None, args


def _cmd_trade(session: Session, entries: list[CompetitionEntry], args: list[str]) -> None:
    """Evaluate a trade: `/trade [competition] <description>`."""
    tradeable = [e for e in entries if e.supports_trades]
    if not tradeable:
        print("  ⚠️  No configured competition supports trade evaluation yet.")
        return

    entry, args = _trade_competition(tradeable, args)
    if entry is None:
        return

    if not args:
        print("  ⚠️  Usage: /trade [competition] <trade description>")
        print("  Example: /trade Give LeBron James, Get Jayson Tatum")
        return

    trade_text = " ".join(args)
    provider = session.provider(entry)
    if not isinstance(provider, TradeProvider):
        # The entry says it trades but its provider cannot: a registry slip,
        # said plainly rather than an AttributeError mid-evaluation.
        print(f"  ⚠️  {entry.label} does not support trade evaluation.")
        return
    engine = trade_engine(provider)
    for ref in provider.list_leagues():
        _print_header(f"{entry.label} — Trade Evaluation — {ref.name}")
        print("  ⏳ Parsing, enriching and evaluating...")
        try:
            verdict, chat = engine.evaluate(ref.league_id, trade_text)
        except FrontOfficeError as e:
            print_error(e)
            continue
        print("\n" + render_trade_verdict(verdict))
        _interactive_followup(chat, "trade")
