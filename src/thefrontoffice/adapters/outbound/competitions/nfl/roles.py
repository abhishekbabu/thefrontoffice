"""Which way a player's role is heading: what a drop is ranked by before his points.

A season average and a projection both lag a role. The receiver whose target
share fell away when a teammate came back still carries the weeks before, and
the back just home from injured reserve carries the weeks he missed, and so
does the projection that reads his season. His share of the work over his
last games against the ones before says which way he is going sooner: a drop
takes the player whose role is falling, and keeps the one whose role is rising
or who heads his club's depth chart, whatever their points so far.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from thefrontoffice.adapters.outbound.competitions.nfl.evidence import (
    MIN_GAMES_FOR_AVERAGE,
    RECEIVERS,
    REGULAR,
    ROLE_GAMES,
    Appearance,
)
from thefrontoffice.adapters.outbound.competitions.nfl.model import Projection
from thefrontoffice.adapters.outbound.competitions.nfl.week import Week
from thefrontoffice.adapters.outbound.competitions.places import ordinal
from thefrontoffice.adapters.outbound.competitions.teammates import surname

Direction = Literal["rising", "holding", "falling"]

STEPS: dict[str, float] = {"snaps": 0.10, "targets": 0.05, "carries": 0.10}
"""How far a share must move, his last games against the ones before, to count as rising or falling: a tenth of
the snaps or of the carries, a twentieth of the targets — a club throws to five or six players, so a twentieth is
a quarter of a regular receiver's share."""

MEASURES: dict[str, tuple[str, ...]] = {
    "RB": ("snaps", "carries"),
    "WR": ("snaps", "targets"),
    "TE": ("snaps", "targets"),
}
"""What a role is at each position: a back's snaps and share of the carries, a receiver's snaps and share of the targets."""

RETURN_GAP = 3
"""Weeks between two of his games for one club that make the later a return: two games missed beside a bye."""

LEAD_RECEIVERS = 2
"""The receivers and tight ends a club's target share counts as leading its passing game: its first two options."""

LEAD_POSITIONS = frozenset({"RB", "WR", "TE"})
"""Where heading the club's depth chart is a role worth keeping: a quarterback's, kicker's or defense's is the slot itself."""


@dataclass(frozen=True)
class Shift:
    """One share over his last games against the ones before."""

    measure: str
    now: float
    before: float
    low: float
    """His least in any of his last games: a role that rose is above where it was in every one of them."""
    high: float
    """His most in any of them: a role that fell is below where it was in every one."""

    @property
    def direction(self) -> Direction:
        """Rising or falling by `STEPS` on average and in every one of his last games; holding otherwise, which is
        what a share that swings game to game is doing."""
        step = STEPS[self.measure]
        if self.now - self.before >= step and self.low >= self.before:
            return "rising"
        if self.before - self.now >= step and self.high <= self.before:
            return "falling"
        return "holding"

    def describe(self) -> str:
        """'target share 9%, was 15%'."""
        noun = {"snaps": "snaps", "targets": "target share", "carries": "carry share"}[self.measure]
        return f"{noun} {self.now:.0%}, was {self.before:.0%}"


@dataclass(frozen=True)
class Heading:
    """Which way his role is going, from what, and since when."""

    direction: Direction
    shifts: tuple[Shift, ...]
    returned: int | None = None
    """The week he came back from an absence of `RETURN_GAP` or more, where his last games start there."""
    teammate: tuple[str, int] | None = None
    """A regular teammate back in his latest games, by surname, and the week he came back."""

    def describe(self) -> str:
        """'target share 9%, was 15%; Pickens back since week 10': what moved, and what it may be down to."""
        moved = [shift for shift in self.shifts if shift.direction != "holding"] or list(self.shifts)
        parts = [", ".join(shift.describe() for shift in moved)]
        if self.returned is not None:
            parts.append(f"back from injury in week {self.returned}")
        if self.teammate is not None:
            parts.append(f"{self.teammate[0]} back since week {self.teammate[1]}")
        return "; ".join(parts)


def window(state: Week, player_id: str) -> tuple[Sequence[Appearance], Sequence[Appearance], int | None]:
    """His last games and the ones before them, and the week he came back where those last games start at a return.

    A return within his last `ROLE_GAMES` games starts them there: the games
    since are his role now, however few, and the ones before the absence what
    it was. Otherwise his last `ROLE_GAMES` against everything earlier.
    """
    played = state.evidence.appearances.get(player_id, ())
    for at in range(max(1, len(played) - ROLE_GAMES), len(played)):
        back, before = played[at], played[at - 1]
        if back.team == before.team and back.week - before.week >= RETURN_GAP:
            return played[at:], played[:at], back.week
    return played[-ROLE_GAMES:], played[:-ROLE_GAMES], None


def heading(state: Week, player_id: str) -> Heading | None:
    """Which way his role is going; None for a position with no role to read, or too few games before to compare."""
    measures = MEASURES.get(state.evidence.positions.get(player_id, ""))
    if measures is None:
        return None
    recent, earlier, returned = window(state, player_id)
    if len(earlier) < MIN_GAMES_FOR_AVERAGE:
        return None
    shifts = tuple(found for measure in measures if (found := _shift(measure, recent, earlier)) is not None)
    if not shifts:
        return None
    directions = {shift.direction for shift in shifts}
    if "rising" in directions and "falling" not in directions:
        direction: Direction = "rising"
    elif "falling" in directions and "rising" not in directions:
        direction = "falling"
    else:
        direction = "holding"
    teammate = _teammate_back(state, player_id, recent) if direction == "falling" else None
    return Heading(direction, shifts, returned, teammate)


def leads(state: Week, player: Projection) -> str:
    """How he leads his club's work, where he does: 'depth-1 RB' for a back, '2nd in DAL target share' for a
    receiver or tight end in its top `LEAD_RECEIVERS` over his last games; empty otherwise.

    A receiver by his share rather than the depth chart: Sleeper lists a depth-1 at every receiver spot, three a
    club, which says who lines up first and not who the ball goes to.
    """
    meta = state.players.get(player.player_id)
    if meta is None or meta.position not in LEAD_POSITIONS:
        return ""
    if meta.position not in RECEIVERS:
        return f"depth-1 {meta.position}" if meta.depth_chart_order == 1 else ""
    rank = _target_rank(state, player.player_id)
    return f"{ordinal(rank)} in {meta.team} target share" if rank is not None and rank <= LEAD_RECEIVERS else ""


def _target_rank(state: Week, player_id: str) -> int | None:
    """Where his share of his club's targets over his last `ROLE_GAMES` games ranks among its players in those
    weeks, 1 the most; None where he has drawn none."""
    played = state.evidence.appearances.get(player_id, ())
    if not played:
        return None
    club = played[-1].team
    weeks = {game.week for game in played[-ROLE_GAMES:] if game.team == club}
    shares = {
        other: total
        for other, games in state.evidence.appearances.items()
        if (total := sum(game.target_share or 0.0 for game in games if game.team == club and game.week in weeks))
    }
    mine = shares.get(player_id)
    if mine is None:
        return None
    return 1 + sum(1 for other, total in shares.items() if other != player_id and total > mine)


def protected(state: Week, player: Projection) -> str:
    """Why he is the last to drop — 'role rising', 'depth-1 RB', '1st in DAL target share' — or empty."""
    found = heading(state, player.player_id)
    meta = state.players.get(player.player_id)
    # A role that rose filling in for a teammate who is back is not his.
    filling_in = meta is not None and state.teammates.filling_in(meta) is not None
    if found is not None and found.direction == "rising" and not filling_in:
        return "role rising"
    return leads(state, player)


def falling(state: Week, player_id: str) -> Heading | None:
    """His heading where his role is falling; None otherwise."""
    found = heading(state, player_id)
    return found if found is not None and found.direction == "falling" else None


def _shift(measure: str, recent: Sequence[Appearance], earlier: Sequence[Appearance]) -> Shift | None:
    def read(game: Appearance) -> float | None:
        return {"snaps": game.snap_share, "targets": game.target_share, "carries": game.carry_share}[measure]

    now = [value for game in recent if (value := read(game)) is not None]
    before = [value for game in earlier if (value := read(game)) is not None]
    if not now or not before:
        return None
    return Shift(measure, sum(now) / len(now), sum(before) / len(before), min(now), max(now))


def _teammate_back(state: Week, player_id: str, recent: Sequence[Appearance]) -> tuple[str, int] | None:
    """A regular teammate at his position — any receiver, for a receiver — who missed one of his last games and
    played his latest: whose return his role may have given way to. The one back most recently, where several are."""
    latest = recent[-1]
    position = state.evidence.positions.get(player_id, "")
    group = RECEIVERS if position in RECEIVERS else frozenset({position})
    weeks = [game.week for game in recent]
    found: tuple[str, int] | None = None
    for teammate, games in state.evidence.appearances.items():
        if teammate == player_id or state.evidence.positions.get(teammate) not in group:
            continue
        mine = {game.week: game for game in games if game.team == latest.team}
        shares = [game.snap_share for game in mine.values() if game.snap_share is not None]
        if latest.week not in mine or not shares or sum(shares) / len(shares) < REGULAR:
            continue
        missed = [week for week in weeks if week not in mine]
        if not missed:
            continue
        back = min(week for week in mine if week > max(missed))
        meta = state.players.get(teammate)
        if meta is not None and (found is None or back > found[1]):
            found = (surname(meta.name), back)
    return found
