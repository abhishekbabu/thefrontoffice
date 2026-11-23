"""The drawer that opens on a basketball player: his week, his averages, his games, and the tabs read only when opened.

Split from `views.py`, which draws him as a row, because the drawer reads what
no row needs — Sleeper's game log and seasons, and the tabs that cost a
request each — and the provider is the place those are gathered, not drawn.
"""

import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from thefrontoffice.adapters.outbound.competitions.careers import experience
from thefrontoffice.adapters.outbound.competitions.dates import WEEKDAYS, day_month, parse_day
from thefrontoffice.adapters.outbound.competitions.injuries import designation
from thefrontoffice.adapters.outbound.competitions.matchups import Matchup
from thefrontoffice.adapters.outbound.competitions.nba.form import FORM_WEEKS
from thefrontoffice.adapters.outbound.competitions.nba.model import LeagueCategory, Player, PrintedLine
from thefrontoffice.adapters.outbound.competitions.nba.projections import ProjectedTotals
from thefrontoffice.adapters.outbound.competitions.nba.rules import (
    ASSISTS,
    BLOCKS,
    CATEGORIES,
    FIELD_GOALS,
    FREE_THROWS,
    POINTS,
    REBOUNDS,
    STEALS,
    THREES,
    TURNOVERS,
    Category,
    clears,
    fantasy_points,
    line,
    status_word,
)
from thefrontoffice.adapters.outbound.competitions.nba.teammates import Teammate
from thefrontoffice.adapters.outbound.competitions.nba.views import (
    FANTASY_POINTS,
    GAMES_LEFT,
    LAST_MONTH,
    POINTS_HINT,
    SEASON,
    VALUE,
    VALUE_HINT,
    WEEK,
    WINDOW,
    averages,
    number,
    per_game,
)
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading, Valuer
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog, NBASeason, PlayerMeta, ScheduledGame
from thefrontoffice.domain.models import (
    NOT_APPLICABLE,
    ActivityRow,
    Better,
    PlayerDetail,
    Stat,
    StatGroup,
    StatRow,
    StatTable,
)

WEEK_TAB, GAME_LOG_TAB, SEASONS_TAB, HISTORY_TAB, NEWS_TAB = "This week", "Game log", "Seasons", "History", "News"
"""The drawer's tabs, in order: a group or table with no tab of its own sits in the first."""

DEFERRED = (SEASONS_TAB, HISTORY_TAB, NEWS_TAB)
"""The tabs read only when opened (`PlayerDetail.deferred`): each costs a request the first tab does not need."""

THIS_WEEK = WEEK_TAB

RECENT = 5
"""Games the first tab shows of the log, and the run his minutes and usage are read over beside the window."""

NEWS_IN_DRAWER = 10
"""Headlines the news tab lists: the window's worth, which is rarely more."""

USAGE_HINT = (
    f"Plays that end with him a game — FGA + 0.44×FTA + TO — over his last {RECENT} games, then every game "
    f"of the last {FORM_WEEKS} weeks."
)
MINUTES_HINT = f"Minutes a game over his last {RECENT} games, then every game of the last {FORM_WEEKS} weeks."


@dataclass(frozen=True)
class DrawerWeek:
    """His matchup week as the drawer reads it."""

    left: str
    """His games left (`counted`); empty where the schedule would not load."""

    fixtures: Sequence[ScheduledGame] = ()
    """His club's games still to play in the week, in date order."""

    reading: Reading | None = None
    """His week weighed (`worth.read`); None where it could not be."""

    projected: ProjectedTotals | None = None
    """Sleeper's projection for his games this week; None where it has none for him."""

    matchup: Matchup | None = None
    """What his next opponent gives up to his position; None without a next game or a position."""


@dataclass(frozen=True)
class Drawer:
    """Everything the drawer's first two tabs show of one player, gathered by the provider."""

    player: Player
    season: PrintedLine | None
    """Yahoo's averages this season; None where it has none."""

    recent: PrintedLine | None
    """Yahoo's averages over the last month; None where it has none."""

    scored: Sequence[LeagueCategory]
    weights: Mapping[str, float] | None
    """A points league's weights by Yahoo stat id; None in a category league."""

    reported: list[Stat] = field(default_factory=list)
    """ESPN's report on him; empty where it has none."""

    splits: Sequence[Teammate] = ()
    week: DrawerWeek | None = None
    """None without a matchup this week."""

    games: Sequence[NBAGameLog] = ()
    """His games in the window, newest first: the game log."""

    venues: Mapping[str, ScheduledGame] = field(default_factory=dict)
    """His club's game on each date of the log, by ISO date: home or away."""

    value: Valuer | None = None
    """What a game is worth in the league's scoring, for each game of the log; None where it would not scale."""

    profile: PlayerMeta | None = None
    """Who Sleeper says he is; None where it cannot place him."""

    priority: int = 0
    """Your place in the league's waiver order, said beside the day he clears them; 0 where unknown."""

    @property
    def by_points(self) -> bool:
        return self.weights is not None


def detail(drawer: Drawer) -> PlayerDetail:
    """The drawer on one player: his week, his averages, his games, and the tabs read only when opened.

    The first tab is his week — games left and against whom, what his next
    opponent gives up to his position, his value a game, his minutes and usage
    over his last five against the window, Sleeper's projection, his last five
    games — then Yahoo's averages over the season and the last month (the
    latter only where it differs), his teammates out, his injury and who he
    is. The game log is every game Sleeper has of him in the window. Seasons,
    history and news each cost a request, so they are `deferred`.

    A points league heads it with his fantasy points a game this season, a
    category league with his points. `reported` is ESPN's report on him,
    which says when he is back; where it has none, Yahoo's status stands
    alone. Nothing for a healthy player.
    """
    player, season, recent = drawer.player, drawer.season, drawer.recent
    by_points = drawer.by_points
    figure = "" if season is None else season.points if by_points else season.stats.get(POINTS.yahoo_stat, "")
    headline = figure if number(figure) is not None else ""
    unit = "fpts/game" if by_points else "pts/game"
    hurt = drawer.reported or designation(status_word(player.status), player.injury_note)
    spans = ((SEASON, season), (LAST_MONTH, None if recent == season else recent))
    week = _week(drawer)
    projected = drawer.week.projected if drawer.week else None
    log = _game_log(drawer)
    who = _profile(drawer.profile)
    return PlayerDetail(
        player_id=player.player_key,
        name=player.name,
        position=player.position,
        team=player.team,
        image_url=player.image_url,
        owner=clears(player, drawer.priority) or player.owner,
        headline=headline,
        headline_label=f"{unit}, season" if headline else "No games this season",
        note=status_word(player.status),
        tone="warning" if player.status else "neutral",
        tabs=[WEEK_TAB, GAME_LOG_TAB, *DEFERRED],
        deferred=list(DEFERRED),
        moves_tab=HISTORY_TAB,
        groups=[
            *([StatGroup(title=THIS_WEEK, stats=week)] if week else []),
            *([_projected(projected, drawer.weights)] if projected and projected.games else []),
            *(StatGroup(title=title, stats=averages(line, drawer.scored, by_points)) for title, line in spans if line),
            *([StatGroup(title="Teammates", stats=[split.stat() for split in drawer.splits])] if drawer.splits else []),
            *([StatGroup(title="Injury", stats=hurt)] if hurt else []),
            *([StatGroup(title="Player", stats=who)] if who else []),
        ],
        tables=[t for t in (log and _recent_games(log), log) if t],
    )


def _week(drawer: Drawer) -> list[Stat]:
    """His week in a few lines; nothing at all without a matchup this week."""
    week = drawer.week
    if week is None:
        return []
    club = drawer.player.team.upper()
    reading = week.reading
    stats = [
        *([Stat(label=GAMES_LEFT, value=week.left)] if week.left else []),
        *([Stat(label="Games", value=" · ".join(_fixture(g, club) for g in week.fixtures))] if week.fixtures else []),
        *([_next(week.fixtures[0], club, week.matchup)] if week.fixtures and week.matchup else []),
    ]
    if reading is not None and reading.per_game is not None:
        stats.append(
            Stat(
                label=per_game(drawer.by_points),
                value=f"{reading.per_game:.1f}",
                better="higher",
                hint=POINTS_HINT if drawer.by_points else VALUE_HINT,
            )
        )
        if reading.worth is not None:
            stats.append(Stat(label=WEEK, value=f"{reading.worth:.1f}", better="higher"))
    stats += _trend(drawer.games)
    return stats


def _fixture(game: ScheduledGame, club: str) -> str:
    """'Thu 20 vs LAL', or '@ LAL' away; the day bare where the schedule's date will not read."""
    day = parse_day(game.date)
    when = f"{WEEKDAYS[day.weekday()]} {day.day}" if day else game.date
    return f"{when} {_versus(game, club)}"


def _versus(game: ScheduledGame, club: str) -> str:
    return f"vs {game.away}" if game.home == club else f"@ {game.home}"


def _next(game: ScheduledGame, club: str, matchup: Matchup) -> Stat:
    """'vs LAL · 4th-most to PGs (24.1 pts a game)', toned by the matchup."""
    return Stat(label="Next", value=f"{_versus(game, club)} · {matchup.allowed_to()}", tone=matchup.tone)


def _trend(games: Sequence[NBAGameLog]) -> list[Stat]:
    """His minutes and usage a game over his last five, beside every game of the window:
    '32.4 last 5 · 28.1 last 6 wks'.

    The window is named by its weeks rather than by his games in it, which
    differ player to player and read as an arbitrary number.
    """
    if not games:
        return []
    last = games[:RECENT]

    def across(measure: Callable[[NBAGameLog], float]) -> str:
        recent = f"{statistics.fmean(measure(g) for g in last):.1f} last {len(last)}"
        if len(games) <= len(last):
            return recent
        return f"{recent} · {statistics.fmean(measure(g) for g in games):.1f} {WINDOW}"

    return [
        Stat(label="Minutes/g", value=across(lambda g: g.minutes), hint=MINUTES_HINT),
        Stat(label="Usage/g", value=across(usage), hint=USAGE_HINT),
    ]


def usage(game: NBAGameLog) -> float:
    """The plays that ended with him in a game: shots, trips to the line, turnovers (`USAGE_HINT`)."""
    return game.get(FIELD_GOALS.attempts) + 0.44 * game.get(FREE_THROWS.attempts) + game.get(TURNOVERS.made)


def _projected(projected: ProjectedTotals, weights: Mapping[str, float] | None) -> StatGroup:
    """Sleeper's projection a game this week, in every category, with his fantasy points in a points league."""
    figures = line(projected.totals, games=projected.games)
    points = fantasy_points(figures, weights) if weights else None
    return StatGroup(
        title="Projected line",
        note=f"{projected.games} game{'' if projected.games == 1 else 's'}",
        stats=[
            *([Stat(label=FANTASY_POINTS, value=f"{points:.1f}", better="higher")] if points is not None else []),
            # Each category says which way it improves, so a comparison can mark the better
            # projection: the fewer turnovers, the more of everything else.
            *(
                Stat(label=c.label, value=_figure(c, figures[c.label]), better=c.better)
                for c in CATEGORIES
                if c.label in figures
            ),
        ],
    )


def _figure(category: Category, value: float) -> str:
    """A figure as Yahoo prints one: '.482' for a rate, '25.3' for a count."""
    return f"{value:.3f}".removeprefix("0") if category.is_percentage else f"{value:.1f}"


def _profile(meta: PlayerMeta | None) -> list[Stat]:
    """'7 seasons · age 27 · #3 · Kentucky', from Sleeper's catalog; nothing where it cannot place him."""
    if meta is None:
        return []
    parts = [
        experience(meta.years_exp),
        *([f"age {meta.age}"] if meta.age else []),
        *([f"#{meta.number}"] if meta.number else []),
        *([meta.college] if meta.college else []),
    ]
    return [Stat(label="Profile", value=" · ".join(parts))]


LOG_COUNTS = (POINTS, REBOUNDS, ASSISTS, STEALS, BLOCKS, TURNOVERS, THREES)
"""The counts a game log's row carries, in the order a box score reads them; the shooting follows as made/tried."""

MINUTES = "Min"


def _game_log(drawer: Drawer) -> StatTable | None:
    """Every game Sleeper has of him in the window, oldest first, box score by box score.

    His fantasy points a game in a points league, his value a game in a
    category one, where the pool would scale; then minutes, the counts, and
    his shooting as made over tried. None before he has played.
    """
    if not drawer.games:
        return None
    rated = drawer.value is not None
    worth = FANTASY_POINTS if drawer.by_points else VALUE
    columns = [
        *([worth] if rated else []),
        MINUTES,
        *(c.label for c in LOG_COUNTS),
        "FG",
        "FT",
    ]
    rows = []
    for game in reversed(drawer.games):
        figures = line(game.stats)
        game_worth = drawer.value(figures) if drawer.value else None
        rows.append(
            StatRow(
                label=_dated(game, drawer.venues.get(game.date)),
                values=[
                    *([f"{game_worth:.1f}" if game_worth is not None else NOT_APPLICABLE] if rated else []),
                    f"{game.minutes:.0f}",
                    *(_count(game.get(c.made)) for c in LOG_COUNTS),
                    f"{_count(game.get(FIELD_GOALS.made))}/{_count(game.get(FIELD_GOALS.attempts))}",
                    f"{_count(game.get(FREE_THROWS.made))}/{_count(game.get(FREE_THROWS.attempts))}",
                ],
            )
        )
    return StatTable(title="Game log", tab=GAME_LOG_TAB, columns=columns, rows=rows)


def _dated(game: NBAGameLog, fixture: ScheduledGame | None) -> str:
    """'13 Nov vs LAL', '@ LAL' away; the opponent bare where the schedule has no game that day."""
    day = parse_day(game.date)
    when = day_month(day) if day else game.date
    if fixture is None:
        return f"{when} {game.opponent}"
    return f"{when} {'vs' if fixture.home == game.team else '@'} {game.opponent}"


def _count(value: float) -> str:
    return f"{value:.0f}"


def _recent_games(log: StatTable) -> StatTable:
    """The log's last `RECENT` games, cut to what shows a role: his value or points, minutes and points."""
    wanted = {VALUE, FANTASY_POINTS, MINUTES, POINTS.label}
    kept = [i for i, column in enumerate(log.columns) if column in wanted]
    return StatTable(
        title="Recent games",
        tab=WEEK_TAB,
        columns=[log.columns[i] for i in kept],
        rows=[StatRow(label=row.label, values=[row.values[i] for i in kept]) for row in log.rows[-RECENT:]],
    )


def season_label(season: str) -> str:
    """'2025-26' for Sleeper's '2025': an NBA season spans two years and is named by both."""
    try:
        year = int(season)
    except ValueError:
        return season
    return f"{year}-{(year + 1) % 100:02d}"


def seasons(by_season: Mapping[str, NBASeason | None], weights: Mapping[str, float] | None) -> StatTable | None:
    """His seasons side by side, newest first, a game at a time: games, minutes, every category, Sleeper's rank.

    Per game rather than total, because a total mostly measures how many games
    he was healthy for. A season he played none of reads as absent. None
    where he played none of any.
    """
    played = {s: totals for s, totals in by_season.items() if totals and totals.games}
    if not played:
        return None
    columns = list(by_season)

    def row(label: str, read: Callable[[NBASeason], str], better: Better | None = "higher") -> StatRow:
        cells = [read(played[s]) if s in played else NOT_APPLICABLE for s in columns]
        return StatRow(label=label, values=cells, better=better)

    def figure(category: Category) -> Callable[[NBASeason], str]:
        def read(totals: NBASeason) -> str:
            value = category.figure(totals.totals, totals.games)
            return _figure(category, value) if value is not None else NOT_APPLICABLE

        return read

    def points(totals: NBASeason) -> str:
        value = fantasy_points(line(totals.totals, totals.games), weights or {})
        return f"{value:.1f}" if value is not None else NOT_APPLICABLE

    rows = [
        row("Games", lambda t: str(t.games)),
        row(MINUTES, lambda t: f"{t.minutes / t.games:.1f}"),
        *([row(FANTASY_POINTS, points)] if weights else []),
        *(row(c.label, figure(c), c.better) for c in CATEGORIES),
    ]
    if any(t.position_rank for t in played.values()):
        rows.append(
            row("Position rank", lambda t: f"#{t.position_rank}" if t.position_rank else NOT_APPLICABLE, "lower")
        )
    return StatTable(title="By season", tab=SEASONS_TAB, columns=[season_label(s) for s in columns], rows=rows)


def deferred_tab(
    player: Player,
    *,
    groups: Sequence[StatGroup] = (),
    tables: Sequence[StatTable] = (),
    moves: Sequence[ActivityRow] = (),
) -> PlayerDetail:
    """One deferred tab of his drawer (`DEFERRED`): who he is, and only what that tab holds."""
    return PlayerDetail(
        player_id=player.player_key,
        name=player.name,
        position=player.position,
        team=player.team,
        tabs=[WEEK_TAB, GAME_LOG_TAB, *DEFERRED],
        moves_tab=HISTORY_TAB,
        groups=list(groups),
        tables=list(tables),
        moves=list(moves),
    )


def news(headlines: list[Stat]) -> list[StatGroup]:
    """His news tab: the newest headlines, each linked to its article; nothing where there are none."""
    return [StatGroup(title="News", tab=NEWS_TAB, stats=headlines)] if headlines else []
