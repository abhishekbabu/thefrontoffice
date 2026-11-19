"""Rendering a Fantasy Premier League gameweek as the text a model reads.

Kept away from the provider because it is a different kind of work: everything
here turns state already gathered into prose, and none of it decides anything.
The provider fetches and the prompt describes.
"""

from thefrontoffice.adapters.outbound.competitions.dates import at_time
from thefrontoffice.adapters.outbound.competitions.premier_league.league import league_of, standing
from thefrontoffice.adapters.outbound.competitions.premier_league.rules import (
    TRANSFER_HIT,
    Lineup,
    Roster,
    Transfer,
    Value,
    affordable_transfers,
    points_with_captain,
)
from thefrontoffice.adapters.outbound.competitions.premier_league.views import fixture_text
from thefrontoffice.adapters.outbound.competitions.premier_league.worth import HORIZON, Valuation
from thefrontoffice.adapters.outbound.competitions.tasks import task_lines
from thefrontoffice.adapters.outbound.platforms.fpl.types import (
    Entry,
    Gameweek,
    Opponent,
    Player,
    Squad,
    as_millions,
)
from thefrontoffice.domain.models import Action, CompetitionContext, Stat, task_id

# The shortlist a prompt carries, which is far shorter than a list somebody
# scrolls: every line here is resent on every turn of the follow-up chat.
MARKET_LIMIT = 20
TRANSFER_LIMIT = 10


FPL_SCOUT_PROMPT = """
You are an elite Fantasy Premier League manager.
Produce a concise, high-impact report for the gameweek that is still open.

LEAGUE RULES:
- One squad of 15: 2 GKP, 5 DEF, 5 MID, 3 FWD, at most 3 players from any one club.
- Eleven of the 15 start. A legal formation needs 1 GKP, 3-5 DEF, 2-5 MID, 1-3 FWD.
- The captain scores double. That is the single highest-leverage decision of the week.
- Transfers beyond the free allowance cost 4 points each, deducted from the gameweek score.
- A benched player scores nothing unless a starter does not play and the auto-subs reach them.
- Fixture difficulty runs 1 (easiest) to 5 (hardest), assigned by the game.

HOW PLAYERS ARE VALUED:
- "worth" is expected points this gameweek: recent points per match (settled toward the season's) beside
  an outlook, each scaled by fixture difficulty, with a quarter from underlying numbers (xG/xA, clean-sheet
  odds, saves, bonus, defensive contributions), summed over every fixture (double gameweeks count both,
  blanks 0), times the chance of playing and up to a tenth for steady minutes.
- FPL's own "xPts" (ep_next) currently repeats its form figure, so it counts only where it differs.
- "next {horizon}" is worth summed over this gameweek and the {horizon_after} after it: what a transfer is weighed on.

{situation}

{constraints}

YOUR CURRENT ELEVEN (as set for the last completed gameweek):
{lineup_str}

BENCH (in substitution order; the goalkeeper can only replace a goalkeeper):
{bench_str}

TO DO — WHAT THE NUMBERS ALREADY SAY NEEDS DECIDING:
- Computed from the squad, not estimated: lineup swaps over every legal formation, the armband,
  the bench order, transfers within the bank and free transfers, and chips about to expire.
- The manager sees this list; your verdicts appear beside it, so judge these items rather than restating them.
{tasks_str}

FIXTURES THIS GAMEWEEK FOR THE CLUBS YOU OWN:
{fixtures_str}

AFFORDABLE TRANSFERS (best upgrade per squad player, within the bank, by worth over the next {horizon}):
- Each cost is the incoming price less the outgoing player's selling price, which keeps only
  half of any rise since he was bought.
{transfers_str}

TOP AVAILABLE PLAYERS BY WORTH (not in your squad):
{market_str}

YOUR TASK:
1. Read the situation: overall rank, mini-league position, and what this gameweek turns on.
2. Give a verdict on every TO DO item, by its id: AGREE to make it, OVERRULE when news, role or
   fixtures say otherwise, WAIT when it turns on news due before the deadline. Never repeat a
   TO DO item as a move.
3. Add only moves the list does not already make: a captain you rate over the list's, a transfer
   it missed. At most {free_transfers} free transfer(s) in all; a points hit only if the gain
   clearly beats the 4-point cost, and say so explicitly.
4. Skip any move you would not actually make. Three good moves beat six padded ones.

Return your analysis in the required structured form. Field guidance:
- situation: rank, mini-league standing, and the decision this week hinges on.
- focus: short labels — 'captaincy', 'DEF fixtures', 'Haaland doubt'.
- verdicts: exactly one per TO DO item, `task` set to its id ('{first_task}'). Empty if the list is empty.
- moves: action CAPTAIN, START, BENCH, TRANSFER or MONITOR. Put the number in `metric`
  with its unit — '6.2 pts', '£8.5m, +1.4 pts over 4', 'fixture difficulty 2'. Pair every
  TRANSFER with the player it `replaces`.
- Be specific and tactical. Do not restate the inputs.
"""


def build(
    *,
    league_id: str,
    entry: Entry,
    upcoming: Gameweek,
    roster: Roster,
    market: list[Player],
    value: Valuation,
    best: Lineup,
    allowance: int,
    fixtures: dict[str, list[Opponent]],
    selling: dict[int, int],
    tasks: list[Action],
) -> CompetitionContext:
    """The scouting prompt, and the parts it was assembled from.

    `market` is everybody buyable, best worth first; `best` the eleven `value`
    picks; `tasks` the to-do list as the page shows it, numbered here so a
    verdict can name its item.
    """
    squad, players, current_starters = roster.squad, roster.players, roster.starters
    current_points = points_with_captain(current_starters, roster.captain, value)

    owned = {p.id for p in players}
    market_lines = {p.name: _market_line(p, value) for p in market if p.id not in owned and p.minutes > 0}
    market_lines = dict(list(market_lines.items())[:MARKET_LIMIT])

    transfers = affordable_transfers(
        players, market, squad.bank, selling=selling, limit=TRANSFER_LIMIT, value=value.horizon
    )

    situation = _situation(entry, league_id, squad, upcoming.name, upcoming.average_score)
    constraints = _constraints(squad, allowance, best, current_points)
    names = {str(p.id): p.name for p in (*players, *market)}
    listed = task_lines(tasks)

    return CompetitionContext(
        headline=headline(squad, allowance, best, current_points, upcoming, value),
        prompt=FPL_SCOUT_PROMPT.format(
            horizon=HORIZON,
            horizon_after=HORIZON - 1,
            situation=situation,
            constraints=constraints,
            lineup_str="".join(_squad_line(p, value, captain=p is roster.captain) for p in current_starters)
            or "- (no eleven set)\n",
            bench_str="".join(_squad_line(p, value) for p in roster.bench) or "- (none)\n",
            tasks_str=listed or NOTHING_TO_DO,
            fixtures_str=_fixture_lines(fixtures),
            transfers_str=_transfer_lines(transfers),
            market_str="".join(market_lines.values()) or "- (none)\n",
            free_transfers=allowance,
            first_task=task_id(1),
        ),
        situation=situation,
        constraints=constraints,
        extra=f"TO DO:\n{listed or NOTHING_TO_DO}",
        roster_lines={p.name: _squad_line(p, value) for p in players},
        candidate_lines=market_lines,
        tasks=tasks,
        listed=frozenset(
            names[pid] for task in tasks for pid in (task.player_id, task.replaces, task.drop) if pid in names
        ),
    )


NOTHING_TO_DO = "- Nothing: the squad asks for no move this gameweek.\n"


def headline(
    squad: Squad, allowance: int, best: Lineup, current_points: float, upcoming: Gameweek, value: Value
) -> list[Stat]:
    """What the gameweek turns on before its deadline: the eleven, the armband, and the money and moves left.

    The season's own figures — points, overall rank, the mini-league — are
    the league view's, and the gameweek is already in the page's title.
    Points left on the bench is the only figure here that is a mistake rather
    than a fact, so it is the only one that ever warns — and only when the
    current eleven really is behind the best legal one. The captain is the
    best eleven's, doubled, with his vice.
    """
    behind = round(best.points - current_points, 1)
    lineup = (
        Stat(label="Lineup", value=f"{current_points:.1f} · best {best.points:.1f} pts", tone="warning")
        if behind > 0
        else Stat(label="Lineup", value=f"{current_points:.1f} pts")
    )
    stats = [
        # Shown in UTC, which is what the API states. A local rendering would
        # be friendlier and would also be a guess about where this is read.
        Stat(label="Deadline", value=f"{at_time(upcoming.deadline)} UTC"),
        lineup,
    ]
    if best.captain is not None:
        vice = f" · vice {best.vice.name}" if best.vice else ""
        stats.append(Stat(label="Captain", value=f"{best.captain.name} {value(best.captain) * 2:.1f}{vice}"))
    return [
        *stats,
        Stat(label="Bank", value=as_millions(squad.bank)),
        Stat(label="Free transfers", value=str(allowance), tone="good" if allowance else "neutral"),
    ]


def season_headline(entry: Entry, league_id: str) -> list[Stat]:
    """How the season is going, in FPL's own currency: points, overall rank, and this mini-league."""
    league = league_of(entry, league_id)
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
    league = league_of(entry, league_id)
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


def _worth_text(player: Player, value: Valuation) -> str:
    """'worth 7.6 (vs FUL (2)), next 4 27.5, 6.6 pts/match, FPL xPts 4.0': what he is weighed on, and its parts."""
    found = value.of(player)
    if found is None:
        return f"FPL xPts {player.expected_points:.1f}"
    form = f", {found.form:.1f} pts/match" if found.form is not None else ""
    return (
        f"worth {found.week:.1f} ({fixture_text(list(found.fixtures))}), next {HORIZON} {found.horizon:.1f}"
        f"{form}, FPL xPts {player.expected_points:.1f}"
    )


def _squad_line(player: Player, value: Valuation, captain: bool = False) -> str:
    flag = player.availability
    note = f" [{flag}]" if flag else ""
    mark = " (C)" if captain else ""
    return (
        f"- {player.name}{mark} ({player.position}, {player.team}, {as_millions(player.cost)})"
        f"{note}: {_worth_text(player, value)}, {player.total_points} pts this season\n"
    )


def _market_line(player: Player, value: Valuation) -> str:
    flag = player.availability
    note = f" [{flag}]" if flag else ""
    return (
        f"- {player.name} ({player.position}, {player.team}, {as_millions(player.cost)}){note}: "
        f"{_worth_text(player, value)}, {player.expected_goal_involvements:.2f} xGI, "
        f"owned by {player.selected_by:.1f}%\n"
    )


def _transfer_lines(transfers: list[Transfer]) -> str:
    if not transfers:
        return "- (nothing in the bank buys an upgrade)\n"
    return "".join(
        f"- {t.incoming.name} ({t.incoming.position}, {t.incoming.team}, {as_millions(t.incoming.cost)}) "
        f"for {t.out.name} (sells for {as_millions(t.sale)}): +{t.gain:.1f} pts over {HORIZON}, "
        f"{'costs' if t.cost > 0 else 'frees'} {as_millions(abs(t.cost))}\n"
        for t in transfers
    )


def _fixture_lines(fixtures: dict[str, list[Opponent]]) -> str:
    """Each owned club's next match and how hard the game rates it.

    A club with no fixture is a blank gameweek — every player of theirs
    scores nothing — which is the single most important thing the report can
    be told, so it is stated rather than omitted.
    """
    lines = []
    for club, matches in fixtures.items():
        if not matches:
            lines.append(f"- {club}: no fixture — blank gameweek, every {club} player scores 0.\n")
            continue
        rendered = ", ".join(f"{'vs' if m.home else 'at'} {m.club} (difficulty {m.difficulty})" for m in matches)
        note = " — double gameweek" if len(matches) > 1 else ""
        lines.append(f"- {club}: {rendered}{note}\n")
    return "".join(lines) or "- (none)\n"
