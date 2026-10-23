"""Tests for reading platform timestamps: `platforms/timestamps.py`."""

from datetime import UTC, datetime, timedelta

from thefrontoffice.adapters.outbound.platforms.timestamps import parse_utc


def test_a_trailing_z_is_utc() -> None:
    """FPL and ESPN both end in Z."""
    assert parse_utc("2026-08-21T17:30:00Z") == datetime(2026, 8, 21, 17, 30, tzinfo=UTC)


def test_a_naive_timestamp_is_read_as_utc() -> None:
    assert parse_utc("2026-08-21T17:30:00").tzinfo == UTC


def test_an_offset_is_converted_to_utc_rather_than_kept() -> None:
    """Stored and compared as UTC everywhere, so two stamps of one instant are equal."""
    parsed = parse_utc("2026-08-21T10:30:00-07:00")
    assert parsed.utcoffset() == timedelta(0)
    assert parsed == datetime(2026, 8, 21, 17, 30, tzinfo=UTC)
