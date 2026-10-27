"""One NFL club, as each platform abbreviates it, and the players on it by name.

The football joins Sleeper to ESPN three times — a club's news feed, its injury
report, and its game on the live scoreboard — and each needs the same spelling
of the same club. Like `competitions/names.py` for players, this is identity
across platforms, so it lives apart from any reader of it.
"""

from collections import defaultdict
from collections.abc import Mapping

from thefrontoffice.adapters.outbound.competitions.names import normalize_name
from thefrontoffice.adapters.outbound.competitions.nfl.model import PlayerInfo
from thefrontoffice.adapters.outbound.competitions.nfl.rules import FANTASY_POSITIONS

SLEEPER_TO_ESPN = {"WAS": "WSH"}
"""Where ESPN's abbreviation differs from Sleeper's. Washington is the only one."""

# A team defense is filed under the club's own name, and everything ESPN
# says about the club would read as being about it.
NOT_PLAYERS = frozenset({"DEF"})


def espn_club(team: str) -> str:
    """Sleeper's abbreviation for a club, in ESPN's spelling."""
    return SLEEPER_TO_ESPN.get(team, team)


def players_by_club(players: Mapping[str, PlayerInfo]) -> dict[str, dict[str, str | None]]:
    """Each club's fantasy players by normalized name, under ESPN's spelling of the club.

    The two platforms share no player identifier, so a join is by name within
    one club. A name two players on a club share maps to None: it is nobody's,
    rather than whichever of them was indexed first.
    """
    clubs: dict[str, dict[str, str | None]] = defaultdict(dict)
    for player_id, meta in players.items():
        team, position, name = str(meta.get("team") or ""), str(meta.get("position") or ""), meta.get("name")
        if not team or team == "FA" or position not in FANTASY_POSITIONS or position in NOT_PLAYERS or not name:
            continue
        key = normalize_name(str(name))
        if not key:
            continue
        roster = clubs[espn_club(team)]
        roster[key] = None if key in roster else player_id
    return dict(clubs)
