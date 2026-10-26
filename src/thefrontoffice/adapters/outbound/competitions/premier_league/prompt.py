"""Rendering a Fantasy Premier League gameweek as the text a model reads.

Kept away from the provider because it is a different kind of work: everything
here turns state already gathered into prose, and none of it decides anything.
The provider fetches and the prompt describes.
"""

import logging

from thefrontoffice.adapters.outbound.competitions.premier_league.league import standing
from thefrontoffice.adapters.outbound.competitions.premier_league.squad import (
    Lineup,
    LineupChange,
    Transfer,
    affordable_transfers,
    best_lineup,
    effective_points,
    lineup_changes,
    points_with_captain,
)
from thefrontoffice.adapters.outbound.platforms.fpl.client import FPLSource, free_transfers
from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLAPIError
from thefrontoffice.adapters.outbound.platforms.fpl.types import (
    TRANSFER_HIT,
    Entry,
    Gameweek,
    Player,
    Squad,
    as_millions,
)
from thefrontoffice.config.constants import FPL_SCOUT_PROMPT
from thefrontoffice.domain.models import CompetitionContext, Stat

logger = logging.getLogger(__name__)

# The shortlist a prompt carries, which is far shorter than a list somebody
# scrolls: every line here is resent on every turn of the follow-up chat.
MARKET_LIMIT = 20
TRANSFER_LIMIT = 10


def build(
    client: FPLSource,
    league_id: str,
    entry_id: int,
    upcoming: Gameweek,
    squad: Squad,
    players: list[Player],
    current_starters: list[Player],
    current_bench: list[Player],
) -> CompetitionContext:
    """The scouting prompt, and the parts it was assembled from."""
    entry = client.get_entry(entry_id)
    catalog = client.get_players()

    captain_id = next((pick.element for pick in squad.picks if pick.is_captain), None)
    captain = next((p for p in current_starters if p.id == captain_id), None)
    best = best_lineup(players)
    current_points = points_with_captain(current_starters, captain)
    changes = lineup_changes(current_starters, best)
    allowance = free_transfers(client.get_history(entry_id), upcoming.id)

    market = sorted(
        (p for p in catalog.values() if p.is_available and p.minutes > 0),
        key=effective_points,
        reverse=True,
    )
    owned = {p.id for p in players}
    market_lines = {p.name: _market_line(p) for p in market if p.id not in owned}
    market_lines = dict(list(market_lines.items())[:MARKET_LIMIT])

    transfers = affordable_transfers(players, market, squad.bank, limit=TRANSFER_LIMIT)

    situation = _situation(entry, league_id, squad, upcoming.name, upcoming.average_score)
    constraints = _constraints(squad, allowance, best, current_points)

    return CompetitionContext(
        headline=headline(squad, allowance, best, current_points, upcoming),
        prompt=FPL_SCOUT_PROMPT.format(
            situation=situation,
            constraints=constraints,
            lineup_str="".join(_squad_line(p, captain=p.id == captain_id) for p in current_starters)
            or "- (no eleven set)\n",
            bench_str="".join(_squad_line(p) for p in current_bench) or "- (none)\n",
            changes_str=_changes_lines(changes),
            fixtures_str=_fixture_lines(client, players, upcoming.id),
            transfers_str=_transfer_lines(transfers),
            market_str="".join(market_lines.values()) or "- (none)\n",
            free_transfers=allowance,
        ),
        situation=situation,
        constraints=constraints,
        extra=f"LINEUP CHANGES IMPLIED BY EXPECTED POINTS:\n{_changes_lines(changes)}",
        roster_lines={p.name: _squad_line(p) for p in players},
        candidate_lines=market_lines,
    )


def headline(squad: Squad, allowance: int, best: Lineup, current_points: float, upcoming: Gameweek) -> list[Stat]:
    """What the gameweek turns on before its deadline: the eleven, and the money and moves left to change it.

    The season's own figures — points, overall rank, the mini-league — are
    the league view's, and the gameweek is already in the page's title.
    Points left on the bench is the only figure here that is a mistake rather
    than a fact, so it is the only one that ever warns — and only when the
    current eleven really is behind the best legal one.
    """
    behind = round(best.points - current_points, 1)
    lineup = (
        Stat(label="Lineup", value=f"{current_points:.1f} · best {best.points:.1f} xPts", tone="warning")
        if behind > 0
        else Stat(label="Lineup", value=f"{current_points:.1f} xPts")
    )
    return [
        # Shown in UTC, which is what the API states. A local rendering would
        # be friendlier and would also be a guess about where this is read.
        Stat(label="Deadline", value=f"{upcoming.deadline:%a %d %b %H:%M} UTC"),
        lineup,
        Stat(label="Bank", value=as_millions(squad.bank)),
        Stat(label="Free transfers", value=str(allowance), tone="good" if allowance else "neutral"),
    ]


def season_headline(entry: Entry, league_id: str) -> list[Stat]:
    """How the season is going, in FPL's own currency: points, overall rank, and this mini-league."""
    league = next((lg for lg in entry.leagues if str(lg.id) == league_id), None)
    stats = [
        Stat(label="Points", value=f"{entry.overall_points:,}"),
        Stat(label="Overall rank", value=f"{entry.overall_rank:,}"),
    ]
    if league:
        stats.append(Stat(label="Mini-league", value=standing(league)))
    return stats


def _situation(entry: Entry, league_id: str, squad: Squad, gameweek_name: str, average: int) -> str:
    """Rank, mini-league standing and money, as the prompt's opening block."""
    lines = [
        f"TEAM: {entry.name} ({entry.manager})",
        f"GAMEWEEK: {gameweek_name}" + (f", average score last time {average}" if average else ""),
        f"OVERALL: {entry.overall_points} points, rank {entry.overall_rank:,}",
    ]
    league = next((lg for lg in entry.leagues if str(lg.id) == league_id), None)
    if league:
        lines.append(f"MINI-LEAGUE: {league.name} — {standing(league)}")
    lines.append(f"MONEY: {as_millions(squad.bank)} in the bank, squad worth {as_millions(squad.value)}")
    if squad.points_on_bench:
        lines.append(f"LAST GAMEWEEK: {squad.points_on_bench} points were left on the bench.")
    return "\n".join(lines) + "\n"


def _constraints(squad: Squad, allowance: int, best: Lineup, current_points: float) -> str:
    """What the manager can actually do this week, and what it is worth."""
    current = round(current_points, 1)
    gain = round(best.points - current, 1)
    lines = [
        f"FREE TRANSFERS: {allowance}. Each extra transfer costs {TRANSFER_HIT} points.",
        f"BANK: {as_millions(squad.bank)}.",
        f"- The eleven as set expects {current:.1f} points with its captain doubled.",
        f"- The best legal eleven is a {best.formation} expecting {best.points:.1f} with the captain doubled"
        + (f", {gain:.1f} more than the current shape.\n" if gain > 0 else ".\n"),
        "- A start/sit change is free. A transfer is not, so it has to beat the alternative by "
        "enough to be worth the allowance.",
    ]
    if squad.active_chip:
        lines.insert(0, f"CHIP PLAYED LAST GAMEWEEK: {squad.active_chip}.")
    return "\n".join(lines)


def _squad_line(player: Player, captain: bool = False) -> str:
    flag = player.availability
    note = f" [{flag}]" if flag else ""
    mark = " (C)" if captain else ""
    return (
        f"- {player.name}{mark} ({player.position}, {player.team}, {as_millions(player.cost)})"
        f"{note}: {player.expected_points:.1f} xPts, form {player.form:.1f}, "
        f"{player.total_points} pts this season\n"
    )


def _market_line(player: Player) -> str:
    return (
        f"- {player.name} ({player.position}, {player.team}, {as_millions(player.cost)}): "
        f"{player.expected_points:.1f} xPts, form {player.form:.1f}, "
        f"{player.expected_goal_involvements:.2f} xGI, owned by {player.selected_by:.1f}%\n"
    )


def _changes_lines(changes: list[LineupChange]) -> str:
    if not changes:
        return "- None; the eleven as set is already the best legal shape.\n"
    return "".join(
        f"- START {c.start.name} ({c.start.position}) for "
        f"{c.drop.name if c.drop else 'an empty place'}: +{c.gain:.1f} xPts\n"
        for c in changes
    )


def _transfer_lines(transfers: list[Transfer]) -> str:
    if not transfers:
        return "- (nothing in the bank buys an upgrade)\n"
    return "".join(
        f"- {t.incoming.name} ({t.incoming.position}, {t.incoming.team}, {as_millions(t.incoming.cost)}) "
        f"for {t.out.name} ({as_millions(t.out.cost)}): +{t.gain:.1f} xPts, "
        f"{'costs' if t.cost > 0 else 'frees'} {as_millions(abs(t.cost))}\n"
        for t in transfers
    )


def _fixture_lines(client: FPLSource, players: list[Player], gameweek: int) -> str:
    """Each owned club's next match and how hard the game rates it.

    A club with no fixture is a blank gameweek — every player of theirs
    scores nothing — which is the single most important thing the report can
    be told, so it is stated rather than omitted.
    """
    try:
        fixtures = client.get_fixtures(gameweek)
    except FPLAPIError as e:
        # Difficulty is context, not the basis of the report; losing it
        # should shrink the prompt rather than fail the run.
        logger.warning(f"Skipping FPL fixtures: {e}")
        return "- (unavailable)\n"

    clubs = sorted({p.team for p in players})
    lines = []
    for club in clubs:
        matches = [m for f in fixtures if (m := f.opponent_of(club))]
        if not matches:
            lines.append(f"- {club}: no fixture — blank gameweek, every {club} player scores 0.\n")
            continue
        rendered = ", ".join(
            f"{'vs' if home else 'at'} {opponent} (difficulty {difficulty})" for opponent, difficulty, home in matches
        )
        note = " — double gameweek" if len(matches) > 1 else ""
        lines.append(f"- {club}: {rendered}{note}\n")
    return "".join(lines) or "- (none)\n"
