"""The league's moves, as its own feed lists them: lately, for the league, and all season, for one player.

Yahoo carries the season's moves in one response, which both read. Each move
names the team that made it, since "dropped" alone does not say whose mistake
it was.
"""

from collections.abc import Collection, Sequence
from datetime import date, datetime, timedelta
from typing import Literal

from thefrontoffice.adapters.outbound.competitions.dates import day_month
from thefrontoffice.adapters.outbound.competitions.nba.model import LeagueMove, MovedPlayer
from thefrontoffice.adapters.outbound.competitions.nba.rules import PACIFIC
from thefrontoffice.domain.models import ActivityMove, ActivityRow

FROM_WAIVERS = "waivers"
"""Where Yahoo says a claimed player came from: a waiver claim, rather than a free-agent add."""

LABELS = {"add": "Add", "drop": "Drop", "add/drop": "Add/drop", "trade": "Trade"}
"""Yahoo's words for a move, as the league's activity names them."""

PENDING_TRADE = "pending_trade"
"""Yahoo's kind for a trade on offer; anything else your team has waiting is a waiver claim."""

PENDING = {PENDING_TRADE: "Pending trade"}
PENDING_CLAIM = "Pending claim"


ACTIVITY_DAYS = 21
"""How far back the league's activity reaches: about three weeks of matchups, as NFL's and FPL's do.

This is "what did I miss", and a season of October waivers is not that.
"""


def recent(transactions: Sequence[LeagueMove], now: datetime, mine: str = "") -> list[ActivityRow]:
    """What the league has done in the last `ACTIVITY_DAYS`, newest first.

    `mine` is your team's name, so your own moves can be found among everyone else's.
    """
    since = (now - timedelta(days=ACTIVITY_DAYS)).timestamp()
    lately = [t for t in transactions if t.timestamp >= since]
    return [_row(t, mine) for t in sorted(lately, key=lambda t: t.timestamp, reverse=True)]


def pending(waiting: Sequence[LeagueMove], mine: str) -> list[ActivityRow]:
    """Your team's moves still waiting, as rows of their own: claims by the day each processes, then offers.

    `mine` is your team's name: Yahoo lists a team's waiting moves only to its
    own manager, so every one is yours.
    """
    order = sorted(waiting, key=lambda m: (m.kind == PENDING_TRADE, m.clears or date.max, m.timestamp))
    return [_waiting(move, mine) for move in order]


def _waiting(move: LeagueMove, mine: str) -> ActivityRow:
    """A move still waiting: 'Pending claim' on the day it processes, or 'Pending trade' on the day it was offered."""
    row = _row(move, mine)
    return row.model_copy(
        update={
            "what": PENDING.get(move.kind, PENDING_CLAIM),
            "when": day_month(move.clears) if move.clears else row.when,
            # A waiting claim names its team by key alone, and every one listed is yours.
            "who": row.who if move.kind == PENDING_TRADE else mine,
            "is_mine": True,
        }
    )


def claimed(waiting: Sequence[LeagueMove]) -> Collection[str]:
    """Whom your waiting claims would add, by Yahoo key: nobody to suggest claiming again."""
    return {p.player_key for m in waiting if m.kind != PENDING_TRADE for p in m.players if p.kind == "add"}


def moves(transactions: Sequence[LeagueMove], player_key: str, mine: str = "") -> list[ActivityRow]:
    """Each move this season he was part of, oldest first, as the league's activity shows it.

    `mine` is your team's name, so your own moves can be found among everyone else's.
    """
    involved = [t for t in transactions if any(p.player_key == player_key for p in t.players)]
    return [_row(t, mine) for t in sorted(involved, key=lambda t: t.timestamp)]


def _row(move: LeagueMove, mine: str) -> ActivityRow:
    moved = [_moved(p) for p in move.players]
    managers = list(dict.fromkeys(m.manager for m in moved if m.manager))
    if move.kind in ("trade", PENDING_TRADE):
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
