"""How a football player reads on a page — the views of him: a table row, a lineup row, the drawer that opens on him.

Split from the provider because it is the one question asked of a player in
every view — the roster, the wire, both lineups, a player opened on his own —
and the provider is the place a week is gathered, not drawn.
"""

import logging
from collections.abc import Callable, Mapping
from typing import Any

from thefrontoffice.adapters.outbound.competitions.nfl import evidence
from thefrontoffice.adapters.outbound.competitions.nfl.lineup import LineupSlot, best_upgrade
from thefrontoffice.adapters.outbound.competitions.nfl.model import (
    Game,
    GameLine,
    NFLSource,
    PlayerInfo,
    Projection,
    SeasonTotals,
    Team,
)
from thefrontoffice.adapters.outbound.competitions.nfl.rules import FANTASY_POSITIONS, ruled_out
from thefrontoffice.adapters.outbound.competitions.nfl.week import (
    Live,
    Week,
    games_by_week,
    projection_for,
    zero_projection,
)
from thefrontoffice.domain.errors import PlatformError, PlayerNotFoundError
from thefrontoffice.domain.models import (
    NOT_APPLICABLE,
    PlayerCard,
    PlayerDetail,
    Side,
    Spot,
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
PROJECTION_LABELS: tuple[tuple[str, str], ...] = (
    ("pass_att", "Pass att"),
    ("pass_cmp", "Completions"),
    ("pass_yd", "Pass yards"),
    ("pass_td", "Pass TD"),
    ("pass_int", "Interceptions"),
    ("rush_att", "Carries"),
    ("rush_yd", "Rush yards"),
    ("rush_td", "Rush TD"),
    ("rec_tgt", "Targets"),
    ("rec", "Receptions"),
    ("rec_yd", "Rec yards"),
    ("rec_td", "Rec TD"),
    ("fum_lost", "Fumbles lost"),
)


def _projection_lines(stats: Mapping[str, float]) -> list[Stat]:
    """The projection broken out, skipping what does not apply.

    A receiver has no passing line, and printing a column of zeroes for one
    buries the three numbers that matter.
    """
    return [
        Stat(label=label, value=f"{stats[key]:.1f}".rstrip("0").rstrip(".") or "0")
        for key, label in PROJECTION_LABELS
        if stats.get(key)
    ]


# Sleeper serves portraits off its own CDN, keyed by the same player_id the
# rest of the API uses, with no key and no lookup.
PORTRAIT_URL = "https://sleepercdn.com/content/nfl/players/{player_id}.jpg"
# Lowercase or it 404s, and the abbreviation everywhere else in this file is
# upper.
TEAM_LOGO_URL = "https://sleepercdn.com/images/team_logos/nfl/{team}.png"

# Where the moves are actually made. Sleeper routes on these — an invented
# path 404s — so they are addresses rather than guesses.
LEAGUE_URL = "https://sleeper.com/leagues/{league_id}"
PLAYER_URL = "https://sleeper.com/players/nfl/{player_id}"

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

SCOREBOARD_STATUS = {"pre": "pre_game", "in": "in_game", "post": "complete"}
"""ESPN's game states in Sleeper's words, which is what the rest of the week reads."""


def lineup_order(state: Week, roster: Team) -> list[str]:
    """Read as a lineup: the starters slot by slot, then the bench best projected first, then reserve."""
    starters = [pid for pid in roster.starter_ids if pid in roster.player_ids]
    bench = [pid for pid in roster.player_ids if pid not in starters and pid not in roster.reserve_ids]
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
    return str(meta.get("position") or "") in FANTASY_POSITIONS and str(meta.get("team") or "FA") != "FA"


def cards(
    state: Week,
    player_ids: list[str],
    starters: set[str],
    owned_column: bool = True,
    fits: bool = False,
) -> list[PlayerCard]:
    """One table shape for every list of players this sport shows.

    `fits` adds what each would add to your lineup — for the wire, where
    "how good is he" is only half the question and "how good is he for
    me" is the other.
    """
    scheduled = any(p.opponent for p in state.projected)

    rows = []
    for player_id in player_ids:
        meta = state.players.get(player_id)
        if not meta:
            continue
        projection = state.projections.get(player_id)
        injury = str(meta.get("injury_status") or "")
        depth = int(meta.get("depth_chart_order") or 0)
        fitted = fit(state, projection) if fits and projection else None
        trend = state.evidence.trends.get(player_id) if fits else None
        rows.append(
            PlayerCard(
                player_id=player_id,
                tone="warning" if injury else "neutral",
                values={
                    **({"Fits": fitted[0]} if fitted else {}),
                    **({"Usage": trend.rise} if trend else {}),
                    "Proj": projection.points if projection else 0.0,
                    "Depth": float(depth) if depth else 0.0,
                    "Exp": float(meta.get("years_exp") or 0),
                },
                columns={
                    "Player": str(meta.get("name") or player_id),
                    "Pos": str(meta.get("position") or ""),
                    "Team": str(meta.get("team") or "FA"),
                    # A free-agent list has no lineup to be in, so the
                    # column would read "BN" down its whole length.
                    **({"Slot": "START" if player_id in starters else "BN"} if owned_column else {}),
                    "Proj": f"{projection.points:.1f}" if projection else "0.0",
                    **({"Fits": fitted[1] if fitted else "—"} if fits else {}),
                    # Whose role just grew: the pickups a projection has
                    # not caught up with yet. Sorts by the size of the jump.
                    **({"Usage": trend.short() if trend else "—"} if fits else {}),
                    # Through the zero-point fallback, which carries his ruling
                    # where Sleeper has published no projection for him.
                    "Opponent": _opponent_label(projection or zero_projection(player_id, meta), scheduled),
                    "Depth": str(depth) if depth else "—",
                    "Exp": f"{int(meta.get('years_exp') or 0)}y",
                    "Status": injury,
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
        return f"Week {week} projections are not published yet"
    return f"Not projected to feature in week {week}"


def fit(state: Week, projection: Projection) -> tuple[float, str] | None:
    """How he compares with your weakest starter he could replace, either way.

    A shortfall is shown as plainly as a gain: in a deep league nobody on
    the wire outprojects a starter, and which of them comes closest is
    then the whole question — a column of blanks would answer none of it.
    None only where he could fill no slot at all.
    """
    upgrade = best_upgrade(state.lineup, projection)
    if upgrade is None:
        return None
    gain, slot = upgrade
    if slot.player is None:
        return gain, f"+{gain:.1f} at {slot.slot}, empty"
    return (gain, f"+{gain:.1f} over {slot.player.name}") if gain > 0 else (gain, f"{gain:.1f} vs {slot.player.name}")


def _role_and_matchup(projection: Projection, state: Week) -> StatGroup | None:
    """What sits behind the projection: the defense he faces, and how he has been used."""
    stats = []
    if matchup := state.evidence.matchup(projection):
        stats.append(Stat(label="Matchup", value=matchup.describe(), tone=matchup.tone))
    if role := state.evidence.roles.get(projection.player_id):
        games = f"last {role.games}" if role.games > 1 else "last game"
        if role.snap_share is not None:
            stats.append(Stat(label=f"Snap share, {games}", value=f"{role.snap_share:.0%}"))
        if role.position in evidence.CARRY_POSITIONS:
            stats.append(Stat(label="Carries a game", value=f"{role.carries:.1f}"))
        if role.position in evidence.TARGET_POSITIONS:
            stats.append(Stat(label="Targets a game", value=f"{role.targets:.1f}"))
            if role.target_share is not None:
                stats.append(Stat(label="Target share", value=f"{role.target_share:.0%}"))
        stats.append(Stat(label=f"Points a game, {games}", value=f"{role.points:.1f}"))
    return StatGroup(title="Role and matchup", stats=stats) if stats else None


def _team_name(team: str, players: Mapping[str, PlayerInfo]) -> str:
    """A club in full, at no extra request.

    Sleeper files every team defense in the player catalog under the club's
    own abbreviation, named the way somebody would say it — so the catalog
    this provider already holds is also the lookup from 'DET' to
    'Detroit Lions'. Falls back to the abbreviation, which is what a caller
    would have shown anyway.
    """
    meta = players.get(team)
    return str(meta.get("name") or team) if meta else team


def _opponent_label(
    projection: Projection | None, scheduled: bool, players: Mapping[str, PlayerInfo] | None = None
) -> str:
    """Who they play. In full where a caller has room for it — the drawer
    does, a table column does not."""
    if projection and projection.opponent:
        opponent = _team_name(projection.opponent, players) if players else projection.opponent
        return f"vs {opponent}"
    if projection and ruled_out(projection.injury_status):
        # Sleeper projects nobody it has ruled out; his club still plays.
        return projection.injury_status.lower()
    return "no game" if scheduled else "—"


def detail(client: NFLSource, state: Week, player_id: str) -> PlayerDetail:
    """One player: the week, what makes the projection, and who they are.

    Raises:
        PlayerNotFoundError: nothing in the catalog has that identifier.
    """
    meta = state.players.get(player_id)
    if meta is None:
        raise PlayerNotFoundError([player_id])

    projection = state.projections.get(player_id)
    scheduled = any(p.opponent for p in state.projected)
    depth = int(meta.get("depth_chart_order") or 0)
    injury = str(meta.get("injury_status") or "")
    body = str(meta.get("injury_body_part") or "")

    groups = [
        StatGroup(
            title=f"Week {state.week}",
            stats=[
                Stat(label="Opponent", value=_opponent_label(projection, scheduled, state.players)),
                Stat(label="Projected", value=f"{projection.points:.1f}" if projection else "—"),
                Stat(
                    label="Status",
                    value=injury or "active",
                    tone="warning" if injury else "good",
                ),
                *([Stat(label="Injury", value=body)] if body else []),
            ],
        )
    ]
    if projection and projection.stats:
        groups.append(StatGroup(title="Projected line", stats=_projection_lines(projection.stats)))
    if projection and (context := _role_and_matchup(projection, state)):
        groups.append(context)
    if headlines := state.news.stats(player_id):
        groups.append(StatGroup(title="Latest news", stats=headlines))
    groups.append(
        StatGroup(
            title="Player",
            stats=[
                Stat(label="Depth chart", value=f"{depth}" if depth else "unlisted"),
                Stat(label="Experience", value=f"{int(meta.get('years_exp') or 0)} seasons"),
                *([Stat(label="Age", value=str(meta["age"]))] if meta.get("age") else []),
                *([Stat(label="Number", value=f"#{meta['number']}")] if meta.get("number") else []),
                *([Stat(label="College", value=str(meta["college"]))] if meta.get("college") else []),
            ],
        )
    )

    return PlayerDetail(
        player_id=player_id,
        name=str(meta.get("name") or player_id),
        position=str(meta.get("position") or ""),
        team=(team := str(meta.get("team") or "FA")),
        team_name=_team_name(team, state.players),
        team_logo_url=TEAM_LOGO_URL.format(team=team.lower()) if team != "FA" else "",
        headline=f"{projection.points:.1f}" if projection else "",
        headline_label=_headline_label(projection, scheduled, state.week),
        note=str(meta.get("injury_notes") or injury),
        # A team defense has no headshot — the CDN 404s on its abbreviation —
        # and the crest beside the club name already says who it is.
        image_url="" if meta.get("position") == "DEF" else PORTRAIT_URL.format(player_id=player_id),
        url=PLAYER_URL.format(player_id=player_id),
        tables=[
            table
            for table in (_game_log(client, player_id, meta, state), _season_table(client, player_id, state))
            if table
        ],
        tone="warning" if injury else "neutral",
        groups=groups,
    )


def _game_log(client: NFLSource, player_id: str, meta: PlayerInfo, state: Week) -> StatTable | None:
    """This season game by game, oldest first, the way Sleeper's own page reads it.

    A season total hides the shape of one: three quiet weeks and a big one
    average the same as four steady ones, and only the games show which. So
    every week so far gets a row — a bye and a game he sat out included,
    since a gap is part of the record — with the points first and the box
    score behind them.

    This week's game gets a row only once he has a line in it: until then
    it has not been played, and a "did not play" would be a guess.

    Degrades to nothing rather than failing the page, like the seasons.
    """
    if not state.is_regular_season:
        return None
    weeks = list(range(1, state.week + 1))
    try:
        lines = [line for line in client.get_nfl_game_lines(state.season, weeks) if line.player_id == player_id]
    except PlatformError as e:
        logger.warning(f"Skipping the game log: {e}")
        return None
    games = {line.week: line for line in lines if line.stats.get("gp") or line.stats.get("off_snp")}
    if not games:
        return None

    position = str(meta.get("position") or "")
    measures = GAME_LOG_COLUMNS.get(position, ())
    snaps = position in evidence.SNAP_POSITIONS
    columns = ["Pts", *(["Snaps"] if snaps else []), *(label for label, _ in measures)]
    schedule = games_by_week(client, state.season)
    team = str(meta.get("team") or "")

    rows: list[StatRow] = []
    for week in weeks:
        line = games.get(week)
        club = line.team if line else team
        fixture = next((g for g in schedule.get(week, []) if club in (g.home, g.away)), None)
        if line:
            values = [
                f"{line.stats.get(state.league.scoring_format, 0.0):.1f}",
                *([_snap_share(line)] if snaps else []),
                *(_box_score(line, keys) for _, keys in measures),
            ]
            rows.append(StatRow(label=f"W{week} {_fixture(club, line.opponent, fixture)}", values=values))
        elif week == state.week or not schedule:
            # Not played yet, or no schedule to tell a bye from a game missed.
            continue
        elif fixture is None:
            rows.append(StatRow(label=f"W{week} bye", values=[NOT_APPLICABLE] * len(columns)))
        else:
            opponent = fixture.away if fixture.home == club else fixture.home
            label = f"W{week} {_fixture(club, opponent, fixture)} · DNP"
            rows.append(StatRow(label=label, values=[NOT_APPLICABLE] * len(columns)))
    return StatTable(title="Game log", columns=columns, rows=rows)


def _fixture(club: str, opponent: str, fixture: Game | None) -> str:
    """'vs GB' at home, '@ GB' away, as a box score writes it; bare where the schedule would not load."""
    if fixture is None:
        return opponent
    return f"vs {opponent}" if fixture.home == club else f"@ {opponent}"


def _snap_share(line: GameLine) -> str:
    team = line.stats.get("tm_off_snp", 0.0)
    return f"{line.stats.get('off_snp', 0.0) / team:.0%}" if team else "0%"


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
            by_season[season] = client.get_season_stats(season).get(player_id)
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

    def row(label: str, of: Callable[[SeasonTotals], str]) -> StatRow:
        return StatRow(
            label=label,
            values=[of(stats) if (stats := played(c)) else NOT_APPLICABLE for c in columns],
        )

    rows = [
        row("Per game", lambda st: f"{st.per_game(scoring):.1f}"),
        row("Total", lambda st: f"{st.scored(scoring):.1f}"),
        row("Games", lambda st: str(st.games)),
        row("Position rank", lambda st: f"#{st.position_rank}" if st.position_rank else NOT_APPLICABLE),
    ]
    # Only the splits somebody actually records: a running back has no
    # completion percentage, and a whole row of N/A is a row of nothing.
    for key, label in SPLIT_LABELS:
        if any(stats and stats.splits.get(key) for stats in by_season.values()):
            rows.append(row(label, lambda st, k=key: _split_value(k, st.splits.get(k))))

    return StatTable(title="By season", columns=columns, rows=rows)


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
        return Spot(slot=slot.slot, player="—", detail="empty", value="0.0", tone="warning")
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
    detail = _spot_detail(projection, scheduled, slot)
    # Where his game is, while it is on: 6.5 in the first quarter and 6.5 in the fourth are different weeks.
    clock = live.clock.get(projection.team) if live and scored is not None else None
    return Spot(
        player_id=projection.player_id,
        slot=slot,
        player=projection.name,
        detail=f"{detail} · {clock}" if clock else detail,
        value=f"{scored:.1f} pts" if scored is not None else f"{points:.1f}",
        tone=_live_tone(scored) if scored is not None else _spot_tone(projection, scheduled),
    )


def reserved(row: Spot, roster: Team) -> Spot:
    """A bench row marked where he is in an injured-reserve or taxi slot, which costs no bench spot."""
    if row.player_id not in roster.reserve_ids:
        return row
    return row.model_copy(update={"detail": f"{row.detail} · reserve slot"})


def _live_tone(scored: float) -> Tone:
    """A game already played answers its own question: a doubt about
    somebody who has been on the field is no longer a doubt."""
    if scored >= HAUL_POINTS:
        return "good"
    return "warning" if scored <= BLANK_POINTS else "neutral"


def _spot_detail(projection: Projection, scheduled: bool, slot: str = "") -> str:
    if projection.opponent:
        opponent = f"vs {projection.opponent}"
    elif ruled_out(projection.injury_status):
        # Sleeper projects nobody it has ruled out, which reads as no game
        # though his club plays: say why he is not playing instead.
        opponent = projection.injury_status.lower()
    else:
        opponent = "no game" if scheduled else "not scheduled yet"
    # The slot column already says "QB", so repeating it here reads as two
    # different facts about one row. A FLEX is the case worth keeping: the
    # place and the position genuinely differ, and which of them is filling
    # it is the whole question the row is asking.
    if projection.position == slot:
        return f"{projection.team} {opponent}"
    return f"{projection.position} · {projection.team} {opponent}"


def _spot_tone(projection: Projection | None, scheduled: bool) -> Tone:
    """A player who will not play is a zero, not a small number.

    Unless nobody is playing, in which case the week simply has not been
    published and there is nothing to notice about any single player.
    """
    if projection is None:
        return "warning"
    if projection.is_questionable:
        return "warning"
    return "warning" if scheduled and not projection.opponent else "neutral"


def side_total(state: Week, live: Live) -> str:
    """The projection until the ball is rolling, then what is on the board."""
    if not live.under_way:
        return f"{state.current_points:.1f} proj"
    scored = sum(live.scored(slot.player.player_id, slot.player.team) or 0 for slot in state.lineup if slot.player)
    return f"{scored:.1f} pts"


def opponent_side(state: Week, roster: Team, entry: dict[str, Any], name: str, live: Live) -> Side:
    """The team you are playing, and what they are starting, in the same rows as your own.

    Walked in slot order rather than filtered out of `player_ids`, which
    Sleeper returns in no order at all. Both sides are read across, so an
    opponent listed QB-first against your kicker is not a comparison.
    `starter_ids` is positionally aligned with the league's starting slots,
    which is the only thing that makes the two columns rows.
    """
    scheduled = state.scheduled
    projected = [p for p in (projection_for(pid, state.projections, state.players) for pid in roster.player_ids) if p]
    starting = set(roster.starter_ids)
    by_id = {p.player_id: p for p in projected}

    slots = state.league.starting_slots
    if len(roster.starter_ids) == len(slots):
        lineup = [
            spot(by_id[pid], scheduled, slot=slot, live=live)
            if pid in by_id
            else Spot(slot=slot, player="—", detail="empty", value="0.0", tone="warning")
            for slot, pid in zip(slots, roster.starter_ids, strict=True)
        ]
    else:
        # Off-length means the positions cannot be trusted, and a WR
        # labelled QB is worse than a row carrying no label at all.
        logger.warning(f"Roster {roster.roster_id} starts {len(roster.starter_ids)} into {len(slots)} slots")
        lineup = [spot(p, scheduled, live=live) for p in projected if p.player_id in starting]
    return Side(
        name=name,
        detail=roster.record,
        points=f"{float(entry.get('points') or 0):.1f}",
        lineup=lineup,
        bench=[spot(p, scheduled, live=live) for p in projected if p.player_id not in starting],
    )
