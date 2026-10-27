"""Each football player's injury designation as the latest report has it: ESPN's, joined to Sleeper.

Sleeper keeps a designation until somebody changes it, so on the Tuesday after
a game a player ruled out of it still reads Out — and every rule reading it
benches him for a week nobody has ruled on yet. ESPN's report is dated and
moves with the week's practices, so where it names a player it wins.

Where it does not, Sleeper's stands: a name that did not join is not news
that he is fit. The join is by name within one club, refusing a name two
players share, as the news is.
"""

from collections.abc import Mapping, Sequence

from thefrontoffice.adapters.outbound.competitions.names import normalize_name
from thefrontoffice.adapters.outbound.competitions.nfl.clubs import players_by_club
from thefrontoffice.adapters.outbound.competitions.nfl.model import PlayerInfo, Projection, Reported
from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport

ESPN_STATUS = {
    "Active": "",
    "Questionable": "Questionable",
    "Doubtful": "Doubtful",
    "Out": "Out",
    "Injured Reserve": "IR",
    "Physically Unable to Perform": "PUP",
    "Suspension": "Sus",
}
"""ESPN's designations in Sleeper's words, which the rules read. One not here changes nothing."""


def designations(reports: Sequence[InjuryReport], players: Mapping[str, PlayerInfo]) -> dict[str, str]:
    """Each reported player's designation, keyed by Sleeper's id; Active as none at all."""
    clubs = players_by_club(players)
    found = {}
    for report in reports:
        status = ESPN_STATUS.get(report.status)
        player_id = clubs.get(report.club, {}).get(normalize_name(report.name))
        if status is not None and player_id:
            found[player_id] = status
    return found


def reported(projections: Mapping[str, Projection], designations: Mapping[str, str]) -> dict[str, Projection]:
    """The projections, each under the designation the report gives him where it gives one."""
    return {
        pid: Reported.of(p, designations[pid]) if pid in designations and designations[pid] != p.injury_status else p
        for pid, p in projections.items()
    }


def catalog(players: Mapping[str, PlayerInfo], designations: Mapping[str, str]) -> dict[str, PlayerInfo]:
    """The player catalog, each under the designation the report gives him where it gives one."""
    updated = dict(players)
    for pid, status in designations.items():
        if pid in players and players[pid].get("injury_status", "") != status:
            meta = players[pid].copy()
            meta["injury_status"] = status
            updated[pid] = meta
    return updated
