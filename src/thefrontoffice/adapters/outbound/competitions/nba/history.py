"""The league's moves, as its own feed lists them: lately, for the league, and all season, for one player.

Yahoo carries the season's moves in one response, which both read. Each move
names the team that made it, since "dropped" alone does not say whose mistake
it was.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Literal

from thefrontoffice.adapters.outbound.competitions.dates import day_month
from thefrontoffice.adapters.outbound.competitions.nba.rules import PACIFIC
from thefrontoffice.adapters.outbound.platforms.yahoo.types import MovedPlayer, YahooTransaction
from thefrontoffice.domain.models import ActivityMove, ActivityRow

FROM_WAIVERS = "waivers"
"""Where Yahoo says a claimed player came from: a waiver claim, rather than a free-agent add."""

LABELS = {"add": "Add", "drop": "Drop", "add/drop": "Add/drop", "trade": "Trade"}
"""Yahoo's words for a move, as the league's activity names them."""


ACTIVITY_DAYS = 21
"""How far back the league's activity reaches: about three weeks of matchups, as NFL's and FPL's do.

This is "what did I miss", and a season of October waivers is not that.
"""


def recent(transactions: Sequence[YahooTransaction], now: datetime, mine: str = "") -> list[ActivityRow]:
    """What the league has done in the last `ACTIVITY_DAYS`, newest first.

    `mine` is your team's name, so your own moves can be found among everyone else's.
    """
    since = (now - timedelta(days=ACTIVITY_DAYS)).timestamp()
    lately = [t for t in transactions if t.timestamp >= since]
    return [_row(t, mine) for t in sorted(lately, key=lambda t: t.timestamp, reverse=True)]


def moves(transactions: Sequence[YahooTransaction], player_key: str, mine: str = "") -> list[ActivityRow]:
    """Each move this season he was part of, oldest first, as the league's activity shows it.

    `mine` is your team's name, so your own moves can be found among everyone else's.
    """
    involved = [t for t in transactions if any(p.player_key == player_key for p in t.players)]
    return [_row(t, mine) for t in sorted(involved, key=lambda t: t.timestamp)]


def _row(move: YahooTransaction, mine: str) -> ActivityRow:
    moved = [_moved(p) for p in move.players]
    managers = list(dict.fromkeys(m.manager for m in moved if m.manager))
    if move.kind == "trade":
        who = " ↔ ".join(managers)
        detail = " · ".join(
            "+" + ", ".join(m.player for m in moved if m.change == "added" and m.manager == name) for name in managers
        )
    else:
        who = managers[0] if managers else ""
        detail = ", ".join(f"{'+' if m.change == 'added' else '-'}{m.player}" for m in moved)
    claimed = any(p.kind == "add" and p.source == FROM_WAIVERS for p in move.players)
    return ActivityRow(
        when=_when(move.timestamp),
        who=who,
        what="Waiver" if claimed else LABELS.get(move.kind, move.kind),
        detail=detail,
        is_mine=bool(mine) and mine in managers,
        moves=moved,
        bid=f"${move.bid}" if move.bid else "",
    )


def _moved(player: MovedPlayer) -> ActivityMove:
    """One player a move moved; in a trade the team that got him, as the team that made it otherwise."""
    change: Literal["added", "dropped"] = "dropped" if player.kind == "drop" else "added"
    manager = player.source if change == "dropped" else player.destination
    return ActivityMove(
        player_id=player.player_key,
        player=player.name,
        position=player.position,
        team=player.team,
        change=change,
        manager=manager,
    )


def _when(timestamp: int) -> str:
    """'19 Nov', on the league's clock."""
    return day_month(datetime.fromtimestamp(timestamp, tz=PACIFIC).date()) if timestamp else ""
