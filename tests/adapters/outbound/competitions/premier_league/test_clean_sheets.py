"""Tests for a club's clean-sheet odds: its defence against the attack it faces, at home or away, settled early on."""

from dataclasses import replace

from support.fpl import player

from thefrontoffice.adapters.outbound.competitions.premier_league.clean_sheets import (
    DIFFICULTY_ODDS,
    Strength,
    strength,
)
from thefrontoffice.adapters.outbound.platforms.fpl.types import Fixture, Opponent, Player

ROUNDS = [(("TGT", "LKY"), ("STR", "WEK")), (("TGT", "STR"), ("LKY", "WEK")), (("TGT", "WEK"), ("LKY", "STR"))]
"""Four clubs, each playing once a round."""

RATES = {"TGT": (1.3, 0.6), "LKY": (1.3, 2.2), "STR": (2.4, 1.3), "WEK": (0.6, 1.3)}
"""Each club's expected goals for and against a match: a tight defence, a leaky one, a strong attack and a weak one."""


def _fixtures(rounds: int, home: int = 1, away: int = 1) -> list[Fixture]:
    """`rounds` rounds kicked off, each match ending `home`–`away`."""
    return [
        Fixture(
            event=n + 1,
            home=h,
            away=a,
            home_difficulty=3,
            away_difficulty=3,
            finished=True,
            home_score=home,
            away_score=away,
        )
        for n in range(rounds)
        for h, a in ROUNDS[n % len(ROUNDS)]
    ]


def _catalog(rounds: int) -> dict[int, Player]:
    """A forward carrying each club's expected goals and a keeper its expected goals conceded, over `rounds` matches."""
    catalog = {}
    for i, (club, (scored, conceded)) in enumerate(RATES.items()):
        catalog[i * 2] = replace(player(i * 2, "FWD", 5.0, team=club), expected_goals=scored * rounds)
        catalog[i * 2 + 1] = replace(
            player(i * 2 + 1, "GKP", 4.0, team=club), expected_goals_conceded=conceded * rounds
        )
    return catalog


def _season(rounds: int = 12, home: int = 1, away: int = 1) -> Strength:
    return strength(_catalog(rounds), _fixtures(rounds, home, away))


def test_a_tight_defence_against_a_weak_attack_keeps_more_clean_sheets_than_a_leaky_one_against_a_strong_attack() -> (
    None
):
    clubs = _season()

    tight = clubs.clean_sheet("TGT", Opponent("WEK", 3, True))
    leaky = clubs.clean_sheet("LKY", Opponent("STR", 3, True))

    assert tight > 0.5 > leaky
    # Each side alone moves it the same way: the defence, then the attack.
    assert clubs.clean_sheet("TGT", Opponent("STR", 3, True)) > clubs.clean_sheet("LKY", Opponent("STR", 3, True))
    assert clubs.clean_sheet("TGT", Opponent("WEK", 3, True)) > clubs.clean_sheet("TGT", Opponent("STR", 3, True))


def test_three_matches_in_a_club_is_mostly_average_and_a_season_in_mostly_itself() -> None:
    def spread(clubs: Strength) -> float:
        return clubs.clean_sheet("TGT", Opponent("WEK", 3, True)) - clubs.clean_sheet("LKY", Opponent("STR", 3, True))

    early, later = spread(_season(rounds=3)), spread(_season(rounds=30))
    assert 0 < early < later


def test_a_club_keeps_more_clean_sheets_at_home_where_the_league_scores_more_at_home() -> None:
    clubs = _season(home=2, away=1)

    assert clubs.clean_sheet("TGT", Opponent("STR", 3, True)) > clubs.clean_sheet("TGT", Opponent("STR", 3, False))


def test_the_venue_counts_for_little_before_the_league_has_played_much() -> None:
    assert _season(rounds=1, home=3, away=0).home < _season(rounds=30, home=3, away=0).home


def test_a_catalog_without_expected_goals_reads_the_real_ones() -> None:
    plain = {pid: player(pid, "GKP", 4.0, team=club) for pid, club in enumerate(RATES)}
    fixtures = [
        Fixture(
            event=1,
            home="TGT",
            away="STR",
            home_difficulty=3,
            away_difficulty=3,
            finished=True,
            home_score=0,
            away_score=3,
        ),
        Fixture(
            event=1,
            home="LKY",
            away="WEK",
            home_difficulty=3,
            away_difficulty=3,
            finished=True,
            home_score=0,
            away_score=0,
        ),
    ]
    clubs = strength(plain, fixtures)

    assert clubs.clean_sheet("LKY", Opponent("WEK", 3, True)) > clubs.clean_sheet("TGT", Opponent("STR", 3, True))


def test_a_club_with_no_matches_falls_back_on_the_fixtures_difficulty() -> None:
    clubs = _season()

    assert clubs.clean_sheet("NEW", Opponent("STR", 2, True)) == DIFFICULTY_ODDS[2]
    assert clubs.clean_sheet("TGT", Opponent("NEW", 5, True)) == DIFFICULTY_ODDS[5]
    assert clubs.clean_sheet("TGT", Opponent("NEW", 0, True)) == DIFFICULTY_ODDS[3]  # unrated is average


def test_before_a_ball_is_kicked_every_club_reads_by_difficulty() -> None:
    unplayed = [replace(f, finished=False) for f in _fixtures(1)]

    assert strength(_catalog(0), unplayed) == Strength()
    assert strength(_catalog(0), []).clean_sheet("TGT", Opponent("WEK", 1, True)) == DIFFICULTY_ODDS[1]


def test_a_season_of_goalless_draws_has_no_average_to_read_from() -> None:
    goalless = strength({}, _fixtures(2, home=0, away=0))
    assert goalless.clean_sheet("TGT", Opponent("WEK", 4, True)) == DIFFICULTY_ODDS[4]
