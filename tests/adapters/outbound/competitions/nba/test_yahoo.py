"""Tests for the Yahoo basketball provider: `nba/yahoo.py`.

Mostly the context it builds, which is where league rules (add budget, IL
slots, matchup context) actually get encoded.
"""

from datetime import datetime
from typing import Any

import pytest
from support.ai import FakeAI
from support.nba import (
    FakeNBA,
    FakeSleeperProjections,
    FakeYahoo,
    FakeYahooAuth,
    make_player,
    nba_provider,
    yahoo_league,
)
from support.nba import yahoo_team as _yahoo_team
from support.reports import MOCK_NBA_REPORT
from support.stores import FakeAnswers

from thefrontoffice.adapters.outbound.competitions.nba.form import PACIFIC, PlayerStats, nine_cat
from thefrontoffice.adapters.outbound.competitions.nba.prompt import NO_MATCHUP
from thefrontoffice.adapters.outbound.competitions.nba.rules import CATEGORIES
from thefrontoffice.adapters.outbound.competitions.nba.yahoo import YahooNBAProvider
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooTeam
from thefrontoffice.application.scouting import ScoutEngine
from thefrontoffice.domain.errors import LeagueNotFoundError, PlayerNotFoundError, TeamNotFoundError
from thefrontoffice.domain.models import PlayerQuery, ScoutReport, Stat


def _scout(yahoo: FakeYahoo, ai: FakeAI | None = None, nba: FakeNBA | None = None) -> ScoutEngine:
    provider = nba_provider(yahoo, nba=nba)
    return ScoutEngine(provider, key="nba-yahoo", ai=ai or FakeAI(), answers=FakeAnswers())


def test_the_header_counts_the_adds_left_this_week() -> None:
    labels = {stat.label: stat.value for stat in nba_provider(FakeYahoo(adds_used=1)).build_context().headline}

    assert labels["Adds left"] == "2 of 3"


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
        nba=FakeNBA(),
        sleeper=FakeSleeperProjections(),
        max_weekly_adds=3,
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


def test_a_roster_card_carries_the_row_and_what_a_row_cannot() -> None:
    """The columns are the table; the id and the tone are what a table needs
    and a column should not be."""
    yahoo = FakeYahoo(roster=[make_player("A B", "PF,C", "LAL", status="O", selected_position="IL")])

    card = nba_provider(yahoo).roster()[0]

    assert card.columns["Player"] == "A B"
    assert card.columns["Slot"] == "IL"
    assert card.player_id
    assert card.tone == "warning"
    assert card.ruled_out


def test_a_game_time_decision_is_flagged_without_being_ruled_out() -> None:
    yahoo = FakeYahoo(roster=[make_player("A B", status="GTD")])

    card = nba_provider(yahoo).roster()[0]

    assert (card.tone, card.ruled_out) == ("warning", False)


def _form(**stats: float) -> PlayerStats:
    """Fifteen identical games, run through the real nine-category line."""
    games = [NBAGameLog(player_id="p", date=f"2026-01-{i + 1:02d}", opponent="BOS", stats=stats) for i in range(15)]
    return PlayerStats(last_15=nine_cat(games))


def test_the_drawer_shows_every_category_of_the_last_fifteen() -> None:
    """The drawer once looked figures up in a way the form line never matched,
    and showed a dash where every figure should have been."""
    stats = _form(pts=20, reb=8, ast=5, stl=1, blk=2, tpm=3, to=2, fgm=9, fga=18, ftm=4, fta=5)
    yahoo = FakeYahoo(roster=[make_player("A B", key="ab")])

    detail = nba_provider(yahoo, nba=FakeNBA(stats={"A B": stats})).player("", "ab")

    figures = {stat.label: stat.value for stat in detail.groups[0].stats}
    assert list(figures) == [c.label for c in CATEGORIES]
    assert figures == {
        "PTS": "20.0",
        "REB": "8.0",
        "AST": "5.0",
        "STL": "1.0",
        "BLK": "2.0",
        "3PTM": "3.0",
        "FG%": "50.0%",
        "FT%": "80.0%",
        "TO": "2.0",
    }
    assert detail.headline == "20.0"


def test_a_table_row_carries_recent_form() -> None:
    yahoo = FakeYahoo(roster=[make_player("A B")])
    card = nba_provider(yahoo, nba=FakeNBA(stats={"A B": _form(pts=20, reb=8, ast=5)})).roster()[0]

    assert (card.columns["PTS"], card.columns["REB"], card.columns["AST"]) == ("20.0", "8.0", "5.0")


def test_recent_form_sorts_as_a_number() -> None:
    """Sorted as text, 9.0 points sits above 20.0."""
    yahoo = FakeYahoo(roster=[make_player("A B")])
    card = nba_provider(yahoo, nba=FakeNBA(stats={"A B": _form(pts=20, reb=8, ast=5)})).roster()[0]

    assert card.values == {"PTS": 20.0, "REB": 8.0, "AST": 5.0}


def test_the_drawer_opens_for_a_player_on_nobodys_roster_or_a_rivals() -> None:
    """The wire and other managers' rosters open the same drawer as your own."""
    yahoo = FakeYahoo(available=[make_player("Free Man", key="fa")])
    provider = nba_provider(yahoo)

    assert provider.player("", "fa").name == "Free Man"
    assert provider.player("", "their-team-one").name == "Their Team One"


def test_a_player_the_league_does_not_know_is_not_found() -> None:
    with pytest.raises(PlayerNotFoundError):
        nba_provider().player("", "nobody")


def test_a_percentage_with_nothing_attempted_is_a_dash_not_zero() -> None:
    yahoo = FakeYahoo(roster=[make_player("A B", key="ab")])
    detail = nba_provider(yahoo, nba=FakeNBA(stats={"A B": _form(pts=10)})).player("", "ab")

    figures = {stat.label: stat.value for stat in detail.groups[0].stats}
    assert (figures["FT%"], figures["PTS"]) == ("—", "10.0")


def test_recent_form_is_a_dash_when_there_is_none() -> None:
    """Out of season there is no line to show, and a zero would read as a bad
    one rather than an absent one."""
    yahoo = FakeYahoo(roster=[make_player("A B")])
    card = nba_provider(yahoo).roster()[0]

    assert card.columns["PTS"] == "—"
    assert "PTS" not in card.values


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


def test_unmatched_players_simply_carry_no_projection() -> None:
    sleeper = FakeSleeperProjections([_game("Someone Entirely Else", "2026-02-10")])
    ctx = _provider_with(sleeper).build_context()
    assert "PROJ" not in ctx.roster_lines["Roster Player 0"]


# ── the league table ────────────────────────────────────────────────────


def test_the_table_comes_back_in_rank_order_and_says_which_is_yours() -> None:
    standings = nba_provider(FakeYahoo()).schedule("").standings

    assert [row.name for row in standings] == ["Their Team", "My Team"]
    assert [row.is_mine for row in standings] == [False, True]


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


def test_a_team_sent_without_standings_has_no_row_in_the_table() -> None:
    yahoo = FakeYahoo(teams=[YahooTeam(name="Half-loaded", team_key="t.9")])

    assert nba_provider(yahoo).schedule("").standings == []


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


def test_available_players_carry_the_same_form_columns_as_a_roster() -> None:
    agents = nba_provider(FakeYahoo()).free_agents("", PlayerQuery()).players

    assert {"Player", "Pos", "Team", "PTS", "REB", "AST", "Status"} <= set(agents[0].columns)


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


# ── the basketball calendar ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("when", "expected"),
    [
        (datetime(2026, 10, 20, tzinfo=PACIFIC), 2026),  # opening night
        (datetime(2026, 12, 31, tzinfo=PACIFIC), 2026),
        (datetime(2027, 1, 2, tzinfo=PACIFIC), 2026),  # January still belongs to the prior season
        (datetime(2027, 4, 15, tzinfo=PACIFIC), 2026),  # playoffs
        (datetime(2026, 9, 1, tzinfo=PACIFIC), 2026),  # September boundary, inclusive
        (datetime(2026, 8, 31, tzinfo=PACIFIC), 2025),  # the day before
    ],
)
def test_nba_season_rolls_over_in_september(when: datetime, expected: int) -> None:
    """Basketball's season starts in the autumn and runs into the next calendar year."""
    assert YahooNBAProvider.season_year(when) == expected
