"""Tests for the shared date formatting.

These exist because of a platform difference, not a formatting preference:
`%-d` is a glibc extension that Windows rejects outright, so the same page
rendered on a laptop and raised `ValueError` in CI. Nothing here may reach for
`strftime` with a dash-modifier again.
"""

from datetime import UTC, date, datetime

from thefrontoffice.adapters.outbound.competitions.dates import at_time, day_month, parse_day, weekday_day_month


def test_a_day_carries_no_leading_zero() -> None:
    assert day_month(date(2026, 9, 3)) == "3 Sep"


def test_a_two_digit_day_is_unchanged() -> None:
    assert day_month(date(2026, 9, 13)) == "13 Sep"


def test_every_month_has_a_name() -> None:
    """An off-by-one in the month table is silent and wrong all year."""
    names = [day_month(date(2026, m, 1)).split()[1] for m in range(1, 13)]
    assert names == ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def test_a_weekday_is_the_one_the_date_actually_falls_on() -> None:
    """13 September 2026 is a Sunday."""
    assert weekday_day_month(date(2026, 9, 13)) == "Sun 13 Sep"


def test_every_weekday_has_a_name() -> None:
    days = [weekday_day_month(date(2026, 9, 7 + i)).split()[0] for i in range(7)]
    assert days == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def test_a_time_is_shown_beside_the_day() -> None:
    assert at_time(datetime(2026, 8, 29, 14, 0, tzinfo=UTC)) == "Sat 29 Aug, 14:00"


def test_a_time_keeps_its_leading_zero() -> None:
    """A clock reads 09:30, not 9:30 — the dash rule is about the date only."""
    assert at_time(datetime(2026, 8, 29, 9, 5, tzinfo=UTC)) == "Sat 29 Aug, 09:05"


def test_a_date_label_reads_as_its_day() -> None:
    assert parse_day("2026-02-09") == date(2026, 2, 9)


def test_a_timestamp_reads_as_the_day_it_falls_on() -> None:
    assert parse_day("2026-02-09T19:30:00") == date(2026, 2, 9)


def test_a_label_that_names_no_day_is_none() -> None:
    assert parse_day("not-a-date") is None
