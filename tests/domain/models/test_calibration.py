"""Tests for the models of how the simulations held up."""

import pytest

from thefrontoffice.domain.models import calibration


def test_chances_are_scored_and_bucketed_by_the_chance_given() -> None:
    called = [(0.9, 1.0), (0.9, 0.0), (0.1, 0.0), (1.0, 1.0)]

    found = calibration(called)

    assert found.matchups == 4
    assert found.brier == pytest.approx((0.01 + 0.81 + 0.01 + 0.0) / 4)
    assert [(b.low, b.high, b.matchups) for b in found.buckets] == [(0.0, 0.2, 1), (0.8, 1.0, 3)]


def test_buckets_a_tenth_apart_split_what_a_fifth_would_hold_together() -> None:
    found = calibration([(0.81, 1.0), (0.95, 0.5)], width=0.1)

    assert [(b.low, b.predicted, b.won) for b in found.buckets] == [(0.8, 0.81, 1.0), (0.9, 0.95, 0.5)]


def test_nothing_called_scores_nothing() -> None:
    assert calibration([]).matchups == 0
