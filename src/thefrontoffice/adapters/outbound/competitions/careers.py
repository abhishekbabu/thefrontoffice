"""A player's career as a drawer says it, in every competition: how long he has played, and the seasons behind him."""

PAST_SEASONS = 2
"""Seasons a drawer shows before this one: two rather than a career, since three years back is a different
team, a different role and usually a different player."""


def experience(years: int) -> str:
    """'rookie', '1 season', '7 seasons'."""
    return "rookie" if years == 0 else f"{years} season{'' if years == 1 else 's'}"


def recent_seasons(season: str) -> list[str]:
    """The `PAST_SEASONS` seasons before this one, newest first; none where `season` is not a year."""
    try:
        year = int(season)
    except ValueError:
        return []
    return [str(year - back) for back in range(1, PAST_SEASONS + 1)]
