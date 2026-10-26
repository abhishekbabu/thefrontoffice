"""One NFL club, as each platform abbreviates it.

The football joins Sleeper to ESPN twice — a club's news feed, and its game on
the live scoreboard — and both need the same spelling of the same club. Like
`competitions/names.py` for players, this is identity across platforms, so it
lives apart from either reader of it.
"""

SLEEPER_TO_ESPN = {"WAS": "WSH"}
"""Where ESPN's abbreviation differs from Sleeper's. Washington is the only one."""


def espn_club(team: str) -> str:
    """Sleeper's abbreviation for a club, in ESPN's spelling."""
    return SLEEPER_TO_ESPN.get(team, team)
