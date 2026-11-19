"""Tests for simulating the rest of a season: `application/season.py`.

Seasons here are built by hand, so each test can say what the simulation
must conclude — a team already through, one already out, a tiebreak —
without any sport's data.
"""

from dataclasses import replace
from datetime import date

from support.simulation import FEW, odds_split

from thefrontoffice.application.season import (
    MarketEngine,
    SeasonEngine,
    chance_now,
    simulate_season,
)
from thefrontoffice.domain.models import (
    Fixture,
    SeasonInput,
    Stat,
    TeamRecord,
    TeamWeek,
    TradeMarket,
    TradeOption,
)


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


# ── this week, weighed in ───────────────────────────────────────────────────────


def test_this_week_is_weighed_by_the_weeks_own_forecast() -> None:
    assert chance_now(odds_split(0.9, 0.5), win=0.75) == 0.8


def test_without_a_forecast_the_season_simulation_stands() -> None:
    assert chance_now(odds_split(0.9, 0.5), win=None) == 0.5


# ── weeks won on categories ─────────────────────────────────────────────────────


def test_a_week_won_on_categories_goes_to_whoever_its_chances_favour() -> None:
    """No score is drawn for it: a certain week is a certain win, and points for stay as they were."""
    season = _season([_team("a", 4), _team("b", 4)], [Fixture(8, "a", "b", chances=(1.0, 0.0))], {})

    assert _odds(season) == {"a": 1.0, "b": 0.0}


def test_a_week_level_on_categories_is_a_draw_for_both() -> None:
    """Neither side can win it, so the half each takes leaves them level and the tiebreak decides."""
    season = _season(
        [_team("a", 4, points=10), _team("b", 4, points=20)], [Fixture(8, "a", "b", chances=(0.0, 0.0))], {}
    )

    assert _odds(season) == {"a": 0.0, "b": 1.0}


def test_an_even_category_week_splits_the_place_evenly() -> None:
    season = _season([_team("a", 4), _team("b", 4)], [Fixture(8, "a", "b", chances=(0.5, 0.5))], {})

    odds = simulate_season(season, FEW)

    assert 0.4 < odds.playoffs < 0.6
    assert odds.with_win == 1.0 and odds.with_loss == 0.0


class _Over:
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


def _trade(
    team: str,
    mine: float,
    theirs: float,
    name: str = "X",
    *,
    season: SeasonInput = RACE,
    playoff: float | None = None,
    get: str = "Y",
) -> TradeOption:
    """A trade with `team` that moves your mean to `mine` and theirs to `theirs` in every week."""
    weeks = {f.week for f in season.fixtures}
    return TradeOption(
        team_id=team,
        giving=(name,),
        receiving=(get,),
        points=mine - 100,
        their_points=theirs - 100,
        scoring=tuple(TeamWeek(t, w, mean, 20.0) for t, mean in (("a", mine), (team, theirs)) for w in weeks),
        playoff_points=playoff,
    )


class _Market:
    def __init__(self, *options: TradeOption, season: SeasonInput = RACE, regular_weeks: int = 3) -> None:
        self.options = options
        self.season = season
        self.regular_weeks = regular_weeks

    def season_input(self, league_id: str) -> SeasonInput | None:
        return self.season

    def trade_market(self, league_id: str) -> TradeMarket | None:
        return TradeMarket(season=self.season, options=self.options, regular_weeks=self.regular_weeks, playoff_weeks=3)


def test_a_trade_that_makes_you_stronger_raises_your_playoff_chance() -> None:
    [idea] = MarketEngine(_Market(_trade("b", mine=115, theirs=101))).trades("L1").ideas

    assert idea.playoffs_change > 0


def test_a_trade_that_changes_nothing_is_not_offered() -> None:
    assert MarketEngine(_Market(_trade("b", mine=100, theirs=100))).trades("L1").ideas == []


def test_trades_are_ranked_on_the_playoff_chance_not_on_points() -> None:
    """More points for you can be worth less, when the trade makes a team you are racing as strong as it makes you."""
    rival = _trade("b", mine=110, theirs=110, name="to the rival")
    other = _trade("c", mine=108, theirs=101, name="elsewhere")

    ideas = MarketEngine(_Market(rival, other)).trades("L1").ideas

    assert [i.giving for i in ideas][0] == ["elsewhere"]


def test_what_a_trade_hands_the_other_side_is_counted() -> None:
    [idea] = MarketEngine(_Market(_trade("b", mine=115, theirs=110))).trades("L1").ideas

    assert idea.their_playoffs_change > 0


def test_no_market_is_no_trades() -> None:
    assert MarketEngine(_Over()).trades("L1").ideas == []


# Two of the three can still reach the one place; "d" has lost every game and cannot.
OUT = _season(
    [_team("a", 5), _team("b", 5), _team("d", 0, losses=10)],
    [Fixture(10, "a", "b"), Fixture(11, "a", "d"), Fixture(11, "b", "d")],
    {"a": 100, "b": 100, "d": 100},
    spots=1,
)


def test_a_trade_that_does_nothing_for_a_contenders_lineup_is_not_offered() -> None:
    """A manager still chasing a place wants his starters better for it."""
    assert MarketEngine(_Market(_trade("b", mine=115, theirs=100), season=OUT)).trades("L1").ideas == []


def test_a_team_out_of_the_race_is_offered_a_trade_on_worth_alone() -> None:
    """With no place left to chase, his lineup is nothing to him; what he gets back is."""
    [idea] = MarketEngine(_Market(_trade("d", mine=115, theirs=100), season=OUT)).trades("L1").ideas

    assert idea.team == "D" and idea.their_playoffs < 0.05


# You have nine wins to everyone else's two: the place is yours whatever you do.
SAFE_SEASON = _season(
    [_team("a", 9), _team("b", 2), _team("c", 2)],
    [Fixture(10, "a", "b"), Fixture(11, "a", "c")],
    {"a": 100, "b": 100, "c": 100},
    spots=1,
)


def test_a_safe_team_is_offered_the_most_points_over_the_rest_of_the_season() -> None:
    """Regular-season weeks still count once the place is safe: the seed and a bye ride on them.

    A trade worth +7 in each of three regular weeks and -0.25 in each of three
    playoff weeks beats one worth -2 now and +4 in December.
    """
    now = _trade("b", mine=107, theirs=101, name="for now", season=SAFE_SEASON, playoff=-0.25, get="now")
    later = _trade("c", mine=98, theirs=101, name="for December", season=SAFE_SEASON, playoff=4.0, get="later")

    trades = MarketEngine(_Market(now, later, season=SAFE_SEASON)).trades("L1")

    assert [i.giving for i in trades.ideas] == [["for now"], ["for December"]]
    assert [round(i.total, 1) for i in trades.ideas] == [20.2, 6.0]
    # The list says which figure it is ordered by, so the page can mark that column.
    assert trades.ranked_by == "total"


def test_a_playoff_week_counts_at_the_chance_of_playing_in_it() -> None:
    # Safe, at about 85%, but with a place still to lose.
    season = _season(
        [_team("a", 7), _team("b", 5), _team("c", 2)],
        [
            Fixture(10, "a", "b"),
            Fixture(11, "a", "c"),
            Fixture(11, "b", "c"),
            Fixture(12, "b", "c"),
            Fixture(12, "a", "c"),
        ],
        {"a": 100, "b": 100, "c": 100},
    )
    option = _trade("c", mine=101, theirs=101, season=season, playoff=10.0)

    [idea] = MarketEngine(_Market(option, season=season, regular_weeks=2)).trades("L1").ideas

    assert 0.8 < idea.playoffs < 1
    assert idea.total == 1 * 2 + idea.playoffs * 10.0 * 3


def test_a_trade_that_loses_points_before_the_playoffs_and_in_them_is_not_offered() -> None:
    """Even where weakening a rival raises your playoff chance."""
    option = replace(_trade("b", mine=99, theirs=70, playoff=-1.0), their_points=1.0)

    assert MarketEngine(_Market(option)).trades("L1").ideas == []


def test_a_safe_team_without_playoff_projections_is_ranked_on_the_regular_season() -> None:
    # Safe, at about 85%, but with a place still to lose.
    season = _season(
        [_team("a", 7), _team("b", 5), _team("c", 2)],
        [
            Fixture(10, "a", "b"),
            Fixture(11, "a", "c"),
            Fixture(11, "b", "c"),
            Fixture(12, "b", "c"),
            Fixture(12, "a", "c"),
        ],
        {"a": 100, "b": 100, "c": 100},
    )

    trades = MarketEngine(_Market(_trade("c", mine=115, theirs=101, season=season), season=season)).trades("L1")

    assert trades.ideas and trades.ranked_by == "total"


def test_a_team_on_the_bubble_is_offered_its_playoff_chance_before_its_december() -> None:
    """A better December lineup is no use to a team that does not get there."""
    december = _trade("b", mine=100, theirs=101, name="for December", playoff=20.0, get="later")
    now = _trade("c", mine=110, theirs=101, name="for now", playoff=1.0, get="now")

    trades = MarketEngine(_Market(december, now)).trades("L1")

    assert [i.giving for i in trades.ideas] == [["for now"], ["for December"]]
    assert trades.ranked_by == "playoffs_change"


def test_two_offers_for_the_same_player_are_one_idea() -> None:
    """Who goes with him is a detail; the second crowds a different trade off the list."""
    first = _trade("b", mine=115, theirs=101, name="one")
    second = _trade("b", mine=114, theirs=101, name="other")

    ideas = MarketEngine(_Market(first, second)).trades("L1").ideas

    assert [i.giving for i in ideas] == [["one"]]


def test_a_trade_names_the_free_agent_for_the_spot_it_frees() -> None:
    option = replace(_trade("b", mine=115, theirs=101), pickup="Wire RB (RB)")

    [idea] = MarketEngine(_Market(option)).trades("L1").ideas

    assert idea.pickup == "Wire RB (RB)"


def test_a_trade_carries_why_its_players_are_priced_off_their_projections() -> None:
    line = Stat(label="Lead Back", value="priced 16.0 a week, projected 12.4: snaps 32→77% in week 9")
    option = replace(_trade("b", mine=115, theirs=101), form=(line,))

    [idea] = MarketEngine(_Market(option)).trades("L1").ideas

    assert idea.form == [line]


def test_a_pickup_most_trades_share_is_said_once_for_the_list() -> None:
    """Freeing a spot for the same free agent is one fact about the wire, not one per trade."""
    shared = [replace(_trade(t, mine=115, theirs=101, get=t), pickup="Wire TE (TE)") for t in ("b", "c")]

    trades = MarketEngine(_Market(*shared)).trades("L1")

    assert trades.pickup == "Wire TE (TE)"
    assert [i.pickup for i in trades.ideas] == ["", ""]


def test_a_pickup_on_one_trade_alone_stays_on_it() -> None:
    first = replace(_trade("b", mine=115, theirs=101, get="b"), pickup="Wire TE (TE)")
    second = replace(_trade("c", mine=114, theirs=101, get="c"), pickup="Wire RB (RB)")

    trades = MarketEngine(_Market(first, second)).trades("L1")

    assert trades.pickup == ""
    assert sorted(i.pickup for i in trades.ideas) == ["Wire RB (RB)", "Wire TE (TE)"]


def test_a_players_pricing_is_said_on_the_first_trade_he_is_in() -> None:
    line = Stat(label="Lead Back", value="priced 16.0 a week, projected 12.4: snaps 32→77% in week 9")
    other = Stat(label="Slot WR", value="priced 9.0 a week, projected 11.0: targets down")
    first = replace(_trade("b", mine=115, theirs=101, get="b"), form=(line,))
    second = replace(_trade("c", mine=114, theirs=101, get="c"), form=(line, other))

    ideas = MarketEngine(_Market(first, second)).trades("L1").ideas

    assert [i.form for i in ideas] == [[line], [other]]


# ── a market on another scale ───────────────────────────────────────────────────


def _category_trade(team: str, mine: float, *, their_gain: float = 0.3, total: float = 1.0) -> TradeOption:
    """A trade with `team` that gives you `mine` of each remaining week against it, counted in categories."""
    weeks = sorted({f.week for f in CATEGORY_RACE.fixtures})
    return TradeOption(
        team_id=team,
        giving=("X",),
        receiving=("Y",),
        points=total / len(weeks),
        their_points=their_gain,
        scoring=(),
        fixtures=tuple(Fixture(w, "a", team, chances=(mine, 1 - mine)) for w in weeks),
    )


CATEGORY_RACE = _season(
    [_team("a", 5), _team("b", 5)],
    [Fixture(w, "a", "b", chances=(0.5, 0.5)) for w in (10, 11, 12)],
    {},
)


class _CategoryMarket:
    def __init__(self, *options: TradeOption, their_least: float = 0.1, total_least: float = 0.5) -> None:
        self.options = options
        self.their_least, self.total_least = their_least, total_least

    def trade_market(self, league_id: str) -> TradeMarket | None:
        return TradeMarket(
            season=CATEGORY_RACE,
            options=self.options,
            regular_weeks=3,
            playoff_weeks=0,
            measure="categories",
            deadline=date(2027, 2, 25),
            least_their_gain=self.their_least,
            least_total_gain=self.total_least,
        )


def test_a_trade_won_on_categories_is_played_out_on_its_own_chances() -> None:
    """The trade's fixtures replace the season's: certain weeks against the partner make a certain place."""
    trades = MarketEngine(_CategoryMarket(_category_trade("b", mine=1.0))).trades("L1")

    assert [round(i.playoffs, 2) for i in trades.ideas] == [1.0]


def test_a_market_says_what_its_figures_count_and_when_trading_ends() -> None:
    trades = MarketEngine(_CategoryMarket(_category_trade("b", mine=1.0))).trades("L1")

    assert (trades.measure, trades.deadline) == ("categories", date(2027, 2, 25))


def test_a_market_on_its_own_scale_sets_what_the_other_side_must_gain() -> None:
    """A tenth of a category a week is reason enough in categories, though short of football's half-point."""
    market = _CategoryMarket(_category_trade("b", mine=1.0, their_gain=0.2), their_least=0.1)
    stingy = _CategoryMarket(_category_trade("b", mine=1.0, their_gain=0.2), their_least=0.5)

    assert len(MarketEngine(market).trades("L1").ideas) == 1
    assert MarketEngine(stingy).trades("L1").ideas == []
