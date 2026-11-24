"""How much each defense gives up to each position, ranked: the matchup half of a player's week.

Every competition with positions reads it alike — a football defense against
running backs, a basketball club against point guards — from the games
already played: what the players at a position scored against each opponent,
per game that opponent played — over the season, and over its last few games,
because a defense changes mid-season (an injury, a new scheme) and its season
figure is slow to say so.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import NamedTuple

from thefrontoffice.adapters.outbound.competitions.places import ordinal
from thefrontoffice.domain.models import Tone

RECENT_GAMES = 5
"""The defense's latest games its recent record is read over: enough to outweigh one blowout, few enough to show a
change in who it is."""


@dataclass(frozen=True)
class Recent:
    """What one defense has given up to one position over its last `RECENT_GAMES` games, against the rest's last."""

    allowed: float
    rank: int


@dataclass(frozen=True)
class Matchup:
    """How much one defense gives up to one position, against the rest."""

    opponent: str
    position: str
    allowed: float
    """Per game, in whatever the competition counts: fantasy points in the league's scoring, or points."""

    rank: int
    """1 is the defense that gives up the most: the softest matchup."""

    defenses: int

    unit: str = ""
    """What `allowed` counts, where a line must say: 'pts'. Empty reads as the league's fantasy points."""

    recent: Recent | None = None
    """Its record over its last `RECENT_GAMES`; None until some defense has played more games than that, before which
    it is the season's record again."""

    @property
    def standing(self) -> float:
        """Where it ranks once its recent games are weighed: midway between its season rank and its recent one.

        The recent games are counted in the season's too, so an even split leans on them without letting five
        games — one of them a blowout — outvote the season.
        """
        return self.rank if self.recent is None else (self.rank + self.recent.rank) / 2

    @property
    def tone(self) -> Tone:
        """Good in the softest quarter, a warning in the toughest, by its `standing`."""
        if self.standing <= self.defenses // 4:
            return "good"
        if self.standing > self.defenses - self.defenses // 4:
            return "warning"
        return "neutral"

    def describe(self) -> str:
        """'vs MIA, 4th-most to RBs (24.10 a game) · 13th over last 5 (18.20)'."""
        return f"vs {self.opponent}, {self.allowed_to()}"

    def allowed_to(self) -> str:
        """'4th-most to RBs (24.10 a game)', or '(24.1 pts a game)' with a `unit`, then its recent record where it
        has one: the defense's record, for a line that already says who it is."""
        noun = "defenses" if self.position == "DEF" else f"{self.position}s"
        if self.rank == 1:
            rank = "the most"
        elif self.rank == self.defenses:
            rank = "the fewest"
        else:
            rank = f"{ordinal(self.rank)}-most"
        season = f"{rank} to {noun} ({self._figure(self.allowed)} a game)"
        if self.recent is None:
            return season
        return f"{season} · {ordinal(self.recent.rank)} over last {RECENT_GAMES} ({self._figure(self.recent.allowed)})"

    def _figure(self, allowed: float) -> str:
        return f"{allowed:.1f} {self.unit}" if self.unit else f"{allowed:.2f}"


class Scored[G: (int, str)](NamedTuple):
    """What one player at one position scored against one opponent in one game."""

    opponent: str
    position: str
    game: G
    """Which of the opponent's games it was, ordered oldest first: a week, an ISO date."""

    figure: float


def allowed[G: (int, str)](lines: Iterable[Scored[G]], unit: str = "") -> dict[tuple[str, str], Matchup]:
    """What each defense has given up per game to each position, ranked, by (opponent, position).

    Per game rather than in total, because byes and schedules leave defenses
    with different numbers of games. Every defense is ranked at every
    position, including ones that have given a position nothing, which is a
    real and good record. The recent record is each defense's own last
    `RECENT_GAMES`, ranked against every other's.
    """
    scored: dict[tuple[str, str], dict[G, float]] = defaultdict(lambda: defaultdict(float))
    games: dict[str, set[G]] = defaultdict(set)
    positions: set[str] = set()
    for line in lines:
        scored[(line.opponent, line.position)][line.game] += line.figure
        games[line.opponent].add(line.game)
        positions.add(line.position)
    latest = {defense: set(sorted(played)[-RECENT_GAMES:]) for defense, played in games.items()}
    windowed = any(len(played) > RECENT_GAMES for played in games.values())

    found: dict[tuple[str, str], Matchup] = {}
    for position in positions:
        season = _ranked(
            {defense: sum(scored[(defense, position)].values()) / len(games[defense]) for defense in games}
        )
        recent = _ranked(
            {
                defense: sum(figure for game, figure in scored[(defense, position)].items() if game in window)
                / len(window)
                for defense, window in latest.items()
            }
        )
        for defense, (rank, per_game) in season.items():
            found[(defense, position)] = Matchup(
                opponent=defense,
                position=position,
                allowed=per_game,
                rank=rank,
                defenses=len(season),
                unit=unit,
                recent=Recent(allowed=recent[defense][1], rank=recent[defense][0]) if windowed else None,
            )
    return found


def _ranked(per_game: Mapping[str, float]) -> dict[str, tuple[int, float]]:
    """Each defense's rank, 1 the most given up, beside its figure."""
    ordered = sorted(per_game, key=lambda defense: -per_game[defense])
    return {defense: (rank, per_game[defense]) for rank, defense in enumerate(ordered, start=1)}
