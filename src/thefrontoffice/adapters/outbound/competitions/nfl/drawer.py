"""The drawer that opens on a football player: his week, the projection behind it, his games and his seasons.

Split from `views.py`, which draws him as a row, because the drawer is the
one view that reads past the week: his game log and seasons, fetched only
when somebody opens him.
"""

import logging
from collections.abc import Callable, Mapping, Sequence

from thefrontoffice.adapters.outbound.competitions.careers import experience, recent_seasons
from thefrontoffice.adapters.outbound.competitions.injuries import BODY_PART
from thefrontoffice.adapters.outbound.competitions.nfl import evidence, history, injuries
from thefrontoffice.adapters.outbound.competitions.nfl.model import (
    Game,
    GameLine,
    NFLSource,
    PlayerInfo,
    Projection,
    SeasonTotals,
    by_club,
)
from thefrontoffice.adapters.outbound.competitions.nfl.rules import FANTASY_POSITIONS
from thefrontoffice.adapters.outbound.competitions.nfl.views import facing, share, team_name
from thefrontoffice.adapters.outbound.competitions.nfl.week import Week
from thefrontoffice.domain.errors import PlatformError, PlayerNotFoundError
from thefrontoffice.domain.models import (
    NOT_APPLICABLE,
    Better,
    PlayerDetail,
    Stat,
    StatGroup,
    StatRow,
    StatTable,
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
    versus = facing(
        projection, state.scheduled, "—", team_name(projection.opponent, state.players) if projection else ""
    )
    matchup = state.evidence.matchup(projection) if projection else None
    if matchup is None:
        return Stat(label="Opponent", value=versus)
    return Stat(label="Opponent", value=f"{versus} · {matchup.allowed_to()}", tone=matchup.tone)


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
        experience(meta.years_exp),
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
        team_name=team_name(team, state.players),
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
    columns = [state.season, *recent_seasons(state.season)]
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
