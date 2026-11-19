"""Tests for simulating a matchup: `application/forecasting.py`.

Players here are built by hand, so each test can say exactly what the
simulation should conclude — a sure thing, a coin flip, a move that cannot
hurt — without depending on any sport's data.
"""

from collections.abc import Mapping, Sequence

import pytest
from support.simulation import FEW, FakeForecast, outcome

from thefrontoffice.application.forecasting import (
    REMEMBERED,
    WORTH_A_ROW,
    ForecastEngine,
    calibrate,
    categories,
    pickup_chances,
    ranked,
    simulate,
)
from thefrontoffice.domain.models import (
    Action,
    CategoryMatchup,
    LineupMove,
    MatchupInput,
    Outcomes,
    PlayedMatchup,
    ScoredCategory,
    StatLines,
)


def _match(mine: list[Outcomes], theirs: list[Outcomes], *moves: LineupMove, seed: int = 7) -> MatchupInput:
    return MatchupInput(mine=tuple(mine), theirs=tuple(theirs), moves=moves, seed=seed)


# ── the chance of winning ───────────────────────────────────────────────


def test_a_lineup_that_always_outscores_always_wins() -> None:
    forecast = simulate(_match([outcome("a", 20, 25)], [outcome("b", 5, 10)]), FEW)

    assert forecast.win == 1.0
    assert forecast.margin.low > 0


def test_two_identical_sides_are_a_coin_flip() -> None:
    forecast = simulate(_match([outcome("a", 0, 10, 20, 30)], [outcome("b", 0, 10, 20, 30)]), FEW)

    assert forecast.win == pytest.approx(0.5, abs=0.05)


def test_a_tie_counts_half() -> None:
    assert simulate(_match([outcome("a", 10)], [outcome("b", 10)]), FEW).win == 0.5


def test_a_player_who_will_not_play_adds_nothing() -> None:
    forecast = simulate(_match([outcome("a", 30, plays=0.0)], [outcome("b", 1)]), FEW)

    assert forecast.win == 0.0


def test_a_game_already_over_counts_what_it_scored_and_nothing_more() -> None:
    finished = outcome("a", 100, floor=12.0, remaining=0.0)

    forecast = simulate(_match([finished], [outcome("b", 11)]), FEW)

    assert forecast.win == 1.0 and forecast.margin.median == 1.0


def test_a_week_of_several_games_sums_every_one_of_them() -> None:
    three = Outcomes("a", "A", 30.0, (10.0,), games=3, floor=5.0)

    forecast = simulate(_match([three], [outcome("b", 34)]), FEW)

    assert forecast.win == 1.0 and forecast.margin.median == 1.0


def test_a_player_with_no_games_left_adds_only_what_is_on_the_board() -> None:
    idle = Outcomes("a", "A", 0.0, (50.0,), games=0, floor=20.0)

    assert simulate(_match([idle], [outcome("b", 21)]), FEW).win == 0.0


def test_the_weeks_of_a_player_with_several_games_spread_wider_than_one_game_and_never_go_below_nothing() -> None:
    def spread(games: int) -> float:
        margin = simulate(
            _match([Outcomes("a", "A", 0.0, (0.0, 20.0), games=games, projection_error=0.2)], []), FEW
        ).margin
        return margin.high - margin.low

    assert spread(4) > spread(1)
    assert (
        simulate(_match([Outcomes("a", "A", 0.0, (0.0, 20.0), games=4, projection_error=0.9)], []), FEW).margin.low >= 0
    )


def test_a_player_who_may_sit_out_the_whole_week_adds_nothing_when_he_does() -> None:
    doubtful = Outcomes("a", "A", 30.0, (10.0,), games=3, plays=0.5)

    forecast = simulate(_match([doubtful], [outcome("b", 1)]), FEW)

    assert forecast.win == pytest.approx(0.5, abs=0.05)
    assert forecast.margin.low == -1.0 and forecast.margin.high == 29.0


def test_the_same_matchup_gives_the_same_answer_every_time() -> None:
    """A win chance that flickered between reloads would read as news."""
    matchup = _match([outcome("a", 0, 10, 20, 30)], [outcome("b", 5, 15, 25)])

    assert simulate(matchup, FEW) == simulate(matchup, FEW)


# ── what each move does ─────────────────────────────────────────────────


def test_a_move_that_is_better_in_every_way_never_lowers_the_chance() -> None:
    """Same draws with and without it: the difference is the decision, not noise."""
    worse, better = outcome("w", 0, 5, 10), outcome("x", 20, 25, 30)
    move = LineupMove(key="x>w", title="Start X over W", out=("w",), into=(better,))

    forecast = simulate(_match([worse, outcome("m", 0, 30)], [outcome("t", 10, 20, 30)], move), FEW)

    assert forecast.moves["x>w"] >= forecast.win
    assert forecast.best_move == "x>w"


def test_pricing_a_move_does_not_change_the_chance_without_it() -> None:
    base = _match([outcome("a", 0, 10, 20)], [outcome("b", 5, 15)])
    move = LineupMove(key="c>a", title="Start C", out=("a",), into=(outcome("c", 0, 40),))

    assert simulate(base, FEW).win == simulate(_match(list(base.mine), list(base.theirs), move), FEW).win


def test_no_move_is_called_best_unless_it_helps() -> None:
    move = LineupMove(key="z>a", title="Start Z", out=("a",), into=(outcome("z", 0),))

    assert simulate(_match([outcome("a", 10, 20)], [outcome("b", 5, 25)], move), FEW).best_move == ""


# ── the to-do list, by the chance of winning ───────────────────────────────────────────────────────


SWAP = Action(
    kind="lineup", urgency="soon", title="Start X over W", reason="+3", key="swap:x:w", player_id="x", replaces="w"
)
DEADLINE = Action(kind="trade", urgency="later", title="Trade by week 11", reason="deadline", key="deadline:11")


def _attached(*actions: Action, moves: tuple[LineupMove, ...] = ()) -> list[Action]:
    matchup = _match([outcome("w", 0, 5, 10), outcome("m", 0, 30)], [outcome("t", 10, 20, 30)], *moves)
    return ranked(list(actions), simulate(matchup, FEW), matchup) or []


def test_a_to_do_move_carries_what_it_does_to_the_chance() -> None:
    move = LineupMove(key="x>w", title="Start X over W", out=("w",), into=(outcome("x", 20, 25, 30),))

    [swap] = _attached(SWAP, moves=(move,))

    assert swap.win_change is not None and swap.win_change > 0


def test_an_item_that_moves_nobody_has_no_change_to_show() -> None:
    [deadline] = _attached(DEADLINE)

    assert deadline.win_change is None


def test_a_better_move_the_list_lacks_becomes_a_row_of_its_own() -> None:
    move = LineupMove(key="x>w", title="Start X over W", out=("w",), into=(outcome("x", 20, 25, 30),))

    actions = _attached(DEADLINE, moves=(move,))

    added = [a for a in actions if a.key.startswith("odds:")]
    assert len(added) == 1 and (added[0].player_id, added[0].replaces) == ("x", "w")
    assert added[0].win_change is not None and added[0].win_change >= WORTH_A_ROW


def test_a_move_already_on_the_list_is_not_added_twice() -> None:
    move = LineupMove(key="x>w", title="Start X over W", out=("w",), into=(outcome("x", 20, 25, 30),))

    actions = _attached(SWAP, moves=(move,))

    assert [a.key for a in actions] == [SWAP.key]


def test_rows_keep_their_urgency_and_sort_within_it_by_what_they_add() -> None:
    small = LineupMove(key="y>w", title="Start Y over W", out=("w",), into=(outcome("y", 6, 8, 12),))
    big = LineupMove(key="x>w", title="Start X over W", out=("w",), into=(outcome("x", 20, 25, 30),))
    lesser = SWAP.model_copy(update={"key": "swap:y:w", "player_id": "y"})

    actions = _attached(DEADLINE, lesser, SWAP, moves=(small, big))

    assert [a.key for a in actions] == [SWAP.key, lesser.key, DEADLINE.key]


# A swap the lineup already makes: X is in, W was benched for him. Written as its undoing.
MADE = LineupMove(key="x<w", title="Start W over X", out=("x",), into=(outcome("w", 0, 5, 10),), made=True)


def _made_matchup(*moves: LineupMove) -> MatchupInput:
    """Yours already starts X, in W's place."""
    return _match([outcome("x", 20, 25, 30), outcome("m", 0, 30)], [outcome("t", 10, 20, 30)], *moves)


def test_a_swap_already_made_carries_what_undoing_it_would_cost() -> None:
    matchup = _made_matchup(MADE)
    forecast = simulate(matchup, FEW)

    [swap] = ranked([SWAP], forecast, matchup) or []

    assert swap.win_change == forecast.win - forecast.moves[MADE.key]
    assert swap.win_change is not None and swap.win_change > 0


def test_undoing_a_swap_already_made_is_never_the_move_to_suggest() -> None:
    """Even where the range likes the benched player more: the lineup chose on more than the range."""
    better_undone = LineupMove(key="x<w", title="Start W over X", out=("x",), into=(outcome("w", 50, 60),), made=True)
    matchup = _made_matchup(better_undone)

    forecast = simulate(matchup, FEW)

    assert forecast.moves[better_undone.key] > forecast.win
    assert forecast.best_move == ""
    assert ranked([DEADLINE], forecast, matchup) == [DEADLINE]


def test_a_swap_already_made_is_no_pickup_chance() -> None:
    matchup = _made_matchup(MADE)

    assert pickup_chances(simulate(matchup, FEW), matchup) == []


def test_a_competition_without_a_to_do_list_still_has_none() -> None:
    matchup = _match([outcome("a", 10)], [outcome("b", 5)])

    assert ranked(None, simulate(matchup, FEW), matchup) is None


# ── how well it predicts ────────────────────────────────────────────────


def _played(mine: float, theirs: float, ours: float, others: float) -> PlayedMatchup:
    return PlayedMatchup(week=2, matchup=_match([outcome("a", ours)], [outcome("b", others)]), mine=mine, theirs=theirs)


class _Season(FakeForecast):
    """Two weeks played, each one sure call that came true, ranged under whatever settings it is handed."""

    weeks = (2, 3)

    def __init__(self) -> None:
        super().__init__()
        self.ranged_under: list[Mapping[str, float] | None] = []

    def played_matchups(
        self, league_id: str, week: int, settings: Mapping[str, float] | None = None
    ) -> list[PlayedMatchup]:
        self.ranged_under.append(settings)
        return [_played(30, 10, 25, 5)]


def test_a_backtest_scores_every_matchup_of_the_weeks_given_under_the_settings_given() -> None:
    """The range search re-runs it per candidate, so a candidate's settings must reach every week."""
    season = _Season()

    calibration = ForecastEngine(season).backtest("L1", [2, 3], {"spread": 2.0}, simulations=FEW)

    assert (calibration.matchups, calibration.brier) == (2, 0.0)
    assert season.ranged_under == [{"spread": 2.0}, {"spread": 2.0}]


def test_certain_calls_that_came_true_score_perfectly() -> None:
    calibration = calibrate([_played(30, 10, 25, 5), _played(5, 20, 5, 25)], FEW)

    assert (calibration.matchups, calibration.brier) == (2, 0.0)


def test_a_coin_flip_scores_a_quarter() -> None:
    calibration = calibrate([_played(30, 10, 10, 10), _played(10, 30, 10, 10)], FEW)

    assert calibration.brier == pytest.approx(0.25)


def test_matchups_are_grouped_by_the_chance_they_were_given() -> None:
    calibration = calibrate([_played(30, 10, 25, 5), _played(5, 20, 5, 25), _played(10, 30, 10, 10)], FEW)

    assert sum(b.matchups for b in calibration.buckets) == 3
    assert {(b.low, b.won) for b in calibration.buckets} >= {(0.8, 1.0), (0.0, 0.0)}


def test_nothing_to_score_scores_nothing() -> None:
    assert calibrate([]).matchups == 0


# ── the projection's own uncertainty ────────────────────────────────────


def test_projection_error_widens_a_range_and_never_scores_below_nothing() -> None:
    plain = outcome("a", 10, 20)
    unsure = Outcomes("a", "A", 15.0, (10.0, 20.0), projection_error=0.3)
    nobody = [outcome("b", 0)]

    widened = simulate(_match([unsure], nobody), FEW).margin

    assert _width(_match([unsure], nobody)) > _width(_match([plain], nobody))
    assert widened.low >= 0


# ── scoring ranges against what happened ────────────────────────────────


def test_a_range_that_matches_reality_holds_four_in_five() -> None:
    import random as rng_module

    from thefrontoffice.application.forecasting import score_ranges

    truth = tuple(float(x) for x in range(101))
    rng = rng_module.Random(3)
    played = [(Outcomes(f"p{i}", "P", 50.0, truth), rng.choice(truth)) for i in range(2_000)]

    result = score_ranges(played)

    assert result.inside == pytest.approx(0.8, abs=0.04)
    assert result.below == pytest.approx(0.1, abs=0.03) and result.above == pytest.approx(0.1, abs=0.03)


def test_a_range_too_narrow_for_reality_holds_less_and_scores_worse() -> None:
    import random as rng_module

    from thefrontoffice.application.forecasting import score_ranges

    truth = tuple(float(x) for x in range(101))
    rng = rng_module.Random(3)
    actuals = [rng.choice(truth) for _ in range(1_000)]
    true_range = score_ranges([(Outcomes("p", "P", 50.0, truth), a) for a in actuals])
    narrow = score_ranges([(Outcomes("p", "P", 50.0, (45.0, 50.0, 55.0)), a) for a in actuals])

    assert narrow.inside < true_range.inside
    assert narrow.loss > true_range.loss


def test_no_games_to_score_scores_nothing() -> None:
    from thefrontoffice.application.forecasting import score_ranges

    assert score_ranges([]).players == 0


# ── the wire, priced ────────────────────────────────────────────────────


def test_a_free_agent_is_priced_at_the_start_that_helps_most() -> None:
    weak, weaker = outcome("weak", 8.0), outcome("weaker", 4.0)
    signing = outcome("fa", 12.0)
    matchup = _match(
        [weak, weaker],
        [outcome("them", 17.0)],  # 16 replacing the weak starter loses; 20 replacing the weaker wins
        LineupMove("fa>weak", "Start FA over WEAK", ("weak",), (signing,)),
        LineupMove("fa>weaker", "Start FA over WEAKER", ("weaker",), (signing,)),
    )

    [chance] = pickup_chances(simulate(matchup, FEW), matchup)

    assert (chance.player_id, chance.title) == ("fa", "Start FA over WEAKER")
    assert chance.win_change > 0


def test_a_free_agent_who_only_hurts_says_by_how_much() -> None:
    """A deep league's wire mostly hurts; the shortfall is still the answer."""
    matchup = _match(
        [outcome("mine", 20.0, 30.0)],
        [outcome("them", 22.0, 28.0)],
        LineupMove("fa>mine", "Start FA over MINE", ("mine",), (outcome("fa", 2.0),)),
    )

    [chance] = pickup_chances(simulate(matchup, FEW), matchup)

    assert chance.win_change < 0


class _Wire(FakeForecast):
    """A matchup whose moves are whatever free agents it is asked about."""

    def matchup(self, candidates: Sequence[str]) -> MatchupInput | None:
        mine = outcome("mine", 10.0)
        moves = tuple(LineupMove(f"{c}>mine", f"Start {c}", ("mine",), (outcome(c, 15.0),)) for c in candidates)
        return _match([mine], [outcome("them", 12.0)], *moves)


def test_the_engine_prices_each_free_agent_it_is_given() -> None:
    chances = ForecastEngine(_Wire()).pickups("L1", ["x", "y"])

    assert {c.player_id for c in chances} == {"x", "y"}


def test_no_free_agents_is_no_simulation() -> None:
    wire = _Wire()

    assert ForecastEngine(wire).pickups("L1", []) == []
    assert wire.asked == []


# ── a week won on categories ────────────────────────────────────────────

STATS = ("fgm", "fga", "pts", "to")
FG = ScoredCategory("FG%", "fgm", "fga", places=3)
PTS = ScoredCategory("PTS", "pts")
TO = ScoredCategory("TO", "to", fewer_wins=True)


def _week(
    mine: tuple[float, ...],
    theirs: tuple[float, ...],
    *,
    scored: tuple[ScoredCategory, ...] = (FG, PTS, TO),
    lines_mine: tuple[StatLines, ...] = (),
    lines_theirs: tuple[StatLines, ...] = (),
) -> CategoryMatchup:
    return CategoryMatchup(STATS, scored, lines_mine, lines_theirs, mine, theirs)


def test_a_side_ahead_in_every_category_with_nothing_left_wins_each_and_the_week() -> None:
    forecast = categories(_week((50, 100, 120, 10), (40, 100, 100, 12)), simulations=FEW)

    assert forecast.categories == {"FG%": 1.0, "PTS": 1.0, "TO": 1.0}
    assert forecast.win == 1.0 and forecast.margin.median == 3.0


def test_fewer_turnovers_wins_turnovers() -> None:
    forecast = categories(_week((50, 100, 120, 14), (40, 100, 100, 12)), simulations=FEW)

    assert forecast.categories["TO"] == 0.0
    assert forecast.win == 1.0  # two categories of three


def test_a_percentage_is_makes_over_attempts_and_ties_where_the_league_prints_it_level() -> None:
    level = categories(_week((4781, 10000, 0, 0), (4779, 10000, 0, 0), scored=(FG,)), simulations=FEW)
    exact = categories(
        _week((4781, 10000, 0, 0), (4779, 10000, 0, 0), scored=(ScoredCategory("FG%", "fgm", "fga"),)),
        simulations=FEW,
    )

    assert level.categories["FG%"] == 0.5
    assert exact.categories["FG%"] == 1.0


def test_a_percentage_with_nothing_attempted_loses_to_any_and_ties_with_none() -> None:
    assert categories(_week((0, 0, 0, 0), (1, 10, 0, 0), scored=(FG,)), simulations=FEW).categories["FG%"] == 0.0
    assert categories(_week((0, 0, 0, 0), (0, 0, 0, 0), scored=(FG,)), simulations=FEW).categories["FG%"] == 0.5


def test_categories_won_level_with_categories_lost_is_a_tied_week() -> None:
    forecast = categories(_week((0, 0, 120, 14), (0, 0, 100, 12), scored=(PTS, TO)), simulations=FEW)

    assert forecast.win == 0.5 and forecast.margin.median == 0.0


def test_the_games_still_to_come_can_turn_a_category() -> None:
    """Behind by ten points with three games of twenty to come against nobody's: a sure comeback."""
    scorer = StatLines("a", ((8.0, 16.0, 20.0, 1.0),), games=3)

    forecast = categories(_week((0, 0, 90, 0), (0, 0, 100, 0), scored=(PTS,), lines_mine=(scorer,)), simulations=FEW)

    assert forecast.categories["PTS"] == 1.0


def test_the_stats_of_one_simulated_game_come_from_the_same_real_game() -> None:
    """A shooter who either goes 10 of 10 or 0 of 10 never shoots 50% in a one-game week."""
    streaky = StatLines("a", ((10.0, 10.0, 0.0, 0.0), (0.0, 10.0, 0.0, 0.0)), games=1)

    forecast = categories(_week((0, 0, 0, 0), (5, 10, 0, 0), scored=(FG,), lines_mine=(streaky,)), simulations=FEW)

    assert 0.4 < forecast.categories["FG%"] < 0.6
    assert forecast.margin.low == -1.0 and forecast.margin.high == 1.0


def test_a_player_with_no_games_or_no_line_adds_nothing() -> None:
    idle = StatLines("a", ((0.0, 0.0, 50.0, 0.0),), games=0)
    unknown = StatLines("b", (), games=3)

    forecast = categories(_week((0, 0, 0, 0), (0, 0, 1, 0), scored=(PTS,), lines_mine=(idle, unknown)), simulations=FEW)

    assert forecast.categories["PTS"] == 0.0


def test_a_category_week_is_simulated_from_the_matchup_and_holds_still_between_reads() -> None:
    lines = (StatLines("a", ((5.0, 10.0, 12.0, 2.0), (3.0, 9.0, 8.0, 1.0)), games=2),)
    week = _week((10, 20, 30, 3), (11, 20, 34, 3), lines_mine=lines, lines_theirs=lines)
    matchup = MatchupInput(mine=(), theirs=(), seed=3, categories=week)

    first, second = simulate(matchup), simulate(matchup)

    assert first == second
    assert set(first.categories) == {"FG%", "PTS", "TO"}


class _Fixed(FakeForecast):
    """One matchup, the same every time it is asked for."""

    def matchup(self, candidates: Sequence[str]) -> MatchupInput | None:
        return _match([outcome("a", 0, 10, 20)], [outcome("b", 5, 15)])


def test_an_unchanged_matchup_is_not_played_again_even_by_an_engine_built_for_the_next_page() -> None:
    first, second = ForecastEngine(_Fixed()).forecast("L1"), ForecastEngine(_Fixed()).forecast("L1")

    assert first is not None and second is not None
    assert first[0] is second[0]


class _Changing(FakeForecast):
    """A matchup that is a different one each time it is asked for, as a live week is, until it comes round again."""

    def matchup(self, candidates: Sequence[str]) -> MatchupInput | None:
        return _match([outcome("a", 0, 10, 20)], [outcome("b", 5, 15)], seed=len(self.asked) % (REMEMBERED + 1))


def test_a_matchup_is_played_again_once_newer_ones_have_pushed_it_out() -> None:
    engine = ForecastEngine(_Changing())
    reads = [engine.forecast("L1") for _ in range(REMEMBERED + 2)]

    first, again = reads[0], reads[-1]
    assert first is not None and again is not None
    assert again[1] == first[1]
    assert again[0] == first[0] and again[0] is not first[0]


# ── teammates ───────────────────────────────────────────────────────────


def _grouped(pid: str, group: str) -> Outcomes:
    return Outcomes(pid, pid.upper(), 10.0, (10.0,), projection_error=0.3, group=group, shared_error=0.3)


def _width(matchup: MatchupInput, simulations: int = FEW) -> float:
    margin = simulate(matchup, simulations).margin
    return margin.high - margin.low


def test_teammates_who_rise_together_make_a_wider_week_than_strangers() -> None:
    """A quarterback and his receiver in one lineup: their good weeks come together."""
    together = _match([_grouped("qb", "KC"), _grouped("wr", "KC")], [outcome("them", 20.0)])
    apart = _match([_grouped("qb", "KC"), _grouped("wr", "BUF")], [outcome("them", 20.0)])

    assert _width(together) > _width(apart)


def test_a_player_ranged_alone_is_as_wide_with_teammates_as_without() -> None:
    """Sharing moves part of his error into the group; it adds none."""
    alone = Outcomes("wr", "WR", 10.0, (10.0,), projection_error=0.3)
    nobody = [outcome("them", 0)]

    widths = [_width(_match([o], nobody), simulations=20_000) for o in (alone, _grouped("wr", "KC"))]

    assert widths[0] == pytest.approx(widths[1], rel=0.05)


def test_a_move_bringing_in_a_new_group_leaves_every_other_week_as_it_was() -> None:
    mine, theirs = [_grouped("qb", "KC")], [_grouped("them", "BUF")]
    move = LineupMove("x>qb", "Start X", ("qb",), (_grouped("x", "DAL"),))

    without = simulate(_match(mine, theirs), FEW)
    with_move = simulate(_match(mine, theirs, move), FEW)

    assert with_move.win == without.win
