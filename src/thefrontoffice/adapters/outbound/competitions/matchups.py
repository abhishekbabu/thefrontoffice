"""How much each defense gives up to each position, ranked: the matchup half of a player's week.

Every competition with positions reads it alike — a football defense against
running backs, a basketball club against point guards — from the games
already played: what the players at a position scored against each opponent,
per game that opponent played.
"""

from collections import defaultdict
from collections.abc import Hashable, Iterable
from dataclasses import dataclass
from typing import NamedTuple

from thefrontoffice.adapters.outbound.competitions.places import ordinal
from thefrontoffice.domain.models import Tone


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

    @property
    def tone(self) -> Tone:
        """Good in the softest quarter, a warning in the toughest."""
        if self.rank <= self.defenses // 4:
            return "good"
        if self.rank > self.defenses - self.defenses // 4:
            return "warning"
        return "neutral"

    def describe(self) -> str:
        """'vs MIA, 4th-most to RBs (24.1 a game)'."""
        return f"vs {self.opponent}, {self.allowed_to()}"

    def allowed_to(self) -> str:
        """'4th-most to RBs (24.10 a game)', or '(24.1 pts a game)' with a `unit`: the defense's record, for a line
        that already says who it is."""
        noun = "defenses" if self.position == "DEF" else f"{self.position}s"
        if self.rank == 1:
            rank = "the most"
        elif self.rank == self.defenses:
            rank = "the fewest"
        else:
            rank = f"{ordinal(self.rank)}-most"
        figure = f"{self.allowed:.1f} {self.unit}" if self.unit else f"{self.allowed:.2f}"
        return f"{rank} to {noun} ({figure} a game)"


class Scored(NamedTuple):
    """What one player at one position scored against one opponent in one game."""

    opponent: str
    position: str
    game: Hashable
    """Which of the opponent's games it was: a week, a date."""

    figure: float


def allowed(lines: Iterable[Scored], unit: str = "") -> dict[tuple[str, str], Matchup]:
    """What each defense has given up per game to each position, ranked, by (opponent, position).

    Per game rather than in total, because byes and schedules leave defenses
    with different numbers of games. Every defense is ranked at every
    position, including ones that have given a position nothing, which is a
    real and good record.
    """
    totals: dict[tuple[str, str], float] = defaultdict(float)
    games: dict[str, set[Hashable]] = defaultdict(set)
    positions: set[str] = set()
    for line in lines:
        totals[(line.opponent, line.position)] += line.figure
        games[line.opponent].add(line.game)
        positions.add(line.position)

    found: dict[tuple[str, str], Matchup] = {}
    for position in positions:
        per_game = {defense: totals[(defense, position)] / len(played) for defense, played in games.items()}
        ranked = sorted(per_game, key=lambda defense: -per_game[defense])
        for rank, defense in enumerate(ranked, start=1):
            found[(defense, position)] = Matchup(
                opponent=defense,
                position=position,
                allowed=per_game[defense],
                rank=rank,
                defenses=len(ranked),
                unit=unit,
            )
    return found
