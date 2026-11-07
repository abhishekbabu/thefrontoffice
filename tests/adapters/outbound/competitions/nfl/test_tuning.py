"""Tests for the NFL's range settings as a tuning run searches them: `nfl/tuning.py`."""

import pytest

from thefrontoffice.adapters.outbound.competitions.nfl import outcomes, tuning


def test_the_current_settings_are_the_apps_own_and_among_the_values_tried() -> None:
    for name, value in tuning.SEARCH.current.items():
        assert value == getattr(outcomes.DEFAULT, name)
        assert value in tuning.SEARCH.grid[name]


def test_a_candidate_overrides_only_the_settings_it_names() -> None:
    chosen = tuning.settings({"max_ratio": 6.0})

    assert chosen.max_ratio == 6.0
    assert chosen.own_half == outcomes.DEFAULT.own_half


def test_a_setting_the_search_does_not_cover_is_refused_rather_than_ignored() -> None:
    with pytest.raises(KeyError, match="min_games"):
        tuning.settings({"min_games": 1.0})
