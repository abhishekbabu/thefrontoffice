"""One NFL club, as each platform abbreviates it, and the players on it by name.

The football joins Sleeper to ESPN three times — a club's news feed, its injury
report, and its game on the live scoreboard — and each needs the same spelling
of the same club. Like `competitions/names.py` for players, this is identity
across platforms, so it lives apart from any reader of it.
"""

from collections.abc import Mapping

from thefrontoffice.adapters.outbound.competitions.injuries import Clubs, by_club
from thefrontoffice.adapters.outbound.competitions.nfl.model import FREE_AGENT, PlayerInfo
from thefrontoffice.adapters.outbound.competitions.nfl.rules import FANTASY_POSITIONS

SLEEPER_TO_ESPN = {"WAS": "WSH"}
"""Where ESPN's abbreviation differs from Sleeper's. Washington is the only one."""

# A team defense is filed under the club's own name, and everything ESPN
# says about the club would read as being about it.
NOT_PLAYERS = frozenset({"DEF"})


def espn_club(team: str) -> str:
    """Sleeper's abbreviation for a club, in ESPN's spelling."""
    return SLEEPER_TO_ESPN.get(team, team)


def on_a_club(meta: PlayerInfo) -> bool:
    """Whether he is a fantasy player on a club: someone ESPN reports on, and not a team defense."""
    return meta.team != FREE_AGENT and meta.position in FANTASY_POSITIONS and meta.position not in NOT_PLAYERS


def players_by_club(players: Mapping[str, PlayerInfo]) -> Clubs:
    """Each club's fantasy players by normalized name, under ESPN's spelling of the club (`injuries.by_club`)."""
    return by_club((espn_club(meta.team), meta.name, pid) for pid, meta in players.items() if on_a_club(meta))
