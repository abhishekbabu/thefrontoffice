"""Tests for how a simulated score is read: `application/results.py`."""

from thefrontoffice.application.results import quantile, result


def test_a_win_counts_one_a_tie_half_and_a_loss_nothing() -> None:
    assert [result(3, 1), result(2, 2), result(1, 3)] == [1.0, 0.5, 0.0]


def test_a_quantile_is_the_value_that_share_of_the_way_up() -> None:
    ordered = [float(n) for n in range(10)]
    assert (quantile(ordered, 0.1), quantile(ordered, 0.5), quantile(ordered, 0.9)) == (1.0, 5.0, 9.0)


def test_the_top_quantile_is_the_largest_value_rather_than_past_it() -> None:
    assert quantile([1.0, 2.0], 1.0) == 2.0
