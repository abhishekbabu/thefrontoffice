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
    Stat,
    StatGroup,
)

CARD_CATEGORIES = (POINTS, REBOUNDS, ASSISTS)
"""The categories a table row has room for; the drawer carries every one the league scores."""

FANTASY_POINTS = "FPTS"
"""A points league's fantasy points per game, as a column and a drawer name them."""

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
) -> list[PlayerCard]:
    """One table shape for every list of players this sport shows.

    `recent` is each player's averages over the last month, by Yahoo's key, as
    Yahoo prints them: the categories a row has room for, and in a points league
    his fantasy points a game. The lineup slot is a column only where somebody
    holds one: on the wire nobody does, and the column would be blank down its
    whole length. `returns` is the day ESPN expects each player back, by
    Yahoo's key. `splits`, on the wire, adds the teammate whose absence matters
    most to each (`teammates.Split`), the rest being in his drawer.
    """
    slotted = any(p.slot for p in players)
    rows = []
    for player in players:
        line = recent.get(player.player_key, YahooLine())
        split = next(iter(splits(player)), None) if splits else None
        back = returns.get(player.player_key) if player.status else None
        shown = {c.label: line.stats.get(c.yahoo_stat, "") for c in CARD_CATEGORIES}
        if by_points:
            shown[FANTASY_POINTS] = line.points
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
                    **{label: printed(figure) for label, figure in shown.items()},
                    **({WITHOUT_COLUMN: split.cell() if split else NO_FIGURE} if splits else {}),
                    STATUS_COLUMN: player.status,
                },
                notes={
                    **({STATUS_COLUMN: f"back {approximately(back)}"} if back else {}),
                    **({WITHOUT_COLUMN: split.note()} if split else {}),
                },
            )
        )
    return rows


def averages(line: YahooLine, scored: Sequence[StatCategory], by_points: bool) -> list[Stat]:
    """A line in every category the league scores, in its order, as Yahoo prints it; a points league's points first."""
    return [
        *([Stat(label=FANTASY_POINTS, value=printed(line.points), better="higher")] if by_points else []),
        *(
            Stat(
                label=c.name,
                value=printed(line.stats.get(c.stat_id, ""), rate=c.name.endswith("%")),
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
) -> PlayerDetail:
    """The drawer on one player: his averages this season and over the last month, his teammates out, his injury.

    Both averages are Yahoo's, in the league's categories `scored`. A points
    league heads it with his fantasy points a game this season, a category
    league with his points. `splits` is his line without each regular teammate
    who is hurt or lately sat out, and with him (`teammates.Split`). `reported`
    is ESPN's report on him, which says when he is back; where it has none,
    Yahoo's status stands alone. Nothing for a healthy player.
    """
    figure = "" if season is None else season.points if by_points else season.stats.get(POINTS.yahoo_stat, "")
    headline = figure if number(figure) is not None else ""
    unit = "fpts/game" if by_points else "pts/game"
    hurt = reported or [
        *([Stat(label="Status", value=player.status, tone="warning")] if player.status else []),
        *([Stat(label=BODY_PART, value=player.injury_note)] if player.injury_note else []),
    ]
    spans = ((SEASON, season), (LAST_MONTH, recent))
    return PlayerDetail(
        player_id=player.player_key,
        name=player.name,
        position=player.position,
        team=player.team,
        headline=headline,
        headline_label=f"{unit}, season" if headline else "No games this season",
        note=player.status,
        tone="warning" if player.status else "neutral",
        groups=[
            *(StatGroup(title=title, stats=averages(line, scored, by_points)) for title, line in spans if line),
            *([StatGroup(title="Teammates", stats=[split.stat() for split in splits])] if splits else []),
            *([StatGroup(title="Injury", stats=hurt)] if hurt else []),
        ],
    )


def games_left(reading: Reading) -> str:
    """His games left, '3', or '3+' while the week's schedule is not final; empty where it would not load."""
    if reading.games is None:
        return ""
    return f"{reading.games}+" if reading.provisional else str(reading.games)


def cell(reading: Reading, by_points: bool) -> str:
    """His week as a lineup row reads it: '3G · 41.5 fpts/g', or in a category league '3G · 22.1p 8.3r 4.0a'.

    Games left, then what he gives a game (`worth.per_game`): fantasy points in
    a points league, the categories a row has room for in a category one. '3+G'
    while the NBA has days of the week to schedule: three at least.
    """
    left = games_left(reading)
    games = f"{left}G" if left else ""
    if by_points:
        figure = f"{reading.per_game:.1f} fpts/g" if reading.per_game is not None else ""
    else:
        figures = reading.line or {}
        figure = " ".join(c.tagged(figures[c.label]) for c in CARD_CATEGORIES if c.label in figures)
    return " · ".join(part for part in (games, figure) if part)


GAMES_LEFT = "G left"
BACK = "Back"
"""When ESPN expects him back, while it reports him hurt."""
WEEK = "Week"
"""What he adds this week: a game's value × minutes nudge × games left (`Reading.worth`)."""


def per_game_label(by_points: bool) -> str:
    """What a game of him is counted in: fantasy points, or his value across the categories."""
    return "FPTS/g" if by_points else "Value/g"


def figures(reading: Reading, by_points: bool) -> list[Stat]:
    """The rows a to-do item compares him on, alike for every player on it; '—' where he has none."""
    worth = reading.worth
    status = reading.player.status
    return [
        Stat(label=GAMES_LEFT, value=games_left(reading) or NO_FIGURE),
        Stat(
            label=per_game_label(by_points),
            value=f"{reading.per_game:.1f}" if reading.per_game is not None else NO_FIGURE,
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
