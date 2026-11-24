"""Tests for how much each defense gives up to each position: `competitions/matchups.py`."""

from dataclasses import replace

import pytest

from thefrontoffice.adapters.outbound.competitions.matchups import RECENT_GAMES, Matchup, Recent, Scored, allowed


@pytest.mark.parametrize(
    ("rank", "described", "tone"),
    [
        (1, "the most", "good"),
        (8, "8th-most", "good"),
        (9, "9th-most", "neutral"),
        (24, "24th-most", "neutral"),
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


# ── the recent window ──────────────────────────────────────────────────


def _turned() -> list[Scored[int]]:
    """Two defenses over seven weeks. SF was stingy for two, then gave TEs 20 a game; DAL gave 12 every week.

    Season: DAL 12.0 a game, SF (2 * 2 + 5 * 20) / 7 = 14.86; last five: SF 20.0, DAL 12.0.
    """
    return [
        *(Scored("SF", "TE", week, 2.0 if week <= 2 else 20.0) for week in range(1, 8)),
        *(Scored("DAL", "TE", week, 12.0) for week in range(1, 8)),
    ]


def test_a_defenses_recent_record_is_its_own_last_five_games_ranked_against_the_rest() -> None:
    found = allowed(_turned())

    recent = found["SF", "TE"].recent
    assert recent is not None
    assert (recent.allowed, recent.rank) == (pytest.approx(20.0), 1)
    assert found["SF", "TE"].allowed == pytest.approx(104 / 7)


def test_the_recent_window_counts_each_defenses_own_games_not_the_calendars_weeks() -> None:
    """DAL's bye in week 7 leaves its last five as weeks 2–6, where it gave up 30 in week 2."""
    lines = [
        *(Scored("SF", "TE", week, 10.0) for week in range(1, 8)),
        Scored("DAL", "TE", 1, 0.0),
        Scored("DAL", "TE", 2, 30.0),
        *(Scored("DAL", "TE", week, 0.0) for week in range(3, 7)),
    ]

    recent = allowed(lines)["DAL", "TE"].recent

    assert recent is not None
    assert recent.allowed == pytest.approx(6.0)


def test_no_recent_record_until_a_defense_has_played_more_games_than_the_window() -> None:
    """Five games each: the last five are the season, which says nothing twice."""
    lines = [Scored(defense, "TE", week, 10.0) for defense in ("SF", "DAL") for week in range(1, 6)]

    assert allowed(lines)["SF", "TE"].recent is None


def test_a_recent_record_is_weighed_evenly_with_the_season_in_the_tone() -> None:
    """13th on the season but 4th lately stands at 8.5 of 32: no longer the middle, not yet the softest quarter."""
    middling = Matchup(opponent="SF", position="TE", allowed=10.0, rank=13, defenses=32)
    turned = replace(middling, recent=Recent(allowed=15.8, rank=4))
    softest = replace(middling, recent=Recent(allowed=18.0, rank=2))

    assert (middling.standing, turned.standing, softest.standing) == (13, 8.5, 7.5)
    assert (middling.tone, turned.tone, softest.tone) == ("neutral", "neutral", "good")


def test_a_matchups_line_carries_its_recent_rank() -> None:
    matchup = allowed(_turned())["SF", "TE"]

    assert matchup.recent is not None
    assert f"{matchup.recent.rank}st over last {RECENT_GAMES}" in matchup.allowed_to()
    assert "20.00" in matchup.describe()
