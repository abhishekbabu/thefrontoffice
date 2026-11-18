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

The report also says when he is expected back. That is a day; which fantasy
week it is depends on the schedule, so the week is worked out here from it.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from thefrontoffice.adapters.outbound.competitions.dates import day_month, weekday_day_month
from thefrontoffice.adapters.outbound.competitions.names import normalize_name
from thefrontoffice.adapters.outbound.competitions.nfl.clubs import players_by_club
from thefrontoffice.adapters.outbound.competitions.nfl.model import Game, PlayerInfo, Projection, Reported
from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport
from thefrontoffice.domain.models import Stat

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


BODY_PART = "Body part"
"""What is hurt, under one label whichever platform said it, so players compare row for row."""

CLEARED = "Active"
"""ESPN's status for a player back off the report, who has no injury left to show."""


def matched(
    reports: Sequence[InjuryReport], players: Mapping[str, PlayerInfo], espn_ids: Mapping[str, str]
) -> dict[str, InjuryReport]:
    """Each reported player's row, keyed by Sleeper's id.

    `espn_ids` is Sleeper's id for each ESPN athlete id it carries. A row
    joins on that first, then on his name within his club — unless the
    player that name finds carries an ESPN id of his own that is not this row's.
    """
    clubs = players_by_club(players)
    known = {pid: eid for eid, pid in espn_ids.items()}
    found: dict[str, InjuryReport] = {}
    for report in reports:
        player_id = espn_ids.get(report.athlete_id) if report.athlete_id else None
        if not player_id:
            named = clubs.get(report.club, {}).get(normalize_name(report.name))
            theirs = known.get(named or "", "")
            player_id = named if named and not (theirs and report.athlete_id and theirs != report.athlete_id) else None
        if player_id and (player_id not in found or report.updated > found[player_id].updated):
            found[player_id] = report
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
    return f"~{day_month(back)}" + (f" · wk {week}" if week else "")


@dataclass(frozen=True)
class PlayerInjuries:
    """Each player's row on ESPN's injury report, keyed by Sleeper's id."""

    by_player: dict[str, InjuryReport] = field(default_factory=dict)

    def of(self, player_id: str) -> InjuryReport | None:
        """His row while he is still hurt; None for a player cleared or never on it."""
        report = self.by_player.get(player_id)
        return report if report and report.status != CLEARED else None

    def returns(self, player_id: str) -> date | None:
        report = self.of(player_id)
        return report.returns if report else None

    def stats(self, player_id: str, schedule: Mapping[int, Sequence[Game]]) -> list[Stat]:
        """What, when he is back, and the latest word, linked to ESPN; nothing for a player not hurt."""
        report = self.of(player_id)
        if report is None:
            return []
        stats = [Stat(label="Status", value=report.status, tone="warning")]
        if report.injury:
            stats.append(Stat(label=BODY_PART, value=report.injury))
        if report.returns:
            stats.append(Stat(label="Back", value=long_return(report.returns, schedule)))
        # A row ESPN filled by hand says only the status again.
        if report.comment and report.comment.casefold() != report.status.casefold():
            stats.append(Stat(label=weekday_day_month(report.updated.date()), value=report.comment, url=report.url))
        return stats


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
