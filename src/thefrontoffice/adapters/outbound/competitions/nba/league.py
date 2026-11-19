"""The league beyond this week: the table, and your head-to-head season week by week.

Yahoo publishes no season schedule as such, but every week's scoreboard lists
every pairing in it, so your season is your side of each one. The playoff weeks
are named from the bracket the settings describe, as football names its own.

Also which season a date belongs to, and where a league and its teams live on Yahoo.
"""

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta

from thefrontoffice.adapters.outbound.competitions import brackets
from thefrontoffice.adapters.outbound.competitions.dates import span
from thefrontoffice.adapters.outbound.competitions.nba.rules import PACIFIC
from thefrontoffice.adapters.outbound.platforms.yahoo.types import LeagueSettings, Pairing, YahooTeam
from thefrontoffice.domain.models import Outcome, ScheduleRow, StandingRow, record

BYE = "bye"
"""A regular-season week with no matchup: Yahoo pairs every team every week, so this is rare."""

CONSOLATION = "Consolation"
"""A playoff week played outside the championship bracket."""

# Where the moves are actually made. Unlike the other two platforms these
# cannot be checked from here — the sport is behind an approval this app does
# not have — so they follow Yahoo's documented shape rather than a probe.
LEAGUE_URL = "https://basketball.fantasysports.yahoo.com/nba/{league_id}"
TEAM_URL = "https://basketball.fantasysports.yahoo.com/nba/{league_id}/{team_id}"


def season_year(now: datetime | None = None) -> int:
    """The NBA season a date belongs to, which rolls over on 1 September,
    ahead of October's opening night.

    Read in Pacific time, like the rest of basketball: a local clock would
    put the night of 31 August in a different season depending on where
    the machine is.
    """
    moment = (now or datetime.now(PACIFIC)).astimezone(PACIFIC)
    return moment.year if moment.month >= 9 else moment.year - 1


def league_url(league_key: str) -> str:
    """A league's page on Yahoo: `<game>.l.<league>` addressed by its number."""
    numbers = _key_numbers(league_key, "l")
    return LEAGUE_URL.format(league_id=numbers[0]) if numbers else ""


def team_url(team_key: str) -> str:
    """A team's page on Yahoo: `<game>.l.<league>.t.<team>` addressed by its two numbers."""
    numbers = _key_numbers(team_key, "l", "t")
    return TEAM_URL.format(league_id=numbers[0], team_id=numbers[1]) if numbers else ""


def _key_numbers(key: str, *kinds: str) -> list[str]:
    """The number after each of `kinds` in a Yahoo key; empty for a key in any other shape.

    A URL wants the numbers, not the key — so a key in an unexpected shape
    yields no link rather than a broken one.
    """
    parts = key.split(".")
    if len(parts) != 1 + 2 * len(kinds) or tuple(parts[1::2]) != kinds:
        return []
    return parts[2::2]


WEEK = timedelta(days=7)


def week_dates(drawn: Mapping[int, Sequence[Pairing]]) -> dict[int, tuple[date, date]]:
    """Each week's first and last day: its scoreboard's, or for a week nobody is drawn in yet — a playoff week
    before the bracket — the seven days after the week before it.

    A week before every drawn one has no dates to follow on from, and is left out.
    """
    dates: dict[int, tuple[date, date]] = {}
    for week in sorted(drawn):
        found = drawn[week]
        if found:
            dates[week] = (found[0].start, found[0].end)
        elif week - 1 in dates:
            start = dates[week - 1][1] + timedelta(days=1)
            dates[week] = (start, start + WEEK - timedelta(days=1))
    return dates


def table(teams: list[YahooTeam], mine: str) -> list[StandingRow]:
    """The table in rank order; a team Yahoo sent without its standings has no row in it.

    Yours is marked by `mine`, the key of the team you own, rather than by the
    table's own flag, which Yahoo's read-only host may leave out.
    """
    rows = [
        StandingRow(
            rank=standing.rank,
            name=team.name,
            # The seed says something the rank does not only once the bracket has reordered the table.
            detail=f"Seed {standing.playoff_seed}"
            if standing.playoff_seed and standing.playoff_seed != standing.rank
            else "",
            record=standing.record,
            points=standing.points_for,
            points_against=standing.points_against,
            waiver_budget=f"${team.faab_balance}" if team.faab_balance else "",
            waiver_order=str(team.waiver_priority) if team.waiver_priority else "",
            team_id=team.team_key,
            is_mine=team.team_key == mine,
        )
        for team in teams
        if (standing := team.standing) is not None
    ]
    return sorted(rows, key=lambda row: row.rank)


def season(
    weeks: Mapping[int, Pairing | None],
    rules: LeagueSettings,
    current: int,
    records: Mapping[str, str],
    *,
    points: bool,
) -> list[ScheduleRow]:
    """Your season, week by week: who you play, their record, and how it went.

    `records` is each team's record by key, from the table. `points` is whether
    the league is won on fantasy points (`YahooLeague.by_points`), whose score
    a week then shows, rather than on categories.
    """
    rows = []
    for week, found in sorted(weeks.items()):
        playoff = _round(rules, week)
        if found is not None and found.consolation:
            playoff = CONSOLATION
        rows.append(
            ScheduleRow(
                label=f"Week {week}",
                date=span(found.start, found.end) if found else "",
                opponent=found.opponent.name if found else "",
                detail=playoff or (records.get(found.opponent.team_key, "") if found else BYE),
                result=_result(found, week, current, points=points),
                outcome=ended(found),
                is_current=week == current,
                playoffs=bool(playoff),
            )
        )
    return rows


def _round(rules: LeagueSettings, week: int) -> str:
    """The bracket round a week is, or empty for the regular season.

    A week from the playoff start that the bracket does not reach — a league
    whose last week runs past its final — is still the playoffs.
    """
    start = rules.playoff_start_week
    if not start or week < start:
        return ""
    rounds = brackets.lengths(rules.playoff_teams, two_week_final=rules.multiweek_final)
    return brackets.round_name(rounds, start, week) or "Playoffs"


def _result(found: Pairing | None, week: int, current: int, *, points: bool) -> str:
    """The score in the league's terms — points, or categories won-lost-tied — once there is one.

    A week to come has no score, and nor has the week being played before anything is on the board.
    """
    if found is None or week > current or found.status == "preevent":
        return ""
    mine, theirs = found.mine.points, found.opponent.points
    if points:
        return f"{mine}-{theirs}" if _amount(mine) or _amount(theirs) else ""
    won, lost, tied = int(_amount(mine)), int(_amount(theirs)), found.tied_categories
    return record(won, lost, tied) if won or lost or tied else ""


def _amount(printed: str) -> float:
    """A score as Yahoo prints it, as a number; nothing printed is nothing scored."""
    try:
        return float(printed)
    except ValueError:
        return 0.0


def ended(found: Pairing | None) -> Outcome | None:
    """How a settled week ended for you; None before then, and for a week you did not play."""
    if found is None or not found.settled:
        return None
    if found.tied:
        return "drawn"
    return "won" if found.winner == found.mine.team_key else "lost" if found.winner else None
