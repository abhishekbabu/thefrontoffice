"""Whose value hangs on a hurt teammate, and what he has actually scored without him.

A backup is picked up the week the starter ahead of him gets hurt, on the
reasoning that the starter's work becomes his. Sometimes it does. Sometimes the
club spreads it around, and the backup scores less without the starter than
beside him — a tight end two who caught balls in two-tight-end sets that went
away with the tight end one. The season already says which: the games the
teammate missed, or left early, against the games he played.

The rule for whose injury counts is kept simple:

- the same club, carrying an injury designation (`HURT`);
- and at the same position as a regular (`REGULAR` of the snaps over his last
  games played), or, for a receiver or tight end, the club's top target earner
  at either position.

A teammate's game counts as one he missed where he did not take the field, or
was on for under `LEFT_EARLY` of the snaps; a game he played for another club
counts as neither. Only games the player himself played for this club count.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from thefrontoffice.adapters.outbound.competitions.nfl.evidence import RISES, Evidence
from thefrontoffice.adapters.outbound.competitions.nfl.model import FREE_AGENT, PlayerInfo
from thefrontoffice.domain.models import Stat, Tone

HURT = frozenset({"QUESTIONABLE", "DOUBTFUL", "OUT", "IR", "PUP"})
"""The designations at which a teammate's absence is worth weighing: this week's report, and the long rulings."""

REGULAR = RISES["snaps"][1]
"""Snap share over his last games played at which a teammate at the same position is a regular."""

RECEIVERS = frozenset({"WR", "TE"})
"""Positions that share one pool of targets: a club's top target earner at either matters to both."""

LEFT_EARLY = 0.30
"""Snap share under which a teammate's game counts as missed: hurt early, or eased back in."""

SHORT_STATUS = {"QUESTIONABLE": "Q", "DOUBTFUL": "D", "OUT": "O", "IR": "IR", "PUP": "PUP"}
"""Each designation as an injury report abbreviates it."""

SUFFIXES = frozenset({"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"})


def surname(name: str) -> str:
    """'Bowers' of 'Brock Bowers', and of 'Marvin Harrison Jr.' 'Harrison'."""
    parts = name.split()
    while len(parts) > 1 and parts[-1].casefold() in SUFFIXES:
        parts.pop()
    return parts[-1] if parts else name


@dataclass(frozen=True)
class Split:
    """His points a game without a hurt teammate, and with him."""

    teammate: PlayerInfo
    without: float
    games: int
    """Games he played that the teammate missed or left early: at least one."""
    alongside: float | None
    """Per game in the games they both played; None where there were none."""
    alongside_games: int

    @property
    def status(self) -> str:
        return SHORT_STATUS.get(self.teammate.injury_status.upper(), self.teammate.injury_status)

    def cell(self) -> str:
        """'Bowers Q', for a table cell."""
        return f"{surname(self.teammate.name)} {self.status}"

    def figures(self) -> str:
        """'6.10/game in 3 games · 8.60 with', the sample stated."""
        games = "1 game" if self.games == 1 else f"{self.games} games"
        with_him = f" · {self.alongside:.2f} with" if self.alongside is not None else " · never with"
        return f"{self.without:.2f}/game in {games}{with_him}"

    def label(self) -> str:
        """'Without Brock Bowers (TE, Q)'."""
        return f"Without {self.teammate.name} ({self.teammate.position}, {self.status})"

    def note(self) -> str:
        """The cell's tooltip: who, and the figures."""
        return f"{self.label()}: {self.figures()}"

    def stat(self) -> Stat:
        """The drawer's row, toned by which way the split cuts — and the figures say so too."""
        tone: Tone = "neutral" if self.alongside is None else ("good" if self.without > self.alongside else "warning")
        return Stat(label=self.label(), value=self.figures(), tone=tone)


class HurtTeammates:
    """Every club's hurt regulars and hurt top receivers, read once for a page of players."""

    def __init__(self, players: Mapping[str, PlayerInfo], evidence: Evidence):
        self.evidence = evidence
        self.by_position: dict[tuple[str, str], list[PlayerInfo]] = defaultdict(list)
        top: dict[str, tuple[float, PlayerInfo]] = {}
        for meta in players.values():
            role = evidence.roles.get(meta.player_id)
            if role is None or meta.team == FREE_AGENT:
                continue
            if meta.position in RECEIVERS and role.target_share is not None:
                best = top.get(meta.team)
                if best is None or role.target_share > best[0]:
                    top[meta.team] = (role.target_share, meta)
            if meta.injury_status.upper() in HURT and role.snap_share is not None and role.snap_share >= REGULAR:
                self.by_position[(meta.team, meta.position)].append(meta)
        self.top_receiver = {club: meta for club, (_, meta) in top.items() if meta.injury_status.upper() in HURT}

    def of(self, player: PlayerInfo) -> list[PlayerInfo]:
        """His hurt teammates whose absence his value hangs on, by the module's rule."""
        found = [m for m in self.by_position.get((player.team, player.position), []) if m.player_id != player.player_id]
        receiver = self.top_receiver.get(player.team) if player.position in RECEIVERS else None
        if (
            receiver
            and receiver.player_id != player.player_id
            and all(m.player_id != receiver.player_id for m in found)
        ):
            found.append(receiver)
        return found

    def splits(self, player: PlayerInfo) -> list[Split]:
        """His points a game without each of them and with, for each he has played at least one game without."""
        return [s for mate in self.of(player) if (s := split(self.evidence, player, mate)) is not None]


def split(evidence: Evidence, player: PlayerInfo, teammate: PlayerInfo) -> Split | None:
    """His points a game in this club's games the teammate missed or left early, against the ones he played.

    None where the player has played no game without him.
    """
    theirs = {game.week: game for game in evidence.appearances.get(teammate.player_id, ())}
    without: list[float] = []
    alongside: list[float] = []
    for game in evidence.appearances.get(player.player_id, ()):
        if game.team != player.team:
            continue
        other = theirs.get(game.week)
        if other is not None and other.team != game.team:
            continue
        missed = other is None or (other.snap_share is not None and other.snap_share < LEFT_EARLY)
        (without if missed else alongside).append(game.points)
    if not without:
        return None
    return Split(
        teammate=teammate,
        without=_mean(without),
        games=len(without),
        alongside=_mean(alongside) if alongside else None,
        alongside_games=len(alongside),
    )


def _mean(points: Sequence[float]) -> float:
    return sum(points) / len(points)
