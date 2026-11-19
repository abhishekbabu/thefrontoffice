"""The gameweeks ahead for one squad: each player's run of fixtures, and the weeks that blank or double.

FPL projects one gameweek and no further, so the weeks after it are read the way
a manager reads them on FPL's own fixture ticker: who each club plays, home or
away, and how hard the game rates it. What changes a plan is a blank (no match,
so no points), a double (two matches, so two goes at them), a stretch of hard
fixtures, and a player already in doubt — so only a player with one of those
gets a row, and everybody else is a count.
"""

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime

from thefrontoffice.adapters.outbound.competitions.premier_league.league import HARD_FIXTURE
from thefrontoffice.adapters.outbound.competitions.premier_league.rules import Roster
from thefrontoffice.adapters.outbound.platforms.fpl.types import Fixture, Player
from thefrontoffice.domain.models import FixtureRun, FixtureWeek, Opposition, Outlook, Stat

RUN_WEEKS = 5
"""How far ahead the grid reads: about as far as a transfer made now is still being judged on."""

HARD_RUN = 3
"""Hard fixtures (4+) in the five that earn a player his row: most clubs face two in any five, so two is no signal."""

UNSCHEDULED = datetime.max.replace(tzinfo=UTC)
"""Where a match with a gameweek but no kickoff yet sorts: after every match that has one."""

type Ticker = dict[tuple[int, str], list[Opposition]]
"""Each club's matches in each gameweek, by `(gameweek, club)`, in kickoff order."""


def ticker(fixtures: Iterable[Fixture]) -> Ticker:
    """Every club's matches by gameweek, from the season's fixture list; a match with no gameweek yet is left out."""
    by: Ticker = defaultdict(list)
    ordered = sorted((f for f in fixtures if f.event is not None), key=lambda f: f.kickoff or UNSCHEDULED)
    for f in ordered:
        week = f.event or 0
        by[(week, f.home)].append(Opposition(opponent=f.away, home=True, difficulty=f.home_difficulty))
        by[(week, f.away)].append(Opposition(opponent=f.home, home=False, difficulty=f.away_difficulty))
    return dict(by)


def run_of(club: str, weeks: Iterable[int], by: Ticker) -> list[FixtureWeek]:
    """One club's matches in each of `weeks`, a blank included as a week with none."""
    return [FixtureWeek(week=week, games=list(by.get((week, club), []))) for week in weeks]


def weeks_from(first: int, last: int) -> list[int]:
    """The gameweeks the grid covers: `RUN_WEEKS` from `first`, stopping at the season's `last`."""
    return list(range(first, min(first + RUN_WEEKS, last + 1)))


def flags(player: Player, run: list[FixtureWeek]) -> list[str]:
    """What in his run is worth acting on, soonest first: blanks, doubles, a hard stretch, a doubt."""
    found = [f"blank GW{w.week}" if not w.games else f"double GW{w.week}" for w in run if len(w.games) != 1]
    hard = sum(g.difficulty >= HARD_FIXTURE for w in run for g in w.games)
    if hard >= HARD_RUN:
        found.append(f"{hard} hard")
    if player.availability:
        found.append(player.availability)
    return found


def outlook(squad: Roster, fixtures: Iterable[Fixture], weeks: list[int]) -> Outlook:
    """The squad's runs over `weeks`: a row for each player with something to act on, and each week that blanks or doubles."""
    if not weeks:
        return Outlook()
    by = ticker(fixtures)
    runs = []
    for player in squad.players:
        run = run_of(player.team, weeks, by)
        runs.append(
            FixtureRun(
                player_id=str(player.id),
                player=player.name,
                detail=f"{player.position} · {player.team}",
                weeks=run,
                flags=flags(player, run),
            )
        )
    flagged = [run for run in runs if run.flags]
    return Outlook(run_weeks=weeks, runs=flagged, clear=len(runs) - len(flagged), warnings=warnings(runs, weeks))


def warnings(runs: list[FixtureRun], weeks: list[int]) -> list[Stat]:
    """Each week a blank or a double lands on the squad, naming who: a blank costs a starter, a double is a chip week."""
    stats = []
    for i, week in enumerate(weeks):
        blank = [run.player for run in runs if not run.weeks[i].games]
        double = [run.player for run in runs if len(run.weeks[i].games) > 1]
        if blank:
            stats.append(Stat(label=f"GW{week}", value=f"{len(blank)} blank: {', '.join(blank)}", tone="warning"))
        if double:
            stats.append(Stat(label=f"GW{week}", value=f"{len(double)} double: {', '.join(double)}", tone="good"))
    return stats
