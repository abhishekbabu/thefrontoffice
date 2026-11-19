"""Tests for how much each defense gives up to each position: `competitions/matchups.py`."""

import pytest

from thefrontoffice.adapters.outbound.competitions.matchups import Matchup, Scored, allowed


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

    assert f"{described} to WRs" in matchup.describe()
    assert matchup.tone == tone


def test_a_defense_is_matched_against_the_offense_it_faces() -> None:
    matchup = Matchup(opponent="TEN", position="DEF", allowed=9.0, rank=3, defenses=32)

    assert "to defenses" in matchup.describe()


def test_a_unit_says_what_the_figure_counts() -> None:
    matchup = Matchup(opponent="LAL", position="PG", allowed=24.06, rank=4, defenses=30, unit="pts")

    assert matchup.allowed_to() == "4th-most to PGs (24.1 pts a game)"


def test_each_defense_is_ranked_per_game_it_played_at_every_position() -> None:
    """BOS gave PGs 30 in one game; LAL 40 over two: BOS gives up more a game, and nothing to Cs ranks too."""
    found = allowed(
        [
            Scored("BOS", "PG", "d1", 30.0),
            Scored("LAL", "PG", "d1", 25.0),
            Scored("LAL", "PG", "d2", 15.0),
            Scored("LAL", "C", "d2", 12.0),
        ]
    )

    assert (found["BOS", "PG"].rank, found["LAL", "PG"].rank) == (1, 2)
    assert found["LAL", "PG"].allowed == pytest.approx(20.0)
    assert (found["BOS", "C"].allowed, found["BOS", "C"].rank, found["BOS", "C"].defenses) == (0.0, 2, 2)
