"""Tests for simulating the rest of a season: `application/season.py`.

Seasons here are built by hand, so each test can say what the simulation
must conclude — a team already through, one already out, a tiebreak —
without any sport's data.
"""

from thefrontoffice.application.season import (
    MarketEngine,
    SeasonEngine,
    attach_season,
    attach_table,
    chance_now,
    simulate_season,
)
from thefrontoffice.domain.models import (
    Fixture,
    Forecast,
    LeagueSchedule,
    MarginRange,
    PlayoffOdds,
    SeasonInput,
    StandingRow,
    Summary,
    TeamOdds,
    TeamRecord,
    TeamWeek,
    TradeMarket,
    TradeOption,
)

FEW = 2_000


def _team(team_id: str, wins: int, losses: int = 0, points: float = 0.0) -> TeamRecord:
    return TeamRecord(team_id=team_id, name=team_id.upper(), wins=wins, losses=losses, ties=0, points_for=points)


def _season(
    teams: list[TeamRecord],
    fixtures: list[Fixture],
    means: dict[str, float],
    *,
    spots: int = 1,
    spread: float = 20.0,
    strength_error: float = 0.0,
    mine: str = "a",
) -> SeasonInput:
    weeks = {f.week for f in fixtures}
    return SeasonInput(
        teams=tuple(teams),
        fixtures=tuple(fixtures),
        scoring=tuple(TeamWeek(team, week, mean, spread) for team, mean in means.items() for week in weeks),
        spots=spots,
        mine=mine,
        week=min(weeks, default=1),
        strength_error=strength_error,
        seed=3,
    )


def _odds(season: SeasonInput) -> dict[str, float]:
    return {t.team_id: t.playoffs for t in simulate_season(season, FEW).teams}


def test_a_lead_nobody_can_catch_is_a_certain_place() -> None:
    season = _season(
        [_team("a", 9), _team("b", 2), _team("c", 1)],
        [Fixture(10, "a", "b"), Fixture(11, "b", "c")],
        {"a": 100, "b": 100, "c": 100},
    )

    odds = _odds(season)

    assert odds["a"] == 1.0 and odds["b"] == odds["c"] == 0.0


def test_level_records_are_settled_by_points_for() -> None:
    """Neither team plays again, so only the tiebreak separates them."""
    season = _season([_team("a", 5, points=700), _team("b", 5, points=650)], [], {})

    assert _odds(season) == {"a": 1.0, "b": 0.0}


def test_every_place_is_given_out_every_season() -> None:
    teams = [_team(t, 3) for t in "abcd"]
    season = _season(teams, [Fixture(8, "a", "b"), Fixture(8, "c", "d")], dict.fromkeys("abcd", 100.0), spots=2)

    assert sum(_odds(season).values()) == 2.0


def test_winning_this_week_is_worth_more_than_losing_it() -> None:
    season = _season(
        [_team("a", 4), _team("b", 4)],
        [Fixture(8, "a", "b"), Fixture(9, "a", "b")],
        {"a": 100, "b": 100},
    )

    odds = simulate_season(season, FEW)

    assert odds.with_win is not None and odds.with_loss is not None
    assert odds.with_win > odds.playoffs > odds.with_loss


def test_a_week_off_has_no_result_to_split_on() -> None:
    season = _season([_team("a", 4), _team("b", 4), _team("c", 4)], [Fixture(8, "b", "c")], dict.fromkeys("abc", 100.0))

    odds = simulate_season(season, FEW)

    assert odds.with_win is None and odds.with_loss is None


def test_doubt_about_how_good_teams_are_pulls_the_favourite_back() -> None:
    teams, fixtures = [_team("a", 3), _team("b", 3)], [Fixture(w, "a", "b") for w in range(8, 12)]
    means = {"a": 115.0, "b": 100.0}

    sure = _odds(_season(teams, fixtures, means))["a"]
    unsure = _odds(_season(teams, fixtures, means, strength_error=30.0))["a"]

    assert 0.5 < unsure < sure


def test_the_same_season_gives_the_same_answer_every_time() -> None:
    season = _season([_team("a", 4), _team("b", 4)], [Fixture(8, "a", "b")], {"a": 100, "b": 100})

    assert simulate_season(season, FEW) == simulate_season(season, FEW)


# ── onto the page ───────────────────────────────────────────────────────


def _odds_split(win: float, loss: float) -> PlayoffOdds:
    return PlayoffOdds(spots=6, playoffs=0.5, with_win=win, with_loss=loss, simulations=1)


def test_this_week_is_weighed_by_the_weeks_own_forecast() -> None:
    assert chance_now(_odds_split(0.9, 0.5), win=0.75) == 0.8


def test_without_a_forecast_the_season_simulation_stands() -> None:
    assert chance_now(_odds_split(0.9, 0.5), win=None) == 0.5


def test_the_week_header_carries_the_playoff_chance_and_what_this_week_is_worth() -> None:
    forecast = Forecast(win=0.5, margin=MarginRange(low=-1, median=0, high=1), simulations=1)

    summary = attach_season(Summary(forecast=forecast), _odds_split(0.9, 0.5))

    [stat] = summary.headline
    assert stat.label == "Playoffs"
    assert all(figure in stat.value for figure in ("70%", "90%", "50%"))


def test_the_table_carries_each_teams_chance_on_its_row() -> None:
    schedule = LeagueSchedule(
        standings=[StandingRow(rank=1, name="A", team_id="a"), StandingRow(rank=2, name="Z", team_id="z")]
    )
    odds = PlayoffOdds(spots=1, teams=[TeamOdds(team_id="a", name="A", playoffs=0.61)], playoffs=0.61, simulations=1)

    attached = attach_table(schedule, odds)
    a, z = attached.standings

    assert (a.playoffs, z.playoffs) == ("61%", "")
    assert {s.label: s.value for s in attached.headline}["Playoffs"] == "61%"


class _Over:
    label = "Test"

    def season_input(self, league_id: str) -> SeasonInput | None:
        return None

    def trade_market(self, league_id: str) -> TradeMarket | None:
        return None


def test_a_season_with_nothing_left_to_play_for_has_no_odds() -> None:
    assert SeasonEngine(_Over()).odds("L1") is None


# ── pricing trades ──────────────────────────────────────────────────────

# Two places for three teams level on record: who gets them is the season left.
RACE = _season(
    [_team("a", 5), _team("b", 5), _team("c", 5)],
    [Fixture(10, "a", "b"), Fixture(11, "a", "c"), Fixture(11, "b", "c"), Fixture(12, "b", "c")],
    {"a": 100, "b": 100, "c": 100},
    spots=1,
)

RACE_ODDS = simulate_season(RACE).playoffs


def _trade(team: str, mine: float, theirs: float, name: str = "X") -> TradeOption:
    """A trade with `team` that moves your mean to `mine` and theirs to `theirs` in every week."""
    weeks = {f.week for f in RACE.fixtures}
    return TradeOption(
        team_id=team,
        giving=(name,),
        receiving=("Y",),
        points=mine - 100,
        their_points=theirs - 100,
        scoring=tuple(TeamWeek(t, w, mean, 20.0) for t, mean in (("a", mine), (team, theirs)) for w in weeks),
    )


class _Market:
    label = "Test"

    def __init__(self, *options: TradeOption) -> None:
        self.options = options

    def season_input(self, league_id: str) -> SeasonInput | None:
        return RACE

    def trade_market(self, league_id: str) -> TradeMarket | None:
        return TradeMarket(season=RACE, options=self.options)


def test_a_trade_that_makes_you_stronger_raises_your_playoff_chance() -> None:
    [idea] = MarketEngine(_Market(_trade("b", mine=115, theirs=101))).trades("L1")

    assert idea.playoffs_change > 0
    assert idea.playoffs == RACE_ODDS + idea.playoffs_change
    assert (idea.team, idea.points, idea.their_points) == ("B", 15, 1)


def test_a_trade_that_changes_nothing_is_not_offered() -> None:
    assert MarketEngine(_Market(_trade("b", mine=100, theirs=100))).trades("L1") == []


def test_trades_are_ranked_on_the_playoff_chance_not_on_points() -> None:
    """More points for you can be worth less, when the trade makes a team you are racing as strong as it makes you."""
    rival = _trade("b", mine=110, theirs=110, name="to the rival")
    other = _trade("c", mine=108, theirs=100, name="elsewhere")

    ideas = MarketEngine(_Market(rival, other)).trades("L1")

    assert [i.giving for i in ideas][0] == ["elsewhere"]


def test_what_a_trade_hands_the_other_side_is_counted() -> None:
    [idea] = MarketEngine(_Market(_trade("b", mine=115, theirs=110))).trades("L1")

    assert idea.their_playoffs_change > 0


def test_no_market_is_no_trades() -> None:
    assert MarketEngine(_Over()).trades("L1") == []


def test_the_seasons_header_weighs_this_week_as_the_weeks_header_does() -> None:
    """One chance shown two ways on two pages reads as a bug in one of them."""
    odds = PlayoffOdds(spots=1, teams=[], playoffs=0.88, with_win=0.96, with_loss=0.79, simulations=1)

    headline = attach_table(LeagueSchedule(), odds, win=0.01).headline

    assert {s.label: s.value for s in headline}["Playoffs"] == f"{chance_now(odds, 0.01):.0%}"
