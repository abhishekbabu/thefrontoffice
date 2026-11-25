"""A basketball day, as the matchup page reads one: both sides as slotted on it, and the day's totals.

A lineup is set day by day, so a week is opened a day at a time as well. A day
played shows who started and who sat, each with his line from it, and what the
bench put up that counted for nothing. The day being played shows the lineup as
set, live or final where games are on or over. A day to come shows the lineup as
set so far, who has a game and what is projected of him, and what to fix: a
starter with no game, and a bench player with one who would add a start.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Protocol

from thefrontoffice.adapters.outbound.competitions.dates import weekday_day_month
from thefrontoffice.adapters.outbound.competitions.names import normalize_name
from thefrontoffice.adapters.outbound.competitions.nba import views
from thefrontoffice.adapters.outbound.competitions.nba import week as nba_week
from thefrontoffice.adapters.outbound.competitions.nba.clubs import espn_club
from thefrontoffice.adapters.outbound.competitions.nba.lineup import seated
from thefrontoffice.adapters.outbound.competitions.nba.model import HeadToHead, LeagueCategory, Player
from thefrontoffice.adapters.outbound.competitions.nba.rules import (
    CATEGORIES,
    INJURED_SLOTS,
    Line,
    amount,
    fantasy_points,
    printed,
    ruled_out,
)
from thefrontoffice.adapters.outbound.platforms.sleeper.types import ScheduledGame
from thefrontoffice.domain.errors import NotFoundError
from thefrontoffice.domain.models import DayRange, Side, Spot, Stat, Summary, Tone, WeekRange

START = "Start"
"""The mark on a bench player with a game who would add a start where he sits: what to fix."""

NO_GAME = "no game"


def days(start: date, end: date) -> list[date]:
    """Every day from `start` to `end`, both included."""
    return [start + timedelta(days=n) for n in range((end - start).days + 1)]


def pick(asked: date | None, start: date, end: date, today: date) -> date:
    """The day to show: the one asked for, or today where the week holds it, else the week's first.

    Raises:
        NotFoundError: the day asked for is not one of the week's.
    """
    if asked is None:
        return today if start <= today <= end else start
    if not start <= asked <= end:
        raise NotFoundError(f"{asked.isoformat()} in the week of {start.isoformat()}")
    return asked


class DayLog(Protocol):
    """Each day's record the platforms do not keep, by Yahoo's key: kept on disk by `storage/days.py`.

    Yahoo's dated roster carries a player's status now, not that day's; Sleeper's
    box scores hold only a recent window. Both are recorded as they are seen,
    so a day long past still reads them.
    """

    def statuses(self, day: date) -> dict[str, str]:
        """Each player's Yahoo status as last seen that day; nobody for a day nothing was kept for."""
        ...

    def keep_statuses(self, day: date, statuses: dict[str, str]) -> None:
        """Keep these as the day's, replacing what was kept for it."""
        ...

    def pregame(self, day: date) -> dict[str, str]:
        """Each player's Yahoo status as last seen that day before his game tipped off."""
        ...

    def keep_pregame(self, day: date, statuses: dict[str, str]) -> None:
        """Keep these as the day's, replacing what was kept for it."""
        ...

    def minutes(self, day: date) -> dict[str, float]:
        """The minutes each player played that day, as the box scores gave them once it stood."""
        ...

    def keep_minutes(self, day: date, minutes: dict[str, float]) -> None:
        """Keep these as the day's, replacing what was kept for it."""
        ...

    def injuries(self) -> dict[str, list[Hurt]]:
        """Every injury ESPN's report has been seen giving each player this season, oldest first."""
        ...

    def keep_injuries(self, injuries: dict[str, list[Hurt]]) -> None:
        """Keep these as the season's, replacing what was kept."""
        ...


@dataclass(frozen=True)
class Hurt:
    """One injury as ESPN's report gave it, over the days it was seen: what the report drops, the log remembers."""

    injury: str
    """What was hurt, as ESPN said it: 'Left hip, soreness'; 'Rest' where the report rested him."""
    first: date
    last: date
    rest: bool = False
    """Whether the report's own words were a rest night or load management, not an injury (`RESTED`)."""

    def covers(self, day: date) -> bool:
        return self.first <= day <= self.last


RESTED = ("rest", "resting", "rested", "load management", "injury management", "not injury related")
"""What a report says of a night off that is no injury."""


def record_injuries(log: DayLog, day: date, seen: Mapping[str, tuple[str, str]]) -> dict[str, list[Hurt]]:
    """Keep what ESPN's report says of each player on `day` — his injury and its latest word, by Yahoo key — as
    one more day of the same injury where it is the one kept last, else as a new one; and answer the season's.

    A report ESPN drops is no longer seen, and the injury it gave stays kept, its last day the last it was seen.
    """
    kept = log.injuries()
    changed = False
    for key, (injury, comment) in seen.items():
        rest = says_rest(f"{injury} {comment}")
        what = injury or ("Rest" if rest else "")
        if not what:
            continue
        history = kept.setdefault(key, [])
        latest = history[-1] if history else None
        if latest is not None and latest.injury == what and latest.first <= day:
            if latest.last < day:
                history[-1] = Hurt(what, latest.first, day, latest.rest or rest)
                changed = True
            continue
        history.append(Hurt(what, day, day, rest))
        changed = True
    if changed:
        log.keep_injuries(kept)
    return kept


def says_rest(text: str) -> bool:
    """Whether a report's words are a night off rather than an injury (`RESTED`)."""
    padded = f" {normalize_name(text)} "
    return any(f" {word} " in padded for word in RESTED)


def record_statuses(
    log: DayLog, day: date, players: Sequence[Player], games: Sequence[ScheduledGame] | None = None
) -> None:
    """Keep each of `players`' status as seen on `day`, the day being played, an empty one included.

    A status moves through a day — game-time decision, then out — and the one
    his game was played under is the last seen before it tipped off. Where
    `games` are the day's, with each one's status, a player whose game has yet
    to tip off has his kept as that (`pregame`); every status seen is kept as
    the day's last, which stands where none was seen before tip-off.
    """
    seen = {p.player_key: p.status for p in players}
    _merge(log.statuses(day), seen, lambda kept: log.keep_statuses(day, kept))
    if games is None:
        return
    waiting = {
        key
        for p in players
        if (key := p.player_key)
        and (game := next((g for g in games if g.opponent_of(p.team.upper()) is not None), None)) is not None
        and game.status not in nba_week.STATUS
    }
    _merge(log.pregame(day), {key: seen[key] for key in waiting}, lambda kept: log.keep_pregame(day, kept))


def _merge(kept: dict[str, str], seen: Mapping[str, str], keep: Callable[[dict[str, str]], None]) -> None:
    """Write `seen` over `kept`, only where it changes anything: most reads see what the last one did."""
    if any(kept.get(key) != status for key, status in seen.items()):
        keep(kept | dict(seen))


def recorded(log: DayLog, day: date) -> dict[str, str]:
    """Each player's status on `day` as kept: the last seen before his game tipped off, else the day's last."""
    return log.statuses(day) | log.pregame(day)


def record_minutes(log: DayLog, day: date, minutes: Mapping[str, float]) -> dict[str, float]:
    """Keep the minutes the box scores give on `day`, a day that has stood, for anybody not kept yet — the first
    reading of a settled day is final — and answer every player's minutes that day, kept or read."""
    kept = log.minutes(day)
    fresh = {key: played for key, played in minutes.items() if key not in kept}
    if fresh:
        log.keep_minutes(day, kept | fresh)
    return dict(minutes) | kept


@dataclass(frozen=True)
class Day:
    """One day of a week, and what is known of its games."""

    day: date
    stage: nba_week.Stage
    """Whether it has been played, is being played, or is still to come, on the league's clock."""

    games: Sequence[ScheduledGame] | None
    """Its real games; None where the schedule would not load, and no row then says whether he plays."""

    tipoff: Mapping[str, datetime] = field(default_factory=dict)
    """When each club's game starts while it has not, by ESPN's abbreviation (`Today.tipoff`)."""

    projected: Mapping[str, Line] = field(default_factory=dict)
    """What is projected of each player's game on it, by Yahoo's key, where the provider projects one."""

    slots: tuple[str, ...] = ()
    """The lineup's scoring slots, one per place (`lineup.slots`): what a bench player could fill."""

    minutes: Mapping[str, float] = field(default_factory=dict)
    """The minutes each player played that day, by Yahoo's key, where the box scores place him: what tells a
    game sat out from one that filled no column. Nobody where they do not hold the day."""

    week: Mapping[str, str] = field(default_factory=dict)
    """Each player's week as a week's row reads it, by Yahoo's key: games left and his averages (`views.cell`)."""

    statuses: Mapping[str, str] = field(default_factory=dict)
    """On a day played, each player's Yahoo status as recorded that day (`recorded`); nobody before recording began."""

    def game(self, club: str) -> ScheduledGame | None:
        """His club's game that day, or None on a day it rests."""
        return next((g for g in self.games or () if g.opponent_of(club.upper()) is not None), None)

    def known(self) -> bool:
        return self.games is not None


def fixture(game: ScheduledGame | None, club: str, stage: nba_week.Stage) -> str:
    """His game that day as his row says it: 'vs TOR', '@ BOS live', 'vs TOR final', 'no game'.

    Live or final only on the day being played: a day played is all final, and saying so on every row is noise.
    """
    found = game.opponent_of(club.upper()) if game else None
    if game is None or found is None:
        return NO_GAME
    opponent, home = found
    where = f"vs {opponent}" if home else f"@ {opponent}"
    status = nba_week.STATUS.get(game.status, "") if stage == "playing" else ""
    return f"{where} {status}".strip()


DNP = "DNP"
"""What a row says of a game he sat out, where the box scores say he played no minutes in it."""


def played(player: Player, day: Day | None = None) -> bool:
    """Whether he played that day: a figure Yahoo prints, or minutes the box scores give him (`Day.minutes`).

    Yahoo prints a dash in every category before his game, and a nought in
    every one, '0/0' shots, both for a game he sat out and for one he played
    and filled no column in: only his minutes tell those two apart.
    """
    for figure in player.stats.values():
        made, slash, taken = figure.partition("/")
        if slash and amount(taken) > 0 or not slash and amount(made) != 0:
            return True
    return day is not None and day.minutes.get(player.player_key, 0.0) > 0


def sat_out(player: Player, day: Day) -> bool:
    """Whether he is known to have sat out his game that day: no figure, and no minutes in the box scores.

    Unknown — not sat out — where the box scores do not place him or hold the day.
    """
    return not played(player, day) and day.minutes.get(player.player_key) == 0.0


def starting(player: Player) -> bool:
    """Whether he is in the day's lineup, rather than on the bench or in an injured slot."""
    return player.slot not in INJURED_SLOTS and player.slot != nba_week.BENCH


def plays(player: Player, day: Day) -> bool:
    """Whether he has a game that day and is not ruled out of it."""
    return day.game(player.team) is not None and not ruled_out(player.status)


def movable(player: Player, day: Day) -> bool:
    """Whether he can still be moved into the lineup that day: a game to come, and nothing ruling him out."""
    game = day.game(player.team)
    if game is None or ruled_out(player.status) or day.stage == "played":
        return False
    return day.stage == "to come" or game.status not in nba_week.STATUS


def projection(line: Line | None, weights: Mapping[str, float] | None) -> str:
    """What is projected of his game: fantasy points in a points league, '18p 7r 4a' in a category one."""
    if not line:
        return ""
    if weights:
        points = fantasy_points(line, weights)
        return f"{points:.1f}" if points is not None else ""
    return " ".join(f"{line[c.label]:.0f}{c.tag}" for c in views.CARD_CATEGORIES if c.label in line)


def spot(
    player: Player,
    day: Day,
    weights: Mapping[str, float] | None,
    scored: Sequence[LeagueCategory],
    fixable: bool = False,
) -> Spot:
    """A player's row that day: where he was slotted, his game, and his line from it or what is projected.

    In a points league his fantasy points, beside his projection while there
    is one; in a category league his line in each category as columns. A game
    over without a line is one he sat out. While the day is open, a starter's status
    ruling him out is flagged, and so, where the bench has somebody to start
    in his place (`fixable`), is a starter with no game.
    """
    game = day.game(player.team)
    # Yahoo's status is his status now, not that day's: a day played shows the one recorded that day, or none.
    status = player.status if day.stage != "played" else day.statuses.get(player.player_key, "")
    about = " · ".join(part for part in (player.position, player.team, status, day.week.get(player.player_key)) if part)
    guess = projection(day.projected.get(player.player_key), weights) if day.stage != "played" else ""
    row = Spot(
        player_id=player.player_key,
        slot=player.slot,
        player=player.name,
        detail=about,
        value="",
        today=fixture(game, player.team, day.stage) if day.known() else "",
        idle=day.known() and game is None,
        kickoff=day.tipoff.get(espn_club(player.team)) if game is not None and day.stage != "played" else None,
    )
    if played(player, day):
        if weights is not None:
            live = day.stage == "playing" and game is not None and game.status == "in_game"
            return row.model_copy(
                update={
                    "value": nba_week.fantasy(player.points),
                    "scored": nba_week.fantasy(player.points),
                    "scoring": "live" if live else "final",
                    "projection": guess,
                }
            )
        return row.model_copy(update={"line": nba_week.line(player, scored)})
    over = game is not None and (day.stage == "played" or game.status == "complete")
    if over and sat_out(player, day):
        return row.model_copy(update={"value": DNP})
    if over or day.stage == "played":
        return row
    if ruled_out(player.status) and starting(player):
        return row.model_copy(update={"value": player.status, "tone": "warning"})
    if fixable and starting(player) and game is None and day.known():
        return row.model_copy(update={"value": NO_GAME, "tone": "warning"})
    if guess and game is not None:
        if weights is not None:
            return row.model_copy(update={"value": guess, "projection": guess, "scoring": "projected"})
        return row.model_copy(update={"value": guess})
    return row


def to_start(roster: Sequence[Player], day: Day) -> tuple[set[str], int]:
    """Your bench players who would add a start that day, by Yahoo's key, and how many starts the bench can add
    at most: each one, put in, lets the lineup seat one more player who plays (`lineup.seated`), however the
    starters are shuffled, but two of them may want the one slot open."""
    if day.stage == "played" or not day.known() or not day.slots:
        return set(), 0
    starters = [p for p in roster if starting(p) and plays(p, day)]
    now = seated(starters, day.slots)
    candidates = [p for p in roster if p.slot == nba_week.BENCH and movable(p, day)]
    each = {p.player_key for p in candidates if seated([*starters, p], day.slots) > now}
    return each, seated([*starters, *candidates], day.slots) - now if each else 0


def totals(players: Sequence[Player], scored: Sequence[LeagueCategory]) -> dict[str, str]:
    """`players`' lines that day summed in each category, by stat id, as a scoreboard prints them; a percentage
    from summed makes and attempts. Empty where none of them has a line."""
    lines = [p for p in players if played(p)]
    if not lines:
        return {}
    shots = {c.yahoo_stat: c for c in CATEGORIES if c.is_percentage}
    found: dict[str, str] = {}
    for category in scored:
        percentage = shots.get(category.stat_id)
        if percentage is None:
            found[category.stat_id] = f"{sum(amount(p.stats.get(category.stat_id, '')) for p in lines):g}"
            continue
        made, taken = (sum(part) for part in zip(*(printed(p.stats, percentage) for p in lines), strict=True))
        found[category.stat_id] = str(made / taken) if taken else ""
    return found


def points(players: Sequence[Player]) -> float | None:
    """`players`' fantasy points that day, summed; None where none of them has a line."""
    lines = [amount(p.points) for p in players if played(p)]
    return sum(lines) if lines else None


def bench_line(players: Sequence[Player], by_points: bool) -> str:
    """What the bench put up that day and the lineup never counted: 'bench 24.5 pts', 'bench 18p 6r 2a'."""
    benched = [p for p in players if p.slot == nba_week.BENCH and played(p)]
    if not benched:
        return ""
    if by_points:
        total = points(benched) or 0.0
        return f"bench {_fantasy(total)} pts" if total else ""
    sums = {c: sum(amount(p.stats.get(c.yahoo_stat, "")) for p in benched) for c in views.CARD_CATEGORIES}
    shown = " ".join(f"{value:g}{c.tag}" for c, value in sums.items() if value)
    return f"bench {shown}" if shown else ""


def board(
    found: HeadToHead,
    weeks: WeekRange,
    span: DayRange,
    records: Mapping[str, str],
    sides: tuple[Sequence[Player], Sequence[Player]],
    scored: Sequence[LeagueCategory] | None,
    weights: Mapping[str, float] | None,
    day: Day,
) -> Summary:
    """One day of a week's head-to-head: both sides as slotted on it, and the day's score.

    `sides` are yours and the opponent's rosters on the day, each player with
    his line from it. `scored` is the league's categories, None in a points
    league, whose `weights` sum a projection. The headline is the day's score —
    categories won that day, or fantasy points — each side's starts, and on a
    day still open, what to fix in your lineup.
    """
    mine, theirs = sides
    by_points = scored is None
    categories = scored or []
    # A day played counts who did play; one still open, who has a game and is not ruled out of it.
    counted = (lambda p: played(p, day)) if day.stage == "played" else (lambda p: plays(p, day))
    starts = [sum(1 for p in side if starting(p) and counted(p)) for side in sides] if day.known() else []
    fix, gain = to_start(mine, day)
    summed = [totals([p for p in side if starting(p)], categories) for side in sides]
    # Nothing to set side by side before anybody has played: a day to come has no categories yet.
    lines = nba_week.categories(categories, *summed) if any(summed) else []
    tally = nba_week.score(lines)
    totaled = [points([p for p in side if starting(p)]) for side in sides] if by_points else []
    projected = [_projected(side, day, weights) for side in sides] if by_points and day.stage != "played" else []

    def side(index: int, roster: Sequence[Player]) -> Side:
        team = (found.mine, found.opponent)[index]
        figure = ""
        if tally is not None:
            won, lost, level = tally
            figure = nba_week.written((won, lost, level) if index == 0 else (lost, won, level))
        elif by_points:
            total = totaled[index]
            scored_points = f"{_fantasy(total)} pts" if total is not None else ""
            guess = f"{projected[index]:.1f} proj" if projected and projected[index] else ""
            figure = " · ".join(part for part in (scored_points, guess) if part)
        word = "played" if day.stage == "played" else "playing"
        detail = " · ".join(
            part for part in (f"{starts[index]} {word}" if starts else "", bench_line(roster, by_points)) if part
        )

        def row(player: Player) -> Spot:
            made = spot(player, day, weights, categories, fixable=index == 0 and bool(fix))
            return made.model_copy(update={"mark": START}) if player.player_key in fix else made

        return Side(
            name=team.name,
            record=records.get(team.team_key, ""),
            detail=detail,
            points=figure,
            lineup=[row(p) for p in roster if starting(p)],
            bench=[row(p).model_copy(update={"slot": ""}) for p in roster if p.slot == nba_week.BENCH],
            reserve=[
                row(p).model_copy(update={"slot": "", "tone": "neutral"}) for p in roster if p.slot in INJURED_SLOTS
            ],
        )

    headline = _headline(tally, totaled, starts, gain)
    return Summary(
        headline=headline,
        mine=side(0, mine),
        opponent=side(1, theirs),
        categories=lines,
        window=f"Week {weeks.week} · {weekday_day_month(day.day)}",
        weeks=weeks,
        days=span,
    )


def _projected(roster: Sequence[Player], day: Day, weights: Mapping[str, float] | None) -> float | None:
    """A points side's day as it projects: what its starters have scored, and what is projected of those still
    to play; None where nothing is projected."""
    if not weights:
        return None
    guesses = [
        fantasy_points(line, weights)
        for p in roster
        if starting(p) and not played(p, day) and plays(p, day) and (line := day.projected.get(p.player_key))
    ]
    left = [guess for guess in guesses if guess is not None]
    if not left:
        return None
    return (points([p for p in roster if starting(p)]) or 0.0) + sum(left)


def _headline(
    tally: tuple[int, int, int] | None, totaled: Sequence[float | None], starts: Sequence[int], fix: int
) -> list[Stat]:
    """The day's score, each side's starts, and how many of your bench would add a start while the day is open."""
    stats: list[Stat] = []
    if tally is not None:
        stats.append(nba_week.headline(tally).model_copy(update={"label": "Day"}))
    elif len(totaled) == 2 and None not in totaled:
        mine, theirs = (total or 0.0 for total in totaled)
        stats.append(Stat(label="Day", value=f"{_fantasy(mine)} – {_fantasy(theirs)}", tone=_ahead(mine - theirs)))
    if starts:
        stats.append(Stat(label="Starts", value=f"{starts[0]} – {starts[1]}", tone=_ahead(starts[0] - starts[1])))
    if fix:
        stats.append(Stat(label="Lineup", value=f"{fix} to start", tone="warning"))
    return stats


def _fantasy(total: float) -> str:
    """Fantasy points summed, to the tenth Yahoo prints: '158.2', never '158.20000000000002'."""
    return f"{round(total, 1):g}"


def _ahead(margin: float) -> Tone:
    return "good" if margin > 0 else "warning" if margin < 0 else "neutral"


INJURED = frozenset({"O", "INJ", "IL", "IL+", "GTD", "DTD", "SUSP", "NA"})
"""Yahoo statuses kept for a day that say the night was no rest: hurt, doubtful, or not with the club."""


def rest_of(history: Sequence[Hurt], statuses: Mapping[date, str]) -> Callable[[date, bool], bool]:
    """Whether a game he missed was a night off (`form.Rest`), by what was kept of the day — never by the schedule
    alone, which cannot tell a rested night from a sore knee: one his report called rest or load management
    (`Hurt.rest`); or the second night of a back-to-back he sat with a status kept for it that says he was well —
    none, while no injury report covers the day."""

    def rest(day: date, back_to_back: bool) -> bool:
        covering = [h for h in history if h.covers(day)]
        if any(h.rest for h in covering):
            return True
        well = day in statuses and statuses[day].upper() not in INJURED
        return back_to_back and well and not covering

    return rest
