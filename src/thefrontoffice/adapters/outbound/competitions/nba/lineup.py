"""The rest of a basketball week as daily lineups read it: which nights a player would actually start.

Yahoo sets a basketball lineup day by day, and each slot takes only some
positions (`rules.fits`). A player's game counts only on a night the lineup
has a slot he can fill once everyone else playing that night is placed — the
most of them any arrangement seats, a maximum matching of players to slots.
So a pickup is worth the nights he fills a slot that would otherwise sit
empty, and a drop costs the nights the lineup cannot seat somebody in his
place. A player ruled out counts from the day ESPN expects him back, a claim
from the day after he clears waivers (`strength.nights`); nobody in an
injured slot plays.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from thefrontoffice.adapters.outbound.competitions.dates import parse_day
from thefrontoffice.adapters.outbound.competitions.nba.rules import INJURED_SLOTS, fits
from thefrontoffice.adapters.outbound.competitions.nba.strength import nights
from thefrontoffice.adapters.outbound.platforms.sleeper.types import ScheduledGame
from thefrontoffice.adapters.outbound.platforms.yahoo.types import UNSTARTED, YahooPlayer


@dataclass(frozen=True)
class Week:
    """The games still to tip off this week, the lineup's slots, and today."""

    games: Sequence[ScheduledGame]
    slots: tuple[str, ...]
    """Every slot that scores, once per place: ('PG', 'SG', 'G', ..., 'Util', 'Util')."""
    today: date
    end: date

    def quiet(self, before: date) -> list[date]:
        """The days after today and before `before`, inside the week, on which no club plays: a free add."""
        played = {day for g in self.games if (day := parse_day(g.date)) is not None}
        days = [self.today + timedelta(days=n) for n in range(1, (self.end - self.today).days + 1)]
        return [day for day in days if day < before and day not in played]


def slots(positions: Mapping[str, int]) -> tuple[str, ...]:
    """The lineup's scoring slots, one per place, from the settings' counts: bench and injured slots left out."""
    return tuple(slot for slot, count in positions.items() if slot not in UNSTARTED for _ in range(count))


def seated(players: Sequence[YahooPlayer], lineup: Sequence[str]) -> int:
    """The most of `players` one lineup of `lineup`'s slots can start at once: a maximum matching."""
    held: dict[int, int] = {}

    def place(index: int, tried: set[int]) -> bool:
        for slot, name in enumerate(lineup):
            if slot in tried or not fits(name, players[index].position):
                continue
            tried.add(slot)
            if slot not in held or place(held[slot], tried):
                held[slot] = index
                return True
        return False

    return sum(1 for index in range(len(players)) if place(index, set()))


Backs = Mapping[str, date | None]
"""The day ESPN expects each player back, by Yahoo key, where it reports him hurt."""


def _playing(roster: Sequence[YahooPlayer], week: Week, backs: Backs) -> dict[date, list[YahooPlayer]]:
    """Each night of the week, the active players of `roster` who can play it."""
    by_night: dict[date, list[YahooPlayer]] = {}
    for player in roster:
        if player.slot in INJURED_SLOTS:
            continue
        for night in nights(player, week.games, backs.get(player.player_key)):
            by_night.setdefault(night, []).append(player)
    return by_night


def starts(roster: Sequence[YahooPlayer], week: Week, backs: Backs) -> int:
    """The games `roster`'s daily lineups can start over the rest of the week."""
    return sum(seated(playing, week.slots) for playing in _playing(roster, week, backs).values())


def open_nights(player: YahooPlayer, roster: Sequence[YahooPlayer], week: Week, backs: Backs) -> list[date]:
    """The nights `player`, added to `roster`, would start: he plays, and the lineup seats one more with him."""
    by_night = _playing(roster, week, backs)
    return [
        night
        for night in nights(player, week.games, backs.get(player.player_key))
        if seated([*by_night.get(night, []), player], week.slots) > seated(by_night.get(night, []), week.slots)
    ]


def needed_nights(player: YahooPlayer, roster: Sequence[YahooPlayer], week: Week, backs: Backs) -> list[date]:
    """The nights `roster` would start one fewer without `player`: what dropping him costs."""
    others = [p for p in roster if p.player_key != player.player_key]
    return open_nights(player, others, week, backs) if player.slot not in INJURED_SLOTS else []
