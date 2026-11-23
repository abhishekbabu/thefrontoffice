"""How a basketball player reads on a page — the views of him: a table row. The drawer that opens on him is `drawer.py`.

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

from thefrontoffice.adapters.outbound.competitions.dates import day_month
from thefrontoffice.adapters.outbound.competitions.injuries import approximately
from thefrontoffice.adapters.outbound.competitions.nba.form import FORM_WEEKS, PlayerStats
from thefrontoffice.adapters.outbound.competitions.nba.model import NO_LINE, LeagueCategory, Player, PrintedLine
from thefrontoffice.adapters.outbound.competitions.nba.rules import (
    ASSISTS,
    CATEGORIES,
    POINTS,
    REBOUNDS,
    clears,
    fantasy_points,
    ruled_out,
)
from thefrontoffice.adapters.outbound.competitions.nba.teammates import Teammate
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading, game_value, moved
from thefrontoffice.adapters.outbound.competitions.teammates import WITHOUT_COLUMN
from thefrontoffice.domain.models import (
    PLAYER_COLUMN,
    POSITION_COLUMN,
    SLOT_COLUMN,
    STATUS_COLUMN,
    Held,
    MovePlayer,
    MoveSide,
    PlayerCard,
    PlayerOrder,
    Stat,
)

CARD_CATEGORIES = (POINTS, REBOUNDS, ASSISTS)
"""The categories a lineup row, and a points league's table, have room for."""

FANTASY_POINTS = "FPTS"
"""A points league's fantasy points per game, as a column and a drawer name them."""

VALUE = "Value"
"""A category league's column of what a game of him is worth across its categories (`worth.category_value`)."""

VALUE_HINT = (
    "What one game of his is worth across your categories, summed; higher is better, and it only means "
    "anything against another player's. Each category counts by how scarce it is among both rosters and the "
    "top of the wire; FG% and FT% by how far his shooting moves a team's, turnovers against him. From recent "
    "form beside this week's projection, leaning on his last 5 games where his minutes have moved."
)
POINTS_HINT = (
    "Fantasy points one game of his is worth this week: recent form beside this week's projection, leaning on "
    "his last 5 games where his minutes have moved."
)

MINUTES_COLUMN = "Min"
"""The wire's minutes a game over his last five, with which way they moved against the window: '37.7 ↑ (33.5)'."""

ROSTERED_COLUMN = "Rost"
"""The wire's share of Yahoo's leagues rostering him, with its week's change: '44% ↑20' — who managers are adding."""

UP, DOWN = "↑", "↓"

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
    players: Sequence[Player],
    recent: Mapping[str, PrintedLine],
    returns: Mapping[str, date],
    by_points: bool,
    splits: Callable[[Player], Sequence[Teammate]] | None = None,
    scored: Sequence[LeagueCategory] = (),
    readings: Mapping[str, Reading] | None = None,
    wire: bool = False,
) -> list[PlayerCard]:
    """One table shape for every list of players this sport shows, best a game first (`ranked`).

    `recent` is each player's averages over the last month, by Yahoo's key, as
    Yahoo prints them: in a points league his fantasy points a game and the
    categories a row has room for; in a category league every category it
    scores (`scored`), then his `VALUE` a game from `readings`. The lineup slot
    is a column only where somebody holds one: on the wire nobody does, and
    the column would be blank down its whole length. `returns` is the day ESPN
    expects each player back, by Yahoo's key. `splits`, on the wire, adds the
    teammate whose absence matters most to each (`teammates.Teammate`), the rest
    being in his drawer. The `wire` adds who is trending: his minutes against
    the window's (`MINUTES_COLUMN`), and how many leagues are adding him
    (`ROSTERED_COLUMN`) where his page carried it.
    """
    slotted = any(p.slot for p in players)
    rostered = wire and any(p.rostered is not None for p in players)
    valued = readings or {}
    rows = []
    for player in players:
        line = recent.get(player.player_key, NO_LINE)
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
        trends = trending(player, valued.get(player.player_key), rostered) if wire else {}
        for column, (cell, figure, _) in trends.items():
            cells[column] = cell
            if figure is not None:
                shown[column] = str(figure)
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
                    STATUS_COLUMN: status(player),
                },
                notes={
                    **({STATUS_COLUMN: note} if (note := status_note(player, back)) else {}),
                    **({WITHOUT_COLUMN: split.note()} if split else {}),
                    **{column: said for column, (_, _, said) in trends.items() if said},
                },
            )
        )
    return ranked(rows, by_points)


Trend = tuple[str, float | None, str]
"""A trend column's cell, the number it sorts by, and its tooltip."""


def trending(player: Player, reading: Reading | None, rostered: bool) -> dict[str, Trend]:
    """His trend cells on the wire: his minutes (`minutes_trend`), and his rostered share where it was read."""
    return {
        MINUTES_COLUMN: minutes_trend(reading),
        **({ROSTERED_COLUMN: rostered_trend(player)} if rostered else {}),
    }


def minutes_trend(reading: Reading | None) -> Trend:
    """'37.7 ↑ (33.5)' where his minutes over his last five moved from the window's by `worth.ROLE.moved`, and his
    value leans on those five; '33.8' where they held; a dash without his minutes."""
    role = reading.role if reading else None
    if role is None:
        minutes = reading.minutes if reading else None
        return (NO_FIGURE, None, "") if minutes is None else (f"{minutes:.1f}", minutes, "")
    over = f"{role.minutes:.1f} a game over his last {role.games} · {role.window:.1f} {WINDOW}"
    if not moved(role):
        return f"{role.minutes:.1f}", role.minutes, over
    arrow, way = (UP, "up") if role.minutes > role.window else (DOWN, "down")
    return (
        f"{role.minutes:.1f} {arrow} ({role.window:.1f})",
        role.minutes,
        f"Minutes {way}: {over}; value leans on the last {role.games}",
    )


def rostered_trend(player: Player) -> Trend:
    """'44% ↑20': the share of Yahoo's leagues rostering him, and its change over the week in points; a dash
    without it."""
    share, change = player.rostered, player.rostered_change
    if share is None:
        return NO_FIGURE, None, ""
    said = f"Rostered in {share:.0f}% of Yahoo leagues"
    if not change:
        return f"{share:.0f}%", share, said
    arrow, way = (UP, "up") if change > 0 else (DOWN, "down")
    return f"{share:.0f}% {arrow}{abs(change):.0f}", share, f"{said}, {way} {abs(change):.0f} this week"


WAIVERS = "W"
"""The status cell's word for a player on waivers, before the day he clears them."""


def status(player: Player) -> str:
    """His status cell: Yahoo's code, then 'W 25 Nov' while he sits on waivers — 'O · W 25 Nov' for both."""
    cleared = player.waiver_date
    waiting = f"{WAIVERS} {day_month(cleared)}" if cleared else ""
    return " · ".join(part for part in (player.status, waiting) if part)


def status_note(player: Player, back: date | None) -> str:
    """The status cell in full: 'back ~3 Dec', 'Waivers · clears Wed 25 Nov', or both; empty for neither."""
    return "; ".join(part for part in (f"back {approximately(back)}" if back else "", clears(player)) if part)


def ranked(rows: list[PlayerCard], by_points: bool) -> list[PlayerCard]:
    """Best a game first: by fantasy points in a points league, by `VALUE` in a category one; blanks last."""
    return PlayerOrder(sort=FANTASY_POINTS if by_points else VALUE).ordered(rows)


def by_worth(rows: list[PlayerCard], readings: Mapping[str, Reading]) -> list[PlayerCard]:
    """The wire worth picking up now first: a game's value times the games he can play this week (`Reading.available`).

    By a game's value alone a player ruled out for a fortnight led the list,
    though he adds nothing this week; he stays on it, his status and return
    beside him, below everyone who can play. Where worths tie — a week with no
    games left — those who can play still lead, then a game's value. A row with
    no reading keeps its place in `rows` after the rest.
    """

    def key(row: PlayerCard) -> tuple[bool, float, bool, float]:
        reading = readings.get(row.player_id)
        worth = reading.available if reading else None
        if reading is None or worth is None:
            return True, 0.0, False, 0.0
        return False, -worth, row.ruled_out, -(game_value(reading) or 0.0)

    return sorted(rows, key=key)


def rate(category: LeagueCategory) -> bool:
    """Whether a category is a rate, '.536', rather than a count."""
    return category.name.endswith("%")


def averages(line: PrintedLine, scored: Sequence[LeagueCategory], by_points: bool) -> list[Stat]:
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


WINDOW = f"last {FORM_WEEKS} wks"
"""Every game of his in the form window, named by its weeks."""


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
    line = reading.average or NO_LINE
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

CATEGORY_VALUE = "Cat value/g"
"""What a game of him is worth across a category league's categories: the figure every weekly call is weighed on."""

POINTS_VALUE = "Pts value/g"
"""The same in a points league: fantasy points a game."""


def per_game(by_points: bool) -> str:
    """What a game of him is worth is called by the scoring it is in, so a category league's reads as no points."""
    return POINTS_VALUE if by_points else CATEGORY_VALUE


WEAK = "Weak in"
"""The categories that drag a player's value, in a category league."""

BY_STAT = {c.yahoo_stat: c for c in CATEGORIES}


def weak(reading: Reading) -> str:
    """The categories that drag his value, with his figures in them: 'FG% .380 · 2.9 TO'; empty where none.

    Each figure is Yahoo's average over his last month where it carries one —
    the number his row and his drawer show — and his figure the value is read
    off where it does not.
    """
    line = reading.average or NO_LINE
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
    average = reading.average or NO_LINE
    return [
        Stat(label=GAMES_LEFT, value=games_left(reading) or NO_FIGURE),
        Stat(
            label=per_game(by_points),
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
