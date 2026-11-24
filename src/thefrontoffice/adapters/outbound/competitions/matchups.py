"""How much each defense gives up to each position, ranked: the matchup half of a player's week.

Every competition with positions reads it alike — a football defense against
running backs, a basketball club against point guards — from the games
already played: what the players at a position scored against each opponent,
per game that opponent played — over the season, and over its last few games,
because a defense changes mid-season (an injury, a new scheme) and its season
figure is slow to say so. Each is ranked for the offenses it faced: a game is
read as what it gave up beyond what that offense usually scores at the
position, so five games against weak offenses do not pass for a hard defense.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import NamedTuple

from thefrontoffice.adapters.outbound.competitions.places import ordinal
from thefrontoffice.domain.models import Tone

RECENT_GAMES = 5
"""The defense's latest games its recent record is read over: enough to outweigh one blowout, few enough to show a
change in who it is."""

MATCHUP_SWING = 0.1
"""The most a matchup moves what a player is weighed by, either way: the softest defense at his position a tenth up,
the toughest a tenth down."""


@dataclass(frozen=True)
class Recent:
    """What one defense has given up to one position over its last `RECENT_GAMES` games, against the rest's last."""

    allowed: float
    rank: int
    adjusted: float | None = None
    """`allowed` for the offenses faced, which `rank` is by; None reads as `allowed`."""


@dataclass(frozen=True)
class Matchup:
    """How much one defense gives up to one position, against the rest."""

    opponent: str
    position: str
    allowed: float
    """Per game, in whatever the competition counts: fantasy points in the league's scoring, or points."""

    rank: int
    """1 is the defense that gives up the most for the offenses it faced: the softest matchup."""

    defenses: int

    unit: str = ""
    """What `allowed` counts, where a line must say: 'pts'. Empty reads as the league's fantasy points."""

    recent: Recent | None = None
    """Its record over its last `RECENT_GAMES`; None until some defense has played more games than that, before which
    it is the season's record again."""

    adjusted: float | None = None
    """`allowed` for the offenses faced (`allowed`, the function), which `rank` is by; None reads as `allowed`."""

    @property
    def turned(self) -> bool:
        """Whether its recent rank is more than a quarter of the league from its season's: a changed defense
        rather than a few games' noise, which its recent games then speak for."""
        return self.recent is not None and abs(self.rank - self.recent.rank) > self.defenses / 4

    @property
    def standing(self) -> float:
        """Where it ranks once its recent games are weighed: its recent rank where it has `turned`, else midway
        between its season rank and its recent one.

        The recent games are counted in the season's too, so an even split leans on them without letting five
        games — one of them a blowout — outvote the season. A gap wider than a quarter of the league is more than
        one blowout moves a schedule-adjusted rank, so there the season is the stale half.
        """
        if self.recent is None:
            return self.rank
        return self.recent.rank if self.turned else (self.rank + self.recent.rank) / 2

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


def matchup_factor(matchup: Matchup | None) -> float:
    """1 ± `MATCHUP_SWING`, straight across its `standing`: 1 is the softest defense, the last the toughest."""
    if matchup is None or matchup.defenses < 2:
        return 1.0
    middle = (matchup.defenses + 1) / 2
    return 1 + MATCHUP_SWING * (middle - matchup.standing) / (middle - 1)


class Scored[G: (int, str)](NamedTuple):
    """What one player at one position scored against one opponent in one game."""

    opponent: str
    position: str
    game: G
    """Which of the opponent's games it was, ordered oldest first: a week, an ISO date."""

    figure: float
    offense: str = ""
    """The club he played for; empty where unknown, which leaves the game unadjusted."""


def allowed[G: (int, str)](lines: Iterable[Scored[G]], unit: str = "") -> dict[tuple[str, str], Matchup]:
    """What each defense has given up per game to each position, ranked, by (opponent, position).

    Per game rather than in total, because byes and schedules leave defenses
    with different numbers of games. Every defense is ranked at every
    position, including ones that have given a position nothing, which is a
    real and good record. The recent record is each defense's own last
    `RECENT_GAMES`, ranked against every other's.

    Ranked for the offenses faced: each game counts what it gave up, less
    what that offense scores at the position a game, plus what an offense
    scores there on average. Additive rather than a ratio, so an offense that
    barely uses a position does not multiply one catch into a rout. The
    figures shown stay what it actually gave up.
    """
    ledger = _Ledger[G]()
    for line in lines:
        ledger.add(line)
    latest = {defense: set(sorted(played)[-RECENT_GAMES:]) for defense, played in ledger.games.items()}
    windowed = any(len(played) > RECENT_GAMES for played in ledger.games.values())

    found: dict[tuple[str, str], Matchup] = {}
    for position in ledger.positions:
        season, recent = ledger.per_game(position, ledger.games), ledger.per_game(position, latest)
        season_ranks, recent_ranks = _ranked(season), _ranked(recent)
        for defense, rank in season_ranks.items():
            found[(defense, position)] = Matchup(
                opponent=defense,
                position=position,
                allowed=season[defense][0],
                rank=rank,
                defenses=len(season_ranks),
                unit=unit,
                recent=(
                    Recent(allowed=recent[defense][0], rank=recent_ranks[defense], adjusted=recent[defense][1])
                    if windowed
                    else None
                ),
                adjusted=season[defense][1],
            )
    return found


@dataclass
class _Ledger[G: (int, str)]:
    """Every line summed by defense and by offense, game by game."""

    scored: dict[tuple[str, str], dict[G, float]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(float))
    )
    games: dict[str, set[G]] = field(default_factory=lambda: defaultdict(set))
    faced: dict[tuple[str, G], str] = field(default_factory=dict)
    """The offense each defense played in each of its games, where a line said."""

    produced: dict[tuple[str, str], float] = field(default_factory=lambda: defaultdict(float))
    offense_games: dict[str, set[tuple[str, G]]] = field(default_factory=lambda: defaultdict(set))
    """Each offense's games, as (defense, game): a week names no game on its own once byes split the league."""

    positions: set[str] = field(default_factory=set)

    def add(self, line: Scored[G]) -> None:
        self.scored[(line.opponent, line.position)][line.game] += line.figure
        self.games[line.opponent].add(line.game)
        self.positions.add(line.position)
        if line.offense:
            self.faced[(line.opponent, line.game)] = line.offense
            self.produced[(line.offense, line.position)] += line.figure
            self.offense_games[line.offense].add((line.opponent, line.game))

    def per_game(self, position: str, window: Mapping[str, set[G]]) -> dict[str, tuple[float, float]]:
        """Each defense's (raw, adjusted) points a game to the position over its games in `window`."""
        average = self._scores(position)
        found: dict[str, tuple[float, float]] = {}
        for defense, played in window.items():
            figures = self.scored[(defense, position)]
            raw = adjusted = 0.0
            for game in played:
                figure = figures.get(game, 0.0)
                offense = self.faced.get((defense, game))
                raw += figure
                adjusted += figure if offense is None else figure - self._scores(position, offense) + average
            found[defense] = (raw / len(played), adjusted / len(played))
        return found

    def _scores(self, position: str, offense: str | None = None) -> float:
        """What an offense scores at the position a game; every offense together without one."""
        offenses = [offense] if offense else list(self.offense_games)
        games = sum(len(self.offense_games[o]) for o in offenses)
        return sum(self.produced[(o, position)] for o in offenses) / games if games else 0.0


def _ranked(per_game: Mapping[str, tuple[float, float]]) -> dict[str, int]:
    """Each defense's rank by its adjusted figure, 1 the most given up."""
    ordered = sorted(per_game, key=lambda defense: -per_game[defense][1])
    return {defense: rank for rank, defense in enumerate(ordered, start=1)}
