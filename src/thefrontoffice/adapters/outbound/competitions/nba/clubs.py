"""One NBA club, as each platform abbreviates it.

Basketball joins its league platform to ESPN's injury report by name within a
club, and the two spell six clubs differently. Like `competitions/names.py`
for players, this is identity across platforms, so it lives apart from any
reader of it.
"""

YAHOO_TO_ESPN = {"GSW": "GS", "NOP": "NO", "NYK": "NY", "SAS": "SA", "UTA": "UTAH", "WAS": "WSH"}
"""Where ESPN's abbreviation differs from Yahoo's, as both published them in November 2026."""


def espn_club(team: str) -> str:
    """A league platform's abbreviation for a club, in ESPN's spelling; read upper-cased."""
    club = team.upper()
    return YAHOO_TO_ESPN.get(club, club)
