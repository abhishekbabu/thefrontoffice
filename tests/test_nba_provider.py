"""Tests for the Scout orchestrator.

Exercises the prompt-building logic, which is where league rules (add budget,
IL slots, matchup context) actually get encoded.
"""

from typing import Any

import pytest
from conftest import FakeAI, FakeAnswers, FakeNBA, FakeYahoo, make_player
from conftest import _team as _yahoo_team
from reports import MOCK_NBA_REPORT

from thefrontoffice.adapters.outbound.competitions.nba.yahoo import YahooNBAProvider
from thefrontoffice.application.scouting import ScoutEngine
from thefrontoffice.domain.errors import TeamNotFoundError
from thefrontoffice.domain.models import PlayerQuery, ScoutReport, Stat


def _scout(yahoo: FakeYahoo, ai: FakeAI | None = None, nba: FakeNBA | None = None) -> ScoutEngine:
    provider = YahooNBAProvider(league=None, nba=nba or FakeNBA(), yahoo=yahoo)  # type: ignore[arg-type]
    return ScoutEngine(provider, ai=ai or FakeAI(), answers=FakeAnswers())  # type: ignore[arg-type]


def test_returns_a_validated_report_and_an_open_chat() -> None:
    ai = FakeAI()
    report, chat = _scout(FakeYahoo(), ai=ai).start_analysis("")
    assert isinstance(report, ScoutReport)
    assert report.model_dump(exclude={"headline"}) == MOCK_NBA_REPORT.model_dump(exclude={"headline"})
    assert chat is ai.chat


def test_headline_figures_come_from_the_platform_not_the_model() -> None:
    """The model is told to leave the field empty but is not trusted to.

    A hallucinated rank or add budget would sit in the header looking exactly
    as authoritative as a real one, so the engine overwrites rather than merges.
    """
    invented = MOCK_NBA_REPORT.model_copy(update={"headline": [Stat(label="Overall", value="1")]})
    report, _ = _scout(FakeYahoo(adds_used=1), ai=FakeAI(report=invented)).start_analysis("")

    labels = {stat.label: stat.value for stat in report.headline}
    assert labels["Adds used"] == "1/3"
    assert "1" not in [s.value for s in report.headline if s.label == "Overall"]


def test_an_exhausted_add_budget_is_flagged_rather_than_stated() -> None:
    """With no adds left every recommendation becomes a MONITOR, so it is the
    one figure in the header that has to pull the eye."""
    report, _ = _scout(FakeYahoo(adds_used=3), ai=FakeAI()).start_analysis("")

    left = next(stat for stat in report.headline if stat.label == "Adds left")
    assert (left.value, left.tone) == ("0", "warning")


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
    assert "LEAGUE RULES" not in briefing  # generation-time instructions
    assert "YOUR TASK" not in briefing


def test_briefing_keeps_what_a_follow_up_needs() -> None:
    ai = FakeAI()
    _scout(_rich_yahoo(), ai=ai).start_analysis("")
    briefing = ai.history[0]["parts"][0]

    assert "CURRENT MATCHUP" in briefing  # why a category is close
    assert "TRANSACTION CONTEXT" in briefing  # why only three adds
    assert "CURRENT ROSTER" in briefing  # why that drop
    assert "Roster Player 0" in briefing


def test_briefing_carries_only_the_recommended_free_agents() -> None:
    """_rich_yahoo offers nine free agents; the canned report names one."""
    ai = FakeAI()
    recommended = MOCK_NBA_REPORT.moves[0].player
    _scout(_rich_yahoo(recommended=recommended), ai=ai).start_analysis("")
    briefing = ai.history[0]["parts"][0]

    assert recommended in briefing
    assert "Free Agent 7" not in briefing
    assert "Free Agent 3" not in briefing


def test_briefing_tells_the_model_the_list_is_partial() -> None:
    """Otherwise the model invents numbers for players it cannot see."""
    ai = FakeAI()
    _scout(_rich_yahoo(), ai=ai).start_analysis("")
    assert "re-run the report" in ai.history[0]["parts"][0]


def test_matchup_is_fetched_once_not_twice() -> None:
    """The context and the dates come from one scoreboard fetch."""
    yahoo = _rich_yahoo()
    _scout(yahoo).start_analysis("")
    assert yahoo.matchup_fetches == 1


def test_missing_team_raises_before_any_ai_call() -> None:
    """A billed Gemini call for a league we do not play in is pure waste."""

    class NoTeam(FakeYahoo):
        def get_user_team(self) -> Any:
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
    ai = FakeAI()
    _scout(yahoo, ai=ai, nba=nba).start_analysis("")
    return ai.prompts[0]


def test_prompt_carries_roster_matchup_and_free_agents() -> None:
    yahoo = FakeYahoo(
        roster=[make_player("Roster One", team="LAL")],
        stat_leaders={"BLK": [make_player("Free Agent One", team="BOS", key="fa-1")]},
    )
    prompt = _prompt_for(yahoo)
    assert "Roster One" in prompt
    assert "Free Agent One" in prompt
    assert "CURRENT MATCHUP" in prompt


def test_free_agents_are_annotated_with_the_categories_they_lead() -> None:
    fa = make_player("Multi Cat", key="fa-1")
    yahoo = FakeYahoo(stat_leaders={"BLK": [fa], "REB": [fa]})
    prompt = _prompt_for(yahoo)
    assert "Top in: BLK, REB" in prompt


def test_free_agents_appearing_in_several_categories_are_listed_once_and_first() -> None:
    """Most versatile first: a two-category player outranks a one-category one."""
    multi = make_player("Multi Cat", key="multi")
    single = make_player("Single Cat", key="single")
    yahoo = FakeYahoo(stat_leaders={"BLK": [multi, single], "REB": [multi]})
    prompt = _prompt_for(yahoo)
    assert prompt.count("Multi Cat") == 1
    assert prompt.index("Multi Cat") < prompt.index("Single Cat")


def test_remaining_adds_drive_the_recommendation_instruction() -> None:
    with_adds = _prompt_for(FakeYahoo(adds_used=0))
    assert "Recommend **3 players** to add" in with_adds
    assert "Adds Used: 0/3" in with_adds


def test_exhausted_add_budget_switches_to_monitoring() -> None:
    """With no adds left the model must not recommend adds it cannot make."""
    exhausted = _prompt_for(FakeYahoo(adds_used=3))
    assert "0 adds remaining" in exhausted
    assert "MONITOR" in exhausted
    assert "Recommend **3 players** to add" not in exhausted


def test_add_budget_cannot_go_negative() -> None:
    """Yahoo can report more adds used than the configured weekly limit."""
    prompt = _prompt_for(FakeYahoo(adds_used=99))
    assert "Adds Used: 99/3" in prompt
    assert "Remaining Adds: 0" in prompt
    assert "Remaining Adds: -" not in prompt
    assert "0 adds remaining" in prompt  # and it switches to monitoring


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


def test_missing_matchup_dates_omit_the_schedule_block() -> None:
    prompt = _prompt_for(FakeYahoo(matchup_dates=("", "")))
    assert "REMAINING GAMES BY TEAM" not in prompt


def test_il_players_are_flagged_so_they_are_not_dropped_carelessly() -> None:
    yahoo = FakeYahoo(roster=[make_player("Hurt Star", selected_position="IL", status="O")])
    prompt = _prompt_for(yahoo)
    assert "[IN IL SPOT]" in prompt
    assert "[O]" in prompt


# ── multi-league selection ──────────────────────────────────────────────


def test_a_specific_league_can_be_selected() -> None:
    """A Yahoo login with several leagues must be able to scout each one."""
    from types import SimpleNamespace

    one = SimpleNamespace(id="1", name="One", league_type="head")
    two = SimpleNamespace(id="2", name="Two", league_type="head")
    provider = YahooNBAProvider(one, all_leagues=[one, two], nba=FakeNBA(), yahoo=FakeYahoo())  # type: ignore[arg-type]
    assert [r.league_id for r in provider.list_leagues()] == ["1", "2"]
    assert provider._select("2") is two
    assert provider._select("") is one


def test_selecting_an_unknown_league_raises() -> None:
    from types import SimpleNamespace

    from thefrontoffice.domain.errors import LeagueNotFoundError

    one = SimpleNamespace(id="1", name="One")
    provider = YahooNBAProvider(one, all_leagues=[one], nba=FakeNBA(), yahoo=FakeYahoo())  # type: ignore[arg-type]
    with pytest.raises(LeagueNotFoundError, match="not one of yours"):
        provider._select("999")


def test_a_roster_card_carries_the_row_and_what_a_row_cannot() -> None:
    """The columns are the table; the id and the tone are what a table needs
    and a column should not be."""
    yahoo = FakeYahoo(roster=[make_player("A B", "PF,C", "LAL", status="O", selected_position="IL")])

    card = YahooNBAProvider(league=None, nba=FakeNBA(), yahoo=yahoo).roster()[0]  # type: ignore[arg-type]

    assert card.columns["Player"] == "A B"
    assert card.columns["Slot"] == "IL"
    assert card.player_id
    assert card.tone == "warning"


def test_recent_form_is_a_dash_when_there_is_none() -> None:
    """Out of season there is no line to show, and a zero would read as a bad
    one rather than an absent one."""
    yahoo = FakeYahoo(roster=[make_player("A B")])
    card = YahooNBAProvider(league=None, nba=FakeNBA(), yahoo=yahoo).roster()[0]  # type: ignore[arg-type]

    assert card.columns["PTS"] == "—"


# ── projections ─────────────────────────────────────────────────────────


class FakeSleeperProjections:
    """Stands in for SleeperClient's NBA projection endpoints."""

    def __init__(self, rows: Any = None, error: Exception | None = None, season: str = "2026", week: int = 12):
        self.rows = rows if rows is not None else []
        self.error = error
        self.season, self.week = season, week
        self.weeks_requested: list[int] = []

    def get_state(self, sport: str = "nfl") -> Any:
        from thefrontoffice.adapters.outbound.platforms.sleeper.types import SeasonState

        return SeasonState(week=self.week, season=self.season, season_type="regular")

    def get_nba_projections(self, season: str, week: int) -> Any:
        self.weeks_requested.append(week)
        if self.error:
            raise self.error
        return self.rows if week == self.week else []


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
    from types import SimpleNamespace

    return YahooNBAProvider(
        SimpleNamespace(id="1", name="One"),  # type: ignore[arg-type]
        nba=FakeNBA(),
        yahoo=yahoo or _rich_yahoo(),  # type: ignore[arg-type]
        sleeper=sleeper,
    )


def test_projected_totals_are_attached_to_players() -> None:
    """Projected totals for the matchup period, beside recent form."""
    sleeper = FakeSleeperProjections([_game("Roster Player 0", "2026-02-10")])
    ctx = _provider_with(sleeper).build_context()
    assert "PROJ 1G" in ctx.roster_lines["Roster Player 0"]
    assert "25p" in ctx.roster_lines["Roster Player 0"]


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


def test_the_prompt_tells_the_model_projections_are_present() -> None:
    sleeper = FakeSleeperProjections([_game("Roster Player 0", "2026-02-10")])
    prompt = _provider_with(sleeper).build_context().prompt
    assert "lines marked PROJ" in prompt
    assert "Prefer them to recent form" in prompt


def test_out_of_season_falls_back_to_recent_form() -> None:
    """Sleeper publishes no NBA projections before opening night."""
    prompt = _provider_with(FakeSleeperProjections([])).build_context().prompt
    assert "PROJECTIONS: unavailable" in prompt
    assert "PROJ " not in prompt


def test_a_projection_failure_does_not_lose_the_report() -> None:
    from thefrontoffice.domain.errors import SleeperAPIError

    sleeper = FakeSleeperProjections(error=SleeperAPIError("429"))
    ctx = _provider_with(sleeper).build_context()
    assert "PROJECTIONS: unavailable" in ctx.prompt
    assert ctx.roster_lines  # everything else still built


def test_the_next_week_is_tried_when_the_current_one_is_empty() -> None:
    """A matchup period can straddle two Sleeper weeks."""
    sleeper_state_week = 12

    class Straddling(FakeSleeperProjections):
        def get_state(self, sport: str = "nfl") -> Any:
            from thefrontoffice.adapters.outbound.platforms.sleeper.types import SeasonState

            return SeasonState(week=sleeper_state_week, season="2026", season_type="regular")

    straddling = Straddling([_game("Roster Player 0", "2026-02-10")], week=13)
    ctx = _provider_with(straddling).build_context()
    assert straddling.weeks_requested == [12, 13]
    assert "PROJ 1G" in ctx.roster_lines["Roster Player 0"]


def test_unmatched_players_simply_carry_no_projection() -> None:
    sleeper = FakeSleeperProjections([_game("Someone Entirely Else", "2026-02-10")])
    ctx = _provider_with(sleeper).build_context()
    assert "PROJ" not in ctx.roster_lines["Roster Player 0"]


def test_the_prompt_explains_team_games_versus_player_games() -> None:
    """[3G left] beside PROJ 1G is a warning about missed games, not a
    contradiction — and the model has to be told which is which."""
    sleeper = FakeSleeperProjections([_game("Roster Player 0", "2026-02-10")])
    prompt = _provider_with(sleeper).build_context().prompt
    assert "how many games the player's TEAM has left" in prompt
    assert "expected to miss games" in prompt


# ── the league table ────────────────────────────────────────────────────


def _provider(yahoo: FakeYahoo) -> YahooNBAProvider:
    return YahooNBAProvider(league=None, nba=FakeNBA(), yahoo=yahoo)  # type: ignore[arg-type]


def test_the_table_comes_back_in_rank_order_and_says_which_is_yours() -> None:
    standings = _provider(FakeYahoo()).schedule("").standings

    assert [row.name for row in standings] == ["Their Team", "My Team"]
    assert [row.is_mine for row in standings] == [False, True]


def test_a_record_includes_ties_only_where_there_are_any() -> None:
    standings = _provider(FakeYahoo()).schedule("").standings

    assert standings[0].record == "5-1"
    assert standings[1].record == "4-2-1"


def test_a_team_with_no_standings_block_is_skipped_rather_than_failing() -> None:
    """yahoofantasy sets these by setattr, so a missing block is a shape
    question rather than an error."""
    from types import SimpleNamespace

    yahoo = FakeYahoo(teams=[SimpleNamespace(name="Half-loaded", team_key="t.9")])

    assert _provider(yahoo).schedule("").standings == []


def test_the_sections_yahoo_cannot_answer_are_empty_rather_than_invented() -> None:
    """A category league has no fixture list, and there is no transaction feed."""
    schedule = _provider(FakeYahoo()).schedule("")

    assert schedule.season == []
    assert schedule.matches == []
    assert schedule.activity == []


def test_the_teams_list_puts_you_first() -> None:
    teams = _provider(FakeYahoo()).teams("")

    assert teams[0].is_mine
    assert teams[0].name == "My Team"


def test_another_managers_roster_comes_back_in_your_own_columns() -> None:
    yahoo = FakeYahoo()

    mine = _provider(yahoo).roster("")
    theirs = _provider(yahoo).roster_of("", "t.2")

    assert set(theirs[0].columns) == set(mine[0].columns)


def test_an_unknown_team_is_refused() -> None:
    with pytest.raises(TeamNotFoundError):
        _provider(FakeYahoo()).roster_of("", "t.99")


def test_available_players_have_no_lineup_column() -> None:
    """Somebody on the wire is not in a lineup of yours."""
    assert "Slot" not in _provider(FakeYahoo()).free_agents("", PlayerQuery()).players[0].columns


def test_available_players_carry_the_same_form_columns_as_a_roster() -> None:
    agents = _provider(FakeYahoo()).free_agents("", PlayerQuery()).players

    assert {"Player", "Pos", "Team", "PTS", "REB", "AST", "Status"} <= set(agents[0].columns)


def test_a_team_link_is_built_from_the_two_numbers_in_its_key() -> None:
    """A team key is `nba.l.<league>.t.<team>` and the URL wants the numbers."""
    teams = {
        t.name: t.url
        for t in _provider(FakeYahoo(teams=[_yahoo_team("Theirs", "nba.l.123.t.4", rank=1, wins=1, losses=0)])).teams(
            ""
        )
    }

    assert teams["Theirs"] == "https://basketball.fantasysports.yahoo.com/nba/123/4"


def test_a_key_in_an_unexpected_shape_yields_no_link_rather_than_a_broken_one() -> None:
    teams = _provider(FakeYahoo(teams=[_yahoo_team("Odd", "something-else", rank=1, wins=1, losses=0)])).teams("")

    assert teams == [] or teams[0].url == ""
