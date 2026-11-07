"""Tests for the slash commands, each run over a session of fake competitions."""

from typing import Any

import pytest
from support.ai import FakeAI
from support.wiring import LEAGUE, FakeCompetition, entry, wiring

from thefrontoffice.adapters.inbound.cli import commands
from thefrontoffice.adapters.inbound.cli.session import Session
from thefrontoffice.bootstrap import CompetitionEntry
from thefrontoffice.domain.errors import LeagueNotFoundError, PlayerNotFoundError, TeamNotFoundError
from thefrontoffice.domain.models import Action, CompetitionContext, PlayerCard, Stat, Summary
from thefrontoffice.domain.ports import LeagueRef


class _Roster(FakeCompetition):
    def roster(self, league_id: str) -> list[PlayerCard]:
        return [PlayerCard(player_id="qb1", columns={"Player": "Star QB", "Pos": "QB"})]


class _Trades(FakeCompetition):
    """A competition that can price a trade, or fails to with `error`."""

    def __init__(self, error: Exception | None = None) -> None:
        self.error = error

    def build_context(self, league_id: str) -> CompetitionContext:
        if self.error:
            raise self.error
        return CompetitionContext(prompt="PROMPT")

    def build_trade_context(self, league_id: str, proposal: Any) -> CompetitionContext:
        if self.error:
            raise self.error
        return CompetitionContext(prompt="TRADE PROMPT")


def _nfl(provider: FakeCompetition | None = None, **kw: Any) -> CompetitionEntry:
    return entry(provider or FakeCompetition(), **kw)


def _nba(provider: FakeCompetition | None = None, **kw: Any) -> CompetitionEntry:
    return entry(
        provider or FakeCompetition(),
        competition="nba",
        platform="yahoo",
        label="NBA (Yahoo)",
        sport="basketball",
        requires="YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET",
        **kw,
    )


def _fpl(**kw: Any) -> CompetitionEntry:
    return entry(
        FakeCompetition(),
        competition="premier-league",
        platform="fpl",
        label="FPL (Fantasy Premier League)",
        sport="soccer",
        requires="FPL_ENTRY_ID",
        **kw,
    )


def _session(*entries: CompetitionEntry, ai: FakeAI | None = None) -> Session:
    return Session(wiring(*entries, ai=ai or FakeAI()))


# ── which competitions a command runs for ───────────────────────────────


def test_no_argument_runs_every_configured_competition() -> None:
    session = _session(_nfl(), _nba())

    assert commands.resolve(session, []) == session.entries


def test_a_named_competition_runs_only_that_one() -> None:
    assert [e.key for e in commands.resolve(_session(_nfl(), _nba()), ["nfl"])] == ["nfl-sleeper"]


def test_a_competition_is_named_by_its_key_too() -> None:
    assert [e.key for e in commands.resolve(_session(_nfl(), _nba()), ["nba-yahoo"])] == ["nba-yahoo"]


def test_an_unknown_competition_resolves_to_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    assert commands.resolve(_session(_nfl()), ["cricket"]) == []
    assert "cricket" in capsys.readouterr().out  # names what was not recognised


def test_an_unconfigured_competition_names_what_to_set(capsys: pytest.CaptureFixture[str]) -> None:
    """Asking for one you have no credentials for must explain, not crash."""
    assert commands.resolve(_session(_nfl(), _nba(configured=False)), ["nba"]) == []
    assert "YAHOO_CLIENT_ID" in capsys.readouterr().out


# ── help ────────────────────────────────────────────────────────────────


def test_help_names_the_configured_competitions(capsys: pytest.CaptureFixture[str]) -> None:
    commands.print_help(_session(_nfl(), _nba()))

    assert "nfl-sleeper | nba-yahoo" in capsys.readouterr().out


def test_help_omits_a_command_with_nothing_to_run_it_on(capsys: pytest.CaptureFixture[str]) -> None:
    """No competition here trades, so listing /trade could only refuse."""
    commands.print_help(_session(_nfl()))

    assert "/trade" not in capsys.readouterr().out


def test_help_omits_everything_needing_a_model_without_one(capsys: pytest.CaptureFixture[str]) -> None:
    """The rule the web UI follows: nothing is offered that cannot work."""
    commands.print_help(_session(_nfl(_Trades()), ai=FakeAI(available=False)))
    out = capsys.readouterr().out

    assert "/scout" not in out
    assert "/trade" not in out
    assert "/roster" in out


# ── leagues, rosters and the week ───────────────────────────────────────


def test_roster_renders_rows_for_the_selected_competition(capsys: pytest.CaptureFixture[str]) -> None:
    commands.roster(_session(_nfl(_Roster())), [])
    out = capsys.readouterr().out

    assert LEAGUE.name in out
    assert "Star QB" in out


def test_leagues_lists_every_configured_competition(capsys: pytest.CaptureFixture[str]) -> None:
    commands.leagues(_session(_nfl()))
    out = capsys.readouterr().out

    assert LEAGUE.name in out
    assert LEAGUE.detail in out


class _Unreachable(FakeCompetition):
    def list_leagues(self) -> list[LeagueRef]:
        raise LeagueNotFoundError("the platform has no record of you")


def test_a_platform_failure_is_reported_not_raised(capsys: pytest.CaptureFixture[str]) -> None:
    commands.roster(_session(_nfl(_Unreachable())), [])

    assert "no record of you" in capsys.readouterr().out


class _Week(FakeCompetition):
    """A week with one to-do item, and one the manager dismissed."""

    def summary(self, league_id: str) -> Summary:
        return Summary(
            headline=[Stat(label="Lineup", value="123.5")],
            actions=[
                Action(kind="lineup", urgency="soon", title="Start A over B", reason="A projects more.", key="a"),
                Action(kind="trade", urgency="later", title="Gone", reason="", key="b", hidden="dismissed"),
            ],
        )


def test_week_shows_the_figures_and_what_to_do_but_not_what_was_dismissed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    commands.week(_session(_nfl(_Week())), [])

    out = capsys.readouterr().out
    assert "123.5" in out and "Start A over B" in out
    assert "Gone" not in out


# ── scouting ────────────────────────────────────────────────────────────


def test_scout_renders_a_report(capsys: pytest.CaptureFixture[str]) -> None:
    commands.scout(_session(_nfl(_Trades())), [])
    out = capsys.readouterr().out

    assert LEAGUE.name in out
    assert "SITUATION" in out  # the rendered report


def test_scout_reports_a_platform_failure(capsys: pytest.CaptureFixture[str]) -> None:
    commands.scout(_session(_nfl(_Trades(error=TeamNotFoundError("Some League")))), [])

    assert "Some League" in capsys.readouterr().out


class _NoLeagues(FakeCompetition):
    leagues = ()


def test_scout_warns_when_a_competition_has_no_leagues(capsys: pytest.CaptureFixture[str]) -> None:
    commands.scout(_session(_nfl(_NoLeagues())), [])

    assert "No NFL (Sleeper) leagues" in capsys.readouterr().out


# ── trades ──────────────────────────────────────────────────────────────


def test_trade_renders_a_verdict(capsys: pytest.CaptureFixture[str]) -> None:
    commands.trade(_session(_nfl(_Trades())), ["Give", "A,", "Get", "B"])

    assert "VERDICT" in capsys.readouterr().out


def test_trade_reports_a_domain_error(capsys: pytest.CaptureFixture[str]) -> None:
    commands.trade(_session(_nfl(_Trades(error=PlayerNotFoundError(["Ghost"])))), ["x"])

    assert "Ghost" in capsys.readouterr().out


def test_trade_reports_when_no_competition_supports_it(capsys: pytest.CaptureFixture[str]) -> None:
    built: list[int] = []

    commands.trade(_session(_nfl(built=built)), ["Give A, Get B"])

    assert built == []  # nothing was run
    assert "No configured competition supports trade evaluation" in capsys.readouterr().out


def test_trade_usage_is_shown_without_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    commands.trade(_session(_nfl(_Trades())), [])

    assert "Usage: /trade" in capsys.readouterr().out


def test_usage_is_shown_when_only_a_competition_is_given(capsys: pytest.CaptureFixture[str]) -> None:
    commands.trade(_session(_nfl(_Trades())), ["nfl"])

    assert "Usage: /trade" in capsys.readouterr().out


def test_a_lone_trading_competition_needs_no_argument() -> None:
    """Nothing to disambiguate, so the whole line is the trade description."""
    chosen, args = commands.trade_competition(_session(_nfl(_Trades())), ["Give", "A,", "Get", "B"])

    assert chosen is not None and chosen.key == "nfl-sleeper"
    assert args == ["Give", "A,", "Get", "B"]


def test_a_named_competition_is_split_off_the_description() -> None:
    chosen, args = commands.trade_competition(
        _session(_nba(_Trades()), _nfl(_Trades())), ["nfl", "Give", "A,", "Get", "B"]
    )

    assert chosen is not None and chosen.key == "nfl-sleeper"
    assert args == ["Give", "A,", "Get", "B"]


def test_several_competitions_without_one_named_refuses_to_guess(capsys: pytest.CaptureFixture[str]) -> None:
    """A trade names players on one platform; running it against both is meaningless."""
    chosen, _ = commands.trade_competition(_session(_nba(_Trades()), _nfl(_Trades())), ["Give", "A,", "Get", "B"])

    assert chosen is None
    assert "nba-yahoo | nfl-sleeper" in capsys.readouterr().out  # offers the choices


def test_a_leading_word_that_is_not_a_competition_stays_in_the_description() -> None:
    chosen, args = commands.trade_competition(_session(_nfl(_Trades())), ["Give", "nfl-ish", "player"])

    assert chosen is not None
    assert args == ["Give", "nfl-ish", "player"]


def test_an_unconfigured_trading_competition_says_what_to_set(capsys: pytest.CaptureFixture[str]) -> None:
    session = _session(_nfl(_Trades()), _nba(_Trades(), configured=False))

    chosen, args = commands.trade_competition(session, ["nba", "Give", "A"])

    assert chosen is None
    assert "YAHOO_CLIENT_ID" in capsys.readouterr().out
    assert args == ["nba", "Give", "A"]  # left in the text rather than silently dropped


def test_a_competition_that_cannot_trade_at_all_says_so(capsys: pytest.CaptureFixture[str]) -> None:
    """FPL managers transfer against the market, so there is no trade to price."""
    chosen, args = commands.trade_competition(_session(_nfl(_Trades()), _fpl()), ["premier-league", "Give", "Saka"])

    assert chosen is None
    assert "FPL (Fantasy Premier League) does not support trade evaluation" in capsys.readouterr().out
    assert args == ["premier-league", "Give", "Saka"]


def test_a_provider_that_cannot_trade_is_refused_by_name_before_any_evaluation(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The class says it trades and the build returns something that does not: said plainly, not an AttributeError."""
    ai = FakeAI()
    slip = CompetitionEntry(
        sport="football",
        competition="nfl",
        platform="sleeper",
        label="NFL (Sleeper)",
        provider=lambda: _Trades,
        build=FakeCompetition,
        is_configured=lambda: True,
        requires="SLEEPER_USERNAME",
    )

    commands.trade(_session(slip, ai=ai), ["Give A, Get B"])

    assert "NFL (Sleeper) does not support trade evaluation" in capsys.readouterr().out
    assert ai.structured == []
