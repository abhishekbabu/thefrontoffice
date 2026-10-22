"""Tests for a football player's role and matchup: `nfl/evidence.py`.

Built from hand-written game lines, so every share and rank below can be
checked with a pencil.
"""

import pytest
from conftest import _proj

from thefrontoffice.adapters.outbound.competitions.nfl.evidence import Matchup, gather
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NFLGameLine

SCORING = "pts_ppr"


def _line(
    pid: str, week: int, position: str = "WR", team: str = "KC", opponent: str = "LV", **stats: float
) -> NFLGameLine:
    return NFLGameLine(player_id=pid, week=week, team=team, opponent=opponent, position=position, stats=stats)


# ── role ────────────────────────────────────────────────────────────────


def test_a_role_is_his_share_of_the_offense_over_his_last_three_games() -> None:
    lines = [
        # Week 1 is a fourth game back, and must not count.
        _line("wr", 1, off_snp=10, tm_off_snp=60, rec_tgt=1, pts_ppr=2),
        *(_line("wr", w, off_snp=45, tm_off_snp=60, rec_tgt=8, pts_ppr=15) for w in (2, 3, 4)),
        # A teammate, so the team saw 10 targets a game.
        *(_line("te", w, position="TE", off_snp=50, tm_off_snp=60, rec_tgt=2, pts_ppr=4) for w in (2, 3, 4)),
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
        _line("rb", 2, position="RB", off_snp=40, tm_off_snp=60, rush_att=18, pts_ppr=16),
        _line("rb", 3, position="RB", off_snp=0, tm_off_snp=60),
    ]

    role = gather(lines, SCORING).roles["rb"]

    assert (role.games, role.carries) == (1, 18.0)
    assert role.describe().startswith("last game: ")


def test_a_kicker_or_a_defense_is_not_given_a_snap_share() -> None:
    """Snaps are recorded for the offense only, and '0% of snaps' would be false."""
    lines = [_line("k", w, position="K", pts_ppr=9) for w in (2, 3)]

    role = gather(lines, SCORING).roles["k"]

    assert role.snap_share is None
    assert role.describe() == "last 2 games: 9.0 pts"


def test_points_are_counted_in_the_leagues_own_scoring() -> None:
    lines = [_line("wr", 2, off_snp=40, tm_off_snp=60, pts_ppr=12, pts_std=7)]

    assert gather(lines, "pts_std").roles["wr"].points == 7.0


# ── matchup ─────────────────────────────────────────────────────────────


def _defenses() -> list[NFLGameLine]:
    """Four defenses against running backs: MIA gives up the most, NE nothing."""
    return [
        _line("a", 1, position="RB", opponent="MIA", pts_ppr=30),
        _line("b", 1, position="RB", opponent="NYJ", pts_ppr=20),
        _line("c", 1, position="RB", opponent="BUF", pts_ppr=10),
        _line("d", 1, position="WR", opponent="NE", pts_ppr=10),
        # Two games for NYJ: 20 and 10 is 15 a game, not 30 in total.
        _line("e", 2, position="RB", opponent="NYJ", pts_ppr=10),
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

    matchup = evidence.matchup(_proj("x", "Run Back", "RB", 12.0, opp="MIA"))

    assert matchup is not None and matchup.describe() == "vs MIA, the most to RBs (30.0 a game)"


def test_a_player_with_no_game_has_no_matchup() -> None:
    assert gather(_defenses(), SCORING).matchup(_proj("x", "Idle", "RB", 0.0, opp="")) is None


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
    lines = [*_defenses(), _line("x", 2, position="RB", off_snp=30, tm_off_snp=60, rush_att=12, pts_ppr=11)]

    stat = gather(lines, SCORING).stat(_proj("x", "Run Back", "RB", 12.0, opp="MIA"))

    assert stat is not None
    assert stat.label == "Run Back"
    evidence = gather(lines, SCORING)
    matchup = evidence.matchup(_proj("x", "Run Back", "RB", 12.0, opp="MIA"))
    assert matchup is not None
    assert stat.value == f"{matchup.describe()}; {evidence.roles['x'].describe()}"
    assert stat.tone == "good"


def test_a_player_with_nothing_played_has_nothing_to_say() -> None:
    evidence = gather([], SCORING)
    player = _proj("x", "Rookie", "RB", 12.0, opp="MIA")

    assert (evidence.describe(player), evidence.stat(player)) == ("", None)
