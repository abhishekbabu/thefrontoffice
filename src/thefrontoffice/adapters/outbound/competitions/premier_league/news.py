"""FPL's one line of news on a player, read into the Injury group every sport's drawer shows.

The game publishes a status, a chance of playing and a sentence — "Knee injury -
Expected back 28 Nov", "Suspended until 29 Nov" — with the moment it was set. The
sentence is the only place it says when he is back, and says it without a year,
so the year is the first that puts the day on or after the news itself.
"""

import re
from dataclasses import dataclass
from datetime import date

from thefrontoffice.adapters.outbound.competitions.dates import MONTHS
from thefrontoffice.adapters.outbound.competitions.injuries import approximately, injury_stats
from thefrontoffice.adapters.outbound.platforms.fpl.types import Gameweek, Player
from thefrontoffice.domain.models import StatGroup

_RETURN = re.compile(r"\b(?:expected back|until)\s+(\d{1,2})\s+([A-Za-z]{3})", re.IGNORECASE)
"""'Expected back 28 Nov', 'Suspended until 29 Nov': the day, and the month as FPL abbreviates it."""

_SEPARATOR = " - "
"""Between what is wrong and what the club says of it: 'Thigh injury - Unknown return date'."""

TITLES = {"i": "Injury", "d": "Injury", "s": "Suspension"}
"""The group's heading by status; anything else — on loan, left the club — is about whether he is there at all."""


@dataclass(frozen=True)
class News:
    """One player's news, read: what is wrong, the club's word on it, and the day he is due back."""

    what: str
    """'Thigh injury'; empty where the line names nothing, as a suspension or a transfer."""

    word: str
    """The rest of the line: 'Expected back 28 Nov', 'Has joined Al Hilal permanently'."""

    returns: date | None


def read(player: Player) -> News:
    """His news line in its parts; the day back where FPL gives one, in the year the news was set or the next."""
    text = player.news.strip()
    what, _, word = text.partition(_SEPARATOR) if _SEPARATOR in text else ("", "", text)
    return News(what=what.strip(), word=word.strip(), returns=_return_day(text, player))


def _return_day(text: str, player: Player) -> date | None:
    found = _RETURN.search(text)
    if found is None or player.news_added is None:
        return None
    month = next((i for i, name in enumerate(MONTHS, start=1) if name.casefold() == found.group(2).casefold()), None)
    if month is None:
        return None
    said = player.news_added.date()
    try:
        day = date(said.year, month, int(found.group(1)))
        return day if day >= said else date(said.year + 1, month, day.day)
    except ValueError:
        return None


@dataclass(frozen=True)
class BackBy:
    """How a return day reads: '~28 Nov · GW13', with the first gameweek whose deadline is on or after it."""

    gameweeks: list[Gameweek]

    def __call__(self, day: date) -> str:
        week = next((g for g in sorted(self.gameweeks, key=lambda g: g.id) if g.deadline.date() >= day), None)
        return f"{approximately(day)} · GW{week.id}" if week else approximately(day)


def group(player: Player, gameweeks: list[Gameweek]) -> StatGroup | None:
    """The drawer's Injury group — or Suspension, or Availability — for a player FPL has flagged; None for one fit."""
    if not player.availability:
        return None
    news = read(player)
    stats = injury_stats(
        player.availability,
        injury=news.what,
        returns=news.returns,
        comment=news.word,
        updated=player.news_added.date() if player.news_added else None,
        back=BackBy(gameweeks),
    )
    return StatGroup(title=TITLES.get(player.status, "Availability"), stats=stats)
