"""A player's season in this league: who holds him, where he was drafted, and every move since.

Read when his drawer opens, never for a page: a season of transactions is a
request a week, and only one player at a time is asked about. Each move
names the team that made it, since "dropped" alone does not say whose
mistake it was.
"""

import logging
from collections.abc import Mapping

from thefrontoffice.adapters.outbound.competitions.nfl.model import LeagueMove, NFLSource, Team
from thefrontoffice.adapters.outbound.competitions.nfl.week import Week, moment
from thefrontoffice.domain.errors import PlatformError
from thefrontoffice.domain.models import Stat

logger = logging.getLogger(__name__)

FREE_AGENT = "Free agent"
"""Whose roster a player nobody holds is on."""


def owner(state: Week, player_id: str) -> str:
    """The team holding him, by its manager's name, or "Free agent"."""
    holder = next((team for team in state.rosters if player_id in team.player_ids), None)
    return state.team_name(holder) if holder else FREE_AGENT


def history(client: NFLSource, state: Week, player_id: str) -> list[Stat]:
    """His draft pick, then each move this season, oldest first, each with the team that made it.

    A week whose moves would not load is left out rather than failing the
    drawer, and the draft likewise: the rest of the record is still true.
    """
    by_roster = {team.roster_id: team for team in state.rosters}
    lines = _drafted(client, state, player_id, by_roster)
    weeks = list(range(1, state.week + 1))
    moves = client.get_transactions_bulk(state.league.league_id, weeks)
    for week, error in moves.failures.items():
        logger.warning(f"Leaving week {week} out of a player's history: {error}")
    dated = sorted(
        ((t.when, week, t) for week, ts in moves.values.items() for t in ts if _involves(t, player_id)),
        key=lambda entry: entry[0],
    )
    for when, week, move in dated:
        label = " · ".join(part for part in (f"Week {week}", moment(when)) if part)
        lines.append(Stat(label=label, value=_said(move, player_id, state, by_roster)))
    return lines


def _drafted(client: NFLSource, state: Week, player_id: str, by_roster: Mapping[int, Team]) -> list[Stat]:
    """Where the league's draft took him, or nothing where it did not, or has no draft."""
    if not state.league.draft_id:
        return []
    try:
        picks = client.get_draft_picks(state.league.draft_id)
    except PlatformError as e:
        logger.warning(f"Leaving the draft out of a player's history: {e}")
        return []
    pick = next((p for p in picks if p.player_id == player_id), None)
    if pick is None:
        return [Stat(label="Draft", value="Undrafted")]
    teams = state.league.total_rosters or 1
    in_round = pick.pick_no - (pick.round - 1) * teams
    return [
        Stat(
            label="Draft",
            value=f"Round {pick.round}, pick {in_round} ({_ordinal(pick.pick_no)} overall) by {_team(pick.roster_id, state, by_roster)}",
        )
    ]


def _involves(move: LeagueMove, player_id: str) -> bool:
    return player_id in move.adds or player_id in move.drops


def _said(move: LeagueMove, player_id: str, state: Week, by_roster: Mapping[int, Team]) -> str:
    """One move as it happened to him: who took him, who let him go."""
    to = _team(move.adds[player_id], state, by_roster) if player_id in move.adds else ""
    left = _team(move.drops[player_id], state, by_roster) if player_id in move.drops else ""
    if move.kind == "trade":
        return f"Traded from {left} to {to}" if left and to else f"Traded to {to or left}"
    if to:
        bid = f" for ${move.bid}" if move.bid else ""
        how = {"waiver": f"Claimed off waivers{bid}", "free_agent": "Added as a free agent"}.get(
            move.kind, "Moved by the commissioner"
        )
        return f"{how} by {to}"
    return f"Dropped by {left}"


def _team(roster_id: int, state: Week, by_roster: Mapping[int, Team]) -> str:
    team = by_roster.get(roster_id)
    return state.team_name(team) if team else f"Roster {roster_id}"


def _ordinal(n: int) -> str:
    """'1st', '22nd', '113th'."""
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"
