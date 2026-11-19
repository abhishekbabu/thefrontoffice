"""What an FPL player is worth: the one figure the eleven, the armband, transfers and the market are weighed on.

FPL's own projection (`ep_next`) is no projection at all this season — it
equals `form` for every pick — so ranking on it alone captains a defender on a
good month over a striker at home to a side near the bottom. A match of him
here is his recent form beside an outlook (`competitions.worth.blend`, the rule
every competition reads a player by), each scaled by how hard the match is,
with a modest share of what his underlying numbers say he should score. A
gameweek is every match his club plays in it — two in a double, none in a
blank — times how likely he is to play and how steady his minutes are.

    match   = (1 − UNDERLYING_WEIGHT) × blend(form × difficulty, outlook) + UNDERLYING_WEIGHT × underlying
    week    = Σ match over the club's fixtures × availability × usage
    horizon = Σ week over the next `HORIZON` gameweeks, availability recovering week by week

Form is points per match his club played over the last `FORM_WEEKS` finished
gameweeks — a match he missed counts as nought, which is what weighs it by his
minutes — settled toward his season's (`SETTLE_MATCHES`). The outlook is
`ep_next` × difficulty wherever FPL projects something other than form, and
his underlying numbers where it does not — counting form twice is how a month
of clean sheets outranks a striker — and `ep_next` again before he has played a
minute, when it is all there is. One live feed a gameweek carries every
player at once, so the whole market is read for five requests, not seven hundred.
"""

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from thefrontoffice.adapters.outbound.competitions import worth as shared
from thefrontoffice.adapters.outbound.competitions.premier_league.rules import (
    APPEARANCE_POINTS,
    ASSIST_POINTS,
    CLEAN_SHEET_POINTS,
    GOAL_POINTS,
    SAVES_PER_POINT,
    plays,
)
from thefrontoffice.adapters.outbound.platforms.fpl.client import FPLSource
from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLAPIError
from thefrontoffice.adapters.outbound.platforms.fpl.types import Fixture, Gameweek, LiveStat, Opponent, Player

logger = logging.getLogger(__name__)

FORM_WEEKS = 5
"""Finished gameweeks his form is read over: five, about a month of matches.

Fewer and one haul or one rest decides it; more and a player who lost his
place in October still reads as the one who had it in August.
"""

HORIZON = 4
"""Gameweeks a transfer is weighed over: this one and the three after.

A transfer is kept for weeks, so one judged on a single fixture buys a
player for the one easy match before three hard ones. Four is as far as
fixtures, form and fitness still say anything about the same player.
"""

DIFFICULTY_STEP = 0.1
"""How far each step of FPL's 1-5 fixture difficulty moves a match: a tenth either side of a 3.

A 2 is worth 1.1 of an average match and a 5 is worth 0.8 — enough to break
a tie between two players in like form, not to bench a premium for a cheap
player at home.
"""

UNDERLYING_WEIGHT = 0.25
"""The share of a match that his underlying numbers decide, the rest his points.

A quarter: expected goals and assists, clean-sheet odds, saves, bonus and
defensive contributions say what he should have scored, which steadies a run
of lucky or unlucky weeks, but points are what the game pays.
"""

CLEAN_SHEET_ODDS = {1: 0.5, 2: 0.4, 3: 0.3, 4: 0.2, 5: 0.12}
"""The chance of a clean sheet by the fixture's difficulty, for his side.

A proxy, since FPL publishes no defensive strength this season: about half
of matches against the weakest attacks end goalless for the defending side,
and about one in eight against the strongest.
"""

SETTLE_MATCHES = 5
"""Matches of his season average his recent form is settled with: as many as the window holds.

A month is long enough to show a change of role and short enough to be a run
of clean sheets or penalties; his season beside it keeps a hot month from
reading as a new level, and a cold one from writing a regular off.
"""

PROJECTION_TOLERANCE = 0.05
"""How far `ep_next` must sit from `form` to count as a projection of its own rather than form again."""

RATE_MINUTES = 270
"""The fewest minutes a per-90 rate is divided by: three full matches.

Twenty minutes and one assist is not 13.5 assists a season, and dividing by
at least this keeps a cameo from reading as a regular's output.
"""

USAGE_STEADY = 60
USAGE_SWING = 45
USAGE_GAMES = 3
"""How his minutes nudge his worth (`competitions.worth.usage`), over the gameweeks his club played in the window.

60 or more a match in every one is a nailed starter: a tenth more. Sixty is
the full appearance, and a forward taken off at seventy minutes is as nailed
as a centre-back who plays ninety — a higher bar rewards defenders for the
substitutions attackers get. A gap of
45 between his most and least, his latest not his most, is a player rotated
in and out: a tenth less. Fewer than three gameweeks say nothing.
"""

RECOVERY = 0.5
"""How much of a doubt is left a gameweek later: half.

`chance_of_playing_next_round` is about the next gameweek alone. A player at
50% now is counted at 75% the week after and 88% the one after that, and one
ruled out at nought at 50%, 75%, 88% — so a horizon neither writes off a knock
nor assumes it clears by Saturday.
"""

GONE = frozenset({"u", "n"})
"""Unavailable or not in the squad: usually a player sold or loaned out, who is not coming back in a month."""

AVERAGE_DIFFICULTY = 3


@dataclass(frozen=True)
class Worth:
    """One player's worth, and the parts it is made of, so every page that shows it can say why."""

    week: float
    """What he adds the gameweek being decided: every match his club plays, his chance and his minutes in."""

    horizon: float
    """What he adds over the next `HORIZON` gameweeks, for a transfer."""

    form: float | None
    """Points per match his club played over the last `FORM_WEEKS` finished gameweeks, settled toward his
    season's (`SETTLE_MATCHES`); None with no record."""

    outlook: float
    """FPL's own projection for the gameweek (`ep_next`)."""

    projected: bool
    """Whether `outlook` is a projection of its own, and so counted; where it only repeats form, it is not."""

    underlying: float | None
    """What his underlying numbers say a match of him is worth, at the gameweek's first fixture; None with no minutes."""

    fixtures: tuple[Opponent, ...]
    """His club's matches in the gameweek being decided: none is a blank, two a double."""

    availability: float
    """His chance of playing it, from nought to one."""

    usage: float
    """What his minutes multiply his worth by: 1 ± `competitions.worth.USAGE_SWING`, or 1."""

    @property
    def per_match(self) -> float | None:
        """What a match of him is worth when he plays it: the week over its matches and his chance; None with neither."""
        if not self.fixtures or not self.availability:
            return None
        return self.week / (len(self.fixtures) * self.availability)


class Valuation:
    """Every player's `Worth`, read the way the rules ask for a value: a function of a player.

    Keeps the fixtures it was figured on, by gameweek from the one decided, so a
    chip's timing reads the same doubles and blanks the figures do.
    """

    def __init__(self, worths: Mapping[int, Worth], weeks: Mapping[int, list[Fixture]] | None = None) -> None:
        self._worths = dict(worths)
        self.weeks = dict(weeks or {})

    def of(self, player: Player) -> Worth | None:
        return self._worths.get(player.id)

    def __call__(self, player: Player) -> float:
        """His worth the gameweek being decided, nought where he has none: what the eleven and the armband use."""
        found = self._worths.get(player.id)
        return found.week if found else 0.0

    def horizon(self, player: Player) -> float:
        """His worth over the next `HORIZON` gameweeks: what a transfer uses."""
        found = self._worths.get(player.id)
        return found.horizon if found else 0.0


@dataclass(frozen=True)
class Record:
    """What one player did over the window."""

    points: int = 0
    matches: int = 0
    minutes: int = 0
    bonus: int = 0
    defending: int = 0
    per_match: tuple[float, ...] = ()
    """His minutes a match in each gameweek his club played, oldest first."""


def gather(client: FPLSource, upcoming: Gameweek) -> Valuation:
    """Every player's worth for `upcoming` and the `HORIZON` from it.

    Form degrades to the projection alone where the results will not load,
    rather than failing a page over it. The fixtures do not: without them a
    blank cannot be told from a match, and every figure would be a guess.
    """
    gameweeks = client.get_gameweeks()
    finished = [g.id for g in gameweeks if g.finished and g.id < upcoming.id]
    window = finished[-FORM_WEEKS:]
    try:
        results = client.get_results(window) if window else {}
    except FPLAPIError as e:
        logger.warning(f"Valuing on projections alone, without recent form: {e}")
        results = {}
    weeks = [g.id for g in gameweeks if upcoming.id <= g.id < upcoming.id + HORIZON] or [upcoming.id]
    fixtures = {week: client.get_fixtures(week) for week in weeks}
    return valuation(client.get_players(), results, fixtures, played=len(finished))


def valuation(
    catalog: Mapping[int, Player],
    results: Mapping[int, Mapping[int, LiveStat]],
    fixtures: Mapping[int, list[Fixture]],
    *,
    played: int,
) -> Valuation:
    """Every player's `Worth` from the window's `results`, oldest first, and each gameweek's `fixtures`, the first
    being the one decided. `played` is how many gameweeks of the season are over, for a share of minutes where the
    window has none."""
    schedule = [_by_club(week) for week in fixtures.values()]
    return Valuation(
        {pid: value(player, record(pid, results.values()), schedule, played=played) for pid, player in catalog.items()},
        fixtures,
    )


def _by_club(fixtures: Iterable[Fixture]) -> dict[str, list[Opponent]]:
    clubs: dict[str, list[Opponent]] = {}
    for fixture in fixtures:
        for club in (fixture.home, fixture.away):
            if (opponent := fixture.opponent_of(club)) is not None:
                clubs.setdefault(club, []).append(opponent)
    return clubs


def record(pid: int, weeks: Iterable[Mapping[int, LiveStat]]) -> Record:
    """His points, matches and minutes over the window, summed."""
    lines = [line for week in weeks if (line := week.get(pid)) is not None]
    return Record(
        points=sum(line.points for line in lines),
        matches=sum(line.matches for line in lines),
        minutes=sum(line.minutes for line in lines),
        bonus=sum(line.bonus for line in lines),
        defending=sum(line.defending for line in lines),
        per_match=tuple(line.minutes / line.matches for line in lines if line.matches),
    )


def value(player: Player, run: Record, schedule: list[dict[str, list[Opponent]]], *, played: int) -> Worth:
    """One player's `Worth` from his run and his club's fixtures, gameweek by gameweek from the one decided."""
    first = schedule[0].get(player.team, []) if schedule else []
    projects = projected(player)
    form = settled(player, run, played)
    share = _share(player, run, played)
    nudge = shared.usage(run.per_match, steady_from=USAGE_STEADY, swings_by=USAGE_SWING, fewest=USAGE_GAMES)
    chance = availability(player)

    def match(opponent: Opponent) -> float:
        scale = difficulty(opponent.difficulty)
        expected = underlying(player, run, share, opponent.difficulty)
        projection = player.expected_points / max(len(first), 1) * scale
        # Before a minute has been played the projection is all there is, form or not.
        outlook = projection if projects or expected is None else expected
        blended = shared.blend(None if form is None else form * scale, outlook) or 0.0
        return blended if expected is None else (1 - UNDERLYING_WEIGHT) * blended + UNDERLYING_WEIGHT * expected

    weeks = [
        sum(match(o) for o in clubs.get(player.team, [])) * recovered(player, chance, ahead) * nudge
        for ahead, clubs in enumerate(schedule)
    ]
    return Worth(
        week=round(weeks[0], 2) if weeks else 0.0,
        horizon=round(sum(weeks), 2),
        form=form,
        outlook=player.expected_points,
        projected=projects,
        underlying=underlying(player, run, share, first[0].difficulty) if first else None,
        fixtures=tuple(first),
        availability=chance,
        usage=nudge,
    )


def projected(player: Player) -> bool:
    """Whether FPL's `ep_next` says anything `form` does not (`PROJECTION_TOLERANCE`)."""
    return abs(player.expected_points - player.form) > PROJECTION_TOLERANCE


def settled(player: Player, run: Record, played: int) -> float | None:
    """His points per match over the window, settled toward his season's (`SETTLE_MATCHES`); None with neither."""
    season = player.total_points / played if played else None
    if not run.matches:
        return season
    if season is None:
        return run.points / run.matches
    return (run.points + SETTLE_MATCHES * season) / (run.matches + SETTLE_MATCHES)


def difficulty(rating: int) -> float:
    """What a fixture's 1-5 difficulty multiplies a match by (`DIFFICULTY_STEP`); an unrated one counts as average."""
    return 1 + DIFFICULTY_STEP * (AVERAGE_DIFFICULTY - (rating or AVERAGE_DIFFICULTY))


def availability(player: Player) -> float:
    """His chance of playing the next gameweek: nought when ruled out, FPL's published chance, otherwise certain."""
    if not plays(player):
        return 0.0
    return 1.0 if player.chance_of_playing is None else player.chance_of_playing / 100


def recovered(player: Player, chance: float, ahead: int) -> float:
    """His chance `ahead` gameweeks past the next (`RECOVERY`); nought throughout for a player gone (`GONE`)."""
    if player.status in GONE:
        return 0.0
    return 1 - (1 - chance) * RECOVERY**ahead


def _share(player: Player, run: Record, played: int) -> float | None:
    """The share of his club's minutes he played: over the window, else the season, else unknown."""
    if run.matches:
        return min(1.0, run.minutes / (90 * run.matches))
    if played and player.minutes:
        return min(1.0, player.minutes / (90 * played))
    return None


def _per_90(total: float, minutes: int) -> float:
    return total * 90 / max(minutes, RATE_MINUTES)


def underlying(player: Player, run: Record, share: float | None, rating: int) -> float | None:
    """What a match of him should score at this difficulty, from his underlying numbers; None without minutes.

    Appearance, expected goals and assists at his position's rates (scaled by
    the difficulty), clean-sheet odds (`CLEAN_SHEET_ODDS`), saves, bonus, and the
    defensive-contribution points he has been earning a match — all at his
    share of the minutes. Goals conceded are left to the clean-sheet odds.
    """
    if share is None:
        return None
    minutes = player.minutes
    attacking = (
        _per_90(player.expected_goals, minutes) * GOAL_POINTS.get(player.position, 0)
        + _per_90(player.expected_assists, minutes) * ASSIST_POINTS
    ) * difficulty(rating)
    clean_sheet = CLEAN_SHEET_ODDS.get(rating or AVERAGE_DIFFICULTY, 0.3) * CLEAN_SHEET_POINTS.get(player.position, 0)
    saves = _per_90(player.saves, minutes) / SAVES_PER_POINT
    bonus = _per_90(player.bonus, minutes)
    defending = run.defending / run.matches if run.matches else 0.0
    return share * (APPEARANCE_POINTS + attacking + clean_sheet + saves + bonus) + defending
