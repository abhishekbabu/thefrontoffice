"""How a football player reads on a page — the views of him: a table row, a lineup row, the drawer that opens on him.

Split from the provider because it is the one question asked of a player in
every view — the roster, the wire, both lineups, a player opened on his own —
and the provider is the place a week is gathered, not drawn.
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from thefrontoffice.adapters.outbound.competitions.injuries import BODY_PART
from thefrontoffice.adapters.outbound.competitions.nfl import evidence, history, injuries
from thefrontoffice.adapters.outbound.competitions.nfl.lineup import LineupSlot, eligible_positions
from thefrontoffice.adapters.outbound.competitions.nfl.model import (
    FREE_AGENT,
    Game,
    GameLine,
    NFLSource,
    PlayerInfo,
    Projection,
    SeasonTotals,
    Team,
    active,
    by_club,
    fielded,
    let_go,
    open_spots,
)
from thefrontoffice.adapters.outbound.competitions.nfl.rules import (
    FANTASY_POSITIONS,
    RULED_OUT_SHORT,
    STREAMED,
    listed,
    long_term,
    ruled_out,
)
from thefrontoffice.adapters.outbound.competitions.nfl.week import (
    Live,
    Week,
    projections_for,
    zero_projection,
)
from thefrontoffice.adapters.outbound.competitions.nfl.worth import plays, value
from thefrontoffice.adapters.outbound.competitions.places import ordinal
from thefrontoffice.adapters.outbound.competitions.teammates import WITHOUT_COLUMN
from thefrontoffice.domain.errors import PlatformError, PlayerNotFoundError
from thefrontoffice.domain.models import (
    FIT_COLUMN,
    NOT_APPLICABLE,
    PLAYER_COLUMN,
    POSITION_COLUMN,
    SLOT_COLUMN,
    STATUS_COLUMN,
    Better,
    Held,
    MovePlayer,
    MoveSide,
    PlayerCard,
    PlayerDetail,
    Side,
    Spot,
    SpotScoring,
    Stat,
    StatGroup,
    StatRow,
    StatTable,
    Tone,
)

logger = logging.getLogger(__name__)


# Sleeper's projection keys, in the order a box score reads them. Only the ones
# a fantasy line is actually made of — the payload carries dozens more, most of
# which are zero for any given player.
PROJECTION_LABELS: dict[str, str] = {
    "pass_att": "Pass att",
    "pass_cmp": "Completions",
    "pass_yd": "Pass yards",
    "pass_td": "Pass TD",
    "pass_int": "Interceptions",
    "rush_att": "Carries",
    "rush_yd": "Rush yards",
    "rush_td": "Rush TD",
    "rec_tgt": "Targets",
    "rec": "Receptions",
    "rec_yd": "Rec yards",
    "rec_td": "Rec TD",
}

_PASSING = ("pass_att", "pass_cmp", "pass_yd", "pass_td", "pass_int")
_RUSHING = ("rush_att", "rush_yd", "rush_td")
_CATCHING = ("rec_tgt", "rec", "rec_yd", "rec_td")
PROJECTED_FOR: dict[str, tuple[str, ...]] = {
    "QB": (*_PASSING, *_RUSHING),
    "RB": (*_RUSHING, *_CATCHING),
    "WR": _CATCHING,
    "TE": _CATCHING,
}
"""The projected line each position is played for. A receiver's tenth of a carry is
noise beside his targets; a position not listed reads every key that has a figure."""

LOWER_IS_BETTER = frozenset({"pass_int", "Interceptions"})
"""Measures a player is better for having less of, by projection key and by season split label."""


def _projection_lines(stats: Mapping[str, float], position: str) -> list[Stat]:
    """The projection broken out: only what his position is played for, and nothing that rounds to nought."""
    keys = PROJECTED_FOR.get(position, tuple(PROJECTION_LABELS))
    lines = []
    for key in keys:
        value = f"{stats.get(key, 0.0):.1f}".rstrip("0").rstrip(".")
        if value not in ("", "0", "-0"):
            better: Better = "lower" if key in LOWER_IS_BETTER else "higher"
            lines.append(Stat(label=PROJECTION_LABELS[key], value=value, better=better))
    return lines


SPLIT_LABELS = (
    ("pass_yd", "Passing yards"),
    ("pass_td", "Passing TDs"),
    ("pass_int", "Interceptions"),
    ("cmp_pct", "Completion %"),
    ("rush_yd", "Rushing yards"),
    ("rush_td", "Rushing TDs"),
    ("rec", "Receptions"),
    ("rec_tgt", "Targets"),
    ("rec_yd", "Receiving yards"),
    ("rec_td", "Receiving TDs"),
)

# A game log's columns past the points, by position, as Sleeper's own player
# page reads them: what the position is scored on, and nothing it never records.
# Two keys make one "made/tried" cell.
_RECEIVING = (
    ("Tgt", ("rec_tgt",)),
    ("Rec", ("rec",)),
    ("Rec yd", ("rec_yd",)),
    ("Rec TD", ("rec_td",)),
    ("Car", ("rush_att",)),
    ("Rush yd", ("rush_yd",)),
)
GAME_LOG_COLUMNS: dict[str, tuple[tuple[str, tuple[str, ...]], ...]] = {
    "QB": (
        ("Cmp/Att", ("pass_cmp", "pass_att")),
        ("Pass yd", ("pass_yd",)),
        ("Pass TD", ("pass_td",)),
        ("INT", ("pass_int",)),
        ("Car", ("rush_att",)),
        ("Rush yd", ("rush_yd",)),
        ("Rush TD", ("rush_td",)),
    ),
    "RB": (
        ("Car", ("rush_att",)),
        ("Rush yd", ("rush_yd",)),
        ("Rush TD", ("rush_td",)),
        ("Tgt", ("rec_tgt",)),
        ("Rec", ("rec",)),
        ("Rec yd", ("rec_yd",)),
        ("Rec TD", ("rec_td",)),
    ),
    "WR": _RECEIVING,
    "TE": _RECEIVING,
    "K": (("FG", ("fgm", "fga")), ("XP", ("xpm", "xpa"))),
    "DEF": (
        ("Pts allowed", ("pts_allow",)),
        ("Sacks", ("sack",)),
        ("INT", ("int",)),
        ("Fum rec", ("fum_rec",)),
        ("TD", ("td",)),
    ),
}


def _split_value(key: str, value: float | None) -> str:
    """A production figure, or nothing where that position never records one."""
    if not value:
        return NOT_APPLICABLE
    return f"{value:.1f}%" if key == "cmp_pct" else f"{value:.0f}"


# A week made and a week wasted, on a points-league scale where a startable
# flex is worth around ten.
HAUL_POINTS = 20.0
BLANK_POINTS = 5.0


def lineup_order(state: Week, roster: Team) -> list[str]:
    """Read as a lineup: the starters slot by slot, then the bench best projected first, then reserve."""
    starters = [pid for pid in roster.starter_ids if pid]
    bench = [pid for pid in active(roster) if pid not in starters]
    bench.sort(key=lambda pid: -(state.projections[pid].points if pid in state.projections else 0.0))
    return starters + bench + [pid for pid in roster.player_ids if pid in roster.reserve_ids]


def is_signing(meta: PlayerInfo) -> bool:
    """Whether adding this player could do anything.

    Two cuts, both about what the wire is for. The catalog carries every
    position the sport has, and a fantasy league scores six of them. It
    also never forgets anybody: Reggie Wayne retired in 2014 and is still
    in it, unsigned, which the default ranking hid because he has no
    projection — and sorting by experience put him on the first page.
    A player on no NFL roster cannot score for yours.
    """
    return meta.position in FANTASY_POSITIONS and meta.team != FREE_AGENT


def held(roster: Team) -> dict[str, str]:
    """The slot each reserve player is held in, as Sleeper names it: IR, or TAXI."""
    return {pid: "IR" if pid in roster.ir_ids else "TAXI" for pid in roster.reserve_ids}


ROS_COLUMN = "ROS"
"""Projected points over the rest of the season, through the fantasy final: see `outlook.rest_of_season` for which weeks."""

SNAP_COLUMN, TARGET_COLUMN = "Snap%", "Tgt%"
"""His share of his offense's snaps, and of its targets, over his last few games (`evidence.ROLE_GAMES`)."""

TREND_COLUMN = "Trend"
"""Whose role just jumped: the pickups a projection has not caught up with yet."""

BACK_COLUMN = "Back"
"""When ESPN expects him back from injury, as a week of the season: the stash question on the IR list."""


def with_returns(rows: Sequence[PlayerCard], state: Week, schedule: Mapping[int, Sequence[Game]]) -> list[PlayerCard]:
    """Each row with when he is expected back, sorting by the day; a dash and no value where ESPN gives none."""
    out = []
    for row in rows:
        back = state.injuries.returns(row.player_id)
        out.append(
            row.model_copy(
                update={
                    "columns": {**row.columns, BACK_COLUMN: injuries.short_return(back, schedule) if back else "—"},
                    "values": {**row.values, **({BACK_COLUMN: float(back.toordinal())} if back else {})},
                }
            )
        )
    return out


def share(value: float | None) -> str:
    """A share of the offense as a cell or a stat reads it; a dash where his position has none."""
    return f"{value:.0%}" if value is not None else "—"


def cards(
    state: Week,
    player_ids: list[str],
    starters: set[str],
    wire: bool = False,
    reserve: Mapping[str, str] | None = None,
    ahead: Mapping[str, float] | None = None,
) -> list[PlayerCard]:
    """One table shape for every list of players this sport shows.

    The wire has no lineup to be in, so no slot; it has instead what each
    would add to your lineup — "how good is he" is only half the question
    there, and "how good is he for me" is the other — and how he has been
    used, which a projection alone hides. `reserve` names the slot of each
    player held in one (see `held`), who is neither started nor benched.
    `ahead` is each player's rest-of-season projection, where it loaded;
    without it there is no such column, rather than one of noughts.
    """
    reserve = reserve or {}
    hurt = state.teammates if wire else None
    rows = []
    for player_id in player_ids:
        meta = state.players.get(player_id)
        if not meta:
            continue
        projection = state.projections.get(player_id)
        injury = meta.injury_status
        depth = meta.depth_chart_order
        fitted = fit(state, projection) if wire and projection else None
        trend = state.evidence.trends.get(player_id) if wire else None
        role = state.evidence.roles.get(player_id) if wire else None
        snaps, targets = (role.snap_share, role.target_share) if role else (None, None)
        rest = ahead.get(player_id, 0.0) if ahead is not None else None
        # The teammate whose absence he would gain most from, first; the rest are in the drawer.
        split = next(iter(hurt.splits(meta)), None) if hurt else None
        identity = {PLAYER_COLUMN: meta.name, POSITION_COLUMN: meta.position, "Team": meta.team}
        proj = f"{projection.points:.2f}" if projection else "0.00"
        ros = {ROS_COLUMN: f"{rest:.1f}"} if rest is not None else {}
        # Through the zero-point fallback, which carries his ruling
        # where Sleeper has published no projection for him.
        versus = _versus(projection or zero_projection(player_id, meta), state.scheduled, "—")
        depth_cell = str(depth) if depth else "—"
        columns = (
            # Read left to right as a pickup is weighed: who he is, what he is
            # worth to you, how he is used, and then the week's context.
            {
                **identity,
                FIT_COLUMN: fitted.cell() if fitted else "—",
                "Proj": proj,
                **ros,
                SNAP_COLUMN: share(snaps),
                TARGET_COLUMN: share(targets),
                # Sorts by the size of the jump.
                TREND_COLUMN: trend.short() if trend else "—",
                WITHOUT_COLUMN: split.cell() if split else "—",
                "Opponent": versus,
                STATUS_COLUMN: injury,
                "Depth": depth_cell,
            }
            if wire
            else {
                **identity,
                SLOT_COLUMN: _slot(player_id, starters, reserve),
                "Proj": proj,
                **ros,
                "Opponent": versus,
                "Depth": depth_cell,
                # Years in the league are in the player's drawer: a column of them decides nothing.
                STATUS_COLUMN: injury,
            }
        )
        rows.append(
            PlayerCard(
                player_id=player_id,
                ruled_out=ruled_out(injury),
                # Who a fit is measured against, on hover: the cell has room for the gap alone.
                notes={
                    **({FIT_COLUMN: fitted.against} if fitted else {}),
                    **({WITHOUT_COLUMN: split.note()} if split else {}),
                },
                columns=columns,
                values={
                    **({FIT_COLUMN: fitted.gain} if fitted else {}),
                    **({TREND_COLUMN: trend.rise} if trend else {}),
                    **({SNAP_COLUMN: snaps} if snaps is not None else {}),
                    **({TARGET_COLUMN: targets} if targets is not None else {}),
                    **({ROS_COLUMN: rest} if rest is not None else {}),
                    "Proj": projection.points if projection else 0.0,
                    "Depth": float(depth) if depth else 0.0,
                },
            )
        )
    return rows


def _headline_label(projection: Projection | None, scheduled: bool, week: int) -> str:
    """What the figure is, or why there is not one.

    The two reasons differ and a reader can act on the difference: nothing
    is published yet, versus published and this player is not in it.
    """
    if projection:
        return f"projected for week {week}"
    if not scheduled:
        return f"Week {week} projections not out yet"
    return f"Not projected in week {week}"


@dataclass(frozen=True)
class Fit:
    """How a free agent compares with the weakest starter he could replace: the gap, and against whom."""

    gain: float
    """His `worth.value` less that starter's; his whole value where the slot is empty, or its starter cannot play this week."""
    against: str
    """Who he is measured against, 'over Josh Allen' or 'vs Josh Allen', or the slot he would fill, 'at FLEX, empty', 'for Josh Allen, out'."""

    def cell(self) -> str:
        """The gap alone, as a column has room for: '+2.10', '-8.44'."""
        return f"{self.gain:+.2f}"

    def text(self) -> str:
        """The gap and against whom, as the model reads it: '-8.44 vs Josh Allen'."""
        return f"{self.cell()} {self.against}"


def _standing(state: Week, slot: LineupSlot) -> float | None:
    """What a starting slot holds this week, by `worth.value`; None where nobody in it can play: a hole."""
    if slot.player is None or not plays(state, slot.player):
        return None
    return value(state, slot.player)


def fit(state: Week, projection: Projection) -> Fit | None:
    """How he compares with your weakest starter he could replace, either way, both read by `worth.value`.

    The figure the to-do list weighs a pickup by, not this week's projection:
    a projection alone ranks the wire's kickers and defenses within a point
    of yours above every useful back, and misses a fill-in's role ending.
    Measured against the best lineup, so the bench has already made its
    moves; a starter there who cannot play this week is a hole, and a
    player who fills it gains his whole value.

    A shortfall is shown as plainly as a gain: in a deep league nobody on
    the wire outvalues a starter, and which of them comes closest is
    then the whole question — a column of blanks would answer none of it.
    None only where he could fill no slot at all.
    """
    eligible = [slot for slot in state.best if projection.position in eligible_positions(slot.slot)]
    if not eligible:
        return None
    standings = [(_standing(state, slot), slot) for slot in eligible]
    held, slot = min(standings, key=lambda pair: float("-inf") if pair[0] is None else pair[0])
    gain = round(value(state, projection) - (held or 0.0), 2)
    starter = slot.player
    if starter is None:
        return Fit(gain, f"at {slot.slot}, empty")
    if held is None:
        why = RULED_OUT_SHORT.get(starter.injury_status.upper(), "on bye")
        return Fit(gain, f"for {starter.name}, {why}")
    return Fit(gain, f"{'over' if gain > 0 else 'vs'} {starter.name}")


def short_at(state: Week) -> set[str]:
    """The streamed positions (`STREAMED`) where your best lineup has a hole this week: nobody, or nobody who can play."""
    return {slot.slot for slot in state.best if slot.slot in STREAMED and _standing(state, slot) is None}


def by_fit(state: Week, rows: Sequence[PlayerCard]) -> list[PlayerCard]:
    """The wire best fit first: the players who would most help this lineup lead, whatever their position.

    By projection alone a 1QB league's list opens on quarterbacks nobody can
    start. Two kinds follow everyone else, still best fit first among
    themselves, which is the order a position filter shows:

    - kickers and defenses, unless your lineup is short there this week
      (`short_at`): one on the wire is always within a point or two of
      yours, so it would lead a list it rarely changes;
    - a player out past this week (`long_term`): his worth is his season
      average, which no slot of yours gets — he is the IR list's question.

    Stable, so equal fits keep the projection's order, and a player who
    fits no slot goes last.
    """
    short = short_at(state)

    def key(row: PlayerCard) -> tuple[bool, float]:
        position = row.columns.get(POSITION_COLUMN, "")
        later = (position in STREAMED and position not in short) or long_term(row.columns.get(STATUS_COLUMN, ""))
        return later, -row.values.get(FIT_COLUMN, float("-inf"))

    return sorted(rows, key=key)


def _role(projection: Projection, state: Week) -> list[Stat]:
    """How he has been used, behind the projection; nothing before he has played."""
    stats = []
    if role := state.evidence.roles.get(projection.player_id):
        games = f"last {role.games}" if role.games > 1 else "last game"
        if role.snap_share is not None:
            stats.append(Stat(label=f"Snap share, {games}", value=share(role.snap_share), better="higher"))
        if role.position in evidence.CARRY_POSITIONS:
            stats.append(Stat(label="Carries a game", value=f"{role.carries:.1f}", better="higher"))
        if role.position in evidence.TARGET_POSITIONS:
            stats.append(Stat(label="Targets a game", value=f"{role.targets:.1f}", better="higher"))
            if role.target_share is not None:
                stats.append(Stat(label="Target share", value=share(role.target_share), better="higher"))
        stats.append(Stat(label=f"Points a game, {games}", value=f"{role.points:.2f}", better="higher"))
    return stats


def _opponent(projection: Projection | None, state: Week) -> Stat:
    """Who he plays and what that defense gives up, in one line: 'vs Miami Dolphins · 19th-most to QBs (17.51 a game)'.

    Toned by the matchup; a bye, a ruling or no fixtures yet reads as itself.
    """
    versus = _versus(
        projection, state.scheduled, "—", _team_name(projection.opponent, state.players) if projection else ""
    )
    matchup = state.evidence.matchup(projection) if projection else None
    if matchup is None:
        return Stat(label="Opponent", value=versus)
    return Stat(label="Opponent", value=f"{versus} · {matchup.allowed_to()}", tone=matchup.tone)


RECENT = f"(L{evidence.ROLE_GAMES})"
"""How a compared figure says it is his last few games, not his season: 'L3'."""

DASH = "—"


def compared(state: Week, moved: Sequence[tuple[MoveSide, Projection]], told: frozenset[str]) -> list[MovePlayer]:
    """The players a to-do item moves, each on the same rows, for reading side by side.

    The rows are his role over his last few games, his projection and his
    matchup — and his trend or his injury where any of them has one. A row
    no player has a figure for is left out, so a kicker swap is not a column
    of dashes. `told` are the players whose trend the item's own reason
    already states.
    """
    rows = [_figures(state, player, trend=player.player_id not in told) for _, player in moved]
    blank = {label for label in rows[0] if all(row[label].value == DASH for row in rows)} if rows else set()
    return [
        MovePlayer(
            side=side,
            player_id=player.player_id,
            name=player.name,
            position=player.position,
            team=player.team,
            held=standing(state, player.player_id),
            figures=[figure for label, figure in row.items() if label not in blank],
        )
        for (side, player), row in zip(moved, rows, strict=True)
    ]


def _figures(state: Week, player: Projection, trend: bool) -> dict[str, Stat]:
    """One player's rows, keyed by label, every row present: '—' where he has no figure for it."""
    role = state.evidence.roles.get(player.player_id)
    targets = role is not None and role.position in evidence.TARGET_POSITIONS
    grew = state.evidence.trends.get(player.player_id) if trend else None
    season = evidence.average(state.evidence, player.player_id)
    matchup = state.evidence.matchup(player)
    plays = (bool(player.opponent) or not state.scheduled) and not ruled_out(player.injury_status)
    rows = [
        Stat(label=f"{SNAP_COLUMN} {RECENT}", value=share(role.snap_share) if role else DASH),
        Stat(label=f"Tgt/g {RECENT}", value=f"{role.targets:.1f}" if role and targets else DASH),
        Stat(label=f"{TARGET_COLUMN} {RECENT}", value=share(role.target_share) if role and targets else DASH),
        Stat(label=f"Pts/g {RECENT}", value=f"{role.points:.2f}" if role else DASH),
        Stat(label="Pts/g (season)", value=f"{season:.2f}" if season is not None else DASH),
        # A bye or a ruling projects nought, which says nothing about him: the opponent row says why.
        Stat(label="Proj", value=f"{player.points:.2f}" if plays else DASH),
        Stat(
            label="Opp",
            value=_versus(player, state.scheduled, DASH) + (f", {ease(matchup)}" if matchup else ""),
            tone=matchup.tone if matchup else "neutral",
        ),
        Stat(label=TREND_COLUMN, value=grew.short() if grew else DASH, tone="good" if grew else "neutral"),
        Stat(
            label=STATUS_COLUMN,
            value=player.injury_status.lower() if listed(player.injury_status) else DASH,
            tone="warning" if listed(player.injury_status) else "neutral",
        ),
    ]
    return {row.label: row for row in rows}


def ease(matchup: evidence.Matchup) -> str:
    """'6th-easiest' where a defense gives up more than most to the position, '3rd-toughest' where less."""
    if matchup.rank == 1:
        return "easiest"
    if matchup.rank == matchup.defenses:
        return "toughest"
    if matchup.rank <= matchup.defenses // 2:
        return f"{ordinal(matchup.rank)}-easiest"
    return f"{ordinal(matchup.defenses - matchup.rank + 1)}-toughest"


def standing(state: Week, player_id: str) -> Held:
    """Where he stands to the manager: starting, benched, held in reserve, or nobody's."""
    if player_id in state.starter_ids:
        return "starter"
    if player_id in state.roster.reserve_ids:
        return "reserve"
    if player_id in state.roster.player_ids:
        return "bench"
    return "free agent"


def _team_name(team: str, players: Mapping[str, PlayerInfo]) -> str:
    """A club in full, at no extra request.

    Sleeper files every team defense in the player catalog under the club's
    own abbreviation, named the way somebody would say it — so the catalog
    this provider already holds is also the lookup from 'DET' to
    'Detroit Lions'. Falls back to the abbreviation, which is what a caller
    would have shown anyway.
    """
    meta = players.get(team)
    return meta.name if meta else team


def _versus(projection: Projection | None, scheduled: bool, unscheduled: str, opponent: str = "") -> str:
    """Who he plays, or why he plays nobody: ruled out, on bye, or no fixtures published yet.

    `opponent` is the club in full, where a caller has room for it — the
    drawer does, a table column does not. `unscheduled` is what a caller
    shows before any fixture is published.
    """
    if projection and projection.opponent:
        return f"vs {opponent or projection.opponent}"
    if projection and ruled_out(projection.injury_status):
        # Sleeper projects nobody it has ruled out, which reads as no game
        # though his club plays: say why he is not playing instead.
        return RULED_OUT_SHORT[projection.injury_status.upper()]
    return "no game" if scheduled else unscheduled


POSITION_RANK = "Position rank"

WEEK_TAB, GAME_LOG_TAB, SEASONS_TAB, HISTORY_TAB, NEWS_TAB = "This week", "Game log", "Seasons", "History", "News"
"""The drawer's tabs, in order: a group or table with no tab of its own sits in the first."""

NEWS_IN_DRAWER = 10
"""Headlines the drawer's news tab lists: the window's worth, which is rarely more."""


def detail(client: NFLSource, state: Week, player_id: str, schedule: Mapping[int, Sequence[Game]]) -> PlayerDetail:
    """One player: the week, what makes the projection, and who they are.

    Raises:
        PlayerNotFoundError: nothing in the catalog has that identifier.
    """
    meta = state.players.get(player_id)
    if meta is None:
        raise PlayerNotFoundError([player_id])

    projection = state.projections.get(player_id)
    scheduled = state.scheduled
    depth = meta.depth_chart_order
    injury = meta.injury_status
    body = meta.injury_body_part

    groups = [
        StatGroup(
            title=f"Week {state.week}",
            stats=[
                _opponent(projection, state),
                *(_role(projection, state) if projection else []),
                *(s.stat() for s in state.teammates.splits(meta)),
            ],
        )
    ]
    # ESPN's report where it has him, which says when he is back; Sleeper's
    # designation where it does not. Nothing for a healthy player.
    hurt = state.injuries.stats(player_id, lambda back: injuries.long_return(back, schedule)) or [
        *([Stat(label="Status", value=injury, tone="warning")] if injury else []),
        *([Stat(label=BODY_PART, value=body)] if body else []),
    ]
    if hurt:
        groups.append(StatGroup(title="Injury", stats=hurt))
    if projection and projection.stats:
        groups.append(StatGroup(title="Projected line", stats=_projection_lines(projection.stats, meta.position)))
    # Who he is matters least to a lineup call, so it goes last and on two lines.
    profile = [
        _experience(meta.years_exp),
        *([f"age {meta.age}"] if meta.age else []),
        *([f"#{meta.number}"] if meta.number else []),
        *([meta.college] if meta.college else []),
    ]
    groups.append(
        StatGroup(
            title="Player",
            stats=[
                Stat(label="Depth chart", value=f"{depth}" if depth else "unlisted"),
                Stat(label="Profile", value=" · ".join(profile)),
            ],
        )
    )

    groups.append(StatGroup(title="Draft", tab=HISTORY_TAB, stats=history.drafted(client, state, player_id)))
    if headlines := state.news.stats(player_id, limit=NEWS_IN_DRAWER):
        groups.append(StatGroup(title="News", tab=NEWS_TAB, stats=headlines))

    seasons = _season_table(client, player_id, state)
    log = _game_log(client, player_id, meta, state, schedule)
    tables = [t for t in (log and _recent_form(log, meta.position), log, seasons) if t]
    return PlayerDetail(
        player_id=player_id,
        name=meta.name,
        owner=history.owner(state, player_id),
        moves=history.moves(client, state, player_id),
        moves_tab=HISTORY_TAB,
        tabs=[WEEK_TAB, GAME_LOG_TAB, SEASONS_TAB, HISTORY_TAB, NEWS_TAB],
        position=meta.position,
        team=(team := meta.team),
        team_name=_team_name(team, state.players),
        headline=f"{projection.points:.2f}" if projection else "",
        headline_label=_headline_label(projection, scheduled, state.week),
        note=meta.injury_notes or injury,
        tables=tables,
        rank=_rank(meta.position, seasons),
        tone="warning" if injury else "neutral",
        groups=groups,
    )


def _game_log(
    client: NFLSource, player_id: str, meta: PlayerInfo, state: Week, schedule: Mapping[int, Sequence[Game]]
) -> StatTable | None:
    """This season game by game, oldest first, the way Sleeper's own page reads it.

    A season total hides the shape of one: three quiet weeks and a big one
    average the same as four steady ones, and only the games show which. So
    every week so far gets a row — a bye and a game he sat out included,
    since a gap is part of the record — with the points first and the box
    score behind them.

    This week's game gets a row only once he has a line in it: until then
    it has not been played, and a "did not play" would be a guess. So does a
    week whose lines would not load, for the same reason.
    """
    if not state.is_regular_season:
        return None
    weeks = list(range(1, state.week + 1))
    by_week = client.get_nfl_game_lines(
        state.season, weeks, FANTASY_POSITIONS, state.league.scoring_format, state.league.scoring_rules
    )
    # The same rule the averages are read by, so the log shows the games they count.
    games = {
        week: line
        for week, lines in by_week.values.items()
        for line in lines
        if line.player_id == player_id and evidence.took_the_field(line)
    }
    if not games:
        return None

    position = meta.position
    measures = GAME_LOG_COLUMNS.get(position, ())
    snaps = position in evidence.SNAP_POSITIONS
    columns = ["Pts", *(["Snaps"] if snaps else []), *(label for label, _ in measures)]
    team = meta.team

    rows: list[StatRow] = []
    for week in weeks:
        line = games.get(week)
        club = line.team if line else team
        fixture = by_club(schedule.get(week, [])).get(club)
        if line:
            values = [
                f"{line.stats.get(state.league.scoring_format, 0.0):.2f}",
                *([_snap_share(line)] if snaps else []),
                *(_box_score(line, keys) for _, keys in measures),
            ]
            rows.append(StatRow(label=f"W{week} {_fixture(club, line.opponent, fixture)}", values=values))
        elif week == state.week or week in by_week.failures or not schedule:
            # Not played yet, not loaded, or no schedule to tell a bye from a game missed.
            continue
        elif fixture is None:
            rows.append(StatRow(label=f"W{week} bye", values=[NOT_APPLICABLE] * len(columns)))
        else:
            opponent = fixture.away if fixture.home == club else fixture.home
            label = f"W{week} {_fixture(club, opponent, fixture)} · DNP"
            rows.append(StatRow(label=label, values=[NOT_APPLICABLE] * len(columns)))
    return StatTable(title="Game log", tab=GAME_LOG_TAB, columns=columns, rows=rows)


def _experience(years: int) -> str:
    """'rookie', '1 season', '7 seasons'."""
    return "rookie" if years == 0 else f"{years} season{'' if years == 1 else 's'}"


RECENT_WEEKS = 5
"""Weeks the drawer's first tab shows of the game log: enough to see a role change, few enough to read at a glance."""


def _recent_form(log: StatTable, position: str) -> StatTable:
    """The game log's last few weeks, cut to the columns that show a role — a snap share going 21%, 82%, 95%.

    What he scored, how much he played, and how often the ball came his way:
    targets for a pass catcher, carries for a runner, both for a back.
    """
    wanted = {
        "Pts",
        "Snaps",
        *(["Tgt"] if position in evidence.TARGET_POSITIONS else []),
        *(["Car"] if position in evidence.CARRY_POSITIONS else []),
    }
    rows = log.rows[-RECENT_WEEKS:]
    kept = [i for i, column in enumerate(log.columns) if column in wanted]
    return StatTable(
        title="Recent weeks",
        tab=WEEK_TAB,
        columns=[log.columns[i] for i in kept],
        rows=[StatRow(label=row.label, values=[row.values[i] for i in kept]) for row in rows],
    )


def _fixture(club: str, opponent: str, fixture: Game | None) -> str:
    """'vs GB' at home, '@ GB' away, as a box score writes it; bare where the schedule would not load."""
    if fixture is None:
        return opponent
    return f"vs {opponent}" if fixture.home == club else f"@ {opponent}"


def _snap_share(line: GameLine) -> str:
    share = evidence.snap_share(line)
    return f"{share:.0%}" if share is not None else "0%"


def _box_score(line: GameLine, keys: tuple[str, ...]) -> str:
    """One cell: a count, or 'made/tried'. A game played with none of it is a nought, which is an answer."""
    return "/".join(_count(line.stats.get(key, 0.0)) for key in keys)


def _count(value: float) -> str:
    """Whole where it is whole — a half sack is the one figure that is not."""
    return f"{value:.0f}" if value == int(value) else f"{value:.1f}"


def _season_table(client: NFLSource, player_id: str, state: Week) -> StatTable | None:
    """This season beside the two before it, read across rather than down.

    A projection is a guess; these are the seasons it is a guess about, and
    a page showing only the guess gives no way to weigh it. Stacked groups
    make you hold last year's yards in your head while scrolling to this
    year's; a row puts them side by side.

    Per game as well as total, because a total mostly measures availability
    — twelve games is not a worse week.

    Degrades to nothing rather than failing the page: a rookie has no
    history, and neither does a season Sleeper has not published.
    """
    scoring = state.league.scoring_format
    columns = [state.season, *_recent_seasons(state.season)]
    by_season: dict[str, SeasonTotals | None] = {}
    for season in columns:
        try:
            by_season[season] = client.get_season_stats(season, scoring, state.league.scoring_rules).get(player_id)
        except PlatformError as e:
            logger.warning(f"Skipping {season} totals: {e}")
            by_season[season] = None

    # A season nobody has played yet has no answers, and a column of
    # noughts claims it does.
    if not state.is_regular_season:
        by_season[state.season] = None
    if not any(stats and stats.games for stats in by_season.values()):
        return None

    def played(season: str) -> SeasonTotals | None:
        """The season's totals, or nothing where it was never played."""
        stats = by_season.get(season)
        return stats if stats and stats.games else None

    def row(label: str, of: Callable[[SeasonTotals], str], better: Better = "higher") -> StatRow:
        return StatRow(
            label=label,
            values=[of(stats) if (stats := played(c)) else NOT_APPLICABLE for c in columns],
            better=better,
        )

    rows = [
        row("Per game", lambda st: f"{st.per_game(scoring):.2f}"),
        row("Total", lambda st: f"{st.scored(scoring):.2f}"),
        row("Games", lambda st: str(st.games)),
        row(POSITION_RANK, lambda st: f"#{st.position_rank}" if st.position_rank else NOT_APPLICABLE, "lower"),
    ]
    # Only the splits somebody actually records: a running back has no
    # completion percentage, and a whole row of N/A is a row of nothing.
    for key, label in SPLIT_LABELS:
        if any(stats and stats.splits.get(key) for stats in by_season.values()):
            better: Better = "lower" if label in LOWER_IS_BETTER else "higher"
            rows.append(row(label, lambda st, k=key: _split_value(k, st.splits.get(k)), better))

    return StatTable(title="By season", tab=SEASONS_TAB, columns=columns, rows=rows)


def _rank(position: str, seasons: StatTable | None) -> str:
    """'WR12': this season's position rank, read off the by-season table's first column."""
    row = next((r for r in seasons.rows if r.label == POSITION_RANK), None) if seasons else None
    value = row.values[0] if row and row.values else NOT_APPLICABLE
    return "" if value == NOT_APPLICABLE else f"{position}{value.lstrip('#')}"


def _recent_seasons(season: str) -> list[str]:
    """The two seasons before this one, newest first.

    Two rather than a career: three years back is a different team, a
    different scheme and usually a different player.
    """
    try:
        year = int(season)
    except ValueError:
        return []
    return [str(year - 1), str(year - 2)]


def lineup_spot(slot: LineupSlot, scheduled: bool, live: Live | None = None) -> Spot:
    if slot.player is None:
        return Spot(
            slot=slot.slot,
            player="—",
            detail="empty",
            value="0.00",
            tone="warning",
            scoring="projected",
            projection="0.00",
        )
    return spot(slot.player, scheduled, slot=slot.slot, live=live, projected=slot.points)


def spot(
    projection: Projection,
    scheduled: bool,
    slot: str = "",
    live: Live | None = None,
    projected: float | None = None,
) -> Spot:
    """One row, showing what happened where the game has started.

    Once a club has kicked off, what its players actually scored is the
    number somebody is looking for, and the projection beside it is a guess
    about a question already being answered.
    """
    scored = live.scored(projection.player_id, projection.team) if live else None
    points = projection.points if projected is None else projected
    versus = _versus(projection, scheduled, "not scheduled yet")
    # The slot column already says "QB", so repeating it here reads as two
    # different facts about one row. A FLEX is the case worth keeping: the
    # place and the position genuinely differ, and which of them is filling
    # it is the whole question the row is asking.
    if projection.position == slot:
        detail = f"{projection.team} {versus}"
    else:
        detail = f"{projection.position} · {projection.team} {versus}"
    # Where his game is, while it is on: 6.5 in the first quarter and 6.5 in the fourth are different weeks.
    clock = live.clock.get(projection.team) if live and scored is not None else None
    return Spot(
        player_id=projection.player_id,
        slot=slot,
        player=projection.name,
        detail=f"{detail} · {clock}" if clock else detail,
        value=f"{scored:.2f} pts" if scored is not None else f"{points:.2f} proj",
        tone=_live_tone(scored) if scored is not None else _spot_tone(projection, scheduled),
        scoring=_scoring(projection.team, live) if scored is not None else "projected",
        scored=f"{scored:.2f}" if scored is not None else "",
        projection=f"{points:.2f}",
    )


def _scoring(team: str, live: Live | None) -> SpotScoring:
    """Live while his game is on, final once it is over. Where the scoreboard would not load, a game
    that has kicked off reads as live: saying a game is over that is not is the worse mistake."""
    return "final" if live is not None and team in live.final else "live"


def _slot(player_id: str, starters: set[str], reserve: Mapping[str, str]) -> str:
    if player_id in reserve:
        return reserve[player_id]
    return "START" if player_id in starters else "BN"


def sitting(rows: Sequence[Spot], roster: Team) -> tuple[list[Spot], list[Spot]]:
    """Everyone not starting, parted into the bench and the reserve slots, which cost no roster spot.

    A reserve row lines up with the bench's: the section says where he is, and
    an injured player's row already says "on IR". A taxi player's says nothing
    of the kind, so it says taxi. His zero is no warning, since a player held
    there was never going to play.
    """
    slots = held(roster)
    bench = [row for row in rows if row.player_id not in slots]
    reserve = [
        row.model_copy(
            update={"detail": row.detail if slots[row.player_id] == "IR" else f"{row.detail} · taxi", "tone": "neutral"}
        )
        for row in rows
        if row.player_id in slots
    ]
    return bench, reserve


def released(row: Spot, team: Team) -> Spot:
    """A lineup row marked where the team has since let him go: his points this week still count."""
    if row.player_id not in let_go(team):
        return row
    return row.model_copy(update={"detail": f"{row.detail} · {GONE}"})


GONE = "off roster"
"""Said of a starter dropped or traded after his game: he played for the team this week, and holds no spot on it."""


def _live_tone(scored: float) -> Tone:
    """A game already played answers its own question: a doubt about
    somebody who has been on the field is no longer a doubt."""
    if scored >= HAUL_POINTS:
        return "good"
    return "warning" if scored <= BLANK_POINTS else "neutral"


def _spot_tone(projection: Projection | None, scheduled: bool) -> Tone:
    """A player who will not play is a zero, not a small number.

    Unless nobody is playing, in which case the week simply has not been
    published and there is nothing to notice about any single player.
    """
    if projection is None:
        return "warning"
    if listed(projection.injury_status):
        return "warning"
    return "warning" if scheduled and not projection.opponent else "neutral"


def side_total(state: Week, live: Live) -> str:
    """The projection until the ball is rolling, then what is on the board beside it."""
    if not live.under_way:
        return f"{state.current_points:.2f} proj"
    scored = sum(live.scored(slot.player.player_id, slot.player.team) or 0 for slot in state.lineup if slot.player)
    return f"{scored:.2f} pts · {state.current_points:.2f} proj"


def _opponent_total(scored: float, starters: Sequence[Projection], live: Live) -> str:
    """The opponent's figure in the same words as yours: projected, then scored beside it."""
    projected = sum(p.points for p in starters)
    return f"{scored:.2f} pts · {projected:.2f} proj" if live.under_way else f"{projected:.2f} proj"


def opponent_side(state: Week, roster: Team, points: float, live: Live) -> Side:
    """The team you are playing, and what they are starting, in the same rows as your own.

    Walked in slot order rather than filtered out of `player_ids`, which
    Sleeper returns in no order at all. Both sides are read across, so an
    opponent listed QB-first against your kicker is not a comparison.
    `starter_ids` is positionally aligned with the league's starting slots,
    which is the only thing that makes the two columns rows.
    """
    scheduled = state.scheduled
    projected = projections_for(fielded(roster), state.projections, state.players)
    starting = set(roster.starter_ids)
    by_id = {p.player_id: p for p in projected}

    slots = state.league.starting_slots
    if len(roster.starter_ids) == len(slots):
        lineup = [
            released(spot(by_id[pid], scheduled, slot=slot, live=live), roster)
            if pid in by_id
            else Spot(
                slot=slot,
                player="—",
                detail="empty",
                value="0.00",
                tone="warning",
                scoring="projected",
                projection="0.00",
            )
            for slot, pid in zip(slots, roster.starter_ids, strict=True)
        ]
    else:
        # Off-length means the positions cannot be trusted, and a WR
        # labelled QB is worse than a row carrying no label at all.
        logger.warning(f"Roster {roster.roster_id} starts {len(roster.starter_ids)} into {len(slots)} slots")
        lineup = [released(spot(p, scheduled, live=live), roster) for p in projected if p.player_id in starting]
    bench, reserve = sitting(
        [
            spot(p, scheduled, live=live)
            for p in sorted(projected, key=lambda p: -p.points)
            if p.player_id not in starting
        ],
        roster,
    )
    return Side(
        name=state.team_name(roster),
        open_spots=open_spots(state.league, roster),
        detail=roster.record,
        points=_opponent_total(points, [by_id[pid] for pid in roster.starter_ids if pid in by_id], live),
        lineup=lineup,
        bench=bench,
        reserve=reserve,
    )
