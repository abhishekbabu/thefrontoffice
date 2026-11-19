"""Whose value hangs on a teammate's absence, and what he has actually scored without him.

A backup is picked up the week the starter ahead of him gets hurt, on the
reasoning that the starter's work becomes his. Sometimes it does. Sometimes the
club spreads it around, and the backup scores less without the starter than
beside him — a tight end two who caught balls in two-tight-end sets that went
away with the tight end one. The season already says which: the games the
teammate missed, or left early, against the games he played.

The same split answers the opposite question once the teammate is back: a
receiver who scored eleven a game in the two weeks the starter sat is worth
what he scored beside him, and that is the figure a decision reads
(`HurtTeammates.filling_in`).

The rule for whose absence counts is kept simple:

- the same club, carrying an injury designation (`HURT`), or having sat out
  one of the club's last `ROLE_GAMES` games;
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

from thefrontoffice.adapters.outbound.competitions.nfl.evidence import (
    LEFT_EARLY,
    RECEIVERS,
    REGULAR,
    ROLE_GAMES,
    Evidence,
)
from thefrontoffice.adapters.outbound.competitions.nfl.model import FREE_AGENT, PlayerInfo
from thefrontoffice.adapters.outbound.competitions.nfl.rules import ruled_out
from thefrontoffice.domain.models import Stat, Tone

HURT = frozenset({"QUESTIONABLE", "DOUBTFUL", "OUT", "IR", "PUP"})
"""The designations at which a teammate's absence is worth weighing: this week's report, and the long rulings."""

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
    """His points a game without a teammate, and with him."""

    teammate: PlayerInfo
    without: float
    games: int
    """Games he played that the teammate missed or left early: at least one."""
    alongside: float | None
    """Per game in the games they both played; None where there were none."""
    alongside_games: int
    weeks: tuple[int, ...] = ()
    """The weeks of the games without him."""

    @property
    def back(self) -> bool:
        """Whether the teammate is due to play this week — not ruled out — so the figure with him is the one that counts."""
        return not ruled_out(self.teammate.injury_status)

    @property
    def status(self) -> str:
        """'Q' for a designation; 'back' for a teammate who carries none."""
        status = self.teammate.injury_status
        return SHORT_STATUS.get(status.upper(), status) or "back"

    def cell(self) -> str:
        """'Bowers Q', for a table cell."""
        return f"{surname(self.teammate.name)} {self.status}"

    def figures(self) -> str:
        """'6.10/game in 3 games · 8.60 with', the sample stated; the figure with him first once he is back."""
        if self.back:
            with_him = (
                f"{self.alongside:.2f}/game in {_games(self.alongside_games)}"
                if self.alongside is not None
                else "never with"
            )
            return f"{with_him} · {self.without:.2f} without in {_games(self.games)}"
        with_him = f" · {self.alongside:.2f} with" if self.alongside is not None else " · never with"
        return f"{self.without:.2f}/game in {_games(self.games)}{with_him}"

    def label(self) -> str:
        """'Without Brock Bowers (TE, O)', or 'With Brock Bowers (TE, Q)' once he is back."""
        return f"{'With' if self.back else 'Without'} {self.teammate.name} ({self.teammate.position}, {self.status})"

    def note(self) -> str:
        """The cell's tooltip: who, and the figures."""
        return f"{self.label()}: {self.figures()}"

    def stat(self) -> Stat:
        """The drawer's row, toned by whether the figure that counts beats the other — and the figures say so too."""
        if self.alongside is None:
            tone: Tone = "neutral"
        else:
            counts, other = (self.alongside, self.without) if self.back else (self.without, self.alongside)
            tone = "good" if counts > other else "warning"
        return Stat(label=self.label(), value=self.figures(), tone=tone)


def _games(count: int) -> str:
    return "1 game" if count == 1 else f"{count} games"


class HurtTeammates:
    """Every club's hurt or recently absent regulars and top receivers, read once for a page of players."""

    def __init__(self, players: Mapping[str, PlayerInfo], evidence: Evidence):
        self.evidence = evidence
        self.by_position: dict[tuple[str, str], list[PlayerInfo]] = defaultdict(list)
        missing = _recently_absent(evidence)
        top: dict[str, tuple[float, PlayerInfo]] = {}
        for meta in players.values():
            role = evidence.roles.get(meta.player_id)
            if role is None or meta.team == FREE_AGENT:
                continue
            if meta.position in RECEIVERS and role.target_share is not None:
                best = top.get(meta.team)
                if best is None or role.target_share > best[0]:
                    top[meta.team] = (role.target_share, meta)
            weighed = meta.injury_status.upper() in HURT or meta.player_id in missing
            if weighed and role.snap_share is not None and role.snap_share >= REGULAR:
                self.by_position[(meta.team, meta.position)].append(meta)
        self.top_receiver = {
            club: meta
            for club, (_, meta) in top.items()
            if meta.injury_status.upper() in HURT or meta.player_id in missing
        }

    def of(self, player: PlayerInfo) -> list[PlayerInfo]:
        """His teammates whose absence his value hangs on, by the module's rule."""
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

    def filling_in(self, player: PlayerInfo) -> Split | None:
        """The split on a teammate who is back, where his own last `ROLE_GAMES` games were partly fill-in work.

        Fill-in where any of them were without the teammate and, beside him, he was
        no regular (`REGULAR` of the snaps): those games describe work going back
        to its owner. A regular beside him kept his own role either way. Where
        there are several, the one with the lowest figure beside him.
        """
        games = self.evidence.appearances.get(player.player_id, ())
        recent = {game.week for game in games[-ROLE_GAMES:]}

        def understudy(found: Split) -> bool:
            shares = [
                game.snap_share
                for game in games
                if game.team == player.team and game.week not in found.weeks and game.snap_share is not None
            ]
            return not shares or sum(shares) / len(shares) < REGULAR

        found = [s for s in self.splits(player) if s.back and recent & set(s.weeks) and understudy(s)]
        return min(found, key=lambda s: s.alongside if s.alongside is not None else 0.0, default=None)


def _recently_absent(evidence: Evidence) -> set[str]:
    """Who sat out one of his club's last `ROLE_GAMES` games, having played for it before.

    Sat out, not merely played little: a part-timer's quiet game is no absence,
    and reading it as one would weigh a receiver against a backup who outplayed him.
    """
    club_weeks: dict[str, set[int]] = defaultdict(set)
    for games in evidence.appearances.values():
        for game in games:
            club_weeks[game.team].add(game.week)
    absent = set()
    for pid, games in evidence.appearances.items():
        team = games[-1].team
        there = {game.week for game in games if game.team == team}
        first = min(game.week for game in games if game.team == team)
        recent = sorted(club_weeks[team])[-ROLE_GAMES:]
        if any(week not in there for week in recent if week > first):
            absent.add(pid)
    return absent


def split(evidence: Evidence, player: PlayerInfo, teammate: PlayerInfo) -> Split | None:
    """His points a game in this club's games the teammate missed or left early, against the ones he played.

    None where the player has played no game without him.
    """
    theirs = {game.week: game for game in evidence.appearances.get(teammate.player_id, ())}
    without: list[float] = []
    weeks: list[int] = []
    alongside: list[float] = []
    for game in evidence.appearances.get(player.player_id, ()):
        if game.team != player.team:
            continue
        other = theirs.get(game.week)
        if other is not None and other.team != game.team:
            continue
        missed = other is None or (other.snap_share is not None and other.snap_share < LEFT_EARLY)
        (without if missed else alongside).append(game.points)
        if missed:
            weeks.append(game.week)
    if not without:
        return None
    return Split(
        teammate=teammate,
        without=_mean(without),
        games=len(without),
        alongside=_mean(alongside) if alongside else None,
        alongside_games=len(alongside),
        weeks=tuple(weeks),
    )


def _mean(points: Sequence[float]) -> float:
    return sum(points) / len(points)
