"""Tests for a football player's role and matchup: `nfl/evidence.py`.

Built from hand-written game lines, so every share and rank below can be
checked with a pencil.
"""

import pytest
from support.nfl import game_line, proj

from thefrontoffice.adapters.outbound.competitions.nfl.evidence import Matchup, gather
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NFLGameLine

SCORING = "pts_ppr"


# ── role ────────────────────────────────────────────────────────────────


def test_a_role_is_his_share_of_the_offense_over_his_last_three_games() -> None:
    lines = [
        # Week 1 is a fourth game back, and must not count.
        game_line("wr", 1, off_snp=10, tm_off_snp=60, rec_tgt=1, pts_ppr=2),
        *(game_line("wr", w, off_snp=45, tm_off_snp=60, rec_tgt=8, pts_ppr=15) for w in (2, 3, 4)),
        # A teammate, so the team saw 10 targets a game.
        *(game_line("te", w, position="TE", off_snp=50, tm_off_snp=60, rec_tgt=2, pts_ppr=4) for w in (2, 3, 4)),
    ]

    role = gather(lines, SCORING).roles["wr"]

    assert role.games == 3
    assert role.snap_share == pytest.approx(0.75)
    assert role.targets == pytest.approx(8.0)
    assert role.target_share == pytest.approx(0.8)
    assert role.points == pytest.approx(15.0)
    assert role.describe() == "last 3 games: 75% of snaps, 8.0 targets (80% share), 15.0 pts"


def test_a_game_he_never_took_the_field_in_is_not_part_of_his_role() -> None:
    """Sleeper files a row for an inactive player; averaging it in would halve a
    role that did not change."""
    lines = [
        game_line("rb", 2, position="RB", off_snp=40, tm_off_snp=60, rush_att=18, pts_ppr=16),
        game_line("rb", 3, position="RB", off_snp=0, tm_off_snp=60),
    ]

    role = gather(lines, SCORING).roles["rb"]

    assert (role.games, role.carries) == (1, 18.0)
    assert role.describe().startswith("last game: ")


def test_a_kicker_or_a_defense_is_not_given_a_snap_share() -> None:
    """Snaps are recorded for the offense only, and '0% of snaps' would be false."""
    lines = [game_line("k", w, position="K", pts_ppr=9) for w in (2, 3)]

    role = gather(lines, SCORING).roles["k"]

    assert role.snap_share is None
    assert role.describe() == "last 2 games: 9.0 pts"


def test_points_are_counted_in_the_leagues_own_scoring() -> None:
    lines = [game_line("wr", 2, off_snp=40, tm_off_snp=60, pts_ppr=12, pts_std=7)]

    assert gather(lines, "pts_std").roles["wr"].points == 7.0


# ── matchup ─────────────────────────────────────────────────────────────


def _defenses() -> list[NFLGameLine]:
    """Four defenses against running backs: MIA gives up the most, NE nothing."""
    return [
        game_line("a", 1, position="RB", opponent="MIA", pts_ppr=30),
        game_line("b", 1, position="RB", opponent="NYJ", pts_ppr=20),
        game_line("c", 1, position="RB", opponent="BUF", pts_ppr=10),
        game_line("d", 1, position="WR", opponent="NE", pts_ppr=10),
        # Two games for NYJ: 20 and 10 is 15 a game, not 30 in total.
        game_line("e", 2, position="RB", opponent="NYJ", pts_ppr=10),
    ]


def test_defenses_are_ranked_by_points_a_game_given_up_to_the_position() -> None:
    allowed = gather(_defenses(), SCORING).allowed

    ranks = {defense: allowed[(defense, "RB")].rank for defense in ("MIA", "NYJ", "BUF", "NE")}

    assert ranks == {"MIA": 1, "NYJ": 2, "BUF": 3, "NE": 4}
    assert allowed[("NYJ", "RB")].allowed == pytest.approx(15.0)


def test_a_defense_that_gave_a_position_nothing_is_ranked_rather_than_missing() -> None:
    """Holding running backs to nothing is the best record there is, not no record."""
    nothing = gather(_defenses(), SCORING).allowed[("NE", "RB")]

    assert (nothing.allowed, nothing.rank, nothing.defenses) == (0.0, 4, 4)


def test_a_player_is_matched_against_this_weeks_opponent() -> None:
    evidence = gather(_defenses(), SCORING)

    matchup = evidence.matchup(proj("x", "Run Back", "RB", 12.0, opp="MIA"))

    assert matchup is not None and matchup.describe() == "vs MIA, the most to RBs (30.0 a game)"


def test_a_player_with_no_game_has_no_matchup() -> None:
    assert gather(_defenses(), SCORING).matchup(proj("x", "Idle", "RB", 0.0, opp="")) is None


@pytest.mark.parametrize(
    ("rank", "described", "tone"),
    [
        (1, "the most", "good"),
        (8, "8th-most", "good"),
        (9, "9th-most", "neutral"),
        (11, "11th-most", "neutral"),
        (22, "22nd-most", "neutral"),
        (25, "25th-most", "warning"),
        (32, "the fewest", "warning"),
    ],
)
def test_a_matchup_reads_as_a_rank_and_is_toned_by_quarter(rank: int, described: str, tone: str) -> None:
    matchup = Matchup(opponent="MIA", position="WR", allowed=20.0, rank=rank, defenses=32)

    assert matchup.describe() == f"vs MIA, {described} to WRs (20.0 a game)"
    assert matchup.tone == tone


def test_a_defense_is_matched_against_the_offense_it_faces() -> None:
    matchup = Matchup(opponent="TEN", position="DEF", allowed=9.0, rank=3, defenses=32)

    assert matchup.describe() == "vs TEN, 3rd-most to defenses (9.0 a game)"


# ── together ────────────────────────────────────────────────────────────


def test_a_player_is_described_by_both_halves_and_toned_by_his_matchup() -> None:
    lines = [*_defenses(), game_line("x", 2, position="RB", off_snp=30, tm_off_snp=60, rush_att=12, pts_ppr=11)]

    stat = gather(lines, SCORING).stat(proj("x", "Run Back", "RB", 12.0, opp="MIA"))

    assert stat is not None
    assert stat.label == "Run Back"
    evidence = gather(lines, SCORING)
    matchup = evidence.matchup(proj("x", "Run Back", "RB", 12.0, opp="MIA"))
    assert matchup is not None
    assert stat.value == f"{matchup.describe()}; {evidence.roles['x'].describe()}"
    assert stat.tone == "good"


def test_a_player_with_nothing_played_has_nothing_to_say() -> None:
    evidence = gather([], SCORING)
    player = proj("x", "Rookie", "RB", 12.0, opp="MIA")

    assert (evidence.describe(player), evidence.stat(player)) == ("", None)


# ── a role that grew ────────────────────────────────────────────────────


def _snaps(pid: str, *shares: float, position: str = "WR") -> list[NFLGameLine]:
    """One game a week from week 1, at each share of 60 team snaps."""
    return [
        game_line(pid, week, position=position, off_snp=share * 60, tm_off_snp=60, pts_ppr=5)
        for week, share in enumerate(shares, start=1)
    ]


def test_a_jump_in_the_latest_week_is_a_growing_role() -> None:
    trend = gather(_snaps("wr", 0.3, 0.35, 0.4, 0.8), SCORING).trends["wr"]

    assert (trend.measure, trend.week) == ("snaps", 4)
    assert trend.before == pytest.approx(0.35) and trend.now == pytest.approx(0.8)


def test_a_jump_weeks_ago_is_a_role_by_now() -> None:
    """Somebody else played week 5; his jump in week 4 is old news the projection has read."""
    lines = _snaps("wr", 0.3, 0.35, 0.4, 0.8) + _snaps("other", 0.5, 0.5, 0.5, 0.5, 0.5)

    assert "wr" not in gather(lines, SCORING).trends


def test_one_game_before_is_too_little_to_call_a_change() -> None:
    assert "wr" not in gather(_snaps("wr", 0.2, 0.9), SCORING).trends


def test_a_jump_to_a_role_that_is_still_small_is_no_role() -> None:
    """From 5% to 30% of snaps is a big jump to a part nobody starts."""
    assert "wr" not in gather(_snaps("wr", 0.05, 0.05, 0.3), SCORING).trends


def test_a_steady_role_is_no_trend() -> None:
    assert gather(_snaps("wr", 0.7, 0.72, 0.7, 0.71), SCORING).trends == {}


def test_carries_count_for_a_back_whose_snaps_stayed_level() -> None:
    lines = [
        game_line("rb", week, position="RB", off_snp=30, tm_off_snp=60, rush_att=carries, pts_ppr=5)
        for week, carries in ((1, 2), (2, 3), (3, 16))
    ]

    trend = gather(lines, SCORING).trends["rb"]

    assert trend.measure == "carries" and trend.now == 16


def test_a_growing_role_is_part_of_the_line_a_player_is_read_by() -> None:
    evidence = gather(_snaps("wr", 0.3, 0.35, 0.4, 0.8), SCORING)

    line = evidence.describe(proj("wr", "Wide", "WR", 9.0))

    assert evidence.trends["wr"].describe() in line
