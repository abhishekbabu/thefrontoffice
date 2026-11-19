"""Each football player's injury designation as the latest report has it: ESPN's, joined to Sleeper.

Sleeper keeps a designation until somebody changes it, so on the Tuesday after
a game a player ruled out of it still reads Out — and every rule reading it
benches him for a week nobody has ruled on yet. ESPN's report is dated and
moves with the week's practices, so where it names a player it wins.

Where it does not, Sleeper's stands: a name that did not join is not news
that he is fit.

The join is by ESPN's own athlete id where Sleeper carries it, which is the
one identifier the two share — but Sleeper carries it for barely a quarter of
the injured, so a row with no id match falls back to his full name within one
club, refusing a name two players share, as the news does. A name match whose
player carries a different ESPN id is somebody else, and matches nothing.

The report keeps only a club's latest twenty-five entries, so a player hurt
weeks ago has often fallen off it while Sleeper still has him out. For those,
the provider asks ESPN after each one by id (`ESPNSource.get_athlete_injuries`):
Sleeper's ESPN id where it carries one, otherwise the one his name finds on his
club's ESPN roster — the same full-name join, refusing a name two players share.

The report also says when he is expected back. That is a day; which fantasy
week it is depends on the schedule, so the week is worked out here from it.
"""

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from datetime import date

from thefrontoffice.adapters.outbound.competitions import injuries as shared
from thefrontoffice.adapters.outbound.competitions.dates import day_month
from thefrontoffice.adapters.outbound.competitions.names import normalize_name
from thefrontoffice.adapters.outbound.competitions.nfl.clubs import espn_club, on_a_club, players_by_club
from thefrontoffice.adapters.outbound.competitions.nfl.model import Game, PlayerInfo, Projection, Reported
from thefrontoffice.adapters.outbound.competitions.nfl.rules import ruled_out
from thefrontoffice.adapters.outbound.platforms.espn.types import Athlete, InjuryReport

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


def matched(
    reports: Sequence[InjuryReport], players: Mapping[str, PlayerInfo], espn_ids: Mapping[str, str]
) -> dict[str, InjuryReport]:
    """Each reported player's row, keyed by Sleeper's id (`competitions/injuries.matched`).

    `espn_ids` is Sleeper's id for each ESPN athlete id it carries; the name
    join is over his fantasy players on a club (`clubs.players_by_club`).
    """
    return shared.matched(reports, players_by_club(players), espn_ids)


def unreported(players: Mapping[str, PlayerInfo], found: Mapping[str, InjuryReport]) -> list[str]:
    """Who Sleeper has ruled out, on a club and at a fantasy position, that the report did not name.

    The players the app needs a return for — on IR, PUP or out — and the only
    ones worth a request each. Those it did name, even as cleared, it has spoken for.
    """
    return sorted(
        pid for pid, meta in players.items() if pid not in found and on_a_club(meta) and ruled_out(meta.injury_status)
    )


def athletes(
    wanted: Sequence[str], players: Mapping[str, PlayerInfo], espn_ids: Mapping[str, str], roster: Sequence[Athlete]
) -> dict[str, Athlete]:
    """ESPN's athlete for each of `wanted`, keyed by Sleeper's id; nobody whose id cannot be settled.

    Sleeper's own ESPN id first. Failing that, his full name on his club's
    ESPN roster — unless two there share it, or the id it finds is one Sleeper
    gives somebody else.
    """
    known = {pid: eid for eid, pid in espn_ids.items()}
    by_name: dict[str, dict[str, Athlete | None]] = defaultdict(dict)
    for athlete in roster:
        names = by_name[athlete.club]
        if key := normalize_name(athlete.name):
            names[key] = None if key in names else athlete
    found: dict[str, Athlete] = {}
    for pid in wanted:
        meta = players[pid]
        club = espn_club(meta.team)
        if pid in known:
            found[pid] = Athlete(athlete_id=known[pid], name=meta.name, club=club)
        elif (athlete := by_name[club].get(normalize_name(meta.name))) and athlete.athlete_id not in espn_ids:
            found[pid] = athlete
    return found


def designations(reports: Mapping[str, InjuryReport]) -> dict[str, str]:
    """Each matched player's designation, keyed by Sleeper's id; Active as none at all."""
    return {pid: status for pid, r in reports.items() if (status := ESPN_STATUS.get(r.status)) is not None}


def return_week(back: date, schedule: Mapping[int, Sequence[Game]]) -> int | None:
    """The first week with a game on or after `back`; None where the season has none left by then."""
    weeks = [w for w, games in schedule.items() if any(game.date[:10] >= back.isoformat() for game in games)]
    return min(weeks, default=None)


def short_return(back: date, schedule: Mapping[int, Sequence[Game]]) -> str:
    """'wk 12' in a table cell, or the day itself past the season's last game."""
    week = return_week(back, schedule)
    return f"wk {week}" if week else day_month(back)


def long_return(back: date, schedule: Mapping[int, Sequence[Game]]) -> str:
    """'~22 Nov · wk 12', or just the day past the season's last game: an estimate, and it says so."""
    week = return_week(back, schedule)
    return shared.approximately(back) + (f" · wk {week}" if week else "")


def reported(projections: Mapping[str, Projection], designations: Mapping[str, str]) -> dict[str, Projection]:
    """The projections, each under the designation the report gives him where it gives one."""
    return {
        pid: Reported.of(p, designations[pid]) if pid in designations and designations[pid] != p.injury_status else p
        for pid, p in projections.items()
    }


def catalog[P: PlayerInfo](
    players: Mapping[str, P], designations: Mapping[str, str], designate: Callable[[P, str], P]
) -> dict[str, P]:
    """The player catalog, each under the designation the report gives him where it gives one.

    `designate` is the platform's own copy of an entry under a new designation:
    the catalog's type is the platform's, and only it knows how one is made.
    """
    updated = dict(players)
    for pid, status in designations.items():
        if pid in players and players[pid].injury_status != status:
            updated[pid] = designate(players[pid], status)
    return updated
