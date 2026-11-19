"""How a basketball player reads on a page — the views of him: a table row, and the drawer that opens on him.

Split from the provider because it is the one question asked of a player in
every view — the roster, a rival's, the wire, a player opened on his own — and
the provider is the place a league is read, not drawn. Every average shown is
Yahoo's own, as Yahoo prints it, so a row reads what the league's own page
reads: his last month in a table, his season and his last month in the drawer.
Sleeper's box scores still carry everything game by game — the week's worth,
the forecast, the teammate splits — and none of it is shown as an average.
"""

from collections.abc import Callable, Mapping, Sequence
from datetime import date

from thefrontoffice.adapters.outbound.competitions.injuries import BODY_PART, approximately
from thefrontoffice.adapters.outbound.competitions.nba.form import PlayerStats
from thefrontoffice.adapters.outbound.competitions.nba.rules import (
    ASSISTS,
    CATEGORIES,
    POINTS,
    REBOUNDS,
    fantasy_points,
    ruled_out,
)
from thefrontoffice.adapters.outbound.competitions.nba.teammates import Split
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading
from thefrontoffice.adapters.outbound.competitions.teammates import WITHOUT_COLUMN
from thefrontoffice.adapters.outbound.platforms.yahoo.types import StatCategory, YahooLine, YahooPlayer
from thefrontoffice.domain.models import (
    PLAYER_COLUMN,
    POSITION_COLUMN,
    SLOT_COLUMN,
    STATUS_COLUMN,
    Held,
    MovePlayer,
    MoveSide,
    PlayerCard,
    PlayerDetail,
    PlayerOrder,
    Stat,
    StatGroup,
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


def detail(
    player: YahooPlayer,
    season: YahooLine | None,
    recent: YahooLine | None,
    scored: Sequence[StatCategory],
    by_points: bool,
    reported: list[Stat],
    splits: Sequence[Split] = (),
    left: str = "",
) -> PlayerDetail:
    """The drawer on one player: his week, his averages this season and over the last month, his teammates out, his injury.

    Both averages are Yahoo's, in the league's categories `scored`; the last
    month only where it differs from the season, which early on it does not. A
    points league heads it with his fantasy points a game this season, a
    category league with his points. `left` is his games left this week
    (`games_left`), empty where unknown. `splits` is his line without each
    regular teammate who is hurt or lately sat out, and with him
    (`teammates.Split`). `reported` is ESPN's report on him, which says when he
    is back; where it has none, Yahoo's status stands alone. Nothing for a
    healthy player.
    """
    figure = "" if season is None else season.points if by_points else season.stats.get(POINTS.yahoo_stat, "")
    headline = figure if number(figure) is not None else ""
    unit = "fpts/game" if by_points else "pts/game"
    hurt = reported or [
        *([Stat(label="Status", value=player.status, tone="warning")] if player.status else []),
        *([Stat(label=BODY_PART, value=player.injury_note)] if player.injury_note else []),
    ]
    spans = ((SEASON, season), (LAST_MONTH, None if recent == season else recent))
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
        groups=[
            *([StatGroup(title=THIS_WEEK, stats=[Stat(label=GAMES_LEFT, value=left)])] if left else []),
            *(StatGroup(title=title, stats=averages(line, scored, by_points)) for title, line in spans if line),
            *([StatGroup(title="Teammates", stats=[split.stat() for split in splits])] if splits else []),
            *([StatGroup(title="Injury", stats=hurt)] if hurt else []),
        ],
    )


THIS_WEEK = "This week"


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
