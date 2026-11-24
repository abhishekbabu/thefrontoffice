"""A starter whose games have fallen well short of his projection: a slump the projection has not read.

A projection keeps the number a player's name earned while his weeks say
something else: the tight end on his usual snaps whose targets stopped turning
into yards, the receiver whose quarterback changed. `worth` already blends his
form in, but every free agent at his position is read the same way, so a
starter projected well above what he scores still outranks a streamer playing
better. Once his games and his projection disagree by enough, for long enough,
the slot is weighed on form instead — a call the list labels as one, never a
projection it quotes.

Only a real gap counts: his points a game over his last few games played,
well under this week's projection, in all but one of them. One bad afternoon
is noise either way; three out of four is a trend.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from thefrontoffice.adapters.outbound.competitions.matchups import Matchup
from thefrontoffice.adapters.outbound.competitions.nfl.evidence import (
    MIN_GAMES_FOR_AVERAGE,
    TARGET_POSITIONS,
    Appearance,
)
from thefrontoffice.adapters.outbound.competitions.nfl.model import Projection
from thefrontoffice.adapters.outbound.competitions.nfl.week import Week
from thefrontoffice.adapters.outbound.competitions.nfl.worth import plays, usage

SLUMP_LABEL = "Slump"
"""What a slump is called wherever it is shown: the drawer, a roster row's note, a model's player line."""

SLUMP_GAMES = 4
"""His last games played that a slump is read over, games he missed left out: one bad afternoon is a quarter of it."""

FEWEST = 3
"""Games played the window needs: two is one bad game and a coin flip."""

SHORT_OF = 0.6
"""The share of this week's projection his points a game must fall under. Weekly scoring swings by
about half a projection either way, so a month under three-fifths of it is not a projection running cold."""

SHORT_BY = 3.0
"""And the points a game under it: a five-point player projected seven is not the question a slot turns on."""

COLLAPSED = 0.75
"""Efficiency now against before under which it has collapsed: yards a target for a receiver or tight end,
points a touch for a back. A quarter off is beyond what a month's matchups explain."""

HOLDS = 0.9
"""Usage now against before at which it holds: within a tenth of the snaps, and of the target share."""


@dataclass(frozen=True)
class Change:
    """One measure over the slump against his games before it."""

    measure: str
    now: float
    before: float

    @property
    def ratio(self) -> float:
        return self.now / self.before if self.before else 1.0


@dataclass(frozen=True)
class Slump:
    """A starter scoring well under his projection over his last few games, and what the games say about why."""

    player_id: str
    games: int
    recent: float
    """His points a game over them."""
    projected: float
    efficiency: Change | None = None
    """Yards a target ('yds/tgt'), or for a back points a touch ('pts/touch'); None without games before to compare."""
    snaps: Change | None = None
    targets: Change | None = None
    """His share of his club's targets."""
    passer: tuple[str, str] | None = None
    """His club's starting quarterback before the slump and in his latest game, by name, where they differ."""

    @property
    def collapsed(self) -> bool:
        """Whether his efficiency fell by `COLLAPSED` or more."""
        return self.efficiency is not None and self.efficiency.ratio <= COLLAPSED

    @property
    def usage_holds(self) -> bool | None:
        """Whether his snaps and target share held (`HOLDS`); None with nothing before to compare."""
        measured = [change for change in (self.snaps, self.targets) if change is not None]
        if not measured:
            return None
        return all(change.ratio >= HOLDS for change in measured)

    def short(self) -> str:
        """'4.95/g L4 vs 10.38 proj · 3.4 yds/tgt, was 5.9 (collapsed) · usage down: snaps 79%, was 91%; tgt share
        22%, was 21% · QB Jones→Leonard'."""
        parts = [f"{self.recent:.2f}/g L{self.games} vs {self.projected:.2f} proj"]
        if (rate := self.efficiency) is not None:
            parts.append(
                f"{rate.now:.1f} {rate.measure}, was {rate.before:.1f}" + (" (collapsed)" if self.collapsed else "")
            )
        if (holds := self.usage_holds) is not None:
            shares = [
                f"{name} {change.now:.0%}, was {change.before:.0%}"
                for name, change in (("snaps", self.snaps), ("tgt share", self.targets))
                if change is not None
            ]
            parts.append(f"usage {'holds' if holds else 'down'}: {'; '.join(shares)}")
        if self.passer is not None:
            parts.append(f"QB {self.passer[0]}→{self.passer[1]}")
        return " · ".join(parts)


def slump(state: Week, player: Projection) -> Slump | None:
    """His slump, where his last `SLUMP_GAMES` games played fall short of this week's projection; None otherwise.

    A back, receiver or tight end with a game this week and at least `FEWEST`
    games played: his points a game under `SHORT_OF` of his projection and by
    `SHORT_BY`, with all but one of the games under that line. A quarterback,
    a kicker or a defense turns on things his own line does not show.
    """
    if player.position not in TARGET_POSITIONS or not plays(state, player) or player.points <= 0:
        return None
    played = state.evidence.appearances.get(player.player_id, ())
    window, before = played[-SLUMP_GAMES:], played[:-SLUMP_GAMES]
    if len(window) < FEWEST:
        return None
    line = SHORT_OF * player.points
    recent = sum(game.points for game in window) / len(window)
    if recent >= line or player.points - recent < SHORT_BY:
        return None
    if sum(game.points < line for game in window) < len(window) - 1:
        return None
    earlier = before if len(before) >= MIN_GAMES_FOR_AVERAGE else ()
    return Slump(
        player_id=player.player_id,
        games=len(window),
        recent=recent,
        projected=player.points,
        efficiency=_efficiency(player.position, window, earlier),
        snaps=_mean_change("snaps", window, earlier, lambda game: game.snap_share),
        targets=_mean_change("targets", window, earlier, lambda game: game.target_share),
        passer=_passer_change(state, window, earlier),
    )


def slumps(state: Week) -> dict[str, Slump]:
    """Every slumping starter in your lineup as set, by player id."""
    found = {}
    for slot in state.lineup:
        if slot.player is not None and (sunk := slump(state, slot.player)) is not None:
            found[slot.player.player_id] = sunk
    return found


def _efficiency(position: str, now: Sequence[Appearance], before: Sequence[Appearance]) -> Change | None:
    """Yards a target for a receiver or tight end, points a touch for a back, now against before."""

    def rate(games: Sequence[Appearance]) -> float | None:
        if position == "RB":
            touches = sum(game.opportunities for game in games)
            return sum(game.points for game in games) / touches if touches else None
        targets = sum(game.targets for game in games)
        return sum(game.receiving_yards for game in games) / targets if targets else None

    measure = "pts/touch" if position == "RB" else "yds/tgt"
    found, earlier = rate(now), rate(before)
    return None if found is None or earlier is None else Change(measure, found, earlier)


def _mean_change(
    measure: str,
    now: Sequence[Appearance],
    before: Sequence[Appearance],
    read: Callable[[Appearance], float | None],
) -> Change | None:
    """A per-game share's average over the slump against before; None where either has no reading."""
    found = [value for game in now if (value := read(game)) is not None]
    earlier = [value for game in before if (value := read(game)) is not None]
    if not found or not earlier:
        return None
    return Change(measure, sum(found) / len(found), sum(earlier) / len(earlier))


def _passer_change(state: Week, now: Sequence[Appearance], before: Sequence[Appearance]) -> tuple[str, str] | None:
    """His club's usual starting quarterback before the slump, and the one in his latest game, where they differ."""
    latest = now[-1]
    current = state.evidence.passers.get((latest.team, latest.week))
    usual = [
        passer
        for game in before
        if game.team == latest.team and (passer := state.evidence.passers.get((game.team, game.week)))
    ]
    if current is None or not usual:
        return None
    was = max(set(usual), key=usual.count)
    if was == current:
        return None
    return _name(state, was), _name(state, current)


def _name(state: Week, player_id: str) -> str:
    meta = state.players.get(player_id)
    return meta.name.split(" ")[-1] if meta else player_id


# ── the form call ───────────────────────────────────────────────────────

CALL_FORM = 0.75
"""Form's share of a form call, against the projection's: `worth` weighs them evenly, which is what kept a
slumping starter ahead of every streamer. A quarter stays with the projection, which still reads the week."""

MATCHUP_SWING = 0.1
"""The most a matchup moves a form call, either way: the softest defense at his position a tenth up, the toughest a tenth down."""

CALL_BY = 2.0
"""Points a form call must favour the player coming in by: under it the two are a coin flip, and a hunch is no move."""


def matchup_factor(matchup: Matchup | None) -> float:
    """1 ± `MATCHUP_SWING`, straight across its `standing` (season and recent ranks, evenly): 1 is the softest
    defense, the last the toughest."""
    if matchup is None or matchup.defenses < 2:
        return 1.0
    middle = (matchup.defenses + 1) / 2
    return 1 + MATCHUP_SWING * (middle - matchup.standing) / (middle - 1)


def called(state: Week, player: Projection) -> float | None:
    """What a form call weighs him by: `CALL_FORM` of his points a game over his last `SLUMP_GAMES` played and the
    rest his projection, times his `usage` and his `matchup_factor`. None with too few games to read form from,
    or no game this week."""
    form = recent(state, player.player_id)
    if form is None or not plays(state, player):
        return None
    blended = CALL_FORM * form + (1 - CALL_FORM) * player.points
    return blended * usage(state, player.player_id) * matchup_factor(state.evidence.matchup(player))


def recent(state: Week, player_id: str) -> float | None:
    """His points a game over his last `SLUMP_GAMES` played, as a form call reads them; None with too few."""
    games = [game.points for game in state.evidence.appearances.get(player_id, ())[-SLUMP_GAMES:]]
    return sum(games) / len(games) if len(games) >= MIN_GAMES_FOR_AVERAGE else None
