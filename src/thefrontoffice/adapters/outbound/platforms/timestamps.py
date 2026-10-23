"""Reading the timestamps platforms publish.

Platforms disagree about offsets: FPL and ESPN stamp UTC with a trailing 'Z',
others send none at all and mean UTC by it. Every platform timestamp is parsed
here, so each comes out aware and in UTC — comparable with every other, and
with an aware `now`.
"""

from datetime import UTC, datetime


def parse_utc(value: str) -> datetime:
    """An ISO-8601 timestamp as an aware UTC datetime.

    A naive one is taken to be UTC: that is what every platform here means by
    a timestamp with no offset, and comparing it against an aware `now` would
    otherwise raise.
    """
    parsed = datetime.fromisoformat(value.strip())
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
