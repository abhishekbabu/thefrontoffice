"""How a basketball player reads on a page — the views of him: a table row, and the drawer that opens on him.

Split from the provider because it is the one question asked of a player in
every view — the roster, a rival's, the wire, a player opened on his own — and
the provider is the place a league is read, not drawn. Every average shown is
Yahoo's own, as Yahoo prints it, so a row reads what the league's own page
reads: his last month in a table, his season and his last month in the drawer.
Sleeper's box scores still carry everything game by game — the week's worth,
the forecast, the teammate splits — and none of it is shown as an average.
"""

import statistics
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date

from thefrontoffice.adapters.outbound.competitions.careers import experience
from thefrontoffice.adapters.outbound.competitions.dates import WEEKDAYS, day_month, parse_day
from thefrontoffice.adapters.outbound.competitions.injuries import BODY_PART, approximately
from thefrontoffice.adapters.outbound.competitions.matchups import Matchup
from thefrontoffice.adapters.outbound.competitions.nba.form import PlayerStats
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
    fantasy_points,
    line,
    ruled_out,
)
from thefrontoffice.adapters.outbound.competitions.nba.teammates import Split
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading, Valuer
from thefrontoffice.adapters.outbound.competitions.teammates import WITHOUT_COLUMN
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog, NBASeason, PlayerMeta, ScheduledGame
from thefrontoffice.adapters.outbound.platforms.yahoo.types import StatCategory, YahooLine, YahooPlayer
from thefrontoffice.domain.models import (
    NOT_APPLICABLE,
    PLAYER_COLUMN,
    POSITION_COLUMN,
    SLOT_COLUMN,
    STATUS_COLUMN,
    ActivityRow,
    Better,
    Held,
    MovePlayer,
    MoveSide,
    PlayerCard,
    PlayerDetail,
    PlayerOrder,
    Stat,
    StatGroup,
    StatRow,
    StatTable,
)

CARD_CATEGORIES = (POINTS, REBOUNDS, ASSISTS)
"""The categories a lineup row, and a points league's table, have room for."""

FANTASY_POINTS = "FPTS"
"""A points league's fantasy points per game, as a column and a drawer name them."""

VALUE = "Value"
"""A category league's column of what a game of him is worth across its categories (`worth.category_value`)."""

VALUE_HINT = (
    "What a game of him is worth across the league's categories: each one's figure against its spread "
    "among both rosters and the top of the wire, FG% and FT% weighted by attempts, turnovers counted against. "
    "Recent form beside this week's projection."
)
POINTS_HINT = "Fantasy points a game this week is weighed on: recent form beside this week's projection."

SEASON = "Season"
LAST_MONTH = "Last 30 days"
"""The drawer's groups of a player's averages, as Yahoo's own pages name the spans."""

NO_FIGURE = "—"
"""What a table cell shows where there is no number. A zero would read as a
bad line rather than an absent one."""


def points(stats: PlayerStats | None, weights: Mapping[str, float]) -> float | None:
    """Fantasy points per game over a player's recent run in Sleeper's box scores, under the league's weights.

    What the scout's prompt ranks a points league's wire by; None where there is no line.
    """
    line = (stats or PlayerStats()).get("recent")
    return fantasy_points(line.line, weights) if line else None


def printed(value: str, rate: bool = False) -> str:
    """A figure as Yahoo prints it, or a dash where it prints none ('-', or nothing).

    A `rate` reads to three places without its leading nought, '.536', as
    Yahoo prints it: the parse its XML goes through reads '.536' as 0.536.
    """
    if value in ("", "-"):
        return NO_FIGURE
    figure = number(value)
    return f"{figure:.3f}".removeprefix("0") if rate and figure is not None else value


def number(value: str) -> float | None:
    """The number behind a printed figure, for sorting; None where it is not one."""
    try:
        return float(value)
    except ValueError:
        return None


def cards(
    players: list[YahooPlayer],
    recent: Mapping[str, YahooLine],
    returns: Mapping[str, date],
    by_points: bool,
    splits: Callable[[YahooPlayer], Sequence[Split]] | None = None,
    scored: Sequence[StatCategory] = (),
    readings: Mapping[str, Reading] | None = None,
) -> list[PlayerCard]:
    """One table shape for every list of players this sport shows, best a game first (`ranked`).

    `recent` is each player's averages over the last month, by Yahoo's key, as
    Yahoo prints them: in a points league his fantasy points a game and the
    categories a row has room for; in a category league every category it
    scores (`scored`), then his `VALUE` a game from `readings`. The lineup slot
    is a column only where somebody holds one: on the wire nobody does, and
    the column would be blank down its whole length. `returns` is the day ESPN
    expects each player back, by Yahoo's key. `splits`, on the wire, adds the
    teammate whose absence matters most to each (`teammates.Split`), the rest
    being in his drawer.
    """
    slotted = any(p.slot for p in players)
    valued = readings or {}
    rows = []
    for player in players:
        line = recent.get(player.player_key, YahooLine())
        split = next(iter(splits(player)), None) if splits else None
        back = returns.get(player.player_key) if player.status else None
        if by_points:
            shown = {
                FANTASY_POINTS: line.points,
                **{c.label: line.stats.get(c.yahoo_stat, "") for c in CARD_CATEGORIES},
            }
            cells = {label: printed(figure) for label, figure in shown.items()}
        else:
            shown = {c.name: line.stats.get(c.stat_id, "") for c in scored}
            cells = {c.name: printed(shown[c.name], rate=rate(c)) for c in scored}
            reading = valued.get(player.player_key)
            game = reading.per_game if reading else None
            shown[VALUE] = f"{game:.2f}" if game is not None else ""
            cells[VALUE] = f"{game:.1f}" if game is not None else NO_FIGURE
        rows.append(
            PlayerCard(
                player_id=player.player_key,
                ruled_out=ruled_out(player.status),
                values={label: value for label, figure in shown.items() if (value := number(figure)) is not None},
                columns={
                    PLAYER_COLUMN: player.name,
                    POSITION_COLUMN: player.position,
                    "Team": player.team,
                    **({SLOT_COLUMN: player.slot} if slotted else {}),
                    **cells,
                    **({WITHOUT_COLUMN: split.cell() if split else NO_FIGURE} if splits else {}),
                    STATUS_COLUMN: player.status,
                },
                notes={
                    **({STATUS_COLUMN: f"back {approximately(back)}"} if back else {}),
                    **({WITHOUT_COLUMN: split.note()} if split else {}),
                },
            )
        )
    return ranked(rows, by_points)


def ranked(rows: list[PlayerCard], by_points: bool) -> list[PlayerCard]:
    """Best a game first: by fantasy points in a points league, by `VALUE` in a category one; blanks last."""
    return PlayerOrder(sort=FANTASY_POINTS if by_points else VALUE).ordered(rows)


def rate(category: StatCategory) -> bool:
    """Whether a category is a rate, '.536', rather than a count."""
    return category.name.endswith("%")


def averages(line: YahooLine, scored: Sequence[StatCategory], by_points: bool) -> list[Stat]:
    """A line in every category the league scores, in its order, as Yahoo prints it; a points league's points first."""
    return [
        *([Stat(label=FANTASY_POINTS, value=printed(line.points), better="higher")] if by_points else []),
        *(
            Stat(
                label=c.name,
                value=printed(line.stats.get(c.stat_id, ""), rate=rate(c)),
                better="lower" if c.fewer_wins else "higher",
            )
            for c in scored
        ),
    ]


WEEK_TAB, GAME_LOG_TAB, SEASONS_TAB, HISTORY_TAB, NEWS_TAB = "This week", "Game log", "Seasons", "History", "News"
"""The drawer's tabs, in order: a group or table with no tab of its own sits in the first."""

DEFERRED = (SEASONS_TAB, HISTORY_TAB, NEWS_TAB)
"""The tabs read only when opened (`PlayerDetail.deferred`): each costs a request the first tab does not need."""

THIS_WEEK = WEEK_TAB

RECENT = 5
"""Games the first tab shows of the log, and the run his minutes and usage are read over beside the window."""

NEWS_IN_DRAWER = 10
"""Headlines the news tab lists: the window's worth, which is rarely more."""

USAGE_HINT = "Shots, trips to the line and turnovers a game — FGA + 0.44×FTA + TO: the plays that end with him."


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

    player: YahooPlayer
    season: YahooLine | None
    """Yahoo's averages this season; None where it has none."""

    recent: YahooLine | None
    """Yahoo's averages over the last month; None where it has none."""

    scored: Sequence[StatCategory]
    weights: Mapping[str, float] | None
    """A points league's weights by Yahoo stat id; None in a category league."""

    reported: list[Stat] = field(default_factory=list)
    """ESPN's report on him; empty where it has none."""

    splits: Sequence[Split] = ()
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
    hurt = drawer.reported or [
        *([Stat(label="Status", value=player.status, tone="warning")] if player.status else []),
        *([Stat(label=BODY_PART, value=player.injury_note)] if player.injury_note else []),
    ]
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
        owner=player.owner,
        headline=headline,
        headline_label=f"{unit}, season" if headline else "No games this season",
        note=player.status,
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
                label=PER_GAME,
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
    """His minutes and usage a game over his last five, beside every game of the window: '32.4 L5 · 28.1 L14'."""
    if not games:
        return []
    last = games[:RECENT]

    def across(measure: Callable[[NBAGameLog], float]) -> str:
        recent = f"{statistics.fmean(measure(g) for g in last):.1f} L{len(last)}"
        if len(games) <= len(last):
            return recent
        return f"{recent} · {statistics.fmean(measure(g) for g in games):.1f} L{len(games)}"

    return [
        Stat(label="Minutes", value=across(lambda g: g.minutes)),
        Stat(label="Usage", value=across(usage), hint=USAGE_HINT),
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
            *([Stat(label=FANTASY_POINTS, value=f"{points:.1f}")] if points is not None else []),
            *(Stat(label=c.label, value=_figure(c, figures[c.label])) for c in CATEGORIES if c.label in figures),
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
    player: YahooPlayer,
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


def games_left(reading: Reading) -> str:
    """His games left, '3', or '3+' while the week's schedule is not final; empty where it would not load."""
    return counted(reading.games, reading.provisional)


def counted(games: int | None, provisional: bool) -> str:
    """Games left as a page says them: '3', '3+' while the schedule is not final, or empty where unknown."""
    if games is None:
        return ""
    return f"{games}+" if provisional else str(games)


def cell(reading: Reading, by_points: bool) -> str:
    """His week as a lineup row reads it: '3G · 41.5 fpts/g', or in a category league '3G · 22.1p 8.3r 4.0a'.

    Games left, then Yahoo's averages over his last month (`Reading.average`),
    the figures every table and his drawer show: fantasy points a game in a
    points league, the categories a row has room for in a category one. '3+G'
    while the NBA has days of the week to schedule: three at least.
    """
    left = games_left(reading)
    games = f"{left}G" if left else ""
    line = reading.average or YahooLine()
    if by_points:
        figure = f"{line.points} fpts/g" if number(line.points) is not None else ""
    else:
        figure = " ".join(
            f"{value}{c.tag}" for c in CARD_CATEGORIES if number(value := line.stats.get(c.yahoo_stat, "")) is not None
        )
    return " · ".join(part for part in (games, figure) if part)


GAMES_LEFT = "G left"
BACK = "Back"
"""When ESPN expects him back, while it reports him hurt."""
WEEK = "Week"
"""What he adds this week: a game's value × minutes nudge × games left (`Reading.worth`)."""

PER_GAME = "Value/g"
"""What a game of him is worth, in the league's scoring: the figure every weekly call is weighed on."""

WEAK = "Weak in"
"""The categories that drag a player's value, in a category league."""

BY_STAT = {c.yahoo_stat: c for c in CATEGORIES}


def weak(reading: Reading) -> str:
    """The categories that drag his value, with his figures in them: 'FG% .380 · 2.9 TO'; empty where none.

    Each figure is Yahoo's average over his last month where it carries one —
    the number his row and his drawer show — and his figure the value is read
    off where it does not.
    """
    line = reading.average or YahooLine()
    figures = reading.line or {}
    parts = []
    for category in reading.weak:
        shown = printed(line.stats.get(category.stat_id, ""), rate=rate(category))
        if shown == NO_FIGURE:
            weighed = figures.get(BY_STAT[category.stat_id].label)
            if weighed is None:
                continue
            shown = f"{weighed:.3f}".removeprefix("0") if rate(category) else f"{weighed:.1f}"
        parts.append(f"{category.name} {shown}" if rate(category) else f"{shown} {category.name}")
    return " · ".join(parts)


def figures(reading: Reading, by_points: bool) -> list[Stat]:
    """The rows a to-do item compares him on, alike for every player on it; '—' where he has none.

    Beside the figures the week is weighed on, Yahoo's own: his fantasy points
    a game in a points league, as his row shows them; in a category league the
    categories that drag his value (`weak`), so a drop reads as more than a number.
    """
    worth = reading.worth
    status = reading.player.status
    average = reading.average or YahooLine()
    return [
        Stat(label=GAMES_LEFT, value=games_left(reading) or NO_FIGURE),
        Stat(
            label=PER_GAME,
            value=f"{reading.per_game:.1f}" if reading.per_game is not None else NO_FIGURE,
            hint=POINTS_HINT if by_points else VALUE_HINT,
        ),
        (
            Stat(label=FANTASY_POINTS, value=printed(average.points))
            if by_points
            else Stat(label=WEAK, value=weak(reading) or NO_FIGURE)
        ),
        Stat(label="Min/g", value=f"{reading.minutes:.1f}" if reading.minutes is not None else NO_FIGURE),
        Stat(label=WEEK, value=f"{worth:.1f}" if worth is not None else NO_FIGURE),
        Stat(label=STATUS_COLUMN, value=status or NO_FIGURE, tone="warning" if ruled_out(status) else "neutral"),
        Stat(label=BACK, value=approximately(reading.back) if reading.back else NO_FIGURE),
    ]


def compared(moved: Sequence[tuple[MoveSide, Held, Reading]], by_points: bool) -> list[MovePlayer]:
    """The players a to-do item moves, each on the same rows (`figures`), for reading side by side."""
    return [
        MovePlayer(
            side=side,
            player_id=reading.player.player_key,
            name=reading.player.name,
            position=reading.player.position,
            team=reading.player.team,
            held=held,
            figures=figures(reading, by_points),
        )
        for side, held, reading in moved
    ]
