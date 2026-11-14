"""What a player's own games say his projection misses, for pricing him over the weeks ahead.

A projection is slow to read a changed role: the back handed the starter's
snaps is projected as the backup he was for weeks after, and a receiver whose
targets have dried up keeps the projection his name earned. The games he has
played say both sooner. So a player is priced at his projection pulled part
of the way toward the rate his games have been scoring at — the games since
his role changed where it has, otherwise his recent games against his season.

Each week's projection is scaled rather than replaced, so a bye, an injury
the platform has priced in, or a soft matchup still shows where it falls; and
the pull is bounded, so a single big game cannot turn a trade.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from thefrontoffice.adapters.outbound.competitions.nfl.evidence import SNAP_POSITIONS, Evidence, average
from thefrontoffice.adapters.outbound.competitions.nfl.model import Projection
from thefrontoffice.domain.models import Stat

FORM_WEIGHT = 0.5
"""How far toward his games' rate a player's price moves from his projection: the projection still
sees what his games cannot — matchups, a quarterback change, an injury report."""

RECENT_WEIGHT = 0.6
"""His last few games' share of the rate, against his season's, where his role has not changed."""

MOST = 0.3
"""The furthest his price may sit from his projection, either way."""

SAID_FROM = 0.05
"""The least change in price worth saying beside a trade."""


@dataclass(frozen=True)
class Form:
    """How far a player's games move his price, and why."""

    factor: float
    """What each week's projection is multiplied by."""
    projected: float
    """His projection a week across the weeks priced, the ones he is projected to play."""
    reason: str
    """What the rate rests on: 'snaps 32%→77% in week 9, 19.6 pts in 2 games since'."""

    def stat(self, name: str) -> Stat:
        """The line a trade shows for him: 'priced 16.0 a week, projected 12.4: <reason>'."""
        return Stat(
            label=name,
            value=f"priced {self.projected * self.factor:.1f} a week, projected {self.projected:.1f}: {self.reason}",
        )


@dataclass(frozen=True)
class Formed:
    """A projection scaled by his form: the same week, opponent and stat line, priced at what he has been scoring."""

    player_id: str
    name: str
    position: str
    team: str
    opponent: str
    points: float
    injury_status: str
    stats: Mapping[str, float] = field(default_factory=dict)

    @classmethod
    def of(cls, projection: Projection, factor: float) -> Formed:
        return cls(
            player_id=projection.player_id,
            name=projection.name,
            position=projection.position,
            team=projection.team,
            opponent=projection.opponent,
            points=projection.points * factor,
            injury_status=projection.injury_status,
            stats=projection.stats,
        )


def forms(
    evidence: Evidence, projections: Mapping[int, Mapping[str, Projection]], weeks: Sequence[int]
) -> dict[str, Form]:
    """Every player whose games say something his projection across `weeks` does not.

    Only an offensive player with games to go on: a kicker's or a defense's
    week turns on the opponent, which the projection already reads.
    """
    projected: dict[str, list[float]] = {}
    positions: dict[str, str] = {}
    for week in weeks:
        for pid, projection in projections.get(week, {}).items():
            if projection.points > 0:
                projected.setdefault(pid, []).append(projection.points)
                positions[pid] = projection.position
    found = {}
    for pid, points in projected.items():
        if positions[pid] not in SNAP_POSITIONS:
            continue
        rate = _rate(evidence, pid)
        if rate is None:
            continue
        played, reason = rate
        per_week = sum(points) / len(points)
        pull = FORM_WEIGHT * (played / per_week - 1)
        factor = 1 + max(-MOST, min(MOST, pull))
        if factor != 1:
            found[pid] = Form(factor=factor, projected=per_week, reason=reason)
    return found


def _rate(evidence: Evidence, player_id: str) -> tuple[float, str] | None:
    """The points a game his own games say he scores, and what that rests on; None with too few games."""
    games = evidence.games.get(player_id, ())
    trend = evidence.trends.get(player_id)
    if trend is not None and len(games) >= trend.games:
        since = games[-trend.games :]
        rate = sum(since) / len(since)
        count = "the game" if trend.games == 1 else f"{trend.games} games"
        return rate, f"{trend.short()} in week {trend.week}, {rate:.1f} pts in {count} since"
    season, role = average(evidence, player_id), evidence.roles.get(player_id)
    if season is None or role is None:
        return None
    rate = RECENT_WEIGHT * role.points + (1 - RECENT_WEIGHT) * season
    games_back = "last game" if role.games == 1 else f"last {role.games}"
    return rate, f"{role.points:.1f} pts a game in his {games_back}, {season:.1f} this season"


def bent(
    projections: Mapping[int, Mapping[str, Projection]], found: Mapping[str, Form]
) -> dict[int, Mapping[str, Projection]]:
    """Every week's projections, each player's scaled by his form."""
    return {
        week: {pid: Formed.of(p, found[pid].factor) if pid in found else p for pid, p in by_player.items()}
        for week, by_player in projections.items()
    }


def said(found: Mapping[str, Form], player_ids: Iterable[str], names: Mapping[str, str]) -> tuple[Stat, ...]:
    """The lines worth showing for these players: those whose form moves their price enough to matter."""
    return tuple(
        found[pid].stat(names.get(pid, pid))
        for pid in player_ids
        if pid in found and abs(found[pid].factor - 1) >= SAID_FROM
    )
