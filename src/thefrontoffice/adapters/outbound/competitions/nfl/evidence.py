"""The evidence behind a football decision: a player's role, and his matchup.

A projection is a single number, and it hides the mechanism behind it. The
mechanism is what a decision should rest on: how much of the offense runs
through a player — snaps, targets, carries — and how much the defense he
faces gives up to his position. Sleeper publishes neither as a figure. Both
are computed here from its per-game stat lines, so a recommendation can say
*why* rather than only *how much*.

Only games already played count. A week still under way would read a
Monday-night starter as a player who did nothing.
"""

from collections import defaultdict
from dataclasses import dataclass, field

from thefrontoffice.adapters.outbound.platforms.sleeper.types import NFLGameLine, WeeklyProjection
from thefrontoffice.domain.models import Stat, Tone

ROLE_GAMES = 3
"""Recent enough to catch a changed role, long enough that one game is not a role."""

# Snaps are recorded for offensive players only; a kicker or a team defense
# has no share of anything, and saying "0% of snaps" about one is false.
SNAP_POSITIONS = frozenset({"QB", "RB", "WR", "TE"})
TARGET_POSITIONS = frozenset({"RB", "WR", "TE"})
CARRY_POSITIONS = frozenset({"QB", "RB"})


@dataclass(frozen=True)
class Role:
    """What a player has been asked to do, per game, over his last few games."""

    position: str
    games: int
    points: float
    snap_share: float | None = None
    targets: float = 0.0
    target_share: float | None = None
    carries: float = 0.0

    def describe(self) -> str:
        """'last 3 games: 71% of snaps, 6.3 targets (24% share), 14.2 pts'."""
        parts = []
        if self.snap_share is not None:
            parts.append(f"{self.snap_share:.0%} of snaps")
        if self.position in CARRY_POSITIONS and self.carries:
            parts.append(f"{self.carries:.1f} carries")
        if self.position in TARGET_POSITIONS:
            share = f" ({self.target_share:.0%} share)" if self.target_share is not None else ""
            parts.append(f"{self.targets:.1f} targets{share}")
        parts.append(f"{self.points:.1f} pts")
        games = "last game" if self.games == 1 else f"last {self.games} games"
        return f"{games}: {', '.join(parts)}"


@dataclass(frozen=True)
class Matchup:
    """How much one defense gives up to one position, against the rest."""

    opponent: str
    position: str
    allowed: float
    """Fantasy points per game, in the league's own scoring."""

    rank: int
    """1 is the defense that gives up the most: the softest matchup."""

    defenses: int

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
        noun = "defenses" if self.position == "DEF" else f"{self.position}s"
        if self.rank == 1:
            rank = "the most"
        elif self.rank == self.defenses:
            rank = "the fewest"
        else:
            rank = f"{_ordinal(self.rank)}-most"
        return f"vs {self.opponent}, {rank} to {noun} ({self.allowed:.1f} a game)"


@dataclass(frozen=True)
class Evidence:
    """Every rostered and available player's role, and every defense's record."""

    roles: dict[str, Role] = field(default_factory=dict)
    allowed: dict[tuple[str, str], Matchup] = field(default_factory=dict)
    games: dict[str, tuple[float, ...]] = field(default_factory=dict)
    """Each player's points in every game he played this season, oldest first."""

    positions: dict[str, str] = field(default_factory=dict)
    """The position he played those games at."""

    def matchup(self, player: WeeklyProjection) -> Matchup | None:
        return self.allowed.get((player.opponent, player.position)) if player.opponent else None

    def describe(self, player: WeeklyProjection) -> str:
        """Both halves in one line, or empty when there is nothing played to go on."""
        matchup, role = self.matchup(player), self.roles.get(player.player_id)
        parts = [matchup.describe()] if matchup else []
        return "; ".join(parts + [role.describe()] if role else parts)

    def stat(self, player: WeeklyProjection) -> Stat | None:
        """The same line labelled with the player, toned by the matchup."""
        text = self.describe(player)
        if not text:
            return None
        matchup = self.matchup(player)
        return Stat(label=player.name, value=text, tone=matchup.tone if matchup else "neutral")


def gather(lines: list[NFLGameLine], scoring: str) -> Evidence:
    """Roles and matchups from the season's played game lines."""
    games, positions = _games(lines, scoring)
    return Evidence(roles=_roles(lines, scoring), allowed=_allowed(lines, scoring), games=games, positions=positions)


def _games(lines: list[NFLGameLine], scoring: str) -> tuple[dict[str, tuple[float, ...]], dict[str, str]]:
    """Each player's scores in the games he took the field in, by the same rule his role is read by."""
    played: dict[str, list[NFLGameLine]] = defaultdict(list)
    for line in lines:
        if line.position in SNAP_POSITIONS and not line.stats.get("off_snp"):
            continue
        played[line.player_id].append(line)
    games = {
        pid: tuple(game.stats.get(scoring, 0.0) for game in sorted(each, key=lambda game: game.week))
        for pid, each in played.items()
    }
    positions = {pid: each[-1].position for pid, each in played.items()}
    return games, positions


def _roles(lines: list[NFLGameLine], scoring: str) -> dict[str, Role]:
    team_targets: dict[tuple[str, int], float] = defaultdict(float)
    by_player: dict[str, list[NFLGameLine]] = defaultdict(list)
    for line in lines:
        team_targets[(line.team, line.week)] += line.stats.get("rec_tgt", 0.0)
        # A row for a game he never took the field in is not a game he
        # played; averaging it in halves a role that did not change.
        if line.position in SNAP_POSITIONS and not line.stats.get("off_snp"):
            continue
        by_player[line.player_id].append(line)

    roles = {}
    for player_id, played in by_player.items():
        recent = sorted(played, key=lambda line: line.week, reverse=True)[:ROLE_GAMES]
        position = recent[0].position
        snaps = _total(recent, "tm_off_snp")
        targets_available = sum(team_targets[(line.team, line.week)] for line in recent)
        roles[player_id] = Role(
            position=position,
            games=len(recent),
            points=_total(recent, scoring) / len(recent),
            snap_share=_total(recent, "off_snp") / snaps if position in SNAP_POSITIONS and snaps else None,
            targets=_total(recent, "rec_tgt") / len(recent),
            target_share=(
                _total(recent, "rec_tgt") / targets_available
                if position in TARGET_POSITIONS and targets_available
                else None
            ),
            carries=_total(recent, "rush_att") / len(recent),
        )
    return roles


def _allowed(lines: list[NFLGameLine], scoring: str) -> dict[tuple[str, str], Matchup]:
    """Points each defense has given up per game to each position, ranked.

    Per game rather than in total, because byes leave defenses with different
    numbers of games. Every defense is ranked at every position, including
    ones that have given a position nothing, which is a real and good record.
    """
    totals: dict[tuple[str, str], float] = defaultdict(float)
    games: dict[str, set[int]] = defaultdict(set)
    for line in lines:
        totals[(line.opponent, line.position)] += line.stats.get(scoring, 0.0)
        games[line.opponent].add(line.week)

    positions = {line.position for line in lines}
    allowed: dict[tuple[str, str], Matchup] = {}
    for position in positions:
        per_game = {defense: totals[(defense, position)] / len(weeks) for defense, weeks in games.items()}
        ranked = sorted(per_game, key=lambda defense: -per_game[defense])
        for rank, defense in enumerate(ranked, start=1):
            allowed[(defense, position)] = Matchup(
                opponent=defense,
                position=position,
                allowed=per_game[defense],
                rank=rank,
                defenses=len(ranked),
            )
    return allowed


def _total(lines: list[NFLGameLine], key: str) -> float:
    return sum(line.stats.get(key, 0.0) for line in lines)


def _ordinal(n: int) -> str:
    suffix = "th" if 11 <= n % 100 <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
