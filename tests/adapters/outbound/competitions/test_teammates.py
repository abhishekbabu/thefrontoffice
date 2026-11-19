"""Tests for the teammate split every competition shares: `competitions/teammates.py`.

Games are numbered as the season played them; the club is LV.
"""

from dataclasses import dataclass

import pytest

from thefrontoffice.adapters.outbound.competitions.teammates import (
    figures,
    games,
    heading,
    parted,
    recently_absent,
    surname,
    tone,
)


@dataclass(frozen=True)
class Game:
    game: int
    team: str = "LV"
    partial: bool = False


def _numbers(found: list[Game]) -> list[int]:
    return [g.game for g in found]


def test_his_games_part_by_whether_the_teammate_played_them() -> None:
    found = parted([Game(1), Game(2), Game(3)], [Game(1), Game(3)], "LV")

    assert (_numbers(found.without), _numbers(found.alongside)) == ([2], [1, 3])


def test_a_game_the_teammate_left_early_counts_as_one_he_missed() -> None:
    found = parted([Game(1), Game(2)], [Game(1), Game(2, partial=True)], "LV")

    assert (_numbers(found.without), _numbers(found.alongside)) == ([2], [1])


def test_a_game_the_teammate_played_for_another_club_counts_neither_way() -> None:
    found = parted([Game(1), Game(2)], [Game(1, team="KC")], "LV")

    assert (_numbers(found.without), _numbers(found.alongside)) == ([2], [])


def test_only_his_own_games_for_the_club_count() -> None:
    found = parted([Game(1, team="KC"), Game(2)], [], "LV")

    assert _numbers(found.without) == [2]


def test_a_regular_who_sat_out_one_of_the_clubs_last_games_is_recently_absent() -> None:
    appearances = {
        "star": [Game(1), Game(2), Game(4)],
        "backup": [Game(g) for g in (1, 2, 3, 4)],
    }

    assert recently_absent(appearances, 3) == {"star"}
    # Game 3 is not the club's last.
    assert recently_absent(appearances, 1) == set()


def test_games_before_he_joined_the_club_are_no_absence() -> None:
    appearances = {
        "signing": [Game(1, team="KC"), Game(3), Game(4)],
        "backup": [Game(g) for g in (1, 2, 3, 4)],
    }

    assert recently_absent(appearances, 4) == set()


def test_the_figure_without_him_comes_first_while_he_sits() -> None:
    text = figures(False, "6.10", 3, "8.60", 4)

    assert text.index("6.10") < text.index("8.60")
    assert "3 games" in text


def test_the_figure_beside_him_comes_first_once_he_is_back() -> None:
    text = figures(True, "6.10", 3, "8.60", 4)

    assert text.index("8.60") < text.index("6.10")
    assert "4 games" in text and "3 games" in text


def test_a_split_with_no_game_beside_him_says_so() -> None:
    assert "never with" in figures(False, "6.10", 1, None, 0)


def test_a_heading_says_with_once_the_teammate_is_due_back() -> None:
    assert heading(False, "Brock Bowers", "TE, O").startswith("Without Brock Bowers")
    assert heading(True, "Brock Bowers", "TE, Q").startswith("With Brock Bowers")


def test_a_heading_names_every_teammate_who_missed_the_same_games() -> None:
    text = heading(False, "Jalen Williams", "O", ("Chet Holmgren", "O"))

    assert text.startswith("Without Jalen Williams")
    assert text.index("Jalen Williams") < text.index("Chet Holmgren")


@pytest.mark.parametrize(
    ("back", "without", "alongside", "expected"),
    [
        (False, 9.0, 6.0, "good"),
        (False, 6.0, 9.0, "warning"),
        (True, 9.0, 6.0, "warning"),
        (True, 6.0, None, "neutral"),
    ],
)
def test_the_tone_follows_the_figure_that_counts(
    back: bool, without: float, alongside: float | None, expected: str
) -> None:
    assert tone(back, without, alongside) == expected


def test_a_count_of_games_reads_in_the_singular_for_one() -> None:
    assert (games(1), games(2)) == ("1 game", "2 games")


@pytest.mark.parametrize(
    ("name", "short"),
    [("Brock Bowers", "Bowers"), ("Marvin Harrison Jr.", "Harrison"), ("Kenneth Walker III", "Walker"), ("Jr", "Jr")],
)
def test_a_surname_leaves_a_generational_suffix_off(name: str, short: str) -> None:
    assert surname(name) == short
