"""Tests for REPL command parsing and sport selection."""

from thefrontoffice.adapters.inbound.cli.repl import parse_command


def test_command_token_is_case_insensitive() -> None:
    assert parse_command("/SCOUT")[0] == "/scout"
    assert parse_command("/Rosters")[0] == "/rosters"


def test_argument_casing_is_preserved() -> None:
    """Player-name lookups depend on casing, so only the command token is
    lowercased."""
    cmd, args = parse_command("/trade Give LeBron James, Get Jayson Tatum")
    assert cmd == "/trade"
    assert args == ["Give", "LeBron", "James,", "Get", "Jayson", "Tatum"]


def test_flags_are_stripped_from_arguments() -> None:
    """A flag is never part of a trade description or a sport name."""
    cmd, args = parse_command("/trade --verbose Give LeBron")
    assert cmd == "/trade"
    assert args == ["Give", "LeBron"]


def test_empty_input_yields_empty_command() -> None:
    assert parse_command("") == ("", [])
    assert parse_command("   ") == ("", [])


# ── sport-aware dispatch ────────────────────────────────────────────────

from typing import Any  # noqa: E402

import pytest  # noqa: E402

from thefrontoffice.adapters.inbound.cli import commands as cmd  # noqa: E402
from thefrontoffice.adapters.inbound.cli import output  # noqa: E402
from thefrontoffice.adapters.inbound.cli import repl as cli  # noqa: E402
from thefrontoffice.adapters.inbound.cli.session import Session  # noqa: E402
from thefrontoffice.domain.models import PlayerCard  # noqa: E402


class FakeProvider:
    sport = "football"
    competition = "nfl"
    label = "NFL (Sleeper)"

    def list_leagues(self) -> Any:
        from thefrontoffice.domain.ports import LeagueRef

        return [LeagueRef("L1", "My League", "nfl", "12-team")]

    def roster(self, league_id: str) -> list[PlayerCard]:
        return [PlayerCard(player_id="qb1", columns={"Player": "Star QB", "Pos": "QB"})]


SPORT_OF = {"nfl": "football", "nba": "basketball", "premier-league": "soccer"}


def fake_entry(
    competition: str = "nfl",
    label: str = "NFL (Sleeper)",
    build: Any = None,
    counter: list[int] | None = None,
) -> Any:
    """A real CompetitionEntry with a stubbed build, so the CLI sees what it expects."""
    from thefrontoffice.bootstrap import CompetitionEntry

    def _build() -> Any:
        if counter is not None:
            counter.append(1)
        return FakeProvider()

    return CompetitionEntry(
        sport=SPORT_OF.get(competition, "football"),
        competition=competition,
        platform=competition,
        label=label,
        build=build or _build,
        is_configured=lambda: True,
        requires="SLEEPER_USERNAME" if competition == "nfl" else "YAHOO_CLIENT_ID",
    )


def test_providers_are_built_once_per_session() -> None:
    """Building the NBA provider opens an OAuth flow; twice would be twice."""
    built: list[int] = []
    entry = fake_entry(counter=built)
    session = Session()
    session.provider(entry)
    session.provider(entry)
    assert built == [1]


def test_no_sport_argument_runs_every_configured_sport() -> None:
    entries = [fake_entry("nfl"), fake_entry("nba", "NBA (Yahoo)")]
    assert cmd._resolve_competitions([], entries) == entries


def test_a_named_sport_runs_only_that_one() -> None:
    nfl, nba = fake_entry("nfl"), fake_entry("nba", "NBA (Yahoo)")
    resolved = cmd._resolve_competitions(["nfl"], [nfl, nba])
    assert [e.competition for e in resolved] == ["nfl"]


def test_an_unknown_competition_resolves_to_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert cmd._resolve_competitions(["cricket"], [fake_entry()]) == []
    assert "Unknown competition" in capsys.readouterr().out


def test_an_unconfigured_sport_names_what_to_set(capsys: pytest.CaptureFixture[str]) -> None:
    """Asking for a sport you have no credentials for must explain, not crash."""
    assert cmd._resolve_competitions(["nba"], [fake_entry("nfl")]) == []
    out = capsys.readouterr().out
    assert "not configured" in out
    assert "YAHOO_CLIENT_ID" in out


def test_roster_renders_rows_for_the_selected_sport(capsys: pytest.CaptureFixture[str]) -> None:
    cmd._cmd_roster(Session(), [fake_entry()], [])
    out = capsys.readouterr().out
    assert "My League" in out
    assert "Star QB" in out


def test_leagues_lists_every_configured_sport(capsys: pytest.CaptureFixture[str]) -> None:
    cmd._cmd_leagues(Session(), [fake_entry()])
    out = capsys.readouterr().out
    assert "My League" in out
    assert "12-team" in out


def test_a_platform_failure_is_reported_not_raised(capsys: pytest.CaptureFixture[str]) -> None:
    from thefrontoffice.domain.errors import LeagueNotFoundError

    def _boom() -> Any:
        raise LeagueNotFoundError("SLEEPER_USERNAME is not set in .env")

    cmd._cmd_roster(Session(), [fake_entry(build=_boom)], [])
    assert "SLEEPER_USERNAME" in capsys.readouterr().out


def test_quit_raises_the_sentinel() -> None:
    with pytest.raises(cli.QuitRequested):
        cli._dispatch(Session(), [], "/quit", [])


def test_unknown_command_is_reported(capsys: pytest.CaptureFixture[str]) -> None:
    cli._dispatch(Session(), [], "/nonsense", [])
    assert "Unknown command" in capsys.readouterr().out


def test_help_names_the_configured_competitions(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("thefrontoffice.bootstrap.ai_available", lambda: True)
    cmd._print_help([fake_entry("nfl"), fake_entry("nba", "NBA (Yahoo)")])
    assert "nfl | nba" in capsys.readouterr().out


def test_rows_are_printed_with_aligned_columns(capsys: pytest.CaptureFixture[str]) -> None:
    output._print_rows([{"Player": "A", "Pos": "QB"}, {"Player": "Longer Name", "Pos": "RB"}])
    lines = [ln for ln in capsys.readouterr().out.splitlines() if ln.strip()]
    assert len({len(ln.rstrip()) for ln in lines}) <= 2  # header, rule and rows align


def test_an_empty_roster_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    output._print_rows([])
    assert "no players found" in capsys.readouterr().out


def test_trade_reports_when_no_sport_supports_it(capsys: pytest.CaptureFixture[str]) -> None:
    """Football is configured but has no trade path yet."""
    cmd._cmd_trade(Session(), [fake_entry("nfl")], ["Give A, Get B"])
    assert "supports trade evaluation" in capsys.readouterr().out


def test_trade_usage_is_shown_without_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    cmd._cmd_trade(Session(), [_tradeable("nfl")], [])
    assert "Usage: /trade" in capsys.readouterr().out


def test_help_omits_a_command_with_nothing_to_run_it_on(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`fake_entry` declares no trade support, so listing /trade could only
    refuse — and a shorter list beats a command that explains itself away."""
    monkeypatch.setattr("thefrontoffice.bootstrap.ai_available", lambda: True)

    cmd._print_help([fake_entry("nfl")])

    assert "/trade" not in capsys.readouterr().out


def test_help_omits_everything_needing_a_model_without_one(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The same rule the web UI follows: nothing is offered that cannot work,
    and the absence needs no explaining because nothing is missing."""
    monkeypatch.setattr("thefrontoffice.bootstrap.ai_available", lambda: False)

    cmd._print_help([_tradeable("nfl")])
    out = capsys.readouterr().out

    assert "/scout" not in out
    assert "/trade" not in out
    assert "/roster" in out


# ── command bodies ──────────────────────────────────────────────────────


class RecordingProvider(FakeProvider):
    """A provider whose context and engine calls can be observed."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def build_context(self, league_id: str) -> Any:
        from thefrontoffice.domain.models import CompetitionContext

        if self.error:
            raise self.error
        return CompetitionContext(prompt="PROMPT")

    def build_trade_context(self, league_id: str, proposal: Any) -> Any:
        from thefrontoffice.domain.models import CompetitionContext

        if self.error:
            raise self.error
        return CompetitionContext(prompt="TRADE PROMPT")


def _entry_with(provider: Any, competition: str = "nfl", trades: bool = False) -> Any:
    from thefrontoffice.bootstrap import CompetitionEntry

    return CompetitionEntry(
        sport=SPORT_OF.get(competition, "football"),
        competition=competition,
        platform=competition,
        label="NFL (Sleeper)",
        build=lambda: provider,
        is_configured=lambda: True,
        requires="SLEEPER_USERNAME",
        supports_trades=trades,
    )


class WeekProvider(FakeProvider):
    """A provider with a week to show: one to-do item, and one the manager dismissed."""

    def summary(self, league_id: str) -> Any:
        from thefrontoffice.domain.models import Action, Stat, Summary

        return Summary(
            headline=[Stat(label="Lineup", value="123.5")],
            actions=[
                Action(kind="lineup", urgency="soon", title="Start A over B", reason="A projects more.", key="a"),
                Action(kind="trade", urgency="later", title="Gone", reason="", key="b", hidden="dismissed"),
            ],
        )

    def schedule(self, league_id: str) -> Any:
        from thefrontoffice.domain.models import LeagueSchedule

        return LeagueSchedule()

    def free_agents(self, league_id: str, query: Any) -> Any:
        from thefrontoffice.domain.models import PlayerPage

        return PlayerPage()


def test_week_shows_the_figures_and_what_to_do_but_not_what_was_dismissed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from conftest import FakeItemStates

    from thefrontoffice.application.items import ItemDecisions

    monkeypatch.setattr(cmd, "item_decisions", lambda: ItemDecisions(FakeItemStates()))
    cmd._cmd_week(Session(), [_entry_with(WeekProvider())], [])

    out = capsys.readouterr().out
    assert "123.5" in out and "Start A over B" in out
    assert "Gone" not in out


def test_week_is_a_command(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []
    monkeypatch.setattr(cli, "_cmd_week", lambda session, entries, args: seen.append("week"))

    cli._dispatch(Session(), [], "/week", [])

    assert seen == ["week"]


def test_scout_renders_a_report(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from conftest import FakeAI

    monkeypatch.setattr(cmd, "scout_engine", lambda provider: _scout_with(provider, FakeAI()))
    cmd._cmd_scout(Session(), [_entry_with(RecordingProvider())], [])
    out = capsys.readouterr().out
    assert "My League" in out
    assert "SITUATION" in out  # the rendered report


def _scout_with(provider: Any, ai: Any) -> Any:
    from conftest import FakeAnswers

    from thefrontoffice.application.scouting import ScoutEngine

    return ScoutEngine(provider, ai=ai, answers=FakeAnswers())


def test_scout_reports_a_platform_failure(capsys: pytest.CaptureFixture[str]) -> None:
    from thefrontoffice.domain.errors import TeamNotFoundError

    entry = _entry_with(RecordingProvider(error=TeamNotFoundError("Some League")))
    cmd._cmd_scout(Session(), [entry], [])
    assert "Some League" in capsys.readouterr().out


def test_scout_warns_when_a_sport_has_no_leagues(capsys: pytest.CaptureFixture[str]) -> None:
    class NoLeagues(RecordingProvider):
        def list_leagues(self) -> Any:
            return []

    cmd._cmd_scout(Session(), [_entry_with(NoLeagues())], [])
    assert "No NFL (Sleeper) leagues" in capsys.readouterr().out


def test_trade_renders_a_verdict(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from conftest import FakeAI

    from thefrontoffice.application.trading import TradeEngine

    provider = RecordingProvider()
    monkeypatch.setattr(cmd, "trade_engine", lambda p: TradeEngine(p, ai=FakeAI()))
    cmd._cmd_trade(Session(), [_entry_with(provider, trades=True)], ["Give", "A,", "Get", "B"])
    out = capsys.readouterr().out
    assert "VERDICT" in out


def test_trade_reports_a_domain_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from conftest import FakeAI

    from thefrontoffice.application.trading import TradeEngine
    from thefrontoffice.domain.errors import PlayerNotFoundError

    provider = RecordingProvider(error=PlayerNotFoundError(["Ghost"]))
    monkeypatch.setattr(cmd, "trade_engine", lambda p: TradeEngine(p, ai=FakeAI()))
    cmd._cmd_trade(Session(), [_entry_with(provider, trades=True)], ["x"])
    assert "Ghost" in capsys.readouterr().out


# ── trade sport selection ───────────────────────────────────────────────


def _tradeable(competition: str) -> Any:
    from thefrontoffice.bootstrap import CompetitionEntry

    def _build() -> Any:
        return FakeProvider()

    return CompetitionEntry(
        sport=SPORT_OF.get(competition, "football"),
        competition=competition,
        platform=competition,
        label=f"{competition.upper()} label",
        build=_build,
        is_configured=lambda: True,
        requires="X",
        supports_trades=True,
    )


def test_a_lone_trading_sport_needs_no_argument() -> None:
    """Nothing to disambiguate, so the whole line is the trade description."""
    entry, args = cmd._trade_competition([_tradeable("nfl")], ["Give", "A,", "Get", "B"])
    assert entry is not None
    assert entry.competition == "nfl"
    assert args == ["Give", "A,", "Get", "B"]


def test_a_named_sport_is_split_off_the_description() -> None:
    entries = [_tradeable("nba"), _tradeable("nfl")]
    entry, args = cmd._trade_competition(entries, ["nfl", "Give", "A,", "Get", "B"])
    assert entry is not None
    assert entry.competition == "nfl"
    assert args == ["Give", "A,", "Get", "B"]


def test_several_sports_without_one_named_refuses_to_guess(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A trade names players on one platform; running it against both is meaningless."""
    entries = [_tradeable("nba"), _tradeable("nfl")]
    entry, _ = cmd._trade_competition(entries, ["Give", "A,", "Get", "B"])
    assert entry is None
    out = capsys.readouterr().out
    assert "Name one" in out
    assert "nba | nfl" in out


def test_a_leading_word_that_is_not_a_sport_stays_in_the_description() -> None:
    entry, args = cmd._trade_competition([_tradeable("nfl")], ["Give", "nfl-ish", "player"])
    assert entry is not None
    assert args == ["Give", "nfl-ish", "player"]


def test_an_unconfigured_trading_sport_says_what_to_set(capsys: pytest.CaptureFixture[str]) -> None:
    """`nba` trades, but is absent from the trade-capable list here."""
    entry, args = cmd._trade_competition([_tradeable("nfl")], ["nba", "Give", "A"])

    assert entry is None
    assert "is not configured" in capsys.readouterr().out
    assert args == ["nba", "Give", "A"]  # left in the text rather than silently dropped


def test_usage_is_shown_when_only_a_sport_is_given(capsys: pytest.CaptureFixture[str]) -> None:
    cmd._cmd_trade(Session(), [_tradeable("nfl")], ["nfl"])
    assert "Usage: /trade" in capsys.readouterr().out


def test_a_sport_that_cannot_trade_at_all_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    """FPL managers transfer against the market, so there is no trade to price."""
    entry, args = cmd._trade_competition([_tradeable("nfl")], ["premier-league", "Give", "Saka"])

    assert entry is None
    assert "does not support trade evaluation" in capsys.readouterr().out
    assert args == ["premier-league", "Give", "Saka"]


def test_a_competition_marked_tradeable_whose_provider_cannot_trade_says_so(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A registry slip is reported, not an AttributeError halfway through an evaluation."""
    cmd._cmd_trade(Session(), [_entry_with(FakeProvider(), trades=True)], ["Give A, Get B"])

    out = capsys.readouterr().out
    assert "NFL (Sleeper)" in out  # names which competition
    assert "Parsing" not in out  # and never starts the evaluation
