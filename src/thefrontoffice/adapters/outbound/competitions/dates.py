"""Reading date labels and formatting dates the way a person reads them, on every platform.

`strftime`'s `%-d` — a day with no leading zero — is a glibc extension. macOS
and Linux accept it and Windows raises `ValueError: Invalid format string`, so
a date that reads fine on a laptop takes the page down on another machine. The
day is built here instead of asked for, and every sport formats through this.
"""

from datetime import date, datetime

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def parse_day(label: str) -> date | None:
    """The day an ISO date label names, or None when it names none.

    A label rather than an instant: platforms publish a game's day without a
    tip-off time, so this is compared against other days, never a clock. Only
    the first ten characters are read, so a timestamp yields its own day.
    """
    try:
        return date.fromisoformat(label[:10])
    except ValueError, TypeError:
        return None


def day_month(when: date) -> str:
    """'13 Sep' — the shortest form that still says which month."""
    return f"{when.day} {MONTHS[when.month - 1]}"


def weekday_day_month(when: date) -> str:
    """'Sun 13 Sep'. The weekday is what somebody checks a fixture against."""
    return f"{WEEKDAYS[when.weekday()]} {day_month(when)}"


def at_time(when: datetime) -> str:
    """'Sat 29 Aug, 14:00', in whatever zone the caller has already chosen."""
    return f"{weekday_day_month(when)}, {when:%H:%M}"
