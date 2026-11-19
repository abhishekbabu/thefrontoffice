"""A player's games with a regular teammate and without him: the split every competition reads the same way.

A backup is picked up the day the starter ahead of him gets hurt, on the
reasoning that the starter's work becomes his. Sometimes it does; sometimes the
club spreads it around. The season already says which: the games the teammate
missed, or left early, against the games they both played.

What is shared is the parting itself and how it reads. Whose absence is worth
weighing — a regular at his position by snaps in football, a club's
high-minutes or top-usage player in basketball — and what "left early" means
are the competition's own (`nfl/teammates.py`, `nba/teammates.py`).

A teammate's game counts as one he missed where he did not take the field, or
barely did (`Outing.partial`); a game he played for another club counts as
neither. Only games the player himself played for this club count.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from thefrontoffice.domain.models import Tone

WITHOUT_COLUMN = "Without"
"""A hurt teammate a free agent's value hangs on, 'Bowers Q', with his figures without him and with in the
tooltip (`PlayerCard.notes`): whether a pickup chasing an injury actually gains from it."""

SUFFIXES = frozenset({"jr", "jr.", "sr", "sr.", "ii", "iii", "iv", "v"})


def surname(name: str) -> str:
    """'Bowers' of 'Brock Bowers', and of 'Marvin Harrison Jr.' 'Harrison'."""
    parts = name.split()
    while len(parts) > 1 and parts[-1].casefold() in SUFFIXES:
        parts.pop()
    return parts[-1] if parts else name


class Outing(Protocol):
    """One game a player took the field in, as a split reads it."""

    @property
    def game(self) -> int:
        """Which of the club's games, ordered as they were played: a week in football, a day's ordinal in basketball."""
        ...

    @property
    def team(self) -> str: ...

    @property
    def partial(self) -> bool:
        """On for too little of it to count as having played: hurt early, or eased back in."""
        ...


@dataclass(frozen=True)
class Parted[O: Outing]:
    """His games for one club, parted by whether a teammate played them."""

    without: list[O] = field(default_factory=list)
    """The ones the teammate missed or left early, in the order given."""
    alongside: list[O] = field(default_factory=list)


def parted[O: Outing](mine: Iterable[O], theirs: Iterable[O], team: str) -> Parted[O]:
    """His games for `team`, parted by whether the teammate missed them (or left early) or played them too.

    A game the teammate played for another club counts as neither: it says
    nothing about this club with him or without him.
    """
    by_game = {game.game: game for game in theirs}
    found: Parted[O] = Parted()
    for game in mine:
        if game.team != team:
            continue
        other = by_game.get(game.game)
        if other is not None and other.team != game.team:
            continue
        (found.without if other is None or other.partial else found.alongside).append(game)
    return found


def recently_absent[O: Outing](appearances: Mapping[str, Sequence[O]], recent: int) -> set[str]:
    """Who sat out one of his club's last `recent` games, having played for it before.

    His club is the one his latest game was for; a club's games are every game
    any of its players took the field in. Sat out, not merely played little: a
    part-timer's quiet game is no absence, and reading it as one would weigh a
    starter against a backup who outplayed him.
    """
    club_games: dict[str, set[int]] = defaultdict(set)
    for played in appearances.values():
        for game in played:
            club_games[game.team].add(game.game)
    absent = set()
    for pid, played in appearances.items():
        if not played:
            continue
        team = max(played, key=lambda game: game.game).team
        there = {game.game for game in played if game.team == team}
        first = min(there)
        if any(game not in there for game in sorted(club_games[team])[-recent:] if game > first):
            absent.add(pid)
    return absent


def games(count: int) -> str:
    """'1 game', '3 games'."""
    return "1 game" if count == 1 else f"{count} games"


def heading(back: bool, name: str, detail: str, *others: tuple[str, str]) -> str:
    """'Without Brock Bowers (TE, O)', or 'With Brock Bowers (TE, Q)' once he is due back.

    `others` are more teammates who missed the same games, each as (name, detail): one split names them all.
    """
    named = ", ".join(f"{who} ({what})" for who, what in ((name, detail), *others))
    return f"{'With' if back else 'Without'} {named}"


def figures(
    back: bool, without: str, count: int, alongside: str | None, alongside_count: int, per: str = "/game"
) -> str:
    """Both sides of a split, the sample stated, and the one that counts first.

    Without him first while he sits — '6.10/game in 3 games · 8.60 with' — and
    with him first once he is back: what he scored beside him is what he is worth again.
    """
    if back:
        first = f"{alongside}{per} in {games(alongside_count)}" if alongside is not None else "never with"
        return f"{first} · {without} without in {games(count)}"
    second = f" · {alongside} with" if alongside is not None else " · never with"
    return f"{without}{per} in {games(count)}{second}"


def tone(back: bool, without: float, alongside: float | None) -> Tone:
    """Good where the figure that counts beats the other, a warning where it does not; neutral with nothing to compare."""
    if alongside is None:
        return "neutral"
    counts, other = (alongside, without) if back else (without, alongside)
    return "good" if counts > other else "warning"


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)
