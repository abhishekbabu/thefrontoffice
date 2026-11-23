"""Tests for the Yahoo basketball provider: `nba/yahoo/provider.py`.

Mostly the context it builds, which is where league rules (add budget, IL
slots, matchup context) actually get encoded.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from support.ai import FakeAI
from support.espn import FakeESPN
from support.nba import (
    DEFAULT_TEAMS,
    FakeForecast,
    FakeNBA,
    FakeSleeperNBA,
    FakeSleeperProjections,
    FakeYahoo,
    FakeYahooAuth,
    box_scores,
    game_log,
    make_player,
    nba_provider,
    toronto,
    yahoo_league,
)
from support.nba import yahoo_team as _yahoo_team
from support.reports import MOCK_NBA_REPORT
from support.stores import FakeAnswers

from thefrontoffice.adapters.outbound.competitions.nba import week as nba_week
from thefrontoffice.adapters.outbound.competitions.nba.actions import PROVISIONAL
from thefrontoffice.adapters.outbound.competitions.nba.form import PlayerStats, RecentForm, Role, nine_cat
from thefrontoffice.adapters.outbound.competitions.nba.prompt import NO_MATCHUP
from thefrontoffice.adapters.outbound.competitions.nba.rules import BLOCKS, CATEGORIES, PACIFIC
from thefrontoffice.adapters.outbound.competitions.nba.week import SleeperNBASchedule
from thefrontoffice.adapters.outbound.competitions.nba.yahoo import YahooNBAProvider
from thefrontoffice.adapters.outbound.platforms.espn.errors import ESPNAPIError
from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport, ScoreboardGame
from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog, NBASeason, ScheduledGame
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooAPIError, YahooCaptureMissingError
from thefrontoffice.adapters.outbound.platforms.yahoo.types import (
    Average,
    MatchupSide,
    MovedPlayer,
    Pairing,
    Timeframe,
    YahooLeague,
    YahooLine,
    YahooTeam,
    YahooTransaction,
)
from thefrontoffice.application.scouting import ScoutEngine
from thefrontoffice.domain.errors import (
    InvalidRequestError,
    LeagueNotFoundError,
    NotFoundError,
    PlayerNotFoundError,
    TeamNotFoundError,
    UnsupportedError,
)
from thefrontoffice.domain.models import Action, PlayerQuery, ScoutReport, Spot, Stat, TradeProposal, WeekAhead
from thefrontoffice.domain.ports import ForecastProvider, OutlookProvider, WireProvider


def _scout(yahoo: FakeYahoo, ai: FakeAI | None = None, nba: FakeNBA | None = None) -> ScoutEngine:
    provider = nba_provider(yahoo, nba=nba)
    return ScoutEngine(provider, key="nba-yahoo", ai=ai or FakeAI(), answers=FakeAnswers())


def test_follow_up_chat_is_seeded_with_the_report() -> None:
    """Follow-ups must see the analysis without re-sending the whole context."""
    ai = FakeAI()
    _scout(FakeYahoo(), ai=ai).start_analysis("")
    roles = [item["role"] for item in ai.history]
    assert roles == ["user", "model"]
    # The model turn is the report itself, as JSON the follow-up can reason over.
    seeded = ScoutReport.model_validate_json(ai.history[1]["parts"][0])
    assert seeded.model_dump(exclude={"headline"}) == MOCK_NBA_REPORT.model_dump(exclude={"headline"})


def test_follow_up_is_seeded_with_a_briefing_not_the_whole_prompt() -> None:
    """The history is resent on every follow-up, so the prompt's free-agent
    block — over half its volume — must not ride along."""
    ai = FakeAI()
    _scout(_rich_yahoo(), ai=ai).start_analysis("")
    briefing, prompt = ai.history[0]["parts"][0], ai.prompts[0]

    assert len(briefing) < len(prompt) / 2


def test_matchup_is_fetched_once_not_twice() -> None:
    """The context and the dates come from one scoreboard fetch."""
    yahoo = _rich_yahoo()
    _scout(yahoo).start_analysis("")
    assert yahoo.matchup_fetches == 1


def test_missing_team_raises_before_any_ai_call() -> None:
    """A billed Gemini call for a league we do not play in is pure waste."""

    class NoTeam(FakeYahoo):
        def get_user_team(self) -> YahooTeam:
            raise TeamNotFoundError("Some League")

    ai = FakeAI()
    with pytest.raises(TeamNotFoundError):
        _scout(NoTeam(), ai=ai).start_analysis("")
    assert ai.prompts == []


# ── prompt content ──────────────────────────────────────────────────────


def _rich_yahoo(recommended: str = "Mock Player One") -> FakeYahoo:
    """A league with a full roster and several free agents, one of which the
    canned report recommends."""
    roster = [make_player(f"Roster Player {i}", key=f"r{i}") for i in range(10)]
    fas = [make_player(f"Free Agent {i}", key=f"fa{i}") for i in range(8)]
    fas.append(make_player(recommended, key="rec"))
    return FakeYahoo(roster=roster, stat_leaders={"BLK": fas, "REB": fas[:3]})


def _prompt_for(yahoo: FakeYahoo, nba: FakeNBA | None = None) -> str:
    return nba_provider(yahoo, nba=nba).build_context().prompt


def test_prompt_carries_roster_matchup_and_free_agents() -> None:
    yahoo = FakeYahoo(
        roster=[make_player("Roster One", team="LAL")],
        stat_leaders={"BLK": [make_player("Free Agent One", team="BOS", key="fa-1")]},
    )
    prompt = _prompt_for(yahoo)
    assert "Roster One" in prompt
    assert "Free Agent One" in prompt
    assert "BLK: 12 vs 17" in prompt  # FakeYahoo's matchup score


def test_a_free_agents_line_carries_his_figures_without_a_teammate_out() -> None:
    """The model weighs a pickup on what he did while the star sat, not on a guess that he inherits the role."""
    poeltl = make_player("Jakob Poeltl", "C", "TOR", key="poeltl")
    yahoo = FakeYahoo(roster=[make_player("Roster One")], stat_leaders={"REB": [poeltl]})

    context = nba_provider(yahoo, nba=FakeNBA(scores=toronto())).build_context()

    assert "Scottie Barnes" in context.candidate_lines["Jakob Poeltl"]
    assert "Scottie Barnes" not in context.roster_lines["Roster One"]


def test_free_agents_are_annotated_with_the_categories_they_lead() -> None:
    fa = make_player("Multi Cat", key="fa-1")
    yahoo = FakeYahoo(stat_leaders={"BLK": [fa], "REB": [fa]})
    prompt = _prompt_for(yahoo)
    assert "Top in: REB, BLK" in prompt  # in the league's own order


def test_free_agents_appearing_in_several_categories_are_listed_once_and_first() -> None:
    """Most versatile first: a two-category player outranks a one-category one."""
    multi = make_player("Multi Cat", key="multi")
    single = make_player("Single Cat", key="single")
    yahoo = FakeYahoo(stat_leaders={"BLK": [multi, single], "REB": [multi]})
    prompt = _prompt_for(yahoo)
    assert prompt.count("Multi Cat") == 1
    assert prompt.index("Multi Cat") < prompt.index("Single Cat")


def test_an_untouched_add_budget_is_all_left() -> None:
    ctx = nba_provider(FakeYahoo(adds_used=0)).build_context()
    assert ctx.headline == [Stat(label="Adds left", value="3 of 3", tone="good")]


def test_add_budget_cannot_go_negative() -> None:
    """Yahoo can report more adds used than the configured weekly limit."""
    ctx = nba_provider(FakeYahoo(adds_used=99)).build_context()
    assert ctx.headline == [Stat(label="Adds left", value="0 of 3", tone="warning")]
    assert "99/3" in ctx.constraints  # what Yahoo reported, still stated
    assert "-96" not in ctx.constraints


def test_schedule_context_lists_teams_by_games_remaining() -> None:
    yahoo = FakeYahoo(
        roster=[make_player("Roster One", team="LAL")],
        stat_leaders={"BLK": [make_player("FA", team="BOS", key="fa")]},
    )
    nba = FakeNBA(games={"LAL": 2, "BOS": 4})
    prompt = _prompt_for(yahoo, nba=nba)
    assert "BOS: 4 games left" in prompt
    assert "LAL: 2 games left" in prompt
    assert prompt.index("BOS: 4") < prompt.index("LAL: 2")  # descending


def test_a_schedule_that_will_not_load_leaves_games_remaining_unknown_rather_than_nought() -> None:
    """Nought games left for every club reads as a week nobody plays, and steers every add."""
    yahoo = FakeYahoo(roster=[make_player("Roster One", team="LAL")])
    games = SleeperNBASchedule(client=FakeSleeperNBA(error=SleeperAPIError("down")), season="2026")

    ctx = nba_provider(yahoo, games=games).build_context()

    assert "G left]" not in ctx.roster_lines["Roster One"]
    assert "LAL:" not in ctx.extra


def test_missing_matchup_dates_leave_games_remaining_uncounted() -> None:
    yahoo = FakeYahoo(roster=[make_player("Roster One", team="LAL")], matchup_dates=None)
    ctx = nba_provider(yahoo, nba=FakeNBA(games={"LAL": 2})).build_context()
    assert "G left]" not in ctx.roster_lines["Roster One"]
    assert "LAL: 2" not in ctx.extra
    assert ctx.situation == NO_MATCHUP


def test_il_players_are_flagged_so_they_are_not_dropped_carelessly() -> None:
    yahoo = FakeYahoo(roster=[make_player("Hurt Star", selected_position="IL", status="O")])
    prompt = _prompt_for(yahoo)
    assert "[IN IL SPOT]" in prompt
    assert "[O]" in prompt


# ── multi-league selection ──────────────────────────────────────────────


def _two_league_provider(auth: FakeYahooAuth | None = None) -> YahooNBAProvider:
    """A login in two leagues, each with its own table, roster and budget, so which was read shows."""
    clients = {
        "1": FakeYahoo(
            teams=[_yahoo_team("League One Side", "t.1", rank=1, wins=1, losses=0, mine=True)],
            roster=[make_player("League One Player", key="p1")],
            adds_used=0,
        ),
        "2": FakeYahoo(
            teams=[_yahoo_team("League Two Side", "t.1", rank=1, wins=1, losses=0, mine=True)],
            roster=[make_player("League Two Player", key="p2")],
            adds_used=3,
        ),
    }
    return YahooNBAProvider(
        auth=auth or FakeYahooAuth([yahoo_league("1", "One"), yahoo_league("2", "Two")]),
        yahoo_for=lambda league: clients[league.league_key],
        form=FakeNBA(),
        games=FakeNBA(),
        sleeper=FakeSleeperProjections(),
        espn=FakeESPN(),
        fallback_weekly_adds=3,
        forecast=FakeForecast(),
    )


def test_every_league_of_the_login_is_listed() -> None:
    leagues = _two_league_provider().list_leagues()

    assert [(r.league_id, r.name, r.detail) for r in leagues] == [("1", "One", "head"), ("2", "Two", "head")]


def test_this_seasons_nba_leagues_are_looked_up_once_per_provider() -> None:
    auth = FakeYahooAuth([yahoo_league("1", "One")])
    provider = _two_league_provider(auth)

    provider.list_leagues()
    provider.teams("1")

    assert auth.searches == [("nba", YahooNBAProvider.season_year())]


def test_playing_in_no_nba_league_is_a_clear_error() -> None:
    provider = _two_league_provider(FakeYahooAuth([]))

    with pytest.raises(LeagueNotFoundError):
        provider.list_leagues()


def test_a_specific_league_can_be_selected() -> None:
    """A Yahoo login with several leagues must be able to scout each one."""
    assert [t.name for t in _two_league_provider().teams("2")] == ["League Two Side"]


def test_a_refresh_drops_the_league_it_names_and_no_other() -> None:
    one, two = FakeYahoo(), FakeYahoo()
    provider = YahooNBAProvider(
        auth=FakeYahooAuth([yahoo_league("1", "One"), yahoo_league("2", "Two")]),
        yahoo_for=lambda league: {"1": one, "2": two}[league.league_key],
        form=FakeNBA(),
        games=FakeNBA(),
        sleeper=FakeSleeperProjections(),
        espn=FakeESPN(),
        forecast=FakeForecast(),
        fallback_weekly_adds=3,
    )

    dropped = provider.refresh("2")

    assert (one.forgotten, two.forgotten) == (0, 1)
    assert dropped == 3


def test_no_league_id_reads_the_current_league() -> None:
    assert [t.name for t in _two_league_provider().teams("")] == ["League One Side"]


def test_every_view_reads_the_league_it_names_whatever_was_asked_before() -> None:
    """The provider once moved itself to whichever league the last call named,
    so the summary, roster and player views answered from that league instead."""
    provider = _two_league_provider()
    provider.teams("1")

    assert [c.columns["Player"] for c in provider.roster("2")] == ["League Two Player"]
    assert provider.summary("2").headline[0].value == "0 of 3"
    assert provider.player("2", "p2").name == "League Two Player"

    provider.teams("2")
    assert [c.columns["Player"] for c in provider.roster("1")] == ["League One Player"]
    assert provider.summary("1").headline[0].value == "3 of 3"


def test_selecting_an_unknown_league_raises() -> None:
    with pytest.raises(LeagueNotFoundError):
        nba_provider().schedule("999")


def _form(played: int = 15, **stats: float) -> PlayerStats:
    """`played` identical games, run through the real nine-category line."""
    games = [NBAGameLog(player_id="p", date=f"2026-01-{i + 1:02d}", opponent="BOS", stats=stats) for i in range(played)]
    return PlayerStats(recent=RecentForm(games=played, line=nine_cat(games)))


# ── projections ─────────────────────────────────────────────────────────


def _game(name: str, day: str, **stats: float) -> Any:
    from thefrontoffice.adapters.outbound.platforms.sleeper.types import GameProjection

    base = {
        "pts": 25.0,
        "reb": 10.0,
        "ast": 5.0,
        "stl": 1.0,
        "blk": 1.0,
        "to": 2.0,
        "tpm": 2.0,
        "fgm": 9.0,
        "fga": 18.0,
        "ftm": 5.0,
        "fta": 6.0,
    }
    base.update(stats)
    return GameProjection(player_id=name, name=name, team="LAL", opponent="BOS", date=day, stats=base)


def _provider_with(sleeper: Any, yahoo: FakeYahoo | None = None) -> Any:
    return nba_provider(yahoo or _rich_yahoo(), sleeper=sleeper)


def test_projected_totals_are_attached_to_players() -> None:
    """Projected totals for the matchup period, beside recent form."""
    sleeper = FakeSleeperProjections([_game("Roster Player 0", "2026-02-10")])
    ctx = _provider_with(sleeper).build_context()
    assert "PROJ 1G" in ctx.roster_lines["Roster Player 0"]
    assert "25.0p" in ctx.roster_lines["Roster Player 0"]


def test_only_games_inside_the_matchup_period_are_counted() -> None:
    """FakeYahoo's window is 2026-02-09..15."""
    sleeper = FakeSleeperProjections(
        [
            _game("Roster Player 0", "2026-02-10"),
            _game("Roster Player 0", "2026-02-28"),  # outside
        ]
    )
    ctx = _provider_with(sleeper).build_context()
    assert "PROJ 1G" in ctx.roster_lines["Roster Player 0"]


def test_out_of_season_falls_back_to_recent_form() -> None:
    """Sleeper publishes no NBA projections before opening night."""
    ctx = _provider_with(FakeSleeperProjections([])).build_context()
    assert not any("PROJ" in line for line in ctx.roster_lines.values())


def test_a_projection_failure_does_not_lose_the_report() -> None:
    from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError

    sleeper = FakeSleeperProjections(error=SleeperAPIError("429"))
    ctx = _provider_with(sleeper).build_context()
    assert set(ctx.roster_lines) == {f"Roster Player {i}" for i in range(10)}  # everything else still built
    assert not any("PROJ" in line for line in ctx.roster_lines.values())


def test_the_next_week_is_tried_when_the_current_one_is_empty() -> None:
    """A matchup period can straddle two Sleeper weeks."""
    sleeper_state_week = 12

    class Straddling(FakeSleeperProjections):
        def get_nba_state(self) -> Any:
            from thefrontoffice.adapters.outbound.platforms.sleeper.types import SeasonState

            return SeasonState(week=sleeper_state_week, season="2026", season_type="regular")

    straddling = Straddling([_game("Roster Player 0", "2026-02-10")], week=13)
    ctx = _provider_with(straddling).build_context()
    assert "PROJ 1G" in ctx.roster_lines["Roster Player 0"]


# ── the league table ────────────────────────────────────────────────────


def test_a_record_includes_ties_only_where_there_are_any() -> None:
    standings = nba_provider(FakeYahoo()).schedule("").standings

    assert standings[0].record == "5-1"
    assert standings[1].record == "4-2-1"


def test_the_season_is_headed_by_your_record_and_place() -> None:
    headline = {stat.label: stat.value for stat in nba_provider(FakeYahoo()).schedule("").headline}

    assert headline == {"Record": "4-2-1", "Place": "2nd of 2"}


def test_without_your_row_in_the_table_the_season_has_no_figures_to_head_it() -> None:
    yahoo = FakeYahoo(teams=[_yahoo_team("Theirs", "t.2", rank=1, wins=1, losses=0)])

    assert nba_provider(yahoo).schedule("").headline == []


def test_the_season_runs_every_week_from_the_scoreboards_with_the_bracket_named() -> None:
    league = replace(yahoo_league(), start_week=1, end_week=21)

    season = nba_provider(FakeYahoo(), league=league).schedule(league.league_key).season

    assert [row.label for row in season] == [f"Week {week}" for week in range(1, 22)]
    assert {row.opponent for row in season} == {"Their Team"}
    assert season[0].detail == "5-1"
    assert [row.detail for row in season[18:]] == ["Quarterfinals", "Semifinals", "Final"]
    assert [row.label for row in season if row.is_current] == ["Week 5"]


def test_the_schedule_carries_the_leagues_moves_lately_yours_marked() -> None:
    yahoo = FakeYahoo()
    dropped = MovedPlayer("478.p.1", "Jaxson Hayes", "C", "UTA", kind="drop", source="My Team", destination="waivers")
    yahoo.moves = [YahooTransaction(kind="drop", timestamp=int(datetime.now(UTC).timestamp()), players=(dropped,))]

    [row] = nba_provider(yahoo).schedule("").activity

    assert (row.what, row.who, row.detail, row.is_mine) == ("Drop", "My Team", "-Jaxson Hayes", True)


def _waiting_claim(player_key: str, name: str) -> YahooTransaction:
    added = MovedPlayer(player_key, name, "C", "UTA", kind="add", source="waivers", destination="team")
    return YahooTransaction(kind="waiver", timestamp=0, players=(added,), clears=date(2026, 11, 25))


def test_your_waiting_claims_lead_the_activity_as_pending_rows() -> None:
    yahoo = FakeYahoo()
    dropped = MovedPlayer("478.p.1", "Jaxson Hayes", "C", "UTA", kind="drop", source="Rival", destination="waivers")
    yahoo.moves = [YahooTransaction(kind="drop", timestamp=int(datetime.now(UTC).timestamp()), players=(dropped,))]
    yahoo.waiting = [_waiting_claim("478.p.2", "Brook Lopez")]

    waiting, done = nba_provider(yahoo).schedule("").activity

    assert (waiting.what, waiting.when, waiting.who, waiting.is_mine) == ("Pending claim", "25 Nov", "My Team", True)
    assert "Brook Lopez" in waiting.detail
    assert (done.what, done.is_mine) == ("Drop", False)


def test_waiting_claims_that_will_not_load_leave_the_leagues_moves_standing() -> None:
    yahoo = FakeYahoo()
    yahoo.waiting_error = YahooAPIError("down")

    assert nba_provider(yahoo).schedule("").activity == []


def test_moves_that_will_not_load_leave_the_table_standing() -> None:
    yahoo = FakeYahoo()
    yahoo.moves_error = YahooAPIError("down")

    schedule = nba_provider(yahoo).schedule("")

    assert (schedule.activity, len(schedule.standings)) == ([], 2)


def test_between_seasons_there_is_a_table_and_no_weeks() -> None:
    league = replace(yahoo_league(), current_week=None)

    schedule = nba_provider(FakeYahoo(), league=league).schedule(league.league_key)

    assert (len(schedule.standings), schedule.season) == (2, [])


def test_a_matchup_without_the_table_shows_both_sides_without_records() -> None:
    yahoo = FakeYahoo(roster=[make_player("Mine One", selected_position="PG")])
    yahoo.standings_error = YahooCaptureMissingError("no standings")

    summary = nba_provider(yahoo).summary("")

    assert summary.mine is not None and summary.opponent is not None
    assert (summary.mine.record, summary.opponent.record) == ("", "")
    assert [s.player for s in summary.mine.lineup] == ["Mine One"]


def test_the_teams_list_says_each_teams_record_from_the_table() -> None:
    refs = nba_provider(FakeYahoo()).teams("")

    assert {ref.name: ref.detail for ref in refs} == {"My Team": "4-2-1", "Their Team": "5-1"}


def test_a_sync_without_the_table_asks_for_the_sync_rather_than_showing_none() -> None:
    yahoo = FakeYahoo()
    yahoo.standings_error = YahooCaptureMissingError("no standings")

    with pytest.raises(YahooCaptureMissingError):
        nba_provider(yahoo).schedule("")


def test_the_teams_list_puts_you_first() -> None:
    """Yours sorts last by name here, so only the is-mine rule can put it first."""
    yahoo = FakeYahoo(
        teams=[
            _yahoo_team("Aardvarks", "t.2", rank=1, wins=5, losses=1),
            _yahoo_team("Zebras", "t.1", rank=2, wins=4, losses=2, mine=True),
        ]
    )

    teams = nba_provider(yahoo).teams("")

    assert [(t.name, t.is_mine) for t in teams] == [("Zebras", True), ("Aardvarks", False)]


def test_another_managers_roster_comes_back_in_your_own_columns() -> None:
    yahoo = FakeYahoo()

    mine = nba_provider(yahoo).roster("")
    theirs = nba_provider(yahoo).roster_of("", "t.2")

    assert set(theirs[0].columns) == set(mine[0].columns)


def test_an_unknown_team_is_refused() -> None:
    with pytest.raises(TeamNotFoundError):
        nba_provider(FakeYahoo()).roster_of("", "t.99")


def test_available_players_have_no_lineup_column() -> None:
    """Somebody on the wire is not in a lineup of yours."""
    assert "Slot" not in nba_provider(FakeYahoo()).free_agents("", PlayerQuery()).players[0].columns


def test_a_list_of_available_players_yahoo_does_not_offer_is_refused() -> None:
    with pytest.raises(InvalidRequestError):
        nba_provider(FakeYahoo()).free_agents("", PlayerQuery(view="Trending"))


def test_available_players_carry_the_same_form_columns_as_a_roster() -> None:
    agents = nba_provider(FakeYahoo()).free_agents("", PlayerQuery()).players

    assert {"Player", "Pos", "Team", "PTS", "REB", "AST", "Status"} <= set(agents[0].columns)


def test_the_wire_is_read_300_deep_by_season_and_100_by_the_last_week() -> None:
    yahoo = FakeYahoo(weights=WEIGHTS)  # a points league reads no value, so the wire is read once, deep

    nba_provider(yahoo, league=POINTS_LEAGUE).free_agents("", PlayerQuery())

    assert yahoo.wire_depths == {Timeframe.SEASON: 300, Timeframe.LAST_WEEK: 100}


def test_the_weeks_risers_sit_beside_the_seasons_best_each_once() -> None:
    """Season rank alone buried a player who had just stepped into a role."""
    season = [make_player("Season One"), make_player("Season Two"), make_player("Season Three")]
    risers = [make_player("Riser"), make_player("Season Two")]

    agents = nba_provider(FakeYahoo(available=season, risers=risers)).free_agents("", PlayerQuery()).players

    assert [card.columns["Player"] for card in agents] == ["Season One", "Riser", "Season Two", "Season Three"]


def test_a_riser_is_in_the_points_scouts_pool() -> None:
    form = FakeNBA(stats={"Riser": _form(pts=30)})
    yahoo = FakeYahoo(weights=WEIGHTS, available=[], risers=[make_player("Riser")])

    assert list(_points(yahoo, form).build_context().candidate_lines) == ["Riser"]


def test_a_player_is_found_by_name_rostered_or_not() -> None:
    found = [
        make_player("Cam Johnson", "SF", "DEN", key="466.p.1"),
        make_player("Cameron Payne", "PG", "", key="466.p.2"),
    ]
    yahoo = FakeYahoo(search_results={"cam": found})

    refs = nba_provider(yahoo).search_players("", " cam ", limit=1)

    assert [(r.player_id, r.name, r.detail) for r in refs] == [("466.p.1", "Cam Johnson", "SF · DEN")]


def test_a_player_found_on_waivers_says_when_he_clears_them() -> None:
    waiting = make_player("Brook Lopez", "C", "LAC", key="466.p.3", waiver_date=date(2026, 11, 25))
    yahoo = FakeYahoo(search_results={"lopez": [waiting]})

    [ref] = nba_provider(yahoo).search_players("", "lopez")

    assert "25 Nov" in ref.detail


def test_a_search_of_one_letter_asks_yahoo_nothing() -> None:
    yahoo = FakeYahoo(search_results={"c": [make_player("Cam Johnson")]})

    assert nba_provider(yahoo).search_players("", " c ") == []


def test_a_team_link_is_built_from_the_two_numbers_in_its_key() -> None:
    """A team key is `nba.l.<league>.t.<team>` and the URL wants the numbers."""
    teams = {
        t.name: t.url
        for t in nba_provider(
            FakeYahoo(teams=[_yahoo_team("Theirs", "nba.l.123.t.4", rank=1, wins=1, losses=0)])
        ).teams("")
    }

    assert teams["Theirs"] == "https://basketball.fantasysports.yahoo.com/nba/123/4"


def test_a_league_link_is_built_from_the_number_in_its_key() -> None:
    """The key `428.l.12345` is not a path Yahoo serves; its number is."""
    [league] = _two_league_provider(FakeYahooAuth([yahoo_league("428.l.12345", "One")])).list_leagues()

    assert league.url == "https://basketball.fantasysports.yahoo.com/nba/12345"


def test_a_key_in_an_unexpected_shape_yields_no_link_rather_than_a_broken_one() -> None:
    teams = nba_provider(FakeYahoo(teams=[_yahoo_team("Odd", "something-else", rank=1, wins=1, losses=0)])).teams("")

    assert [(t.name, t.url) for t in teams] == [("Odd", "")]


# ── the injured list ────────────────────────────────────────────────────


def _il_roster(status: str) -> FakeYahoo:
    return FakeYahoo(
        roster=[
            make_player("Starter", selected_position="PF"),
            make_player("Back Again", key="p.9", selected_position="IL", status=status),
        ]
    )


def test_a_player_the_il_slot_no_longer_takes_is_the_first_thing_to_do() -> None:
    actions = nba_provider(_il_roster("")).summary("").actions

    assert actions is not None
    [item] = actions
    assert (item.title, item.urgency, item.player_id, item.key) == (
        "Move Back Again off IL",
        "now",
        "p.9",
        "il:p.9:ACTIVE",
    )
    assert "cleared to play" in item.reason


@pytest.mark.parametrize("status", ["INJ", "O"])
def test_a_player_still_out_on_il_is_nothing_to_do(status: str) -> None:
    """With nothing computed there is no list, rather than an empty one saying there is nothing to do."""
    assert nba_provider(_il_roster(status)).summary("").actions is None


def test_the_il_item_is_judged_and_the_model_told_adds_are_held() -> None:
    context = nba_provider(_il_roster("GTD")).build_context()

    assert [task.key for task in context.tasks] == ["il:p.9:GTD"]
    assert "Back Again is listed GTD" in context.prompt


def test_a_kept_move_can_name_only_your_roster_or_the_players_still_free() -> None:
    """Someone else claiming a free agent since makes a kept add of him no move at all."""
    context = nba_provider(FakeYahoo(stat_leaders={"PTS": [make_player("Waiver One")]})).build_context()

    assert context.movable == frozenset({"Roster One", "Waiver One"})


# ── the week, and paging through the season ─────────────────────────────


def _today(
    slate: list[ScheduledGame], today: date | None = date(2026, 2, 11), espn: FakeESPN | None = None
) -> dict[str, Spot]:
    """Every row of the week being played, by player, on a day of FakeYahoo's 9-15 Feb window."""
    yahoo = FakeYahoo(
        roster=[
            make_player("Plays Home", team="LAL", selected_position="PG"),
            make_player("Plays Away", team="BOS", selected_position="SG"),
            make_player("Sits Today", team="DEN", selected_position="C"),
            make_player("On The Bench", team="BOS", selected_position="BN"),
        ]
    )
    summary = nba_provider(yahoo, nba=FakeNBA(slate=slate, today=today), espn=espn).summary("")
    assert summary.mine is not None
    return {s.player: s for s in (*summary.mine.lineup, *summary.mine.bench)}


def test_each_row_of_the_week_being_played_says_whether_he_plays_today() -> None:
    """A lineup is set day by day: a starter with no game today scores nothing until he is swapped out."""
    rows = _today(
        [
            ScheduledGame(week=0, date="2026-02-11", home="LAL", away="BOS", status="pre_game"),
            ScheduledGame(week=0, date="2026-02-12", home="DEN", away="MIA"),
        ]
    )

    assert rows["Plays Home"].today == "vs BOS today"
    assert rows["Plays Away"].today == "@ LAL today"
    assert rows["On The Bench"].today == "@ LAL today"
    assert rows["Sits Today"].today == "no game today"
    assert [name for name, row in rows.items() if row.idle] == ["Sits Today"]


def test_a_game_under_way_or_over_says_so_rather_than_today() -> None:
    rows = _today(
        [
            ScheduledGame(week=0, date="2026-02-11", home="LAL", away="BOS", status="in_game"),
            ScheduledGame(week=0, date="2026-02-11", home="DEN", away="MIA", status="complete"),
        ]
    )

    assert rows["Plays Home"].today == "vs BOS live"
    assert rows["Sits Today"].today == "vs MIA final"
    assert not any(row.idle for row in rows.values())


@pytest.mark.parametrize(
    "today",
    [
        None,  # the schedule would not load: unknown, which is not a day nobody plays
        date(2026, 2, 20),  # a day outside the week shown
    ],
)
def test_no_row_claims_a_day_off_it_cannot_know(today: date | None) -> None:
    rows = _today([ScheduledGame(week=0, date="2026-02-20", home="LAL", away="BOS")], today)

    assert not any(row.today or row.idle for row in rows.values())


TIP_OFF = datetime(2026, 2, 12, 3, 30, tzinfo=UTC)


def test_a_game_still_to_come_carries_its_tip_off_from_espns_scoreboard() -> None:
    """Sleeper says the day; ESPN says the hour."""
    espn = FakeESPN(
        scoreboard=[
            ScoreboardGame(home="LAL", away="BOS", state="pre", kickoff=TIP_OFF),
            ScoreboardGame(home="DEN", away="MIA", state="in", kickoff=TIP_OFF),
        ]
    )
    rows = _today(
        [
            ScheduledGame(week=0, date="2026-02-11", home="LAL", away="BOS", status="pre_game"),
            ScheduledGame(week=0, date="2026-02-11", home="DEN", away="MIA", status="in_game"),
        ],
        espn=espn,
    )

    assert set(espn.days_asked) == {date(2026, 2, 11)}
    assert rows["Plays Home"].kickoff == TIP_OFF
    assert rows["On The Bench"].kickoff == TIP_OFF
    assert rows["Sits Today"].kickoff is None  # under way: the row is about the game now


def test_tip_off_times_are_left_out_rather_than_failing_the_week_when_espn_will_not_load() -> None:
    rows = _today(
        [ScheduledGame(week=0, date="2026-02-11", home="LAL", away="BOS", status="pre_game")],
        espn=FakeESPN(scoreboard_error=ESPNAPIError("down")),
    )

    assert rows["Plays Home"].today == "vs BOS today"
    assert not any(row.kickoff for row in rows.values())


LIVE_DAY = [
    ScheduledGame(week=0, date="2026-02-11", home="LAL", away="BOS", status="in_game"),
    ScheduledGame(week=0, date="2026-02-11", home="DEN", away="MIA", status="pre_game"),
]
"""Today: LAL and BOS under way, DEN still to tip off."""


def _played_today(yahoo: FakeYahoo, league: YahooLeague | None = None) -> tuple[dict[str, Spot], dict[str, Spot]]:
    """Both sides' rows on `LIVE_DAY`, by player."""
    yahoo.roster_players = [
        make_player("Plays Home", team="LAL", selected_position="PG"),
        make_player("Sits Today", team="DEN", selected_position="C"),
        make_player("On The Bench", team="BOS", selected_position="BN"),
    ]
    yahoo.others["t.2"] = [make_player("Theirs Live", team="BOS", selected_position="SG")]
    summary = nba_provider(yahoo, nba=FakeNBA(slate=LIVE_DAY, today=date(2026, 2, 11)), league=league).summary("")
    assert summary.mine is not None and summary.opponent is not None
    mine = {s.player: s for s in (*summary.mine.lineup, *summary.mine.bench)}
    return mine, {s.player: s for s in summary.opponent.lineup}


def test_a_game_under_way_shows_what_each_side_has_done_in_it_category_by_category() -> None:
    """His line today in the league's categories, beside his week; nothing for a game still to come."""
    yahoo = FakeYahoo()
    yahoo.today_lines = {
        "t.1": [
            make_player("Plays Home", team="LAL", stats={"12": "25", "15": "6"}),
            make_player("On The Bench", team="BOS", stats={"12": "-", "15": "-"}),
            make_player("Sits Today", team="DEN", stats={"12": "-"}),
        ],
        "t.2": [make_player("Theirs Live", team="BOS", stats={"12": "9"})],
    }

    mine, theirs = _played_today(yahoo)

    figures = {stat.label: stat.value for stat in mine["Plays Home"].line}
    assert (figures["PTS"], figures["REB"]) == ("25", "6")
    assert len(mine["Plays Home"].line) == len(CATEGORIES)  # every category the league scores
    assert {stat.label: stat.value for stat in theirs["Theirs Live"].line}["PTS"] == "9"
    assert mine["On The Bench"].line == []  # on the floor, nothing yet
    assert mine["Sits Today"].line == []  # still to tip off
    assert yahoo.days_read == [date(2026, 2, 11)]


def test_a_game_under_way_in_a_points_league_shows_his_points_live_beside_his_week() -> None:
    yahoo = FakeYahoo(weights=WEIGHTS)
    yahoo.today_lines = {
        "t.1": [
            make_player("Plays Home", team="LAL", points="31.50", stats={"12": "20"}),
            # Yahoo totals a game he never checked into as nought: no score, rather than a zero he did not earn.
            make_player("On The Bench", team="BOS", points="0", stats={"12": "-"}),
        ]
    }

    mine, _ = _played_today(yahoo, POINTS_LEAGUE)

    row = mine["Plays Home"]
    assert (row.scored, row.scoring, row.line) == ("31.5", "live", [])
    assert row.projection == row.value
    assert mine["Sits Today"].scoring is None
    assert mine["On The Bench"].scoring is None


def test_todays_lines_are_left_out_rather_than_failing_the_week_when_yahoo_will_not_give_them() -> None:
    yahoo = FakeYahoo()
    yahoo.today_error = YahooAPIError("down")

    mine, _ = _played_today(yahoo)

    assert mine["Plays Home"].today == "vs BOS live"
    assert not any(row.line for row in mine.values())


def test_a_week_not_being_played_reads_no_days_lines() -> None:
    yahoo = FakeYahoo()

    nba_provider(yahoo, nba=FakeNBA(slate=LIVE_DAY, today=date(2026, 2, 20))).summary("")

    assert yahoo.days_read == []


def test_a_day_the_nba_rests_leaves_every_starter_without_a_game() -> None:
    """Thanksgiving, the All-Star break: nobody plays, which the rows say rather than leaving it unsaid."""
    rows = _today([ScheduledGame(week=0, date="2026-02-12", home="LAL", away="BOS")])

    assert all(row.idle and row.today == "no game today" for row in rows.values())


def test_the_week_being_played_shows_its_categories_and_both_rosters() -> None:
    yahoo = FakeYahoo(roster=[make_player("Mine One", selected_position="PG")])
    summary = nba_provider(yahoo).summary("")

    assert len(summary.categories) == len(CATEGORIES)  # every category the league scores, recorded or not
    assert [(line.name, line.lead) for line in summary.categories if line.lead] == [("BLK", "theirs")]
    assert summary.mine is not None and summary.opponent is not None
    assert [s.player for s in summary.mine.lineup] == ["Mine One"]
    assert [s.player for s in summary.opponent.lineup] == ["Their Team One"]
    assert (summary.mine.record, summary.opponent.record) == ("4-2-1", "5-1")
    labels = {stat.label: stat.value for stat in summary.headline}
    assert labels["Adds left"] == "3 of 3"
    assert labels["Categories"] == "0-1-0"
    assert summary.weeks is not None and summary.weeks.week == summary.weeks.current == 5


def test_the_week_spans_the_season_the_league_carries() -> None:
    league = replace(yahoo_league(), start_week=1, end_week=21)
    weeks = nba_provider(FakeYahoo(), league=league).summary("").weeks

    assert weeks is not None and (weeks.first, weeks.last) == (1, 21)


def test_a_week_played_shows_both_rosters_as_they_ended_it_with_each_line() -> None:
    """Today's roster did not play week 3: the one Yahoo kept for that week did, and his line is that week's."""
    yahoo = FakeYahoo(roster=[make_player("Today Only", selected_position="PG")])
    yahoo.week_stats[3] = ({BLOCKS.yahoo_stat: "30"}, {BLOCKS.yahoo_stat: "21"})
    yahoo.winners[3] = "t.1"
    yahoo.played["t.1"] = [
        make_player("Then Starter", selected_position="C", status="O", stats={BLOCKS.yahoo_stat: "9", "12": "143"}),
        make_player("Then Hurt", selected_position="IL", stats={BLOCKS.yahoo_stat: "-", "12": "-"}),
    ]
    week = nba_provider(yahoo).week_of("", 3)

    assert [line.lead for line in week.categories if line.lead] == ["mine"]
    assert week.actions is None
    assert week.mine is not None and week.opponent is not None
    assert [(s.player, s.value, s.tone) for s in week.mine.lineup] == [("Then Starter", "", "neutral")]
    figures = {s.label: s.value for s in week.mine.lineup[0].line}
    assert (figures["PTS"], figures["BLK"]) == ("143", "9")
    assert [s.player for s in week.mine.reserve] == ["Then Hurt"]
    assert "no games" in week.mine.reserve[0].detail
    assert [s.player for s in week.opponent.lineup] == ["t.2 One"]
    assert {s.label: s.value for s in week.headline}["Result"] == "Won"
    assert week.weeks is not None and (week.weeks.week, week.weeks.current) == (3, 5)


@pytest.mark.parametrize(("winner", "said"), [("t.2", "Lost"), ("", "Tied")])
def test_a_week_settled_says_how_it_ended(winner: str, said: str) -> None:
    yahoo = FakeYahoo()
    yahoo.winners[4] = winner

    week = nba_provider(yahoo).week_of("", 4)

    assert {s.label: s.value for s in week.headline}["Result"] == said


def test_a_week_to_come_shows_both_rosters_as_they_stand() -> None:
    yahoo = FakeYahoo(roster=[make_player("Mine One", selected_position="PG")])
    yahoo.week_stats[6] = ({BLOCKS.yahoo_stat: "-"}, {BLOCKS.yahoo_stat: "-"})
    week = nba_provider(yahoo, league=replace(yahoo_league(), end_week=21)).week_of("", 6)

    assert week.mine is not None and [s.player for s in week.mine.lineup] == ["Mine One"]
    assert week.mine.points == ""  # nothing recorded yet: no 0-0-0
    assert [stat.label for stat in week.headline] == []
    assert yahoo.played_weeks == []


def test_a_week_with_no_opponent_is_just_its_place_in_the_season() -> None:
    week = nba_provider(FakeYahoo(matchup_dates=None)).week_of("", 2)

    assert (week.opponent, week.categories, week.window) == (None, [], "Week 2")


@pytest.mark.parametrize("week", [0, 6])
def test_a_week_outside_the_season_is_not_found(week: int) -> None:
    provider = nba_provider(FakeYahoo())

    with pytest.raises(NotFoundError):
        provider.week_of("", week)
    with pytest.raises(NotFoundError):
        provider.games_of("", week)


def test_between_seasons_there_is_no_week_to_open() -> None:
    provider = nba_provider(FakeYahoo(), league=replace(yahoo_league(), current_week=None))

    assert provider.summary("").weeks is None
    with pytest.raises(NotFoundError):
        provider.week_of("", 1)


def test_a_weeks_real_games_are_those_inside_its_dates_marked_where_you_have_players() -> None:
    slate = [
        ScheduledGame(week=0, date="2026-02-08", home="LAL", away="BOS"),  # the day before the week
        ScheduledGame(week=0, date="2026-02-10", home="LAL", away="GSW", status="complete"),
        ScheduledGame(week=0, date="2026-02-11", home="NYK", away="MIA"),
    ]
    games = nba_provider(FakeYahoo(), nba=FakeNBA(slate=slate)).games_of("", 5).games

    assert [(g.away, g.home) for g in games] == [("GSW", "LAL"), ("MIA", "NYK")]
    assert "final" in games[0].detail
    assert [p.name for p in games[0].yours] == ["Roster One"]  # an LAL forward
    assert games[1].yours == []


def test_a_week_with_no_matchup_has_no_dates_to_list_games_by() -> None:
    assert nba_provider(FakeYahoo(matchup_dates=None)).games_of("", 5).games == []


# ── ESPN's injury report ────────────────────────────────────────────────


def _espn_report(name: str, club: str, back: date | None = date(2026, 11, 22)) -> InjuryReport:
    return InjuryReport(
        name=name,
        club=club,
        status="Out",
        updated=datetime(2026, 11, 17, 23, tzinfo=UTC),
        returns=back,
        injury="Left calf, strain",
        comment=f"{name} (calf) won't play Friday.",
        url="https://espn.example/news",
    )


CURRY = make_player("Stephen Curry", "PG", "GSW", key="curry", status="O", injury_note="Calf")
ESPN_REPORT = FakeESPN(injuries=[_espn_report("Stephen Curry", "GS")])


def test_a_hurt_players_status_cell_says_when_espn_expects_him_back() -> None:
    """Yahoo spells the club GSW and ESPN GS: the join reads both as one club."""
    card = nba_provider(FakeYahoo(roster=[CURRY]), espn=ESPN_REPORT).roster()[0]

    assert card.columns["Status"] == "O"
    assert "~22 Nov" in card.notes["Status"]


def test_a_namesake_on_another_club_borrows_no_return() -> None:
    namesake = make_player("Stephen Curry", team="SAS", key="other", status="O")

    assert nba_provider(FakeYahoo(roster=[namesake]), espn=ESPN_REPORT).roster()[0].notes == {}


def test_a_name_two_players_on_one_club_share_resolves_to_nobody() -> None:
    twins = [CURRY, replace(CURRY, player_key="twin")]

    assert [c.notes for c in nba_provider(FakeYahoo(roster=twins), espn=ESPN_REPORT).roster()] == [{}, {}]


def test_a_player_yahoo_reports_healthy_has_no_status_to_annotate() -> None:
    healthy = replace(CURRY, status="")

    assert nba_provider(FakeYahoo(roster=[healthy]), espn=ESPN_REPORT).roster()[0].notes == {}


def test_the_drawer_shows_espns_injury_its_return_and_the_latest_word() -> None:
    detail = nba_provider(FakeYahoo(roster=[CURRY]), espn=ESPN_REPORT).player("", "curry")

    [injury] = [g for g in detail.groups if g.title == "Injury"]
    stats = {s.label: s.value for s in injury.stats}
    assert (stats["Status"], stats["Back"]) == ("Out", "~22 Nov")
    assert "Stephen Curry (calf) won't play Friday." in stats.values()


def test_off_espns_report_the_drawer_shows_yahoos_status_and_note() -> None:
    detail = nba_provider(FakeYahoo(roster=[CURRY])).player("", "curry")

    [injury] = [g for g in detail.groups if g.title == "Injury"]
    assert [(s.label, s.value) for s in injury.stats] == [("Status", "Out"), ("Body part", "Calf")]


def test_a_healthy_player_has_no_injury_group() -> None:
    detail = nba_provider(FakeYahoo(roster=[make_player("A B", key="ab")]), espn=ESPN_REPORT).player("", "ab")

    assert "Injury" not in [g.title for g in detail.groups]


def test_an_injury_report_that_will_not_load_leaves_yahoos_status_standing() -> None:
    espn = FakeESPN(injuries_error=ESPNAPIError("down"))

    card = nba_provider(FakeYahoo(roster=[CURRY]), espn=espn).roster()[0]

    assert (card.columns["Status"], card.notes) == ("O", {})


def test_the_model_is_told_when_a_hurt_roster_player_is_back() -> None:
    prompt = nba_provider(FakeYahoo(roster=[CURRY]), espn=ESPN_REPORT).build_context().prompt

    [line] = [line for line in prompt.splitlines() if "Stephen Curry" in line]
    assert "~22 Nov" in line


def test_a_trade_is_priced_knowing_when_a_hurt_player_is_back() -> None:
    yahoo = FakeYahoo(roster=[CURRY], search_results={"Stephen Curry": [CURRY]})
    proposal = TradeProposal(giving=["Stephen Curry"], receiving=[])

    text = nba_provider(yahoo, espn=ESPN_REPORT).build_trade_context("", proposal).prompt

    lines = [line for line in text.splitlines() if line.startswith("- Stephen Curry")]
    assert lines
    assert all("~22 Nov" in line for line in lines)


# ── the add limit ───────────────────────────────────────────────────────


def test_the_add_limit_is_the_leagues_own() -> None:
    labels = {s.label: s.value for s in nba_provider(FakeYahoo(adds_used=1, max_weekly_adds=4)).summary("").headline}

    assert labels["Adds left"] == "3 of 4"


def test_a_league_naming_no_add_limit_falls_back_to_the_configured_one() -> None:
    context = nba_provider(FakeYahoo(adds_used=1, max_weekly_adds=None)).build_context()

    assert context.headline == [Stat(label="Adds left", value="2 of 3", tone="good")]


# ── a points league ─────────────────────────────────────────────────────

WEIGHTS = {"12": 1.0, "15": 1.2, "16": 1.5, "17": 3.0, "18": 3.0, "19": -1.0}
"""A standard Yahoo points league's weights, by stat id: PTS, REB, AST, STL, BLK, TO."""

POINTS_LEAGUE = yahoo_league(scoring_type="headpoint")


def _points(yahoo: FakeYahoo | None = None, nba: FakeNBA | None = None) -> YahooNBAProvider:
    return nba_provider(yahoo or FakeYahoo(weights=WEIGHTS), nba=nba, league=POINTS_LEAGUE)


def test_a_points_week_is_scored_in_fantasy_points_with_no_category_table() -> None:
    yahoo = FakeYahoo(weights=WEIGHTS)
    yahoo.week_points[5] = (("349.90", "896.45"), ("575.80", "1107.37"))

    summary = _points(yahoo).summary("")

    headline = {s.label: (s.value, s.tone) for s in summary.headline}
    assert headline["Live"] == ("349.90 – 575.80", "warning")
    assert headline["Projected"] == ("896.45 – 1107.37", "warning")
    assert "Categories" not in headline
    assert summary.categories == []
    assert summary.mine is not None and summary.opponent is not None
    assert (summary.mine.points, summary.opponent.points) == ("349.90 pts · 896.45 proj", "575.80 pts · 1107.37 proj")


def test_a_points_week_played_is_won_on_its_final_total() -> None:
    yahoo = FakeYahoo(weights=WEIGHTS)
    yahoo.week_points[3] = (("1185.50", "1192.10"), ("778.80", "917.22"))

    yahoo.played["t.1"] = [make_player("Then Starter", selected_position="C", stats={"12": "87"}, points="140.80")]

    week = _points(yahoo).week_of("", 3)

    assert [(s.label, s.value, s.tone) for s in week.headline] == [("Final", "1185.50 – 778.80", "good")]
    assert week.mine is not None
    assert [(s.player, s.scored, s.scoring) for s in week.mine.lineup] == [("Then Starter", "140.8", "final")]


def test_a_category_league_keeps_its_categories() -> None:
    """A head-to-head categories league is scored as it always was, however Yahoo spells it."""
    league = yahoo_league(scoring_type="headone")

    summary = nba_provider(FakeYahoo(weights=WEIGHTS), league=league).summary("")

    assert {s.label for s in summary.headline} >= {"Categories"}
    assert len(summary.categories) == len(CATEGORIES)


def test_a_points_league_with_no_weights_is_read_as_a_category_one() -> None:
    """There is nothing to sum a player's line with, so no fantasy-point column claims one."""
    card = nba_provider(FakeYahoo(), league=POINTS_LEAGUE).roster()[0]

    assert "FPTS" not in card.columns


def test_a_points_leagues_season_reads_each_weeks_fantasy_points() -> None:
    """The league's scoring type, read once from the league list, settles how the schedule scores a week too."""
    yahoo = FakeYahoo(weights=WEIGHTS)
    yahoo.week_points[3] = (("1185.50", ""), ("778.80", ""))

    season = _points(yahoo).schedule("").season

    assert next(row.result for row in season if row.label == "Week 3") == "1185.50-778.80"


def test_a_points_leagues_rows_carry_yahoos_fantasy_points_a_game() -> None:
    yahoo = FakeYahoo(weights=WEIGHTS, roster=[make_player("A B", key="ab")])
    yahoo.lines = {Average.LAST_MONTH: {"ab": YahooLine(stats={"12": "20.1"}, points="32.67")}}

    card = _points(yahoo).roster()[0]

    assert (card.columns["FPTS"], card.values["FPTS"]) == ("32.67", pytest.approx(32.67))


def test_a_points_row_with_no_form_shows_a_dash() -> None:
    card = (
        _points(FakeYahoo(weights=WEIGHTS, available=[make_player("Free Man")]))
        .free_agents("", PlayerQuery())
        .players[0]
    )

    assert card.columns["FPTS"] == "—"
    assert "FPTS" not in card.values


def test_a_rivals_roster_in_a_points_league_carries_the_same_column() -> None:
    card = _points().roster_of("", "t.2")[0]

    assert "FPTS" in card.columns


def test_a_points_leagues_drawer_is_headed_by_yahoos_fantasy_points_a_game_this_season() -> None:
    yahoo = FakeYahoo(weights=WEIGHTS, roster=[make_player("A B", key="ab")])
    yahoo.lines = {
        Average.SEASON: {"ab": YahooLine(stats={"12": "20.1"}, points="32.67")},
        Average.LAST_MONTH: {"ab": YahooLine(stats={"12": "24.0"}, points="38.10")},
    }

    detail = _points(yahoo).player("", "ab")

    assert (detail.headline, detail.headline_label) == ("32.67", "fpts/game, season")
    groups = {g.title: {s.label: s.value for s in g.stats} for g in detail.groups}
    assert (groups["Season"]["FPTS"], groups["Last 30 days"]["FPTS"]) == ("32.67", "38.10")


def test_a_points_drawer_without_a_season_says_so() -> None:
    detail = _points(FakeYahoo(weights=WEIGHTS, roster=[make_player("A B", key="ab")])).player("", "ab")

    assert (detail.headline, detail.headline_label) == ("", "No games this season")


def test_a_points_leagues_scout_ranks_the_wire_by_fantasy_points_a_game() -> None:
    wire = [make_player("Scorer", key="s"), make_player("Stopper", key="b"), make_player("Unknown", key="u")]
    form = FakeNBA(stats={"Scorer": _form(pts=30), "Stopper": _form(pts=10, blk=5)})
    yahoo = FakeYahoo(weights=WEIGHTS, available=wire, stat_leaders={"BLK": [make_player("Leader", key="l")]})

    context = _points(yahoo, form).build_context()

    assert list(context.candidate_lines) == ["Scorer", "Stopper"]  # 30 a game, then 25; no line, no rank
    assert "PTS 1, REB 1.2" in context.prompt
    assert "Top in" not in context.prompt  # categories lead nothing in a points league


def test_a_points_leagues_trade_is_priced_in_fantasy_points() -> None:
    yahoo = FakeYahoo(weights=WEIGHTS, search_results={"A B": [make_player("A B")]})
    form = FakeNBA(stats={"A B": _form(played=12, pts=20)})

    context = _points(yahoo, form).build_trade_context("", TradeProposal(giving=["A B"], receiving=[]))

    assert "= 20.0 fpts" in context.prompt
    assert "fantasy points" in context.situation


# ── the week's decisions ────────────────────────────────────────────────


def _line(pts: float, reb: float = 5.0, ast: float = 3.0, blk: float = 0.5) -> PlayerStats:
    """Ten identical games of this line, with steady-enough minutes to leave his worth un-nudged."""
    games = [
        NBAGameLog(
            player_id="p",
            date=f"2026-01-{i + 1:02d}",
            opponent="BOS",
            stats={"pts": pts, "reb": reb, "ast": ast, "blk": blk},
        )
        for i in range(10)
    ]
    return PlayerStats(recent=RecentForm(games=10, line=nine_cat(games)), minutes=(28.0,) * 10)


STARTER = make_player("Starter", "PF", "LAL", key="starter", selected_position="PF")
BENCHED = make_player("Benched", "PF", "BOS", key="benched", selected_position="BN")
SPARE = make_player("Spare", "C", "MIA", key="spare", selected_position="BN")
STREAMER = make_player("Streamer", "SF", "NYK", key="streamer")
WEEK_FORM = {"Starter": _line(30), "Benched": _line(24), "Spare": _line(8), "Streamer": _line(12)}
WEEK_GAMES = {"LAL": 1, "BOS": 3, "MIA": 1, "NYK": 4}
WEEK_DAY = date(2026, 2, 11)
WEEK_SLATE = [ScheduledGame(week=0, date=WEEK_DAY.isoformat(), home="BOS", away="NYK", status="pre_game")]
"""Today, inside FakeYahoo's week: the bench player's club plays, the starter's rests."""
START = f"start:{WEEK_DAY.isoformat()}:benched:starter"


STARTER_MONTH = YahooLine(stats={"12": "28.4", "15": "6.1", "16": "2.9"}, points="44.70")
"""Yahoo's average over the starter's last month: what his row shows, apart from the form his week is weighed on."""


def _averaged(yahoo: FakeYahoo) -> FakeYahoo:
    yahoo.lines = {Average.LAST_MONTH: {"starter": STARTER_MONTH}}
    return yahoo


def _decisions(league: YahooLeague = POINTS_LEAGUE, **extra: Any) -> YahooNBAProvider:
    yahoo = _averaged(FakeYahoo(roster=[STARTER, BENCHED, SPARE], available=[STREAMER], weights=WEIGHTS, **extra))
    return nba_provider(
        yahoo, nba=FakeNBA(stats=WEEK_FORM, games=WEEK_GAMES, slate=WEEK_SLATE, today=WEEK_DAY), league=league
    )


def test_a_points_leagues_rows_read_games_left_and_fantasy_points_a_game() -> None:
    summary = _decisions().summary("")

    assert summary.mine is not None
    [row] = summary.mine.lineup
    assert row.value == "1G · 44.70 fpts/g"


def test_a_bench_player_playing_today_starts_over_a_starter_who_rests_and_a_free_agent_streams_in() -> None:
    actions = _decisions().summary("").actions

    assert actions is not None
    assert [a.key for a in actions] == [START, "stream:streamer:spare"]
    start, stream = actions
    assert [(p.name, p.held) for p in start.players] == [("Benched", "bench"), ("Starter", "starter")]
    assert stream.drop == "spare"


def _claimable(cleared: date | None, priority: int = 0) -> list[Action]:
    """The week's to-do list with Streamer's club playing 11-14 Feb, and Streamer on waivers until `cleared`;
    you at `priority` in the waiver order."""
    streamer = replace(STREAMER, waiver_date=cleared)
    yahoo = _averaged(FakeYahoo(roster=[STARTER, BENCHED, SPARE], available=[streamer], weights=WEIGHTS))
    yahoo.priority = priority
    nyk = [date(2026, 2, day) for day in (11, 12, 13, 14)]
    nba = FakeNBA(stats=WEEK_FORM, games=WEEK_GAMES, slate=WEEK_SLATE, today=WEEK_DAY, dated={"NYK": nyk})
    return nba_provider(yahoo, nba=nba, league=POINTS_LEAGUE).summary("").actions or []


def test_nobody_you_already_have_a_claim_waiting_on_is_suggested_again() -> None:
    yahoo = _averaged(FakeYahoo(roster=[STARTER, BENCHED, SPARE], available=[STREAMER], weights=WEIGHTS))
    nba = FakeNBA(stats=WEEK_FORM, games=WEEK_GAMES, slate=WEEK_SLATE, today=WEEK_DAY)
    provider = nba_provider(yahoo, nba=nba, league=POINTS_LEAGUE)
    assert any(a.player_id == "streamer" for a in provider.summary("").actions or [])

    yahoo.waiting = [_waiting_claim("streamer", "Streamer")]

    assert not any(a.player_id == "streamer" for a in provider.summary("").actions or [])


def test_a_player_on_waivers_streams_in_as_a_claim_weighed_on_the_games_from_the_day_he_clears() -> None:
    [stream] = [a for a in _claimable(date(2026, 2, 12)) if a.kind == "waiver"]
    [free] = [a for a in _claimable(None) if a.kind == "waiver"]

    assert stream.player_id == free.player_id == "streamer"
    assert [p.held for p in stream.players] == ["waivers", "bench"]
    assert "Claim Streamer" in stream.title
    assert "3 games" in stream.title  # the 12th to the 14th
    games = [[f.value for f in a.players[0].figures if f.label == "G left"] for a in (stream, free)]
    assert games == [["3"], ["4"]]


def test_a_claim_says_where_you_stand_in_the_waiver_order() -> None:
    [stream] = [a for a in _claimable(date(2026, 2, 12), priority=7) if a.kind == "waiver"]

    assert "#7" in stream.reason and "Thu 12 Feb" in stream.reason


def test_a_claim_whose_games_after_clearing_add_less_than_the_streaming_floor_is_not_suggested() -> None:
    """Two games of Streamer for one of Spare is a game and a bit of Spare's: short of `STREAM_GAMES`."""
    assert [a for a in _claimable(date(2026, 2, 13)) if a.kind == "waiver"] == []


def test_the_week_reads_streams_from_the_top_of_the_wire_leaving_the_deep_list_to_the_free_agents_page() -> None:
    """The summary is the page opened most: three pages of Yahoo's wire, not sixteen."""
    yahoo = FakeYahoo(roster=[STARTER, BENCHED, SPARE], available=[STREAMER], weights=WEIGHTS)

    nba_provider(yahoo, nba=FakeNBA(stats=WEEK_FORM, games=WEEK_GAMES), league=POINTS_LEAGUE).summary("")

    assert yahoo.wire_depths == {Timeframe.SEASON: 50, Timeframe.LAST_WEEK: 25}


def test_with_no_adds_left_nothing_streams() -> None:
    actions = _decisions(adds_used=3).summary("").actions

    assert actions is not None
    assert [a.key.split(":")[0] for a in actions] == ["start"]


def _categories(forecast: FakeForecast) -> YahooNBAProvider:
    """`_decisions` in a category league, its week played out by `forecast`."""
    yahoo = FakeYahoo(roster=[STARTER, BENCHED, SPARE], available=[STREAMER])
    nba = FakeNBA(stats=WEEK_FORM, games=WEEK_GAMES, slate=WEEK_SLATE, today=WEEK_DAY)
    return nba_provider(yahoo, nba=nba, league=yahoo_league(), forecast=forecast)


def test_a_category_leagues_pickups_are_weighed_on_the_matchup_its_forecast_plays() -> None:
    """One simulation for the page and the list: the summary hands over the very matchup the week's chance reads."""
    forecast = FakeForecast(dict.fromkeys((c.label for c in CATEGORIES), 0.5))
    provider = _categories(forecast)

    provider.summary("")

    assert forecast.played == [provider.matchup_input("")]


def test_a_category_leagues_stream_names_the_close_categories_it_targets() -> None:
    """Every category but points all but settled: what the streamer adds to points is what he targets."""
    chances = dict.fromkeys((c.label for c in CATEGORIES), 0.99) | {"PTS": 0.5}

    [stream] = [a for a in _categories(FakeForecast(chances)).summary("").actions or [] if a.kind == "waiver"]

    assert stream.player_id == "streamer"
    assert "PTS" in stream.reason and "REB" not in stream.reason


def test_a_week_that_cannot_be_simulated_weighs_its_pickups_on_every_category_alike() -> None:
    failing = FakeForecast(error=UnsupportedError("One", "a forecast"))

    with_chances = _categories(FakeForecast()).summary("").actions
    without = _categories(failing).summary("").actions

    assert failing.played
    assert [a.key for a in without or []] == [a.key for a in with_chances or []]


def test_a_points_league_plays_no_forecast_for_its_pickups() -> None:
    forecast = FakeForecast()
    yahoo = FakeYahoo(roster=[STARTER, BENCHED, SPARE], available=[STREAMER], weights=WEIGHTS)

    nba_provider(
        yahoo, nba=FakeNBA(stats=WEEK_FORM, games=WEEK_GAMES), league=POINTS_LEAGUE, forecast=forecast
    ).summary("")

    assert forecast.played == []


def test_a_hurt_player_counts_only_the_games_from_his_return() -> None:
    week = (date(2026, 11, 16), date(2026, 11, 22))
    dated = {"GSW": [date(2026, 11, 18), date(2026, 11, 21), date(2026, 11, 22)]}
    hurt = replace(CURRY, slot="PG")

    def row(espn: FakeESPN) -> str:
        yahoo = FakeYahoo(roster=[hurt], weights=WEIGHTS, matchup_dates=week)
        summary = nba_provider(
            yahoo, nba=FakeNBA(stats={"Stephen Curry": _line(30)}, dated=dated), league=POINTS_LEAGUE, espn=espn
        ).summary("")
        assert summary.mine is not None
        return summary.mine.lineup[0].value

    assert row(ESPN_REPORT).startswith("1G")  # back the 22nd, the week's last game
    assert row(FakeESPN()).startswith("0G")  # out, and nobody says when he is back


@pytest.mark.parametrize("league", [yahoo_league(), POINTS_LEAGUE], ids=["categories", "points"])
def test_the_wire_leads_with_who_can_play_this_week_not_the_best_a_game_ruled_out(league: YahooLeague) -> None:
    """Out until after the week, Curry's game is the wire's best and adds nothing to it."""
    week = (date(2026, 11, 16), date(2026, 11, 22))
    available = make_player("Available", "SF", "NYK", key="available")
    days = [date(2026, 11, 18), date(2026, 11, 20), date(2026, 11, 22)]
    form = FakeNBA(stats={"Stephen Curry": _line(30), "Available": _line(12)}, dated={"GSW": days, "NYK": days})
    espn = FakeESPN(injuries=[_espn_report("Stephen Curry", "GS", back=date(2026, 11, 27))])
    weights = WEIGHTS if league is POINTS_LEAGUE else None
    yahoo = FakeYahoo(roster=[STARTER], available=[CURRY, available], weights=weights, matchup_dates=week)

    agents = nba_provider(yahoo, nba=form, league=league, espn=espn).free_agents("", PlayerQuery()).players

    assert [card.player_id for card in agents] == ["available", "curry"]
    assert (agents[1].columns["Status"], agents[1].notes["Status"]) == ("O", "back ~27 Nov")


def test_a_week_to_come_reads_each_players_games_in_it() -> None:
    week = _decisions(league=replace(POINTS_LEAGUE, end_week=21)).week_of("", 6)

    assert week.mine is not None
    assert week.mine.lineup[0].value.startswith("1G")
    assert week.actions is None


def test_the_model_reads_each_players_week_and_judges_the_same_list_the_page_shows() -> None:
    provider = _decisions()

    context, summary = provider.build_context(), provider.summary("")

    assert [t.key for t in context.tasks] == [a.key for a in summary.actions or []]
    [benched] = [line for line in context.prompt.splitlines() if line.startswith("- Benched")]
    assert "WEEK: 3G" in benched
    assert "T1" in context.prompt and "Streamer" in context.prompt
    assert context.listed == frozenset({"Benched", "Starter", "Streamer", "Spare"})
    assert context.worth["Benched"] > context.worth["Spare"]


def test_a_wire_that_will_not_load_leaves_the_weeks_rows_and_starts_standing() -> None:
    yahoo = FakeYahoo(roster=[STARTER, BENCHED, SPARE], available=[STREAMER], weights=WEIGHTS)
    yahoo.wire_error = YahooCaptureMissingError("players")
    nba = FakeNBA(stats=WEEK_FORM, games=WEEK_GAMES, slate=WEEK_SLATE, today=WEEK_DAY)
    provider = nba_provider(yahoo, nba=nba, league=POINTS_LEAGUE)

    summary = provider.summary("")

    assert [a.key for a in summary.actions or []] == [START]
    assert summary.mine is not None and summary.mine.lineup[0].value.startswith("1G")


# ── the week, simulated ─────────────────────────────────────────────


def _simulated(yahoo: FakeYahoo, league: Any = None) -> YahooNBAProvider:
    """My Roster One and Their Team One both play for the Lakers, twice inside the week, off two recent games each."""
    slate = [
        ScheduledGame(week=1, date=day, home="LAL", away="DEN", status="pre_game")
        for day in ("2026-02-12", "2026-02-14")
    ]
    played = [
        NBAGameLog(player_id="p", date="2026-02-01", opponent="BOS", stats={"pts": 20.0, "reb": 5.0}),
        NBAGameLog(player_id="p", date="2026-01-30", opponent="NYK", stats={"pts": 10.0, "reb": 10.0}),
    ]
    nba = FakeNBA(slate=slate, logs={"Roster One": played, "Their Team One": played})
    return nba_provider(yahoo, nba=nba, league=league)


def test_a_category_week_is_simulated_from_its_board_and_both_rosters_games_left() -> None:
    yahoo = FakeYahoo()
    yahoo.week_stats[5] = ({"12": "100"}, {"12": "90"})

    matchup = _simulated(yahoo).matchup_input("466.l.1")

    assert matchup is not None and matchup.categories is not None
    week = matchup.categories
    assert dict(zip(week.stats, week.board_mine, strict=True))["pts"] == 100.0
    assert [(line.player_id, line.games) for line in (*week.mine, *week.theirs)] == [
        ("roster-one", 2),
        ("their-team-one", 2),
    ]
    assert matchup == _simulated(yahoo).matchup_input("466.l.1")  # the same seed every read


def test_a_points_week_is_simulated_in_fantasy_points_on_top_of_yahoos_live_total() -> None:
    yahoo = FakeYahoo(weights={"12": 1.0, "15": 1.0})
    yahoo.week_points[5] = (("349.90", "896.45"), ("575.80", "1107.37"))

    matchup = _simulated(yahoo, POINTS_LEAGUE).matchup_input("466.l.1")

    assert matchup is not None and matchup.categories is None
    assert [(o.floor, o.games, o.samples) for o in matchup.mine] == [(349.9, 0, ()), (0.0, 2, (25.0, 20.0))]
    assert matchup.theirs[0].floor == 575.8


def test_the_wire_and_a_week_without_an_opponent_are_not_simulated() -> None:
    assert _simulated(FakeYahoo()).matchup_input("466.l.1", candidates=["x"]) is None
    assert _simulated(FakeYahoo(matchup_dates=None)).matchup_input("466.l.1") is None
    between = replace(yahoo_league(), current_week=None)
    assert _simulated(FakeYahoo(), between).matchup_input("466.l.1") is None


def test_a_league_scoring_each_players_best_game_or_no_points_is_not_simulated() -> None:
    best = FakeYahoo(weights={"12": 1.0})
    best.best_game = True

    with pytest.raises(UnsupportedError):
        _simulated(best, POINTS_LEAGUE).matchup_input("466.l.1")
    with pytest.raises(UnsupportedError):
        _simulated(FakeYahoo(), POINTS_LEAGUE).matchup_input("466.l.1")


def test_a_weekly_lineup_counts_only_todays_starters() -> None:
    yahoo = FakeYahoo(roster=[make_player("Roster One", selected_position="BN")])
    yahoo.weekly_lineups = True

    matchup = _simulated(yahoo).matchup_input("466.l.1")

    assert matchup is not None and matchup.categories is not None
    assert matchup.categories.mine == ()


def test_basketball_weeks_already_played_are_not_backtested() -> None:
    provider = _simulated(FakeYahoo())

    assert isinstance(provider, ForecastProvider)
    assert (provider.played_weeks("466.l.1"), provider.played_matchups("466.l.1", 3)) == ([], [])


# ── a schedule not yet final ────────────────────────────────────────────

UNSCHEDULED = [date(2026, 2, 10), date(2026, 2, 11), date(2026, 2, 12)]
"""Days inside the default matchup week, 9-15 Feb, the schedule has no games for yet."""


def _pending(league: YahooLeague = POINTS_LEAGUE, unscheduled: list[date] = UNSCHEDULED) -> YahooNBAProvider:
    yahoo = _averaged(FakeYahoo(roster=[STARTER, BENCHED, SPARE], available=[STREAMER], weights=WEIGHTS))
    nba = FakeNBA(stats=WEEK_FORM, games=WEEK_GAMES, unscheduled=unscheduled)
    return nba_provider(yahoo, nba=nba, league=league)


def test_a_week_with_days_unscheduled_says_so_in_its_header_rows_and_to_do_list() -> None:
    summary = _pending().summary("")

    assert ("Schedule", "not final") in [(s.label, s.value) for s in summary.headline]
    assert summary.mine is not None and summary.mine.lineup[0].value.startswith("1+G · ")
    assert summary.actions and all(a.reason.endswith(PROVISIONAL) for a in summary.actions)


def test_a_week_fully_scheduled_reads_its_games_left_as_a_count() -> None:
    summary = _pending(unscheduled=[]).summary("")

    assert "Schedule" not in [s.label for s in summary.headline]
    assert summary.mine is not None and summary.mine.lineup[0].value.startswith("1G · ")


def test_a_browsed_week_being_played_with_days_unscheduled_says_so_and_a_week_played_does_not() -> None:
    provider = _pending()

    assert "Schedule" in [s.label for s in provider.week_of("", 5).headline]
    assert "Schedule" not in [s.label for s in provider.week_of("", 4).headline]


def test_the_fixtures_of_a_week_with_days_unscheduled_carry_a_note_naming_them() -> None:
    assert "10-12 Feb" in _pending().games_of("", 5).note
    assert _pending(unscheduled=[]).games_of("", 5).note == ""


def test_a_week_with_days_unscheduled_is_simulated_as_provisional() -> None:
    matchup = _pending(league=yahoo_league()).matchup_input("466.l.1")

    plain = _simulated(FakeYahoo()).matchup_input("466.l.1")
    assert matchup is not None and matchup.provisional
    assert plain is not None and not plain.provisional


def test_the_scouts_schedule_names_the_days_still_to_be_scheduled() -> None:
    assert "10-12 Feb" in _pending().build_context().extra


# ── the weeks ahead ─────────────────────────────────────────────────────

AHEAD_DAYS = {"LAL": [7, 9, 11, 13], "BOS": [8], "MIA": [8, 10], "NYK": [7, 9, 11, 13]}
"""Week 6, 7-13 December: Starter's and Streamer's clubs play four, Benched's one, Spare's two."""


def _ahead(
    yahoo: FakeYahoo | None = None, league: YahooLeague | None = None, unscheduled: list[date] | None = None
) -> YahooNBAProvider:
    """Week 5 being played, week 6 dated on the scoreboard, and no matchup in the weeks after."""
    yahoo = yahoo or FakeYahoo(roster=[STARTER, BENCHED, SPARE], available=[STREAMER], weights=WEIGHTS)
    side = MatchupSide(team_key="t.1", name="My Team", points="", stats={})
    yahoo.season_weeks = {6: Pairing(start=date(2026, 12, 7), end=date(2026, 12, 13), mine=side, opponent=side)}
    slate = [
        ScheduledGame(week=0, date=f"2026-12-{day:02d}", home=club, away="ZZZ")
        for club, days in AHEAD_DAYS.items()
        for day in days
    ]
    return nba_provider(
        yahoo,
        nba=FakeNBA(stats=WEEK_FORM, games=WEEK_GAMES, slate=slate, unscheduled=unscheduled),
        league=league or replace(POINTS_LEAGUE, end_week=20),
    )


def test_basketball_plans_its_weeks_ahead_in_games_and_streams_into_a_heavy_one() -> None:
    provider = _ahead()
    assert isinstance(provider, OutlookProvider)

    outlook = provider.weeks_ahead("466.l.1")

    assert outlook.measure == "games"
    [week] = outlook.weeks  # the weeks without a matchup are left out
    assert (week.week, week.points, week.heavy) == (6, 6, True)  # one slot: a game a day on six days
    assert "Streamer" in week.fix
    assert "drop Spare" in week.fix
    assert week.gain == 2


def test_a_player_on_waivers_weeks_ahead_counts_only_the_nights_after_he_clears() -> None:
    def week(cleared: date) -> WeekAhead:
        streamer = replace(STREAMER, waiver_date=cleared)
        yahoo = FakeYahoo(roster=[STARTER, BENCHED, SPARE], available=[streamer], weights=WEIGHTS)
        [found] = _ahead(yahoo).weeks_ahead("466.l.1").weeks
        return found

    claimed = week(date(2026, 12, 8))  # the 9th, 11th and 13th: one more than Spare
    assert "Claim Streamer" in claimed.fix
    assert "clears 8 Dec" in claimed.fix
    assert claimed.gain == 1
    assert week(date(2026, 12, 10)).fix == ""  # the 11th and 13th: no more than Spare


def test_another_managers_weeks_ahead_read_his_roster_and_an_unknown_team_is_refused() -> None:
    provider = _ahead()

    [week] = provider.weeks_ahead("466.l.1", "t.2").weeks
    assert week.points == 4  # Their Team One, at LAL: four games

    with pytest.raises(TeamNotFoundError):
        provider.weeks_ahead("466.l.1", "t.9")


def test_no_weeks_ahead_between_seasons_or_after_the_last() -> None:
    between = replace(POINTS_LEAGUE, current_week=None, end_week=20)

    assert _ahead(league=between).weeks_ahead("466.l.1").weeks == []
    assert _ahead(league=POINTS_LEAGUE).weeks_ahead("466.l.1").weeks == []  # week 5 is the last


def test_a_wire_that_will_not_load_leaves_the_weeks_ahead_without_a_stream() -> None:
    yahoo = FakeYahoo(roster=[STARTER, BENCHED, SPARE], available=[STREAMER], weights=WEIGHTS)
    yahoo.wire_error = YahooCaptureMissingError("the wire")

    [week] = _ahead(yahoo).weeks_ahead("466.l.1").weeks

    assert (week.points, week.fix) == (6, "")


# ── the wire, judged ────────────────────────────────────────────────────

ROOKIE = make_player("Rookie", "PG", "BOS", key="rookie")


def _wire() -> YahooNBAProvider:
    yahoo = FakeYahoo(roster=[STARTER, BENCHED, SPARE], available=[STREAMER, ROOKIE], weights=WEIGHTS)
    return nba_provider(yahoo, nba=FakeNBA(stats=WEEK_FORM, games=WEEK_GAMES), league=POINTS_LEAGUE)


def test_a_free_agents_line_carries_his_id_his_week_and_the_drop_he_streams_over() -> None:
    provider = _wire()
    assert isinstance(provider, WireProvider)

    context = provider.build_wire_context("466.l.1", ["streamer"])

    line = context.targets["streamer"]
    assert line.startswith("- [id streamer] Streamer")
    assert "WEEK: 4G" in line
    assert "streams over Spare" in line
    assert line in context.prompt
    assert "Starter" in context.prompt  # the roster that could make way
    assert context.candidate_lines["Streamer"] == line


def test_a_free_agents_line_is_the_same_whoever_is_asked_about_beside_him() -> None:
    provider = _wire()

    alone = provider.build_wire_context("466.l.1", ["streamer"]).targets["streamer"]
    together = provider.build_wire_context("466.l.1", ["rookie", "streamer"]).targets["streamer"]

    assert alone == together


def test_a_rostered_or_unknown_player_is_not_judged_as_a_free_agent() -> None:
    with pytest.raises(PlayerNotFoundError) as caught:
        _wire().build_wire_context("466.l.1", ["streamer", "spare", "nobody"])

    assert caught.value.names == ["spare", "nobody"]


def test_a_free_agent_is_judged_without_a_week_when_there_is_no_matchup() -> None:
    yahoo = FakeYahoo(roster=[STARTER], available=[STREAMER], weights=WEIGHTS, matchup_dates=None)
    provider = nba_provider(yahoo, nba=FakeNBA(stats=WEEK_FORM), league=POINTS_LEAGUE)

    line = provider.build_wire_context("466.l.1", ["streamer"]).targets["streamer"]

    assert "WEEK" not in line
    assert "fits" not in line


def test_a_week_ahead_the_nba_has_yet_to_schedule_is_provisional() -> None:
    [week] = _ahead(unscheduled=[date(2026, 12, 10)]).weeks_ahead("466.l.1").weeks

    assert (week.provisional, week.fix) == (True, "")
    assert _ahead().weeks_ahead("466.l.1").weeks[0].provisional is False


# ── who is trending on the wire ─────────────────────────────────────────


def _role(window: float, latest: float, minutes: float, before: float) -> PlayerStats:
    """Fifteen games averaging `window` points, the last five `latest` on `minutes` a game against `before`."""
    return PlayerStats(
        recent=RecentForm(games=15, line={"PTS": window}),
        last_5={"PTS": latest},
        minutes=(minutes,) * 5,
        role=Role(games=5, minutes=minutes, window=before),
    )


RISER = replace(make_player("Riser", "SF", "SAC", key="riser"), rostered=34.0, rostered_change=12.0)
STEADIER = replace(make_player("Steadier", "SF", "NYK", key="steadier"), rostered=60.0, rostered_change=-2.0)
FALLER = replace(make_player("Faller", "SG", "LAC", key="faller"), rostered=20.0, rostered_change=0.0)
TRENDS = {
    "Riser": _role(window=12.0, latest=22.0, minutes=37.7, before=33.5),
    "Steadier": _role(window=14.0, latest=14.0, minutes=30.0, before=30.0),
    "Faller": _role(window=16.0, latest=6.0, minutes=20.6, before=25.9),
}


@pytest.mark.parametrize("league", [yahoo_league(), POINTS_LEAGUE], ids=["categories", "points"])
def test_the_wire_ranks_a_riser_over_a_steadier_player_and_drops_a_faller(league: YahooLeague) -> None:
    """Every club plays three: the order is a game's value, which leans on the last five where minutes moved."""
    weights = WEIGHTS if league is POINTS_LEAGUE else None
    yahoo = FakeYahoo(roster=[STARTER], available=[FALLER, STEADIER, RISER], weights=weights)
    nba = FakeNBA(stats={**TRENDS, "Starter": _line(20)}, games={"SAC": 3, "NYK": 3, "LAC": 3, "LAL": 3})

    agents = nba_provider(yahoo, nba=nba, league=league).free_agents("", PlayerQuery()).players

    assert [card.player_id for card in agents] == ["riser", "steadier", "faller"]


def test_the_wire_shows_which_way_his_minutes_and_his_rostered_share_moved_in_text() -> None:
    yahoo = FakeYahoo(roster=[STARTER], available=[RISER, STEADIER, FALLER])
    nba = FakeNBA(stats={**TRENDS, "Starter": _line(20)}, games={"SAC": 3, "NYK": 3, "LAC": 3, "LAL": 3})

    agents = nba_provider(yahoo, nba=nba).free_agents("", PlayerQuery()).players
    rows = {card.player_id: card for card in agents}

    assert rows["riser"].columns["Min"] == "37.7 ↑ (33.5)"
    assert rows["faller"].columns["Min"] == "20.6 ↓ (25.9)"
    assert rows["steadier"].columns["Min"] == "30.0"
    assert rows["riser"].values["Min"] == pytest.approx(37.7)
    assert (rows["riser"].columns["Rost"], rows["riser"].values["Rost"]) == ("34% ↑12", 34.0)
    assert rows["steadier"].columns["Rost"] == "60% ↓2"
    assert rows["faller"].columns["Rost"] == "20%"
    assert "33.5" in rows["riser"].notes["Min"] and "12" in rows["riser"].notes["Rost"]


def test_a_roster_carries_no_trend_columns_and_a_wire_without_shares_no_rostered_one() -> None:
    yahoo = FakeYahoo(roster=[STARTER], available=[make_player("Plain", key="plain")])

    provider = nba_provider(yahoo, nba=FakeNBA(stats={"Plain": _line(12)}))

    assert "Rost" not in provider.free_agents("", PlayerQuery()).players[0].columns
    assert "Min" not in provider.roster()[0].columns


def test_a_backup_whose_role_a_returning_starter_propped_up_is_flagged_on_the_wire() -> None:
    """Duren played two games before getting hurt: too few for a split, and Reed's role is the one he left."""
    today = datetime.now(PACIFIC).date()
    logs = {
        "d1": [game_log("d1", d, 20.0, team="DET") for d in (1, 2)],
        "r1": [game_log("r1", d, 26.0, team="DET", pts=12) for d in range(1, 11)],
    }
    scores = box_scores(logs, {"d1": "Jalen Duren", "r1": "Paul Reed"}, team="DET", positions={"d1": "C", "r1": "C"})
    nba = FakeNBA(stats={"Paul Reed": _line(12)}, scores=scores)
    nba.seasons[("Jalen Duren", "2025")] = NBASeason(player_id="d1", season="2025", games=70, minutes=2100.0, totals={})
    espn = FakeESPN(injuries=[_espn_report("Jalen Duren", "DET", back=today + timedelta(days=2))])
    reed = make_player("Paul Reed", "PF,C", "DET", key="reed")

    [row] = nba_provider(FakeYahoo(available=[reed]), nba=nba, espn=espn).free_agents("", PlayerQuery()).players

    assert row.columns["Without"].startswith("Duren back")
    assert "Jalen Duren" in row.notes["Without"]


def test_last_seasons_minutes_that_will_not_load_leave_the_returning_starter_unflagged() -> None:
    today = datetime.now(PACIFIC).date()
    logs = {
        "d1": [game_log("d1", d, 20.0, team="DET") for d in (1, 2)],
        "r1": [game_log("r1", d, 26.0, team="DET", pts=12) for d in range(1, 11)],
    }
    scores = box_scores(logs, {"d1": "Jalen Duren", "r1": "Paul Reed"}, team="DET", positions={"d1": "C", "r1": "C"})
    nba = FakeNBA(stats={"Paul Reed": _line(12)}, scores=scores)
    nba.season_error = SleeperAPIError("down")
    espn = FakeESPN(injuries=[_espn_report("Jalen Duren", "DET", back=today + timedelta(days=2))])
    reed = make_player("Paul Reed", "PF,C", "DET", key="reed")

    [row] = nba_provider(FakeYahoo(available=[reed]), nba=nba, espn=espn).free_agents("", PlayerQuery()).players

    assert row.columns["Without"] == "—"


# ── pickups weighed on the week's open slots ───────────────────────

SLOTTED = {"PF": 1, "C": 1, "Util": 1, "BN": 2, "IL": 1}


def _slotted(*, weekly: bool = False) -> tuple[FakeYahoo, FakeNBA]:
    """The week's to-do list with a lineup of PF, C and Util: today only Boston and New York play."""
    yahoo = FakeYahoo(roster=[STARTER, BENCHED, SPARE], available=[STREAMER], weights=WEIGHTS)
    yahoo.slots = SLOTTED
    yahoo.weekly_lineups = weekly
    stats = {**WEEK_FORM, "Streamer": _line(24)}
    return yahoo, FakeNBA(stats=stats, games=WEEK_GAMES, slate=WEEK_SLATE, today=WEEK_DAY)


def _games_left(headline: list[Stat]) -> list[str]:
    return [stat.value for stat in headline if stat.label == "Games left"]


def test_the_week_heads_with_the_games_each_side_can_start_and_labels_each_pickup() -> None:
    """Only Benched plays among yours, nobody among theirs; Streamer is three times Spare's points a game."""
    yahoo, nba = _slotted()
    yahoo.league_teams = [replace(t, adds_used=3) if not t.is_mine else t for t in DEFAULT_TEAMS]

    summary = nba_provider(yahoo, nba=nba, league=POINTS_LEAGUE).summary("")

    assert _games_left(summary.headline) == ["1 vs 0"]
    assert [(a.player_id, a.drop, a.pickup) for a in summary.actions or [] if a.kind == "waiver"] == [
        ("streamer", "spare", "keeper")
    ]


def test_the_forecast_counts_the_starts_the_to_do_list_does() -> None:
    """Benched (PF) and Spare (C) both play today with PF, C and Util open: two starts, though one slot is filled."""
    yahoo, _ = _slotted()
    spare = replace(SPARE, team="BOS")
    yahoo.roster_players = [STARTER, BENCHED, spare]
    yahoo.league_teams = [replace(t, adds_used=3) if not t.is_mine else t for t in DEFAULT_TEAMS]
    played = [game_log("p", 1, pts=10.0)]
    logs = {p.name: played for p in [STARTER, BENCHED, spare, *yahoo.roster("t.2")]}
    nba = FakeNBA(stats=WEEK_FORM, games=WEEK_GAMES, slate=WEEK_SLATE, today=WEEK_DAY, logs=logs)
    provider = nba_provider(yahoo, nba=nba, league=POINTS_LEAGUE)

    matchup = provider.matchup_input("")

    assert matchup is not None
    mine = sum(o.games for o in matchup.mine)
    assert _games_left(provider.summary("").headline) == [f"{mine} vs {sum(o.games for o in matchup.theirs)}"]
    assert mine == 2


def test_the_race_in_games_counts_what_the_opponents_adds_left_could_stream_in() -> None:
    """Their Team has adds left and an open slot tonight, when Streamer (New York) plays: one start it could add."""
    yahoo, nba = _slotted()

    summary = nba_provider(yahoo, nba=nba, league=POINTS_LEAGUE).summary("")

    assert _games_left(summary.headline) == [nba_week.volume(1, 0, 1)[0].value]
    yahoo.teams_error = YahooAPIError("down")
    assert _games_left(nba_provider(yahoo, nba=nba, league=POINTS_LEAGUE).summary("").headline) == ["1 vs 0"]


@pytest.mark.parametrize("broken", ["weekly", "schedule"])
def test_without_nights_to_place_them_pickups_are_weighed_on_games_left_and_no_race_is_shown(broken: str) -> None:
    yahoo, nba = _slotted(weekly=broken == "weekly")
    if broken == "schedule":
        nba.left_error = SleeperAPIError("down")

    summary = nba_provider(yahoo, nba=nba, league=POINTS_LEAGUE).summary("")

    assert _games_left(summary.headline) == []
    assert [a.player_id for a in summary.actions or [] if a.kind == "waiver"] == ["streamer"]


def _reed_week(scores_error: Exception | None = None) -> list[Action]:
    """Paul Reed on the wire, Duren due back in two days with two games beside him: the #238 case."""
    today = datetime.now(PACIFIC).date()
    logs = {
        "d1": [game_log("d1", d, 20.0, team="DET") for d in (1, 2)],
        "r1": [game_log("r1", d, 26.0, team="DET", pts=12) for d in range(1, 11)],
    }
    scores = box_scores(logs, {"d1": "Jalen Duren", "r1": "Paul Reed"}, team="DET", positions={"d1": "C", "r1": "C"})
    nba = FakeNBA(stats={**WEEK_FORM, "Paul Reed": _line(24)}, games={**WEEK_GAMES, "DET": 3}, scores=scores)
    nba.seasons[("Jalen Duren", "2025")] = NBASeason(player_id="d1", season="2025", games=70, minutes=2100.0, totals={})
    nba.scores_error = scores_error
    espn = FakeESPN(injuries=[_espn_report("Jalen Duren", "DET", back=today + timedelta(days=2))])
    reed = make_player("Paul Reed", "PF,C", "DET", key="reed")
    yahoo = FakeYahoo(roster=[STARTER, BENCHED, SPARE], available=[reed], weights=WEIGHTS)
    provider = nba_provider(yahoo, nba=nba, espn=espn, league=POINTS_LEAGUE)
    return [a for a in provider.summary("").actions or [] if a.kind == "waiver"]


def test_a_pickup_whose_role_a_returning_starter_propped_up_is_a_streamer_never_a_keeper() -> None:
    """Three times Spare's points a game: a keeper, but for Duren coming back."""
    [item] = _reed_week()

    assert (item.player_id, item.pickup) == ("reed", "streamer")


def test_box_scores_that_will_not_load_weigh_pickups_without_teammates() -> None:
    [item] = _reed_week(scores_error=SleeperAPIError("down"))

    assert (item.player_id, item.pickup) == ("reed", "keeper")


def test_a_pickup_whose_split_leans_on_a_teammate_due_back_is_a_streamer_never_a_keeper() -> None:
    """The Thybulle case: five games beside Reaves and five without, enough for a split rather than a `Returning`
    flag, and fourteen points without him against six beside him; Reaves is back in three days."""
    today = datetime.now(PACIFIC).date()
    logs = {
        "a1": [game_log("a1", d, 34.0, team="DET", pts=20) for d in range(1, 6)],
        "t1": [game_log("t1", d, 26.0, team="DET", pts=6 if d <= 5 else 14) for d in range(1, 11)],
    }
    names = {"a1": "Austin Reaves", "t1": "Matisse Thybulle"}
    scores = box_scores(logs, names, team="DET", positions={"a1": "SG", "t1": "SF"})
    nba = FakeNBA(stats={**WEEK_FORM, "Matisse Thybulle": _line(24)}, games={**WEEK_GAMES, "DET": 3}, scores=scores)
    espn = FakeESPN(injuries=[_espn_report("Austin Reaves", "DET", back=today + timedelta(days=3))])
    thybulle = make_player("Matisse Thybulle", "SG,SF", "DET", key="thybulle")
    yahoo = FakeYahoo(roster=[STARTER, BENCHED, SPARE], available=[thybulle], weights=WEIGHTS)

    actions = nba_provider(yahoo, nba=nba, espn=espn, league=POINTS_LEAGUE).summary("").actions or []
    [item] = [a for a in actions if a.kind == "waiver"]

    assert (item.player_id, item.pickup) == ("thybulle", "streamer")
    assert "Reaves" in item.reason
