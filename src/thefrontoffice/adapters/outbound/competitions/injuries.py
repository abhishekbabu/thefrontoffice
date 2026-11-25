"""ESPN's injury report joined to a league platform's players, and what the app shows of it.

ESPN publishes an injury report per sport with a dated status, the latest
one-line word and an estimated return; the league platforms publish a status
and little else. Whichever sport, the join is the same: by ESPN's athlete id
where the platform carries it, else by full name within one club — refusing a
name two players on a club share, and a name whose player carries a different
ESPN id, since either would show one player's injury on another.

Which players a sport offers, and how it spells a club for ESPN, is the
sport's own (`nfl/clubs.py`, `nba/clubs.py`); so is what a return date means
in its calendar, which `PlayerInjuries.stats` is told rather than knowing.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from thefrontoffice.adapters.outbound.competitions.dates import day_month, weekday_day_month
from thefrontoffice.adapters.outbound.competitions.names import normalize_name
from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport
from thefrontoffice.domain.models import Stat

BODY_PART = "Body part"
"""What is hurt, under one label whichever platform said it, so players compare row for row."""

CLEARED = "Active"
"""ESPN's status for a player back off the report, who has no injury left to show."""

type Clubs = dict[str, dict[str, str | None]]
"""Each club's players by normalized name, under ESPN's spelling of the club; None for a name two share."""


def by_club(players: Iterable[tuple[str, str, str]]) -> Clubs:
    """`(ESPN's club, full name, the platform's id)` for each player, indexed for `matched`.

    A name two players on one club share maps to None: it is nobody's, rather
    than whichever of them was indexed first.
    """
    clubs: Clubs = defaultdict(dict)
    for club, name, player_id in players:
        if key := normalize_name(name):
            roster = clubs[club]
            # The same player listed twice is still one player.
            roster[key] = None if key in roster and roster[key] != player_id else player_id
    return dict(clubs)


def matched(
    reports: Sequence[InjuryReport], clubs: Mapping[str, Mapping[str, str | None]], espn_ids: Mapping[str, str]
) -> dict[str, InjuryReport]:
    """Each reported player's row, keyed by the platform's id; the latest where ESPN lists him twice.

    `espn_ids` is the platform's id for each ESPN athlete id it carries — empty
    for a platform that carries none. A row joins on that first, then on his
    name within his club, unless the player that name finds carries an ESPN id
    of his own that is not this row's.
    """
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


UNSURE = (
    *("day to day", "no timetable", "without a timetable", "no return date", "no set return", "week to week"),
    *("uncertain", "unclear", "indefinitely", "no target date"),
)
"""What a report's latest word says of a return it does not firm: 'considered day-to-day as he progresses in his
rehab' under an estimated date is still no date."""


def unsure(report: InjuryReport) -> bool:
    """Whether the report gives him no firm return: none at all, or one its own latest word leaves open (`UNSURE`)."""
    text = f" {normalize_name(report.comment)} "
    return report.returns is None or any(f" {word} " in text for word in UNSURE)


def approximately(back: date) -> str:
    """'~22 Nov': an estimate, and it says so."""
    return f"~{day_month(back)}"


@dataclass(frozen=True)
class PlayerInjuries:
    """Each player's row on ESPN's injury report, keyed by the platform's id."""

    by_player: dict[str, InjuryReport] = field(default_factory=dict)

    def of(self, player_id: str) -> InjuryReport | None:
        """His row while he is still hurt; None for a player cleared or never on it."""
        report = self.by_player.get(player_id)
        return report if report and report.status != CLEARED else None

    def returns(self, player_id: str) -> date | None:
        report = self.of(player_id)
        return report.returns if report else None

    def stats(self, player_id: str, back: Callable[[date], str] = approximately) -> list[Stat]:
        """What, when he is back as `back` reads the day, and the latest word, linked to ESPN; nothing for a player not hurt."""
        report = self.of(player_id)
        if report is None:
            return []
        return injury_stats(
            report.status,
            injury=report.injury,
            returns=report.returns,
            comment=report.comment,
            updated=report.updated.date(),
            url=report.url,
            back=back,
        )


def in_words(status: str, words: Mapping[str, str]) -> str:
    """A platform's status code as a person would say it, 'O' as 'Out'; a code `words` lacks, as written.

    A table column has room for 'O'; a drawer's header should not make anyone
    decode it, and 'O' set alone reads as the figure zero.
    """
    return words.get(status.upper(), status)


def designation(status: str, body: str = "") -> list[Stat]:
    """The platform's own status and what is hurt, for a player ESPN's report does not have; empty for neither."""
    return [
        *([Stat(label="Status", value=status, tone="warning")] if status else []),
        *([Stat(label=BODY_PART, value=body)] if body else []),
    ]


def injury_stats(
    status: str,
    *,
    injury: str = "",
    returns: date | None = None,
    comment: str = "",
    updated: date | None = None,
    url: str = "",
    back: Callable[[date], str] = approximately,
) -> list[Stat]:
    """An Injury group's figures, the same whoever reported it: the status, what is hurt, when he is back as
    `back` reads the day, and the latest word under the day it was said.

    A word that says only the status again is left out, as ESPN's hand-filled rows do.
    """
    stats = [Stat(label="Status", value=status, tone="warning")]
    if injury:
        stats.append(Stat(label=BODY_PART, value=injury))
    if returns:
        stats.append(Stat(label="Back", value=back(returns)))
    if comment and comment.casefold() != status.casefold():
        stats.append(Stat(label=weekday_day_month(updated) if updated else "Latest", value=comment, url=url))
    return stats
