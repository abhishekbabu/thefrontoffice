"""Tests for simulating a matchup: `application/forecasting.py`.

Players here are built by hand, so each test can say exactly what the
simulation should conclude — a sure thing, a coin flip, a move that cannot
hurt — without depending on any sport's data.
"""

import random
from collections.abc import Sequence
from statistics import pstdev

import pytest

from thefrontoffice.application.forecasting import (
    WORTH_A_ROW,
    ForecastEngine,
    _draw,
    calibrate,
    pickup_chances,
    ranked,
    simulate,
)
from thefrontoffice.domain.models import (
    Action,
    LineupMove,
    MatchupInput,
    Outcomes,
    PlayedMatchup,
)

FEW = 2_000


def _player(pid: str, *samples: float, plays: float = 1.0, floor: float = 0.0, remaining: float = 1.0) -> Outcomes:
    projection = sum(samples) / len(samples) if samples else 0.0
    return Outcomes(pid, pid.upper(), projection, samples, plays=plays, floor=floor, remaining=remaining)


def _match(mine: list[Outcomes], theirs: list[Outcomes], *moves: LineupMove, seed: int = 7) -> MatchupInput:
    return MatchupInput(mine=tuple(mine), theirs=tuple(theirs), moves=moves, seed=seed)


# ── the chance of winning ───────────────────────────────────────────────


def test_a_lineup_that_always_outscores_always_wins() -> None:
    forecast = simulate(_match([_player("a", 20, 25)], [_player("b", 5, 10)]), FEW)

    assert forecast.win == 1.0
    assert forecast.margin.low > 0


def test_two_identical_sides_are_a_coin_flip() -> None:
    forecast = simulate(_match([_player("a", 0, 10, 20, 30)], [_player("b", 0, 10, 20, 30)]), FEW)

    assert forecast.win == pytest.approx(0.5, abs=0.05)


def test_a_tie_counts_half() -> None:
    assert simulate(_match([_player("a", 10)], [_player("b", 10)]), FEW).win == 0.5


def test_a_player_who_will_not_play_adds_nothing() -> None:
    forecast = simulate(_match([_player("a", 30, plays=0.0)], [_player("b", 1)]), FEW)

    assert forecast.win == 0.0


def test_a_game_already_over_counts_what_it_scored_and_nothing_more() -> None:
    finished = _player("a", 100, floor=12.0, remaining=0.0)

    forecast = simulate(_match([finished], [_player("b", 11)]), FEW)

    assert forecast.win == 1.0 and forecast.margin.median == 1.0


def test_the_margin_range_runs_low_to_high() -> None:
    margin = simulate(_match([_player("a", 0, 10, 20, 40)], [_player("b", 5, 15)]), FEW).margin

    assert margin.low <= margin.median <= margin.high


def test_the_same_matchup_gives_the_same_answer_every_time() -> None:
    """A win chance that flickered between reloads would read as news."""
    matchup = _match([_player("a", 0, 10, 20, 30)], [_player("b", 5, 15, 25)])

    assert simulate(matchup, FEW) == simulate(matchup, FEW)


# ── what each move does ─────────────────────────────────────────────────


def test_a_move_that_is_better_in_every_way_never_lowers_the_chance() -> None:
    """Same draws with and without it: the difference is the decision, not noise."""
    worse, better = _player("w", 0, 5, 10), _player("x", 20, 25, 30)
    move = LineupMove(key="x>w", title="Start X over W", out=("w",), into=(better,))

    forecast = simulate(_match([worse, _player("m", 0, 30)], [_player("t", 10, 20, 30)], move), FEW)

    assert forecast.moves["x>w"] >= forecast.win
    assert forecast.best_move == "x>w"


def test_pricing_a_move_does_not_change_the_chance_without_it() -> None:
    base = _match([_player("a", 0, 10, 20)], [_player("b", 5, 15)])
    move = LineupMove(key="c>a", title="Start C", out=("a",), into=(_player("c", 0, 40),))

    assert simulate(base, FEW).win == simulate(_match(list(base.mine), list(base.theirs), move), FEW).win


def test_no_move_is_called_best_unless_it_helps() -> None:
    move = LineupMove(key="z>a", title="Start Z", out=("a",), into=(_player("z", 0),))

    assert simulate(_match([_player("a", 10, 20)], [_player("b", 5, 25)], move), FEW).best_move == ""


# ── the to-do list, by the chance of winning ───────────────────────────────────────────────────────


SWAP = Action(
    kind="lineup", urgency="soon", title="Start X over W", reason="+3", key="swap:x:w", player_id="x", replaces="w"
)
DEADLINE = Action(kind="trade", urgency="later", title="Trade by week 11", reason="deadline", key="deadline:11")


def _attached(*actions: Action, moves: tuple[LineupMove, ...] = ()) -> list[Action]:
    matchup = _match([_player("w", 0, 5, 10), _player("m", 0, 30)], [_player("t", 10, 20, 30)], *moves)
    return ranked(list(actions), simulate(matchup, FEW), matchup) or []


def test_a_to_do_move_carries_what_it_does_to_the_chance() -> None:
    move = LineupMove(key="x>w", title="Start X over W", out=("w",), into=(_player("x", 20, 25, 30),))

    [swap] = _attached(SWAP, moves=(move,))

    assert swap.win_change is not None and swap.win_change > 0


def test_an_item_that_moves_nobody_has_no_change_to_show() -> None:
    [deadline] = _attached(DEADLINE)

    assert deadline.win_change is None


def test_a_better_move_the_list_lacks_becomes_a_row_of_its_own() -> None:
    move = LineupMove(key="x>w", title="Start X over W", out=("w",), into=(_player("x", 20, 25, 30),))

    actions = _attached(DEADLINE, moves=(move,))

    added = [a for a in actions if a.key.startswith("odds:")]
    assert len(added) == 1 and (added[0].player_id, added[0].replaces) == ("x", "w")
    assert added[0].win_change is not None and added[0].win_change >= WORTH_A_ROW


def test_a_move_already_on_the_list_is_not_added_twice() -> None:
    move = LineupMove(key="x>w", title="Start X over W", out=("w",), into=(_player("x", 20, 25, 30),))

    actions = _attached(SWAP, moves=(move,))

    assert [a.key for a in actions] == [SWAP.key]


def test_rows_keep_their_urgency_and_sort_within_it_by_what_they_add() -> None:
    small = LineupMove(key="y>w", title="Start Y over W", out=("w",), into=(_player("y", 6, 8, 12),))
    big = LineupMove(key="x>w", title="Start X over W", out=("w",), into=(_player("x", 20, 25, 30),))
    lesser = SWAP.model_copy(update={"key": "swap:y:w", "player_id": "y"})

    actions = _attached(DEADLINE, lesser, SWAP, moves=(small, big))

    assert [a.key for a in actions] == [SWAP.key, lesser.key, DEADLINE.key]


def test_a_competition_without_a_to_do_list_still_has_none() -> None:
    matchup = _match([_player("a", 10)], [_player("b", 5)])

    assert ranked(None, simulate(matchup, FEW), matchup) is None


# ── how well it predicts ────────────────────────────────────────────────


def _played(mine: float, theirs: float, ours: float, others: float) -> PlayedMatchup:
    return PlayedMatchup(week=2, matchup=_match([_player("a", ours)], [_player("b", others)]), mine=mine, theirs=theirs)


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


def test_projection_error_widens_a_range_without_moving_its_centre() -> None:
    import random as rng_module
    from statistics import mean, pstdev

    from thefrontoffice.application.forecasting import _draw

    plain = _player("a", 10, 20)
    unsure = Outcomes("a", "A", 15.0, (10.0, 20.0), projection_error=0.3)

    certain_draws = _draw(plain, rng_module.Random(1), 20_000)
    unsure_draws = _draw(unsure, rng_module.Random(1), 20_000)

    assert pstdev(unsure_draws) > pstdev(certain_draws)
    assert mean(unsure_draws) == pytest.approx(mean(certain_draws), rel=0.03)
    assert min(unsure_draws) >= 0


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
    weak, weaker = _player("weak", 8.0), _player("weaker", 4.0)
    signing = _player("fa", 12.0)
    matchup = _match(
        [weak, weaker],
        [_player("them", 17.0)],  # 16 replacing the weak starter loses; 20 replacing the weaker wins
        LineupMove("fa>weak", "Start FA over WEAK", ("weak",), (signing,)),
        LineupMove("fa>weaker", "Start FA over WEAKER", ("weaker",), (signing,)),
    )

    [chance] = pickup_chances(simulate(matchup, FEW), matchup)

    assert (chance.player_id, chance.title) == ("fa", "Start FA over WEAKER")
    assert chance.win_change > 0


def test_a_free_agent_who_only_hurts_says_by_how_much() -> None:
    """A deep league's wire mostly hurts; the shortfall is still the answer."""
    matchup = _match(
        [_player("mine", 20.0, 30.0)],
        [_player("them", 22.0, 28.0)],
        LineupMove("fa>mine", "Start FA over MINE", ("mine",), (_player("fa", 2.0),)),
    )

    [chance] = pickup_chances(simulate(matchup, FEW), matchup)

    assert chance.win_change < 0


class _Wire:
    """A matchup whose moves are whatever free agents it is asked about."""

    label = "Test"

    def __init__(self) -> None:
        self.asked: list[list[str]] = []

    def matchup_input(self, league_id: str, candidates: Sequence[str] = ()) -> MatchupInput | None:
        self.asked.append(list(candidates))
        mine = _player("mine", 10.0)
        moves = tuple(LineupMove(f"{c}>mine", f"Start {c}", ("mine",), (_player(c, 15.0),)) for c in candidates)
        return _match([mine], [_player("them", 12.0)], *moves)

    def played_matchups(self, league_id: str, week: int) -> list[PlayedMatchup]:
        return []


def test_the_engine_prices_each_free_agent_it_is_given() -> None:
    chances = ForecastEngine(_Wire()).pickups("L1", ["x", "y"])

    assert {c.player_id for c in chances} == {"x", "y"}


def test_no_free_agents_is_no_simulation() -> None:
    wire = _Wire()

    assert ForecastEngine(wire).pickups("L1", []) == []
    assert wire.asked == []


# ── teammates ───────────────────────────────────────────────────────────


def _grouped(pid: str, group: str) -> Outcomes:
    return Outcomes(pid, pid.upper(), 10.0, (10.0,), projection_error=0.3, group=group, shared_error=0.3)


def _width(matchup: MatchupInput) -> float:
    margin = simulate(matchup, FEW).margin
    return margin.high - margin.low


def test_teammates_who_rise_together_make_a_wider_week_than_strangers() -> None:
    """A quarterback and his receiver in one lineup: their good weeks come together."""
    together = _match([_grouped("qb", "KC"), _grouped("wr", "KC")], [_player("them", 20.0)])
    apart = _match([_grouped("qb", "KC"), _grouped("wr", "BUF")], [_player("them", 20.0)])

    assert _width(together) > _width(apart)


def test_a_player_ranged_alone_is_as_wide_with_teammates_as_without() -> None:
    """Sharing moves part of his error into the group; it adds none."""
    alone = Outcomes("wr", "WR", 10.0, (10.0,), projection_error=0.3)
    grouped = _grouped("wr", "KC")

    widths = [pstdev(_draw(o, random.Random(1), 20_000, shared=None)) for o in (alone, grouped)]

    assert widths[0] == pytest.approx(widths[1], rel=0.05)


def test_a_move_bringing_in_a_new_group_leaves_every_other_week_as_it_was() -> None:
    mine, theirs = [_grouped("qb", "KC")], [_grouped("them", "BUF")]
    move = LineupMove("x>qb", "Start X", ("qb",), (_grouped("x", "DAL"),))

    without = simulate(_match(mine, theirs), FEW)
    with_move = simulate(_match(mine, theirs, move), FEW)

    assert with_move.win == without.win
