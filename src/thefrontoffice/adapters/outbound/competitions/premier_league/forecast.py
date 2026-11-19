"""A head-to-head gameweek as the simulation reads it: each side's eleven, its captain, and its bench.

The generic engine in `application/forecasting.py` plays it out; this says what an
FPL gameweek is made of. Each player's match is drawn from his own recent matches
— those he played in the last `RECENT_GAMEWEEKS` gameweeks — once for every match
his club has left in the gameweek: none in a blank, two in a double. For a
gameweek still to come those matches are scaled to his worth a match (`worth.py`),
so the tie is centred on the figure the eleven and the armband are picked on and
the spread is still his own. Whether he plays at all is FPL's published chance
where there is one, else how often he has played lately.

The captain counts twice (three times under Triple Captain) by appearing that many
times in his side: the same draw, so his week is doubled rather than drawn again.

Auto-subs are approximated. A bench player comes on with the chance that enough
starters ahead of him miss out — the keeper for the keeper, the outfield bench in
the order the manager set — so each side's total is right on average, though not
which starter a substitute replaces, nor whether the formation allows him.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from statistics import fmean

from thefrontoffice.adapters.outbound.competitions.premier_league.rules import Roster, plays
from thefrontoffice.adapters.outbound.platforms.fpl.types import LiveStat, Opponent, Pick, Player, PlayerGame
from thefrontoffice.domain.models import MatchupInput, Outcomes

RECENT_GAMEWEEKS = 8
"""How far back a player's matches are read from: long enough for a range, short enough to be this season's role."""

FORM_ERROR = 0.1
"""Spread of a factor on a player's whole gameweek, for how far his recent matches may be off the one to come."""


@dataclass(frozen=True)
class Gameweek:
    """What a gameweek's draws turn on, for both sides alike."""

    fixtures: Mapping[str, list[Opponent]]
    """Each club's matches this gameweek."""

    games: Mapping[int, list[PlayerGame]]
    """Each player's matches this season, oldest first; none for one whose log would not load."""

    live: Mapping[int, LiveStat]
    """What each has scored so far, once the gameweek is under way."""

    recent_from: int
    """The first gameweek whose matches a player's range is read from."""

    to_come: bool
    """No deadline has passed for it yet: the picks are last week's, and its chips are not this week's."""

    expected: Mapping[int, float] = field(default_factory=dict)
    """Each player's worth a match he plays, for a gameweek to come; empty for one under way."""


def matchup(mine: Roster, theirs: Roster, week: Gameweek, seed: int) -> MatchupInput:
    """Both sides of the tie, ready to simulate."""
    return MatchupInput(mine=side(mine, week, "mine"), theirs=side(theirs, week, "theirs"), seed=seed)


def side(squad: Roster, week: Gameweek, tag: str) -> tuple[Outcomes, ...]:
    """One side's draws: each starter as many times as he counts, then the bench as it would come on.

    `tag` keeps one side's bench apart from the other's: a player both own is the
    same draw in both elevens, but on a bench his chance of counting is that side's own.
    """
    starters = [(pick, player) for pick, player in squad.picked if pick.is_starting]
    bench = [(pick, player) for pick, player in squad.picked if not pick.is_starting]
    drawn: list[Outcomes] = []
    for pick, player in starters:
        drawn += [outcomes(player, week)] * counted(pick, week)
    if bench_boosted(squad, week):
        return (*drawn, *(outcomes(player, week) for _, player in bench))

    misses = {player.id: miss(player, week) for _, player in starters}
    keeper = sum(misses[p.id] for _, p in starters if p.position == "GKP")
    outfield = sum(misses[p.id] for _, p in starters if p.position != "GKP")
    ahead = 0
    for _, player in bench:
        if player.position == "GKP":
            called = min(1.0, keeper)
        else:
            called = min(1.0, max(0.0, outfield - ahead))
            ahead += 1
        if called > 0:
            drawn.append(substitute(outcomes(player, week), called, tag))
    return tuple(drawn)


def counted(pick: Pick, week: Gameweek) -> int:
    """How many times a starter's points count: his pick's multiplier, or for a gameweek to come, two for the captain.

    A gameweek to come is shown with last week's picks, whose multipliers carry
    last week's chips; this week's are not set until its deadline.
    """
    if week.to_come:
        return 2 if pick.is_captain else 1
    return max(pick.multiplier, 1)


def bench_boosted(squad: Roster, week: Gameweek) -> bool:
    """Bench Boost is on, so all fifteen count: known only once the gameweek's picks are published."""
    return not week.to_come and squad.squad.active_chip == "bboost"


def substitute(drawn: Outcomes, called: float, tag: str) -> Outcomes:
    """A bench player as he counts: only when called on, and drawn apart from the same player in an eleven."""
    return replace(
        drawn,
        player_id=f"{drawn.player_id}:bench:{tag}",
        plays=drawn.plays * called,
        floor=drawn.floor * called,
        projection=drawn.projection * called,
    )


def outcomes(player: Player, week: Gameweek) -> Outcomes:
    """His gameweek as a range: his recent matches, one draw for each match his club has left, and what he has already."""
    stat = week.live.get(player.id)
    left = matches_left(player, week)
    samples = recent_points(player, week)
    chance = playing_chance(player, week)
    return Outcomes(
        player_id=str(player.id),
        name=player.name,
        projection=round((stat.points if stat else 0) + (fmean(samples) * left * chance if samples else 0.0), 2),
        samples=samples,
        plays=chance,
        floor=float(stat.points) if stat else 0.0,
        projection_error=FORM_ERROR,
        games=left,
    )


def matches_left(player: Player, week: Gameweek) -> int:
    """His club's matches this gameweek that have not kicked off: none in a blank, two in a double.

    One under way counts as played, its points so far already on the board.
    """
    return sum(not o.started for o in week.fixtures.get(player.team, []))


def recent_points(player: Player, week: Gameweek) -> tuple[float, ...]:
    """Points from each match he played in the recent gameweeks; his season's points a match where there are none."""
    played = [g for g in week.games.get(player.id, []) if g.event >= week.recent_from and g.played]
    samples = tuple(float(g.points) for g in played) or (
        (player.points_per_game,) if player.points_per_game > 0 else ()
    )
    return centred(samples, week.expected.get(player.id))


def centred(samples: tuple[float, ...], expected: float | None) -> tuple[float, ...]:
    """`samples` scaled so their mean is `expected`, his worth a match; as they are without one, or without a mean to scale."""
    if expected is None:
        return samples
    mean = fmean(samples) if samples else 0.0
    if mean <= 0:
        return (expected,) if expected > 0 else samples
    return tuple(round(s * expected / mean, 2) for s in samples)


def playing_chance(player: Player, week: Gameweek) -> float:
    """FPL's own chance where it publishes one, nought where it rules him out, else how often he played lately."""
    if not plays(player):
        return 0.0
    if player.chance_of_playing is not None:
        return player.chance_of_playing / 100
    recent = [g for g in week.games.get(player.id, []) if g.event >= week.recent_from]
    return sum(g.played for g in recent) / len(recent) if recent else 1.0


def miss(player: Player, week: Gameweek) -> float:
    """The chance a starter adds nothing this gameweek, so a substitute comes on for him.

    Certain where his club blanks, or its matches are behind it and he played no
    part; otherwise the chance he does not play.
    """
    if matches_left(player, week) == 0:
        stat = week.live.get(player.id)
        return 0.0 if stat is not None and stat.has_played else 1.0
    return 1.0 - playing_chance(player, week)


def recent_from(current: int) -> int:
    """The first gameweek a range is read from, for a gameweek numbered `current`."""
    return max(1, current - RECENT_GAMEWEEKS)


def everyone(*squads: Roster) -> Sequence[int]:
    """Every player in the squads, once: whose logs a forecast reads."""
    return list(dict.fromkeys(p.id for squad in squads for p in squad.players))
