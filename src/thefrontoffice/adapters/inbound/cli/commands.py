"""One function per slash command, each over the session's configured competitions."""

from thefrontoffice.adapters.inbound import presenting
from thefrontoffice.adapters.inbound.cli import output
from thefrontoffice.adapters.inbound.cli.output import print_error
from thefrontoffice.adapters.inbound.cli.render import render_scout_report, render_trade_verdict, render_week
from thefrontoffice.adapters.inbound.cli.session import Session
from thefrontoffice.bootstrap import CompetitionEntry, Registry
from thefrontoffice.domain.errors import (
    FrontOfficeError,
    NotConfiguredError,
    UnknownCompetitionError,
    UnsupportedError,
)
from thefrontoffice.domain.ports import TradeProvider

TRADES = "trade evaluation"


def print_help(session: Session) -> None:
    """Print the commands that will actually work here.

    Anything needing a model is omitted without one, the same way the web UI
    omits it — listing a command that can only refuse is worse than a shorter
    list, and the absence needs no explaining because nothing is missing.
    """
    keys = " | ".join(e.key for e in session.entries) or "none configured"
    tradeable = " | ".join(e.key for e in session.entries if e.can(TradeProvider))
    commands = [
        ("/leagues", "Every league you are in, per competition"),
        ("/week [competition]", "This week: the figures, the chance of winning, and what to do"),
        ("/roster [competition]", "Your squad"),
    ]
    if session.wiring.ai_available():
        commands.append((f"/scout [{keys}]", "Analyze a week. No competition runs every configured one"))
        if tradeable:
            commands.append((f"/trade [{tradeable}] <txt>", "Evaluate a trade in plain language"))
    commands += [
        ("/help", "Show this message"),
        ("/quit", "Exit"),
    ]

    print()
    print("  Available commands:")
    print("  ─────────────────────────────────────")
    width = max(len(c) for c, _ in commands)
    for command, description in commands:
        print(f"  {command.ljust(width)}   {description}")
    print()


def match(entries: list[CompetitionEntry], token: str) -> CompetitionEntry | None:
    """The entry in `entries` a token names — by key, or by competition alone — if any.

    Matched within the list passed in rather than the whole registry: the
    caller's list is the authority on what is available, and consulting the
    registry first lets the two disagree.
    """
    try:
        return Registry(tuple(entries)).find(token)
    except UnknownCompetitionError:
        return None


def _not_available(session: Session, token: str, needs: tuple[type[object], str] | None = None) -> bool:
    """Say why `token` names nothing in the session, where it names a competition at all.

    Args:
        needs: the port the command needs and what it is called, where the
            competition may be known and unable to do it.

    Returns:
        Whether it did: a word that is no competition can be the start of a trade.
    """
    try:
        known = session.wiring.registry.find(token)
    except FrontOfficeError:
        return False
    if needs is not None and not known.can(needs[0]):
        print_error(UnsupportedError(known.label, needs[1]))
    else:
        print_error(NotConfiguredError(known.label, known.requires))
    return True


def resolve(session: Session, args: list[str]) -> list[CompetitionEntry]:
    """Which competitions a command should run for.

    No argument means every configured competition; a named one means just
    that, provided it is configured.
    """
    if not args:
        return session.entries
    if (chosen := match(session.entries, args[0])) is not None:
        return [chosen]
    if not _not_available(session, args[0]):
        print(f"  ❓ Unknown competition: {args[0]}")
    return []


def scout(session: Session, args: list[str]) -> None:
    """Run a scouting report for each requested competition and league."""
    for entry in resolve(session, args):
        try:
            provider = session.provider(entry)
            refs = provider.list_leagues()
        except FrontOfficeError as e:
            print_error(e, entry.label)
            continue

        if not refs:
            print(f"  ⚠️  No {entry.label} leagues found for this season.")
            continue

        engine = session.wiring.scout(entry, provider)
        for ref in refs:
            output.header(f"{entry.label} — {ref.name}")
            if ref.detail:
                print(f"  {ref.detail}")
            print("  ⏳ Gathering league state and building the report...")
            try:
                report, chat = engine.start_analysis(ref.league_id)
            except FrontOfficeError as e:
                print_error(e)
                continue
            print("\n" + render_scout_report(report))
            output.follow_up(chat, "report", read=session.read)


def week(session: Session, args: list[str]) -> None:
    """Show this week for each requested competition and league, as the web page has it."""
    for entry in resolve(session, args):
        try:
            provider = session.provider(entry)
            engine = session.wiring.week(entry, provider)
            for ref in provider.list_leagues():
                output.header(f"{entry.label} — {ref.name}")
                print(render_week(presenting.week(engine.week(ref.league_id))))
        except FrontOfficeError as e:
            print_error(e, entry.label)


def roster(session: Session, args: list[str]) -> None:
    """Show the user's roster for each requested competition."""
    for entry in resolve(session, args):
        try:
            provider = session.provider(entry)
            for ref in provider.list_leagues():
                output.header(f"{entry.label} — {ref.name}")
                output.rows([card.columns for card in provider.roster(ref.league_id)])
        except FrontOfficeError as e:
            print_error(e, entry.label)


def leagues(session: Session) -> None:
    """List every league across configured competitions."""
    for entry in session.entries:
        output.header(entry.label)
        try:
            refs = session.provider(entry).list_leagues()
        except FrontOfficeError as e:
            print_error(e)
            continue
        if not refs:
            print("  (none this season)")
        for ref in refs:
            print(f"  • {ref.name}" + (f"  —  {ref.detail}" if ref.detail else ""))


def trade_competition(session: Session, args: list[str]) -> tuple[CompetitionEntry | None, list[str]]:
    """Split an optional leading competition off the trade description.

    A trade names players on one platform, so running the same text against
    every competition is meaningless. With one trade-capable competition there
    is nothing to disambiguate; with several the competition must be given
    rather than guessed.
    """
    tradeable = [e for e in session.entries if e.can(TradeProvider)]
    if args and (chosen := match(tradeable, args[0])) is not None:
        return chosen, args[1:]

    # A competition that exists but is not in `tradeable` has to be named as such.
    # Falling through would fold its name into the trade description and price
    # the trade against whichever competition happened to be the only tradeable
    # one — silently, because a description is free text.
    if args and _not_available(session, args[0], needs=(TradeProvider, TRADES)):
        return None, args

    if len(tradeable) == 1:
        return tradeable[0], args

    keys = " | ".join(e.key for e in tradeable)
    print(f"  ⚠️  Several competitions support trades. Name one: /trade [{keys}] <description>")
    return None, args


def trade(session: Session, args: list[str]) -> None:
    """Evaluate a trade: `/trade [competition] <description>`."""
    if not any(e.can(TradeProvider) for e in session.entries):
        print("  ⚠️  No configured competition supports trade evaluation yet.")
        return

    entry, args = trade_competition(session, args)
    if entry is None:
        return

    if not args:
        print("  ⚠️  Usage: /trade [competition] <trade description>")
        print("  Example: /trade Give LeBron James, Get Jayson Tatum")
        return

    trade_text = " ".join(args)
    try:
        provider = session.provider(entry)
        engine = session.wiring.trade(entry.as_port(provider, TradeProvider, TRADES))
        refs = provider.list_leagues()
    except FrontOfficeError as e:
        print_error(e, entry.label)
        return
    for ref in refs:
        output.header(f"{entry.label} — Trade Evaluation — {ref.name}")
        print("  ⏳ Parsing, enriching and evaluating...")
        try:
            verdict, chat = engine.evaluate(ref.league_id, trade_text)
        except FrontOfficeError as e:
            print_error(e)
            continue
        print("\n" + render_trade_verdict(verdict))
        output.follow_up(chat, "trade", read=session.read)
