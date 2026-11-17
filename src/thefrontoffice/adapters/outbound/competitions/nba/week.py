"""A category league's week, as the matchup page reads it: each category, each side, and the score.

Yahoo's scoreboard carries each side's totals by stat id, as it prints them;
these read them into the shared shapes. Who leads a category is worked out
here rather than taken from Yahoo's own winners, so a week still being
played reads the same way as one that has finished.
"""

from collections.abc import Mapping, Sequence
from typing import Literal

from thefrontoffice.adapters.outbound.competitions.nba.rules import CATEGORIES, INJURED_SLOTS, Category, ruled_out
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooPlayer
from thefrontoffice.domain.models import CategoryLine, Side, Spot, Stat, Tone

BENCH = "BN"
"""Yahoo's slot for a player on the roster but not in the day's lineup."""


def categories(mine: Mapping[str, str], theirs: Mapping[str, str]) -> list[CategoryLine]:
    """One line per category the scoreboard carries, in the order the league is read."""
    return [
        CategoryLine(
            name=category.label,
            mine=mine.get(category.yahoo_stat, ""),
            theirs=theirs.get(category.yahoo_stat, ""),
            lead=_lead(category, mine.get(category.yahoo_stat, ""), theirs.get(category.yahoo_stat, "")),
        )
        for category in CATEGORIES
        if category.yahoo_stat in mine or category.yahoo_stat in theirs
    ]


Lead = Literal["mine", "theirs", "even"]


def _lead(category: Category, mine: str, theirs: str) -> Lead | None:
    """Who is ahead, or None where either figure is not a number yet: a week to come prints a dash."""
    try:
        ours, other = float(mine), float(theirs)
    except ValueError:
        return None
    if ours == other:
        return "even"
    return "mine" if (ours < other) == category.fewer_wins else "theirs"


def score(lines: Sequence[CategoryLine]) -> tuple[int, int, int] | None:
    """Categories won, lost and level, from your side; None where nothing has been recorded."""
    leads = [line.lead for line in lines if line.lead is not None]
    if not leads:
        return None
    return leads.count("mine"), leads.count("theirs"), leads.count("even")


def headline(score: tuple[int, int, int]) -> Stat:
    """The week's score in categories, which is how a category week is won."""
    won, lost, _ = score
    tone: Tone = "good" if won > lost else "warning" if won < lost else "neutral"
    return Stat(label="Categories", value=written(score), tone=tone)


def written(score: tuple[int, int, int]) -> str:
    """'5-3-1': won, lost, level."""
    return "-".join(str(n) for n in score)


def side(name: str, detail: str, points: str, roster: Sequence[YahooPlayer] | None) -> Side:
    """One team in the week, its roster parted as Yahoo slots it: the lineup, the bench, the injured list.

    `roster` is None for a week already played: Yahoo sets a basketball lineup
    day by day, so no one roster is the one that played the week, and today's
    would claim one that did not.
    """
    rows = list(roster or [])
    return Side(
        name=name,
        detail=detail,
        points=points,
        lineup=[_spot(p) for p in rows if p.slot not in INJURED_SLOTS and p.slot != BENCH],
        bench=[_spot(p).model_copy(update={"slot": ""}) for p in rows if p.slot == BENCH],
        # A player on the injured list was never going to play: no warning on his row.
        reserve=[_spot(p).model_copy(update={"tone": "neutral"}) for p in rows if p.slot in INJURED_SLOTS],
    )


def _spot(player: YahooPlayer) -> Spot:
    """A player as his row reads: where he is slotted, his positions and club, and any status he carries."""
    return Spot(
        player_id=player.player_key,
        slot=player.slot,
        player=player.name,
        detail=f"{player.position} · {player.team}",
        value=player.status,
        tone="warning" if ruled_out(player.status) else "neutral",
    )
