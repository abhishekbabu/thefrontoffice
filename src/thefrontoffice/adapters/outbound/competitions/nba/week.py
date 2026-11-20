"""A basketball week, as the matchup page reads it: each side, and the score.

A category league is scored category by category. Yahoo's scoreboard carries
each side's totals by stat id, as it prints them; these read them into the
shared shapes. Who leads a category is worked out here rather than taken from
Yahoo's own winners, so a week still being played reads the same way as one
that has finished.

A points league is scored in fantasy points, which Yahoo totals for each side
and projects to the week's end; the categories behind them win nothing.

The real games inside the week, and how many each club has left, are read from
Sleeper's schedule (`SleeperNBASchedule`), since Yahoo publishes none.
"""

import logging
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Literal, Protocol

from thefrontoffice.adapters.outbound.competitions.dates import parse_day, span, weekday_day_month
from thefrontoffice.adapters.outbound.competitions.nba import views
from thefrontoffice.adapters.outbound.competitions.nba.league import ended
from thefrontoffice.adapters.outbound.competitions.nba.rules import INJURED_SLOTS, PACIFIC, ruled_out, stranded
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading
from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperNBASource
from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.types import ScheduledGame
from thefrontoffice.adapters.outbound.platforms.yahoo.types import MatchupSide, Pairing, StatCategory, YahooPlayer
from thefrontoffice.domain.models import (
    Action,
    CategoryLine,
    Match,
    PlayerRef,
    Side,
    Spot,
    Stat,
    Summary,
    Tone,
    WeekRange,
)

logger = logging.getLogger(__name__)

BENCH = "BN"
"""Yahoo's slot for a player on the roster but not in the day's lineup."""


def categories(
    scored: Sequence[StatCategory], mine: Mapping[str, str], theirs: Mapping[str, str]
) -> list[CategoryLine]:
    """One line per category the league scores, in its settings' order, each side's figure by stat id.

    The league's own list rather than the nine this app prices players by: a
    league scoring double-doubles shows them, and one without free throws does not.
    """
    return [
        CategoryLine(
            name=category.name,
            mine=_figure(category, mine.get(category.stat_id, "")),
            theirs=_figure(category, theirs.get(category.stat_id, "")),
            lead=_lead(category, mine.get(category.stat_id, ""), theirs.get(category.stat_id, "")),
        )
        for category in scored
    ]


def _figure(category: StatCategory, value: str) -> str:
    """A side's figure as every page prints it — a rate '.850', not '0.85' — or as Yahoo sent it where not a number."""
    return views.printed(value, rate=views.rate(category)) if views.number(value) is not None else value


Lead = Literal["mine", "theirs", "even"]


def _lead(category: StatCategory, mine: str, theirs: str) -> Lead | None:
    """Who is ahead, or None where either figure is not a number yet: a week to come prints a dash."""
    try:
        ours, other = float(mine), float(theirs)
    except ValueError:
        return None
    if ours == other:
        return "even"
    return "mine" if (ours < other) == category.fewer_wins else "theirs"


def score(lines: Sequence[CategoryLine]) -> tuple[int, int, int] | None:
    """Categories won, lost and level, from your side; None where nothing has been recorded."""
    leads = [line.lead for line in lines if line.lead is not None]
    if not leads:
        return None
    return leads.count("mine"), leads.count("theirs"), leads.count("even")


def headline(score: tuple[int, int, int]) -> Stat:
    """The week's score in categories, which is how a category week is won."""
    won, lost, _ = score
    tone: Tone = "good" if won > lost else "warning" if won < lost else "neutral"
    return Stat(label="Categories", value=written(score), tone=tone)


def written(score: tuple[int, int, int]) -> str:
    """'5-3-1': won, lost, level."""
    return "-".join(str(n) for n in score)


Stage = Literal["played", "playing", "to come"]
"""Where a week sits against the one being played."""


def stage(week: int, current: int) -> Stage:
    return "played" if week < current else "playing" if week == current else "to come"


def points(mine: MatchupSide, theirs: MatchupSide, when: Stage) -> list[Stat]:
    """A points week's score in fantasy points, as Yahoo totals them, and its projected final while games are left.

    A week to come has no score, only a projection, which each side's card
    carries already. Toned by who is ahead, since the week is won on the total.
    """
    stats: list[Stat] = []
    if when != "to come" and (score := _versus(mine.points, theirs.points)):
        stats.append(score.model_copy(update={"label": "Final" if when == "played" else "Live"}))
    if when == "playing" and (projected := _versus(mine.projected, theirs.projected)):
        stats.append(projected.model_copy(update={"label": "Projected"}))
    return stats


def _versus(mine: str, theirs: str) -> Stat | None:
    """Two totals side by side, toned for yours; None where either is not a number."""
    try:
        margin = float(mine) - float(theirs)
    except ValueError:
        return None
    tone: Tone = "good" if margin > 0 else "warning" if margin < 0 else "neutral"
    return Stat(label="", value=f"{mine} – {theirs}", tone=tone)


def total(side: MatchupSide, when: Stage) -> str:
    """One side's fantasy points as its card heads them: scored, then Yahoo's projection while games are left."""
    scored = f"{side.points} pts" if side.points and when != "to come" else ""
    projected = f"{side.projected} proj" if side.projected and when != "played" else ""
    return " · ".join(part for part in (scored, projected) if part)


def side(
    name: str,
    detail: str,
    points: str,
    roster: Sequence[YahooPlayer] | None,
    readings: Mapping[str, Reading] | None = None,
    by_points: bool = False,
    scored: Sequence[StatCategory] = (),
    today: Sequence[ScheduledGame] | None = None,
) -> Side:
    """One team in the week, its roster parted as Yahoo slots it: the lineup, the bench, the injured list.

    `roster` is None where no roster is shown; in a week played, it is as the
    week ended, each player carrying his line over it, read in the league's
    categories `scored`. `readings` are each player's week by Yahoo's key, which
    his row reads its games left and Yahoo's averages from (`views.cell`).
    `today` are the day's real games while the week is being played, None in
    any other: each row then says whether he plays today (`today_line`).
    """
    rows = list(roster or [])
    found = readings or {}

    def spot(player: YahooPlayer) -> Spot:
        row = _spot(player, found.get(player.player_key), by_points, scored)
        if today is None or row.scoring is not None:
            return row
        game = next((g for g in today if g.opponent_of(player.team.upper()) is not None), None)
        return row.model_copy(update={"today": today_line(game, player.team), "idle": game is None})

    return Side(
        name=name,
        detail=detail,
        points=points,
        lineup=[spot(p) for p in rows if p.slot not in INJURED_SLOTS and p.slot != BENCH],
        bench=[spot(p).model_copy(update={"slot": ""}) for p in rows if p.slot == BENCH],
        # A player on the injured list was never going to play: no warning on his row.
        reserve=[spot(p).model_copy(update={"slot": "", "tone": "neutral"}) for p in rows if p.slot in INJURED_SLOTS],
    )


def today_line(game: ScheduledGame | None, club: str) -> str:
    """Whether his club plays today, as his row says it: 'vs TOR today', '@ BOS live', 'vs TOR final', 'no game today'.

    A lineup is set day by day, so a starter with no game today scores nothing
    until he is swapped for one who has. Sleeper publishes no tip-off time, so
    a game to come says the day, not the hour.
    """
    found = game.opponent_of(club.upper()) if game else None
    if game is None or found is None:
        return "no game today"
    opponent, home = found
    where = f"vs {opponent}" if home else f"@ {opponent}"
    return f"{where} {STATUS.get(game.status, 'today')}"


def _spot(
    player: YahooPlayer, reading: Reading | None = None, by_points: bool = False, scored: Sequence[StatCategory] = ()
) -> Spot:
    """A player as his row reads: where he is slotted, his positions and club, and his week or his status.

    With a reading, the row's figure is his games left and Yahoo's averages for
    him, and any status moves beside his club; without one, the status is the
    figure. In a week played, what he did in it instead of what he is listed as
    today: his fantasy points as the figure, or his line in each category as columns.
    """
    about = f"{player.position} · {player.team}"
    if player.stats or player.points:
        points = _fantasy(player.points)
        figures = line(player, scored)
        return Spot(
            player_id=player.player_key,
            slot=player.slot,
            player=player.name,
            detail=about if figures or not scored else f"{about} · no games",
            value=points,
            scoring="final" if points else None,
            scored=points,
            line=figures,
        )
    shown = views.cell(reading, by_points) if reading else ""
    return Spot(
        player_id=player.player_key,
        slot=player.slot,
        player=player.name,
        detail=f"{about} · {player.status}" if shown and player.status else about,
        value=shown or player.status,
        tone="warning" if ruled_out(player.status) else "neutral",
    )


def _fantasy(printed: str) -> str:
    """Fantasy points as Yahoo prints them, without trailing zeros: '140.80' reads '140.8'."""
    try:
        return f"{float(printed):g}"
    except ValueError:
        return printed


def line(player: YahooPlayer, scored: Sequence[StatCategory]) -> list[Stat]:
    """His week in each of the league's categories, in its order, as columns: a rate '.456', a count '143'.

    None where he played no games: a row of dashes says less than 'no games'.
    """
    figures = [player.stats.get(c.stat_id, "") for c in scored]
    if all(views.number(figure) is None for figure in figures):
        return []
    return [
        Stat(
            label=c.name,
            value=views.printed(figure, rate=views.rate(c)),
            better="lower" if c.fewer_wins else "higher",
        )
        for c, figure in zip(scored, figures, strict=True)
    ]


RESULT = {"won": "Won", "lost": "Lost", "drawn": "Tied"}


def result(found: Pairing) -> list[Stat]:
    """How a settled week ended for you, in a word; nothing before it is settled."""
    outcome = ended(found)
    if outcome is None:
        return []
    tone: Tone = "good" if outcome == "won" else "warning" if outcome == "lost" else "neutral"
    return [Stat(label="Result", value=RESULT[outcome], tone=tone)]


STATUS = {"in_game": "live", "complete": "final"}
"""Sleeper's game status, in the word a fixture row shows; a game still to come shows none."""


def match(game: ScheduledGame, roster: Sequence[YahooPlayer]) -> Match:
    """One real game, with your players in it.

    Sleeper publishes the day and a status, and no score.
    """
    day = parse_day(game.date)
    clubs = {game.home.upper(), game.away.upper()}
    yours = [
        PlayerRef(player_id=p.player_key, name=p.name, detail=f"{p.position} · {p.slot or 'bench'}")
        for p in roster
        if p.team.upper() in clubs
    ]
    return Match(
        label=weekday_day_month(day) if day else game.date,
        home=game.home,
        away=game.away,
        # Who has players in it is said by name, from `yours`.
        detail=STATUS.get(game.status, ""),
        yours=yours,
    )


NOT_FINAL = Stat(label="Schedule", value="not final", tone="warning")
"""What a week's header says while the NBA has days of it left to schedule."""

THIN_DAY = 3
"""Fewer games than this on a day inside the regular season is a day the schedule may not have filled.

A normal day has five to a dozen; a holiday has none, but only one at a time."""

UNFILLED_RUN = 3
"""How many thin days in a row it takes to read as unscheduled rather than as a quiet stretch."""

CUP_KNOCKOUTS = (12, range(1, 21))
"""The NBA Cup's knockout weeks, 1-20 December, by month and days: the NBA schedules the clubs knocked out
of the Cup for them only once its group stage ends, so until then Sleeper's and ESPN's schedules both
leave those clubs' games out. The one window it is read in: the All-Star break is as long a run of
empty days, and is final."""


ONE_DAY = timedelta(days=1)


def unsettled(games: Iterable[ScheduledGame], start: date, end: date) -> list[date]:
    """The days between `start` and `end` the NBA has yet to schedule, in order; none where it has.

    A day is thin with fewer than `THIN_DAY` games, between the season's first
    game and its last, in the Cup's knockout weeks (`CUP_KNOCKOUTS`); it is
    unsettled in a run of `UNFILLED_RUN` thin days or more. Read off the whole
    season's schedule, so a run crossing either end of the window still counts,
    and so once the NBA fills the days in, nothing is flagged.
    """
    counts = Counter(day for game in games if (day := parse_day(game.date)) is not None)
    if not counts:
        return []
    first, last = min(counts), max(counts)
    month, days = CUP_KNOCKOUTS

    def thin(day: date) -> bool:
        return first < day < last and day.month == month and day.day in days and counts[day] < THIN_DAY

    def run(day: date) -> int:
        """How many thin days in a row `day` sits among: bounded, since only the knockout weeks can be thin."""
        low = high = day
        while thin(low - ONE_DAY):
            low -= ONE_DAY
        while thin(high + ONE_DAY):
            high += ONE_DAY
        return (high - low).days + 1

    window = (start + n * ONE_DAY for n in range((end - start).days + 1))
    return [day for day in window if thin(day) and run(day) >= UNFILLED_RUN]


def not_final(unscheduled: Sequence[date]) -> str:
    """The line a week's fixtures carry while days of it are unscheduled: 'Schedule not final: no games yet 4-11 Dec.'"""
    if not unscheduled:
        return ""
    return f"Schedule not final: no games yet {span(unscheduled[0], unscheduled[-1])}."


def board(
    found: Pairing,
    weeks: WeekRange,
    records: Mapping[str, str],
    roster: list[YahooPlayer] | None,
    theirs: list[YahooPlayer] | None,
    categories_scored: Sequence[StatCategory] | None,
    readings: Mapping[str, Reading] | None = None,
    unscheduled: Sequence[date] = (),
    today: Sequence[ScheduledGame] | None = None,
) -> Summary:
    """One week's head-to-head, and where it sits in the season.

    `records` is each team's record by key. `roster` is yours and `theirs` the
    opponent's where rosters are shown, and None where they are not: in a week
    played, as it ended, each player with his line over it.
    `categories_scored` is the league's own list, None for a points league.
    `readings` are every shown player's week, by Yahoo's key. `unscheduled` are
    the week's days the NBA has yet to schedule (`unsettled`), which the header
    says, since every games-left count below it is short by them. `today` are
    the day's real games while the week is the one being played (`side`).
    """
    window = f"Week {weeks.week} · {span(found.start, found.end)}"
    pending = [NOT_FINAL] if unscheduled else []
    if categories_scored is None:
        # Won on the fantasy-point total, which Yahoo keeps: the categories behind it win nothing.
        when = stage(weeks.week, weeks.current)
        return Summary(
            headline=[*result(found), *points(found.mine, found.opponent, when), *pending],
            mine=side(
                found.mine.name,
                records.get(found.mine.team_key, ""),
                total(found.mine, when),
                roster,
                readings,
                True,
                today=today,
            ),
            opponent=side(
                found.opponent.name,
                records.get(found.opponent.team_key, ""),
                total(found.opponent, when),
                theirs,
                readings,
                True,
                today=today,
            ),
            window=window,
            weeks=weeks,
        )
    lines = categories(categories_scored, found.mine.stats, found.opponent.stats)
    tally = score(lines)
    return Summary(
        headline=[*result(found), *([headline(tally)] if tally else []), *pending],
        mine=side(
            found.mine.name,
            records.get(found.mine.team_key, ""),
            written(tally) if tally else "",
            roster,
            readings,
            scored=categories_scored,
            today=today,
        ),
        opponent=side(
            found.opponent.name,
            records.get(found.opponent.team_key, ""),
            written((tally[1], tally[0], tally[2])) if tally else "",
            theirs,
            readings,
            scored=categories_scored,
            today=today,
        ),
        categories=lines,
        window=window,
        weeks=weeks,
    )


def off_il(roster: list[YahooPlayer]) -> list[Action]:
    """Each player held in an injured slot his status no longer qualifies him for.

    Yahoo holds every add while one sits there, so it comes before any other
    move. Activating him needs an active roster spot, which may mean a drop.
    """
    items = []
    for player in roster:
        if not stranded(player.slot, player.status):
            continue
        status = f"listed {player.status}" if player.status else "cleared to play"
        items.append(
            Action(
                kind="lineup",
                urgency="now",
                title=f"Move {player.name} off {player.slot}",
                reason=f"{player.name} is {status}. Adds locked until he leaves {player.slot}; needs an open roster spot.",
                when="first",
                player_id=player.player_key,
                key=f"il:{player.player_key}:{player.status.upper() or 'ACTIVE'}",
            )
        )
    return items


def adds(used: int, limit: int) -> list[Stat]:
    """The week's add budget, as what is left of it.

    The one figure the week turns on: an exhausted budget is the constraint
    the whole report bends around, turning every recommendation into a
    MONITOR, so it warns. The team's name is the page's title already, and
    the roster's size is My team's to say.
    """
    left = max(0, limit - used)
    return [Stat(label="Adds left", value=f"{left} of {limit}", tone="good" if left else "warning")]


# ── the real games, from Sleeper ────────────────────────────────────


class ScheduleSource(Protocol):
    """What the basketball provider reads the real games of a matchup week through.
    See `SleeperNBASource` for why it exists.
    """

    def get_remaining_games(self, team_abbr: str, start_date: date, end_date: date, now: datetime | None = None) -> int:
        """Count a club's not-yet-played games inside a matchup window.

        Raises:
            PlatformError: the schedule would not load.
        """
        ...

    def get_remaining_games_bulk(
        self, team_abbrs: list[str], start_date: date, end_date: date, now: datetime | None = None
    ) -> dict[str, int]:
        """One schedule load and one `now` for every club asked about.

        Empty where the schedule would not load: games left unknown, never nought.
        """
        ...

    def games_between(self, start_date: date, end_date: date) -> list[ScheduledGame]:
        """Every real game dated inside a matchup window, in date order.

        Raises:
            PlatformError: the schedule would not load.
        """
        ...

    def games_left(self, start_date: date, end_date: date, now: datetime | None = None) -> list[ScheduledGame]:
        """The games inside a matchup window still to tip off, in date order.

        Raises:
            PlatformError: the schedule would not load.
        """
        ...

    def unscheduled(self, start_date: date, end_date: date) -> list[date]:
        """The days inside a matchup window the NBA has yet to schedule (`unsettled`); none where the schedule
        would not load, which leaves games left unknown already."""
        ...

    def games_today(self, now: datetime | None = None) -> tuple[date, list[ScheduledGame]] | None:
        """Today's date in Pacific, and every real game on it whatever its status: none on a day the NBA rests.
        None where the schedule would not load: no rows then say whether he plays today, rather than every
        one saying he does not."""
        ...


class SleeperNBASchedule:
    """The real games of a basketball matchup week, and how many each club has left.

    Loads the season's schedule once and keeps it: a report asks about every
    club in a matchup, and refetching it per question would be the whole cost
    of the page.
    """

    def __init__(self, client: SleeperNBASource, season: str | None = None) -> None:
        self.client = client
        self._season = season
        self._schedule: dict[str, list[ScheduledGame]] | None = None

    def get_remaining_games(self, team_abbr: str, start_date: date, end_date: date, now: datetime | None = None) -> int:
        """Count a club's not-yet-played games inside a matchup window.

        Two notions of time, kept apart the same way they always were: the
        window test compares date labels, which is what Yahoo's matchup dates
        also are, and the has-it-happened test is decided on the day in
        Pacific — the zone the league schedules by.

        Sleeper publishes a date and a status but no tip-off instant, so a game
        today counts only while its status still says it has not started, and a
        stale status on a past date cannot resurrect a played game.

        Raises:
            SleeperAPIError: the schedule would not load.
        """
        today = self._today(now)
        return sum(
            1
            for game in self._team_schedule().get(team_abbr.upper(), [])
            if self._is_remaining(game, start_date, end_date, today)
        )

    def get_remaining_games_bulk(
        self, team_abbrs: list[str], start_date: date, end_date: date, now: datetime | None = None
    ) -> dict[str, int]:
        """One schedule load and one `now` for every club asked about.

        Empty where the schedule would not load: games left are then unknown,
        and a nought for every club would read as a week nobody plays.
        """
        moment = now or datetime.now(tz=PACIFIC)
        try:
            return {
                abbr.upper(): self.get_remaining_games(abbr, start_date, end_date, now=moment)
                for abbr in set(team_abbrs)
            }
        except SleeperAPIError as e:
            logger.warning(f"Continuing without games left, the basketball schedule would not load: {e}")
            return {}

    def games_between(self, start_date: date, end_date: date) -> list[ScheduledGame]:
        """Every real game dated inside a matchup window, in date order, each once.

        Raises:
            SleeperAPIError: the schedule would not load.
        """
        games = {id(g): g for club in self._team_schedule().values() for g in club}.values()
        inside = [g for g in games if (day := parse_day(g.date)) is not None and start_date <= day <= end_date]
        return sorted(inside, key=lambda g: (g.date, g.away, g.home))

    def games_left(self, start_date: date, end_date: date, now: datetime | None = None) -> list[ScheduledGame]:
        """The games inside a matchup window still to tip off, in date order, counted as `get_remaining_games` counts.

        Raises:
            SleeperAPIError: the schedule would not load.
        """
        today = self._today(now)
        return [
            g for g in self.games_between(start_date, end_date) if self._is_remaining(g, start_date, end_date, today)
        ]

    def unscheduled(self, start_date: date, end_date: date) -> list[date]:
        """The days inside a matchup window the NBA has yet to schedule (`unsettled`), read off the whole season.

        None where the schedule would not load: games left are unknown then, not short.
        """
        try:
            games = {id(g): g for club in self._team_schedule().values() for g in club}.values()
        except SleeperAPIError as e:
            logger.warning(f"Reading the schedule as final, it would not load: {e}")
            return []
        return unsettled(games, start_date, end_date)

    def games_today(self, now: datetime | None = None) -> tuple[date, list[ScheduledGame]] | None:
        today = self._today(now)
        try:
            games = {id(g): g for club in self._team_schedule().values() for g in club}.values()
        except SleeperAPIError as e:
            logger.warning(f"Showing rows without today's games, the schedule would not load: {e}")
            return None
        return today, sorted((g for g in games if parse_day(g.date) == today), key=lambda g: (g.away, g.home))

    @staticmethod
    def _is_remaining(game: ScheduledGame, start: date, end: date, today: date) -> bool:
        played = parse_day(game.date)
        if played is None or not (start <= played <= end):
            return False
        if played < today:
            return False
        # Today's game turns on the status; a future one is remaining whatever
        # a possibly-stale status says.
        return played > today or game.status == "pre_game"

    def _team_schedule(self) -> dict[str, list[ScheduledGame]]:
        if self._schedule is None:
            by_team: dict[str, list[ScheduledGame]] = {}
            for game in self.client.get_nba_schedule(self._schedule_season()):
                for club in (game.home, game.away):
                    if club:
                        by_team.setdefault(club, []).append(game)
            self._schedule = by_team
        return self._schedule

    def _schedule_season(self) -> str:
        """The season whose fixtures are still to be played, which is the one
        the game itself is pointing at even while it has not started."""
        return self._season or self.client.get_nba_state().season

    @staticmethod
    def _today(now: datetime | None) -> date:
        moment = now or datetime.now(tz=PACIFIC)
        return moment.astimezone(PACIFIC).date()
