"""The league beyond this gameweek: the season, the table, the real matches, the league's transfers.

Separate from the gameweek because it answers a different question asked at a
different time — how the season is going, rather than what to do before the
deadline — and it costs requests the week does not need.

FPL has no transfer feed for a mini-league, but every manager's own transfers are
public, so the league's activity is each member's, read one entry at a time.
"""

import logging
from datetime import datetime
from typing import Literal

from thefrontoffice.adapters.outbound.competitions.dates import at_time
from thefrontoffice.adapters.outbound.competitions.places import ordinal
from thefrontoffice.adapters.outbound.competitions.premier_league.rules import TRANSFER_CHIPS, Roster
from thefrontoffice.adapters.outbound.platforms.fpl.client import FPLSource
from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLAPIError
from thefrontoffice.adapters.outbound.platforms.fpl.types import (
    CHIP_NAMES,
    Entry,
    H2HMatch,
    MiniLeague,
    Player,
    TableRow,
    TransferMade,
)
from thefrontoffice.domain.models import (
    ActivityMove,
    ActivityRow,
    LeagueSchedule,
    Match,
    PlayerRef,
    ScheduleRow,
    StandingRow,
    outcome,
)

logger = logging.getLogger(__name__)

# FPL's own scale runs 1-5; 4 is where its UI starts calling a run hard.
HARD_FIXTURE = 4

ACTIVITY_GAMEWEEKS = 3
"""How many gameweeks back the activity reaches: "what did I miss", not the season's every move."""


def build(
    client: FPLSource,
    league: MiniLeague | None,
    entry_id: int,
    playing: int,
    *,
    mine: Roster | None = None,
    theirs: Roster | None = None,
) -> LeagueSchedule:
    """The season, the table, the league's transfers, and the real matches behind the gameweek.

    The matches stand on their own: they are the gameweek itself, and they are
    the same whether or not this id names a league with fixtures to read. Each
    names the players `mine` and `theirs` have in it.
    """
    games = matches(client, playing, mine=mine, theirs=theirs)
    if league is None:
        return LeagueSchedule(matches=games)
    table = client.get_standings(league.id, league.is_h2h)
    return LeagueSchedule(
        season=_season_rows(client, league, entry_id, playing),
        standings=_standings(table, league, entry_id),
        matches=games,
        activity=activity(client, table, entry_id, playing),
    )


def league_of(entry: Entry, league_id: str) -> MiniLeague | None:
    """The mini-league behind an id, or None when the id names none of this entry's.

    `list_leagues` falls back to the manager's overall standing when they have
    joined no private league, and that id is the entry's own — a place in a
    table of eleven million, not a league with a table or fixtures to read.
    """
    return next((lg for lg in entry.leagues if str(lg.id) == league_id), None)


def standing(league: MiniLeague) -> str:
    """How a mini-league position reads, in its own format's terms: '3 of 12', '1st · head-to-head'.

    A head-to-head league has no field to be a position in — it is a table of
    match records, short enough that a placing reads as a placing. A missing
    field size says nothing about the field rather than '1 of 0'.
    """
    if league.is_h2h:
        return f"{ordinal(league.rank)} · head-to-head"
    if league.rank_count:
        return f"{league.rank:,} of {league.rank_count:,}"
    return f"{league.rank:,}"


def tie_score(tie: H2HMatch | None, played: bool) -> tuple[int, int] | None:
    """A tie's score, yours first, once its gameweek has been played; None before that, or with no tie.

    The one reading of a tie's points: before then they are a running total, and
    the 0-0 of a week not yet kicked off is not a draw.
    """
    return (tie.my_points, tie.opponent_points) if tie is not None and played else None


def _season_rows(client: FPLSource, league: MiniLeague, entry_id: int, playing: int) -> list[ScheduleRow]:
    """Your gameweeks, with the tie in each where the league has one.

    A classic league has no season in this sense — it is a running table,
    not a set of fixtures — so it gets the gameweeks and their deadlines
    without opponents, which is still the calendar somebody came for. A
    gameweek has a result once FPL calls it finished, and not before.
    """
    gameweeks = client.get_gameweeks()
    ties = {}
    if league.is_h2h:
        try:
            ties = client.get_h2h_season(league.id, entry_id)
        except FPLAPIError as e:
            logger.warning(f"Continuing without the h2h season: {e}")

    rows = []
    for gw in gameweeks:
        tie = ties.get(gw.id)
        score = tie_score(tie, gw.finished)
        rows.append(
            ScheduleRow(
                label=gw.name,
                date=at_time(gw.deadline),
                opponent=tie.opponent_name if tie else "",
                detail="" if tie else ("no tie" if league.is_h2h else ""),
                result=f"{score[0]}-{score[1]}" if score else "",
                outcome=outcome(*score) if score else None,
                is_current=gw.id == playing,
            )
        )
    return rows


def _standings(table: list[TableRow], league: MiniLeague, entry_id: int) -> list[StandingRow]:
    return [
        StandingRow(
            rank=row.rank,
            name=row.entry_name,
            detail=row.manager,
            record=row.record,
            # In h2h the table is on league points and the FPL total is the
            # tiebreak; in a classic league they are the same number.
            points=f"{row.total:,}" if not league.is_h2h else f"{row.total} ({row.points_for:,} pts)",
            team_id=str(row.entry),
            is_mine=row.entry == entry_id,
        )
        for row in table
    ]


def matches(
    client: FPLSource, gameweek: int, *, mine: Roster | None = None, theirs: Roster | None = None
) -> list[Match]:
    """The real matches a gameweek is made of: both difficulties, the score once each kicks off, and whose players are in it.

    Difficulty is per side, so it is carried per side: a fixture is easy
    for one of these clubs and hard for the other, and one number for the
    match would be true of neither.
    """
    fixtures = client.get_fixtures(gameweek)
    return [
        Match(
            label=at_time(f.kickoff) if f.kickoff else "TBC",
            home=f.home,
            away=f.away,
            detail=f"FDR {f.home_difficulty} / {f.away_difficulty}",
            tone="warning" if max(f.home_difficulty, f.away_difficulty) >= HARD_FIXTURE else "neutral",
            home_score=f.home_score if f.started else None,
            away_score=f.away_score if f.started else None,
            kickoff=f.kickoff,
            yours=_in_match(mine, (f.home, f.away)),
            theirs=_in_match(theirs, (f.home, f.away)),
        )
        for f in sorted(fixtures, key=lambda f: (f.kickoff is None, f.kickoff))
    ]


def _in_match(squad: Roster | None, clubs: tuple[str, str]) -> list[PlayerRef]:
    """A squad's players at either club, starters first, in the order they were picked."""
    if squad is None:
        return []
    return [
        PlayerRef(
            player_id=str(player.id),
            name=player.name,
            detail=f"{player.position} · {player.team}" + ("" if pick.is_starting else " · bench"),
        )
        for pick, player in squad.picked
        if player.team in clubs
    ]


def blanks(client: FPLSource, games: list[Match]) -> list[str]:
    """The clubs with no match in a gameweek's `games`, alphabetical; none where it lists no matches at all."""
    if not games:
        return []
    playing = {club for m in games for club in (m.home, m.away)}
    return sorted(set(client.get_clubs()) - playing)


def activity(client: FPLSource, table: list[TableRow], entry_id: int, playing: int) -> list[ActivityRow]:
    """Every member's transfers over the last few gameweeks, newest first: one row per manager per gameweek.

    FPL transfers are made against a deadline rather than one at a time, so a
    gameweek's set is the move. A Wildcard or Free Hit says so, since its
    transfers are a rebuild rather than separate decisions. A member whose
    transfers will not load is left out rather than failing the page.
    """
    catalog = client.get_players()
    first = playing - ACTIVITY_GAMEWEEKS + 1
    dated: list[tuple[datetime, ActivityRow]] = []
    for member in table:
        try:
            transfers = [t for t in client.get_transfers(member.entry) if first <= t.event <= playing]
            chips = {c.event: c.name for c in client.get_chips_played(member.entry)} if transfers else {}
        except FPLAPIError as e:
            logger.warning(f"Skipping {member.entry_name}'s transfers: {e}")
            continue
        by_week: dict[int, list[TransferMade]] = {}
        for transfer in transfers:
            by_week.setdefault(transfer.event, []).append(transfer)
        for event, moves in by_week.items():
            row = _activity_row(member, event, moves, chips.get(event, ""), catalog, is_mine=member.entry == entry_id)
            dated.append((max(t.time for t in moves), row))
    return [row for _, row in sorted(dated, key=lambda pair: pair[0], reverse=True)]


def _activity_row(
    member: TableRow,
    event: int,
    moves: list[TransferMade],
    chip: str,
    catalog: dict[int, Player],
    *,
    is_mine: bool,
) -> ActivityRow:
    """One manager's transfers for one deadline, each player in before each player out."""
    if chip in TRANSFER_CHIPS:
        label = CHIP_NAMES[chip]
    else:
        label = "1 transfer" if len(moves) == 1 else f"{len(moves)} transfers"
    players = [
        *(_move(t.element_in, "added", catalog, member) for t in moves),
        *(_move(t.element_out, "dropped", catalog, member) for t in moves),
    ]
    return ActivityRow(
        when=at_time(max(t.time for t in moves)),
        who=member.entry_name,
        what=f"GW{event} · {label}",
        detail=", ".join(("+" if m.change == "added" else "-") + m.player for m in players),
        is_mine=is_mine,
        moves=players,
    )


def _move(
    element: int, change: Literal["added", "dropped"], catalog: dict[int, Player], member: TableRow
) -> ActivityMove:
    """One player a transfer moved; one the catalog no longer lists keeps his id."""
    player = catalog.get(element)
    return ActivityMove(
        player_id=str(element),
        player=player.name if player else str(element),
        position=player.position if player else "",
        team=player.team if player else "",
        change=change,
        manager=member.entry_name,
    )
