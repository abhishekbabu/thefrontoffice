"""Reading the timestamps platforms publish.

FPL deadlines and ESPN articles both stamp UTC with a trailing 'Z', which
`datetime.fromisoformat` rejects on Python 3.10 — the floor this project
supports. Every platform timestamp is parsed here so none re-learns that.
"""

from datetime import datetime, timezone


def parse_utc(value: str) -> datetime:
    """An ISO-8601 timestamp as an aware UTC datetime.

    A naive one is taken to be UTC: that is what every platform here means by
    a timestamp with no offset, and comparing it against an aware `now` would
    otherwise raise.
    """
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
