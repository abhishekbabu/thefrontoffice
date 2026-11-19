"""Tests for whether a player plays his next game, as every competition reads it: `competitions/availability.py`."""

import pytest

from thefrontoffice.adapters.outbound.competitions.availability import DOUBTFUL, QUESTIONABLE, expected_games


def test_a_doubt_discounts_his_next_game_alone() -> None:
    assert expected_games(3, QUESTIONABLE) == pytest.approx(2.8)


def test_a_single_game_is_worth_his_chance_of_playing_it() -> None:
    assert expected_games(1, DOUBTFUL) == pytest.approx(0.25)


def test_no_games_left_is_none_to_discount() -> None:
    assert expected_games(0, QUESTIONABLE) == 0.0


def test_a_player_cleared_plays_every_game() -> None:
    assert expected_games(4, 1.0) == 4.0
