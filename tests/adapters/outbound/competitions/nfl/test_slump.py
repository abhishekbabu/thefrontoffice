"""Tests for a starter whose games fall well short of his projection: `nfl/slump.py`.

The games are written by hand, eight a player, so every figure below can be checked with a pencil.
"""

import pytest
from support.nfl import SLEEPER_USER_ID, game_line, proj, week_of

from thefrontoffice.adapters.outbound.competitions.matchups import Matchup, Recent
from thefrontoffice.adapters.outbound.competitions.nfl.slump import (
    CALL_FORM,
    MATCHUP_SWING,
    called,
    matchup_factor,
    slump,
    slumps,
)
from thefrontoffice.adapters.outbound.competitions.nfl.week import Week
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    NFLGameLine,
    PlayerMeta,
    SleeperLeague,
    SleeperRoster,
    WeeklyProjection,
)

LEAGUE = SleeperLeague(
    league_id="L1",
    name="Small",
    season="2026",
    total_rosters=2,
    scoring_format="pts_ppr",
    roster_positions=["TE", "BN"],
)

TE = proj("te", "Tyler End", "TE", 10.0, team="IND", opp="NYG")


def _games(
    pid: str, points: list[float], *, position: str = "TE", team: str = "IND", **per_game: float
) -> list[NFLGameLine]:
    """His games, weeks 1 on, each with the same usage: 80 of his club's 100 snaps and 6 of its 30 targets."""
    usage = {"off_snp": 80.0, "tm_off_snp": 100.0, "rec_tgt": 6.0, "rec_yd": 48.0} | per_game
    return [
        game_line(pid, week, position=position, team=team, opponent="HOU", pts_ppr=scored, **usage)
        for week, scored in enumerate(points, start=1)
    ]


def _club(team: str = "IND", weeks: int = 8, passer: str = "qb1", switch: int | None = None) -> list[NFLGameLine]:
    """The rest of his club's targets, 24 a game, and its quarterback: `passer`, then `qb2` from week `switch`."""
    lines = [
        game_line("wr", week, team=team, opponent="HOU", rec_tgt=24.0, off_snp=60.0) for week in range(1, weeks + 1)
    ]
    for week in range(1, weeks + 1):
        thrower = "qb2" if switch is not None and week >= switch else passer
        lines.append(game_line(thrower, week, position="QB", team=team, opponent="HOU", pass_att=30.0, off_snp=60.0))
    return lines


def _week(lines: list[NFLGameLine], *players: WeeklyProjection, starters: tuple[str, ...] = ("te",)) -> Week:
    projected = [TE, *players] if all(p.player_id != "te" for p in players) else list(players)
    names = {"qb1": "Daniel Jones", "qb2": "Riley Leonard"}
    meta = {
        p.player_id: PlayerMeta(player_id=p.player_id, name=p.name, position=p.position, team=p.team) for p in projected
    }
    meta |= {pid: PlayerMeta(player_id=pid, name=name, position="QB", team="IND") for pid, name in names.items()}
    roster = SleeperRoster(
        roster_id=1,
        owner_id=SLEEPER_USER_ID,
        player_ids=[p.player_id for p in projected],
        starter_ids=list(starters),
    )
    return week_of(LEAGUE, roster, projected, meta, lines=lines)


SOLID = [10.0, 11.0, 9.0, 10.0]


def test_a_month_well_under_his_projection_is_a_slump() -> None:
    """5.8, 8.4, 2.4 and 3.2 against 10.38: 4.95 a game, three of the four under three-fifths of it."""
    state = _week(
        _games("te", [*SOLID, 5.8, 8.4, 2.4, 3.2]) + _club(),
        proj("te", "Tyler End", "TE", 10.38, team="IND", opp="NYG"),
    )

    found = slump(state, state.projections["te"])

    assert found is not None
    assert (found.games, found.recent, found.projected) == (4, pytest.approx(4.95), 10.38)


@pytest.mark.parametrize(
    "recent",
    [
        pytest.param([10.0, 11.0, 0.0, 10.0], id="one bad game"),
        pytest.param([7.0, 7.0, 7.0, 7.0], id="a little under"),
        pytest.param([2.0, 2.0, 12.0, 12.0], id="two big games among four"),
    ],
)
def test_one_bad_game_or_a_gap_inside_the_noise_is_no_slump(recent: list[float]) -> None:
    state = _week(_games("te", [*SOLID, *recent]) + _club())

    assert slump(state, state.projections["te"]) is None


def test_a_small_projection_is_no_slump_however_far_under_it_he_is() -> None:
    """Under 3 points short is not a slot's question, at any share."""
    state = _week(
        _games("te", [*SOLID, 1.0, 1.0, 1.0, 1.0]) + _club(), proj("te", "Tyler End", "TE", 3.5, team="IND", opp="NYG")
    )

    assert slump(state, state.projections["te"]) is None


def test_missed_games_are_left_out_of_his_window() -> None:
    """Weeks he sat have no snaps, and three games played is still enough to read."""
    lines = _games("te", [*SOLID, 3.0, 0.0, 3.0, 3.0])
    sat = [line for line in lines if line.week != 6] + [game_line("te", 6, position="TE", team="IND")]

    found = slump(_week(sat + _club()), TE)

    # Weeks 4, 5, 7 and 8: 10, 3, 3 and 3. Counting week 6 as a nought would read 2.25.
    assert found is not None
    assert (found.games, found.recent) == (4, pytest.approx(4.75))


def test_a_quarterback_or_a_player_with_no_game_this_week_is_never_read() -> None:
    lines = _games("te", [*SOLID, 1.0, 1.0, 1.0, 1.0]) + _club()
    # Somebody else has a game, so fixtures are out and his club has none.
    others = proj("wr9", "Wes Other", "WR", 5.0, team="KC", opp="LV")
    state = _week(lines, proj("te", "Tyler End", "TE", 10.0, team="IND", opp=""), others)

    assert slump(state, state.projections["te"]) is None
    assert slump(state, proj("qb1", "Daniel Jones", "QB", 20.0, team="IND", opp="NYG")) is None


def test_a_slump_says_whether_his_efficiency_collapsed_and_his_usage_held() -> None:
    """Eight yards a target, then three, on the same snaps and share."""
    lines = _games("te", SOLID, rec_yd=48.0) + [
        line for line in _games("te", [*SOLID, 3.0, 3.0, 3.0, 3.0], rec_yd=18.0) if line.week > 4
    ]
    found = slump(_week(lines + _club()), TE)

    assert found is not None and found.efficiency is not None
    assert (found.efficiency.before, found.efficiency.now) == (pytest.approx(8.0), pytest.approx(3.0))
    assert found.collapsed
    assert found.usage_holds is True


def test_a_back_is_read_by_his_points_a_touch() -> None:
    lines = _games("rb", [*SOLID, 2.0, 2.0, 2.0, 2.0], position="RB", rec_tgt=2.0, rush_att=8.0) + _club()
    back = proj("rb", "Ron Back", "RB", 12.0, team="IND", opp="NYG")
    found = slump(_week(lines, back, starters=("rb",)), back)

    assert found is not None and found.efficiency is not None
    assert (found.efficiency.measure, found.efficiency.now, found.efficiency.before) == (
        "pts/touch",
        pytest.approx(0.2),
        pytest.approx(1.0),
    )


def test_a_change_of_quarterback_is_named() -> None:
    state = _week(_games("te", [*SOLID, 3.0, 3.0, 3.0, 3.0]) + _club(switch=6))

    found = slump(state, TE)

    assert found is not None
    assert found.passer == ("Jones", "Leonard")
    assert "Leonard" in found.short()


def test_the_same_quarterback_throughout_is_no_change() -> None:
    found = slump(_week(_games("te", [*SOLID, 3.0, 3.0, 3.0, 3.0]) + _club()), TE)

    assert found is not None and found.passer is None


def test_too_few_games_before_it_compares_nothing() -> None:
    found = slump(_week(_games("te", [12.0, 3.0, 3.0, 3.0, 3.0]) + _club(weeks=5)), TE)

    assert found is not None
    assert (found.efficiency, found.snaps, found.targets, found.passer, found.usage_holds) == (
        None,
        None,
        None,
        None,
        None,
    )


def test_only_your_starters_are_listed() -> None:
    lines = _games("te", [*SOLID, 3.0, 3.0, 3.0, 3.0]) + _games("te2", [*SOLID, 3.0, 3.0, 3.0, 3.0])
    benched = proj("te2", "Ted Bench", "TE", 10.0, team="IND", opp="NYG")

    assert set(slumps(_week(lines + _club(), benched))) == {"te"}


# ── the form call ───────────────────────────────────────────────────────


@pytest.mark.parametrize(("rank", "factor"), [(1, 1 + MATCHUP_SWING), (32, 1 - MATCHUP_SWING)])
def test_a_matchup_moves_a_form_call_a_tenth_at_most_either_way(rank: int, factor: float) -> None:
    assert matchup_factor(
        Matchup(opponent="NYG", position="TE", allowed=10.0, rank=rank, defenses=32)
    ) == pytest.approx(factor)


def test_the_middle_ranks_move_a_form_call_equally_either_way() -> None:
    def factor(rank: int) -> float:
        return matchup_factor(Matchup(opponent="NYG", position="TE", allowed=10.0, rank=rank, defenses=32))

    assert factor(16) - 1 == pytest.approx(1 - factor(17))


def test_a_defenses_recent_games_count_half_its_matchup() -> None:
    """Softest on the season, toughest over its last games: the middle, so nothing either way."""
    turned = Matchup(
        opponent="NYG", position="TE", allowed=10.0, rank=1, defenses=32, recent=Recent(allowed=2.0, rank=32)
    )

    assert matchup_factor(turned) == pytest.approx(1.0)


def test_no_matchup_moves_nothing() -> None:
    assert matchup_factor(None) == 1.0
    assert matchup_factor(Matchup(opponent="NYG", position="TE", allowed=1.0, rank=1, defenses=1)) == 1.0


def test_a_form_call_weighs_three_parts_recent_points_to_one_part_projection() -> None:
    """4 a game and a projection of 10: 5.5, a tenth up for a steady role on every snap he has had."""
    state = _week(_games("te", [*SOLID, 4.0, 4.0, 4.0, 4.0]) + _club())

    assert called(state, TE) == pytest.approx((CALL_FORM * 4.0 + (1 - CALL_FORM) * 10.0) * 1.1)


def test_a_form_call_needs_games_and_a_game_this_week() -> None:
    assert called(_week(_games("te", [4.0]) + _club(weeks=1)), TE) is None
    others = proj("wr9", "Wes Other", "WR", 5.0, team="KC", opp="LV")
    idle = proj("te", "Tyler End", "TE", 10.0, team="IND", opp="")
    assert called(_week(_games("te", SOLID) + _club(weeks=4), idle, others), idle) is None
