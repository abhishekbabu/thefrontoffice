"""How a basketball player reads on a page — the views of him: a table row, and the drawer that opens on him.

Split from the provider because it is the one question asked of a player in
every view — the roster, a rival's, the wire, a player opened on his own — and
the provider is the place a league is read, not drawn. Every figure is his
recent run (`RecentForm`): the last fifteen games, or every game while fewer.
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
    Category,
    fantasy_points,
    ruled_out,
)
from thefrontoffice.adapters.outbound.competitions.nba.teammates import Split
from thefrontoffice.adapters.outbound.competitions.nba.worth import Reading
from thefrontoffice.adapters.outbound.competitions.teammates import WITHOUT_COLUMN
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooPlayer
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
"""The categories a table row has room for; the drawer carries all nine."""

FANTASY_POINTS = "FPTS"
"""A points league's fantasy points per game, as a column and a drawer name them."""

RECENT_FORM = "Recent form"
"""The drawer's group of a player's recent figures."""

NO_FIGURE = "—"
"""What a table cell shows where there is no number. A zero would read as a
bad line rather than an absent one."""


def figure(stats: PlayerStats | None, category: Category) -> float | None:
    """One category over a player's recent run, or None where there is no figure.

    Out of season, and for a player who has not featured, there is no line to
    show; nor is there a percentage for a player who has attempted nothing.
    """
    recent = (stats or PlayerStats()).get("recent")
    return recent.line.get(category.label) if recent else None


def run(stats: PlayerStats | None) -> str:
    """The run a figure averages, as a label reads it: 'last 15', 'last 12'."""
    recent = (stats or PlayerStats()).get("recent")
    return f"last {recent.games}" if recent else ""


def recent(stats: PlayerStats | None, category: Category) -> str:
    """That figure as a cell reads it, or a dash where there is none."""
    value = figure(stats, category)
    return category.show(value) if value is not None else NO_FIGURE


def points(stats: PlayerStats | None, weights: Mapping[str, float]) -> float | None:
    """Fantasy points per game over a player's recent run, under the league's weights; None where there is no line."""
    line = (stats or PlayerStats()).get("recent")
    return fantasy_points(line.line, weights) if line else None


def cards(
    players: list[YahooPlayer],
    stats_for: Callable[[str], PlayerStats | None],
    returns: Mapping[str, date],
    weights: Mapping[str, float] | None,
    splits: Callable[[YahooPlayer], Sequence[Split]] | None = None,
) -> list[PlayerCard]:
    """One table shape for every list of players this sport shows.

    The lineup slot is a column only where somebody holds one: on the wire
    nobody does, and the column would be blank down its whole length. A
    points league adds the fantasy points per game its weights make of the
    same run. `returns` is the day ESPN expects each player back, by Yahoo's key.
    `splits`, on the wire, adds the teammate whose absence matters most to
    each (`teammates.Split`), the rest being in his drawer.
    """
    slotted = any(p.slot for p in players)
    rows = []
    for player in players:
        stats = stats_for(player.name)
        split = next(iter(splits(player)), None) if splits else None
        back = returns.get(player.player_key) if player.status else None
        values = {c.label: value for c in CARD_CATEGORIES if (value := figure(stats, c)) is not None}
        columns = {c.label: recent(stats, c) for c in CARD_CATEGORIES}
        if weights:
            fpts = points(stats, weights)
            columns[FANTASY_POINTS] = f"{fpts:.1f}" if fpts is not None else NO_FIGURE
            if fpts is not None:
                values[FANTASY_POINTS] = fpts
        rows.append(
            PlayerCard(
                player_id=player.player_key,
                ruled_out=ruled_out(player.status),
                values=values,
                columns={
                    PLAYER_COLUMN: player.name,
                    POSITION_COLUMN: player.position,
                    "Team": player.team,
                    **({SLOT_COLUMN: player.slot} if slotted else {}),
                    **columns,
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


def detail(
    player: YahooPlayer,
    stats: PlayerStats | None,
    weights: Mapping[str, float] | None,
    reported: list[Stat],
    splits: Sequence[Split] = (),
) -> PlayerDetail:
    """The drawer on one player: every category of his recent run, his teammates out, and his injury.

    A points league heads it with his fantasy points per game; a category league
    with his points. `splits` is his line without each regular teammate who is
    hurt or lately sat out, and with him (`teammates.Split`). `reported` is ESPN's
    report on him, which says when he is back; where it has none, Yahoo's status
    stands alone. Nothing for a healthy player.
    """
    span = run(stats)
    figures = [Stat(label=c.label, value=recent(stats, c), better=c.better) for c in CATEGORIES]
    if weights:
        fpts = points(stats, weights)
        headline, unit = (f"{fpts:.1f}", "fpts/game") if fpts is not None else ("", "")
        figures.append(Stat(label=FANTASY_POINTS, value=headline or NO_FIGURE, better="higher"))
    else:
        scored = recent(stats, POINTS)
        headline, unit = (scored, "pts/game") if scored != NO_FIGURE else ("", "")
    hurt = reported or [
        *([Stat(label="Status", value=player.status, tone="warning")] if player.status else []),
        *([Stat(label=BODY_PART, value=player.injury_note)] if player.injury_note else []),
    ]
    return PlayerDetail(
        player_id=player.player_key,
        name=player.name,
        position=player.position,
        team=player.team,
        headline=headline,
        headline_label=f"{unit}, {span}" if headline else "No recent form",
        note=player.status,
        tone="warning" if player.status else "neutral",
        groups=[
            # One title however long the run, which the headline already says: a comparison lines
            # up the players' figures by it, and "Last 12" beside "Last 15" would be two tables.
            StatGroup(title=RECENT_FORM, stats=figures),
            *([StatGroup(title="Teammates", stats=[split.stat() for split in splits])] if splits else []),
            *([StatGroup(title="Injury", stats=hurt)] if hurt else []),
        ],
    )


def cell(reading: Reading, by_points: bool) -> str:
    """His week as a lineup row reads it: '3G · 41.5 fpts/g', or in a category league '3G · 22.1p 8.3r 4.0a'.

    Games left, then what he gives a game (`worth.per_game`): fantasy points in
    a points league, the categories a row has room for in a category one.
    """
    games = f"{reading.games}G" if reading.games is not None else ""
    if by_points:
        figure = f"{reading.per_game:.1f} fpts/g" if reading.per_game is not None else ""
    else:
        figures = reading.line or {}
        figure = " ".join(c.tagged(figures[c.label]) for c in CARD_CATEGORIES if c.label in figures)
    return " · ".join(part for part in (games, figure) if part)


GAMES_LEFT = "G left"
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
        Stat(label=GAMES_LEFT, value=str(reading.games) if reading.games is not None else NO_FIGURE),
        Stat(
            label=per_game_label(by_points),
            value=f"{reading.per_game:.1f}" if reading.per_game is not None else NO_FIGURE,
        ),
        Stat(label="Min/g", value=f"{reading.minutes:.1f}" if reading.minutes is not None else NO_FIGURE),
        Stat(label=WEEK, value=f"{worth:.1f}" if worth is not None else NO_FIGURE),
        Stat(label=STATUS_COLUMN, value=status or NO_FIGURE, tone="warning" if ruled_out(status) else "neutral"),
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
