"""How a football player reads on a page — the views of him: a table row, a lineup row. The drawer is `drawer.py`.

Split from the provider because it is the one question asked of a player in
every view — the roster, the wire, both lineups, a player opened on his own —
and the provider is the place a week is gathered, not drawn.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from thefrontoffice.adapters.outbound.competitions.matchups import RECENT_GAMES, Matchup, matchup_factor
from thefrontoffice.adapters.outbound.competitions.nfl import evidence, injuries
from thefrontoffice.adapters.outbound.competitions.nfl.lineup import LineupSlot, eligible_positions
from thefrontoffice.adapters.outbound.competitions.nfl.model import (
    FREE_AGENT,
    Game,
    PlayerInfo,
    Projection,
    Team,
    active,
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
from thefrontoffice.adapters.outbound.competitions.nfl.slump import called, slump
from thefrontoffice.adapters.outbound.competitions.nfl.week import (
    Live,
    Week,
    projections_for,
    zero_projection,
)
from thefrontoffice.adapters.outbound.competitions.nfl.worth import plays, weekly
from thefrontoffice.adapters.outbound.competitions.places import ordinal
from thefrontoffice.adapters.outbound.competitions.teammates import WITHOUT_COLUMN
from thefrontoffice.domain.models import (
    FIT_COLUMN,
    OPPONENT_COLUMN,
    PLAYER_COLUMN,
    POSITION_COLUMN,
    SLOT_COLUMN,
    STATUS_COLUMN,
    Held,
    MovePlayer,
    MoveSide,
    PlayerCard,
    Side,
    Spot,
    SpotScoring,
    Stat,
    Tone,
)

logger = logging.getLogger(__name__)


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
        sunk = slump(state, projection) if not wire and player_id in starters and projection else None
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
        facing_now = projection or zero_projection(player_id, meta)
        matchup = state.evidence.matchup(facing_now)
        versus = opposing(facing(facing_now, state.scheduled, "—"), matchup)
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
                OPPONENT_COLUMN: versus,
                STATUS_COLUMN: injury,
                "Depth": depth_cell,
            }
            if wire
            else {
                **identity,
                SLOT_COLUMN: _slot(player_id, starters, reserve),
                "Proj": proj,
                **ros,
                OPPONENT_COLUMN: versus,
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
                    # His projection is the figure the slump says is wrong.
                    **({"Proj": f"{sunk.label}: {sunk.short()}"} if sunk else {}),
                    **({OPPONENT_COLUMN: matchup.allowed_to()} if matchup else {}),
                },
                tones={OPPONENT_COLUMN: matchup.tone} if matchup and matchup.tone != "neutral" else {},
                columns=columns,
                values={
                    **({FIT_COLUMN: fitted.gain} if fitted else {}),
                    **({TREND_COLUMN: trend.rise} if trend else {}),
                    **({SNAP_COLUMN: snaps} if snaps is not None else {}),
                    **({TARGET_COLUMN: targets} if targets is not None else {}),
                    **({ROS_COLUMN: rest} if rest is not None else {}),
                    "Proj": projection.points if projection else 0.0,
                    "Depth": float(depth) if depth else 0.0,
                    # Softest first when sorted high to low; a bye or no record yet has none, so sorts last.
                    **({OPPONENT_COLUMN: matchup_factor(matchup)} if matchup else {}),
                },
            )
        )
    return rows


@dataclass(frozen=True)
class Fit:
    """How a free agent compares with the weakest starter he could replace: the gap, and against whom."""

    gain: float
    """His `weekly` value less that starter's; his whole value where the slot is empty, or its starter cannot play this week."""
    against: str
    """Who he is measured against, 'over Josh Allen' or 'vs Josh Allen', or the slot he would fill, 'at FLEX, empty', 'for Josh Allen, out'."""

    def cell(self) -> str:
        """The gap alone, as a column has room for: '+2.10', '-8.44'."""
        return f"{self.gain:+.2f}"

    def text(self) -> str:
        """The gap and against whom, as the model reads it: '-8.44 vs Josh Allen'."""
        return f"{self.cell()} {self.against}"


def _standing(state: Week, slot: LineupSlot) -> float | None:
    """What a starting slot holds this week, by `weekly`; None where nobody in it can play: a hole."""
    if slot.player is None or not plays(state, slot.player):
        return None
    return weekly(state, slot.player)


def fit(state: Week, projection: Projection) -> Fit | None:
    """How he compares with your weakest starter he could replace, either way, both read by `weekly`.

    The figure the to-do list weighs a pickup by, not this week's projection:
    a projection alone ranks the wire's kickers and defenses within a point
    of yours above every useful back, and misses a fill-in's role ending.
    Measured against the best lineup, so the bench has already made its
    moves; a starter there who cannot play this week is a hole, and a
    player who fills it gains his whole value.

    A shortfall is shown as plainly as a gain: in a deep league nobody on
    the wire outvalues a starter, and which of them comes closest is
    then the whole question — a column of blanks would answer none of it.
    Against a slumping starter both are read by the form call instead (`slump.called`).
    None only where he could fill no slot at all.
    """
    eligible = [slot for slot in state.best if projection.position in eligible_positions(slot.slot)]
    if not eligible:
        return None
    standings = [(_standing(state, slot), slot) for slot in eligible]
    held, slot = min(standings, key=lambda pair: float("-inf") if pair[0] is None else pair[0])
    gain = round(weekly(state, projection) - (held or 0.0), 2)
    starter = slot.player
    if starter is None:
        return Fit(gain, f"at {slot.slot}, empty")
    if held is None:
        why = RULED_OUT_SHORT.get(starter.injury_status.upper(), "on bye")
        return Fit(gain, f"for {starter.name}, {why}")
    if (formed := _on_form(state, projection, starter)) is not None:
        return Fit(formed, f"{'over' if formed > 0 else 'vs'} {starter.name}, {ON_FORM}")
    return Fit(gain, f"{'over' if gain > 0 else 'vs'} {starter.name}")


ON_FORM = "on form"
"""How a fit says it was read by the form call against a slumping starter, not by `worth.value`."""


def _on_form(state: Week, projection: Projection, starter: Projection) -> float | None:
    """The gap by `slump.called` where the starter he is measured against is slumping; None otherwise,
    or where either has too few games for a form call."""
    if slump(state, starter) is None:
        return None
    mine, theirs = called(state, projection), called(state, starter)
    return None if mine is None or theirs is None else round(mine - theirs, 2)


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
            value=opposing(facing(player, state.scheduled, DASH), matchup),
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


def opposing(versus: str, matchup: Matchup | None) -> str:
    """Who he plays and how easy that defense is: 'vs SF, 15th-easiest · 4th-easiest L5'."""
    return f"{versus}, {ease(matchup)}" if matchup else versus


def ease(matchup: Matchup) -> str:
    """'6th-easiest' where a defense gives up more than most to the position, '3rd-toughest' where less, then its
    recent rank where it has one: '13th-toughest · 4th-easiest L5'."""
    season = _ease(matchup.rank, matchup.defenses)
    if matchup.recent is None:
        return season
    return f"{season} · {_ease(matchup.recent.rank, matchup.defenses)} L{RECENT_GAMES}"


def _ease(rank: int, defenses: int) -> str:
    if rank == 1:
        return "easiest"
    if rank == defenses:
        return "toughest"
    if rank <= defenses // 2:
        return f"{ordinal(rank)}-easiest"
    return f"{ordinal(defenses - rank + 1)}-toughest"


def standing(state: Week, player_id: str) -> Held:
    """Where he stands to the manager: starting, benched, held in reserve, or nobody's."""
    if player_id in state.starter_ids:
        return "starter"
    if player_id in state.roster.reserve_ids:
        return "reserve"
    if player_id in state.roster.player_ids:
        return "bench"
    return "free agent"


def team_name(team: str, players: Mapping[str, PlayerInfo]) -> str:
    """A club in full, at no extra request.

    Sleeper files every team defense in the player catalog under the club's
    own abbreviation, named the way somebody would say it — so the catalog
    this provider already holds is also the lookup from 'DET' to
    'Detroit Lions'. Falls back to the abbreviation, which is what a caller
    would have shown anyway.
    """
    meta = players.get(team)
    return meta.name if meta else team


def facing(projection: Projection | None, scheduled: bool, unscheduled: str, opponent: str = "") -> str:
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
    versus = facing(projection, scheduled, "not scheduled yet")
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
        kickoff=live.kickoff.get(projection.team) if live and scored is None else None,
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
        record=roster.record,
        points=_opponent_total(points, [by_id[pid] for pid in roster.starter_ids if pid in by_id], live),
        lineup=lineup,
        bench=bench,
        reserve=reserve,
    )
