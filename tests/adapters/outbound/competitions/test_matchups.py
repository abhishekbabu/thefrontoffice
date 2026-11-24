"""Tests for how much each defense gives up to each position: `competitions/matchups.py`."""

from dataclasses import replace

import pytest

from thefrontoffice.adapters.outbound.competitions.matchups import (
    MATCHUP_SWING,
    RECENT_GAMES,
    Matchup,
    Recent,
    Scored,
    allowed,
    matchup_factor,
)


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


def test_a_recent_record_close_to_the_season_is_weighed_evenly_with_it() -> None:
    """13th on the season and 6th lately, within a quarter of the league: 9.5 of 32, still the middle."""
    middling = Matchup(opponent="SF", position="TE", allowed=10.0, rank=13, defenses=32)
    lately = replace(middling, recent=Recent(allowed=14.0, rank=6))

    assert (middling.standing, lately.standing, lately.turned) == (13, 9.5, False)
    assert lately.tone == "neutral"


@pytest.mark.parametrize(("season", "recent", "tone"), [(15, 4, "good"), (12, 30, "warning")])
def test_a_defense_whose_recent_rank_is_more_than_a_quarter_of_the_league_away_is_read_by_it(
    season: int, recent: int, tone: str
) -> None:
    """15th on the season but 4th lately, eleven places apart: a changed defense, the softest quarter."""
    matchup = Matchup(opponent="SF", position="TE", allowed=10.0, rank=season, defenses=32, recent=Recent(0.0, recent))

    assert (matchup.turned, matchup.standing, matchup.tone) == (True, recent, tone)


@pytest.mark.parametrize(("rank", "factor"), [(1, 1 + MATCHUP_SWING), (32, 1 - MATCHUP_SWING)])
def test_a_matchup_moves_a_players_weight_a_tenth_at_most_either_way(rank: int, factor: float) -> None:
    assert matchup_factor(
        Matchup(opponent="NYG", position="TE", allowed=10.0, rank=rank, defenses=32)
    ) == pytest.approx(factor)


def test_the_middle_ranks_move_a_players_weight_equally_either_way() -> None:
    def factor(rank: int) -> float:
        return matchup_factor(Matchup(opponent="NYG", position="TE", allowed=10.0, rank=rank, defenses=32))

    assert factor(16) - 1 == pytest.approx(1 - factor(17))


def test_a_matchups_weight_follows_its_standing() -> None:
    """12th and 20th lately stand at 16, as 16th alone does."""
    both = Matchup(opponent="NYG", position="TE", allowed=10.0, rank=12, defenses=32, recent=Recent(0.0, rank=20))

    assert matchup_factor(both) == pytest.approx(matchup_factor(replace(both, rank=16, recent=None)))


def test_no_matchup_moves_nothing() -> None:
    assert matchup_factor(None) == 1.0
    assert matchup_factor(Matchup(opponent="NYG", position="TE", allowed=1.0, rank=1, defenses=1)) == 1.0


# ── the offenses faced ────────────────────────────────────────────────


def test_a_defense_is_ranked_for_the_offenses_it_faced_while_its_figure_stays_what_it_gave_up() -> None:
    """SF and DAL each gave up 10 a game, SF to KC (20 a game elsewhere), DAL to NYG (5 a game elsewhere).

    KC scores 20 a game against everyone else, NYG 5: holding KC to 10 is the hard defense, giving NYG 10 the soft one.
    """
    lines = [
        Scored("SF", "TE", 1, 10.0, "KC"),
        Scored("DAL", "TE", 1, 10.0, "NYG"),
        *(Scored(f"D{week}", "TE", week, 20.0, "KC") for week in range(2, 5)),
        *(Scored(f"E{week}", "TE", week, 5.0, "NYG") for week in range(2, 5)),
    ]

    found = allowed(lines)

    sf, dal = found["SF", "TE"], found["DAL", "TE"]
    assert (sf.allowed, dal.allowed) == (10.0, 10.0)
    assert dal.rank < sf.rank
    assert (sf.adjusted or 0.0) < (dal.adjusted or 0.0)


def test_a_game_against_an_unknown_offense_counts_as_it_was() -> None:
    lines = [Scored("SF", "TE", 1, 10.0), Scored("DAL", "TE", 1, 4.0)]

    assert allowed(lines)["SF", "TE"].adjusted == 10.0


def test_a_matchups_line_carries_its_recent_rank() -> None:
    matchup = allowed(_turned())["SF", "TE"]

    assert matchup.recent is not None
    assert f"{matchup.recent.rank}st over last {RECENT_GAMES}" in matchup.allowed_to()
    assert "20.00" in matchup.describe()
