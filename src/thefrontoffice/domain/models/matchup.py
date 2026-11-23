"""What simulating one matchup takes and gives: lineups in, outcomes and ranges out."""

from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class Outcomes:
    """One player's week as a range of equally likely scores.

    What the simulation draws from. The provider builds it — from his own
    games, his position's, and this week's projection — so the engine never
    needs to know which sport it is.
    """

    player_id: str
    name: str
    projection: float
    samples: tuple[float, ...]
    """Equally likely full-game scores. Empty means he scores only `floor`."""

    plays: float = 1.0
    """The chance he plays at all; otherwise he adds nothing past `floor`."""

    floor: float = 0.0
    """Points already on the board — what a game under way has given him so far."""

    remaining: float = 1.0
    """How much of a full game is still to come: 1 before kickoff, 0 once it is over."""

    projection_error: float = 0.0
    """Spread of a factor around 1 that scales his whole game in each simulated week —
    for how far the projection his range is centred on may itself be off."""

    group: str = ""
    """Players whose weeks rise and fall together — a quarterback and his receivers.
    Empty for a player whose week is his own."""

    shared_error: float = 0.0
    """The part of `projection_error` everyone in `group` shares: one factor per group per
    simulated week. Taken out of his own share rather than added to it, so his range on
    its own is the same either way and only how it moves with his teammates changes."""

    games: int = 1
    """How many games he has left in the week, each drawn from `samples` on its own: one in
    football, as many as his club plays in basketball, nought for a player who will not play."""


@dataclass(frozen=True)
class LineupMove:
    """One change to the manager's lineup the simulation should price."""

    key: str
    title: str
    out: tuple[str, ...]
    """Player ids the move takes out of the lineup."""

    into: tuple[Outcomes, ...]
    """Who comes in instead."""

    made: bool = False
    """Already in `mine`, as the lineup a provider recommends: the move is written as its undo — `out` the
    player it started, `into` the one it benched — and what it is worth is the chance undoing it would cost."""


@dataclass(frozen=True)
class MatchupInput:
    """Both lineups, the moves to price, and a seed so the answer holds still between reloads."""

    mine: tuple[Outcomes, ...]
    theirs: tuple[Outcomes, ...]
    moves: tuple[LineupMove, ...] = ()
    seed: int = 0
    categories: CategoryMatchup | None = None
    """A week won category by category, simulated in place of `mine` and `theirs`, which are then empty."""
    provisional: bool = False
    """Whether games are still to be added to the week — a schedule not yet final — so any forecast of it runs short."""


@dataclass(frozen=True)
class ScoredCategory:
    """One category a week is won on, as the sum of one stat — or of one over another, for a percentage."""

    name: str
    made: str
    """The stat summed; for a percentage, the makes."""

    attempts: str = ""
    """The stat `made` is divided by, which makes this a percentage."""

    fewer_wins: bool = False
    """Won by the side with less of it: turnovers."""

    places: int | None = None
    """Decimal places the league compares it to — a percentage printed '.478' ties at three. None compares exactly."""


@dataclass(frozen=True)
class StatLines:
    """One player's week as figures: his recent games, each equally likely, and how many he has left."""

    player_id: str
    samples: tuple[tuple[float, ...], ...]
    """Each a game's figures, in `CategoryMatchup.stats` order. Empty means he adds nothing."""

    games: int
    """How many games he plays in what is left of the week."""


@dataclass(frozen=True)
class CategoryMatchup:
    """A week won category by category: what each side has so far, and each player's games still to come.

    The matchup goes to whoever wins more categories, a level count a tie — one result for
    the week, which is how a one-win league scores it and what a category league's week is
    called won by.
    """

    stats: tuple[str, ...]
    """The stats every figure below lists, in order."""

    categories: tuple[ScoredCategory, ...]
    mine: tuple[StatLines, ...]
    theirs: tuple[StatLines, ...]
    board_mine: tuple[float, ...]
    """Each stat's total so far, in `stats` order."""

    board_theirs: tuple[float, ...]


@dataclass(frozen=True)
class PlayedMatchup:
    """A matchup already played, as it stood before kickoff — what a backtest scores the simulation on."""

    week: int
    matchup: MatchupInput
    mine: float
    theirs: float


@dataclass(frozen=True)
class RangeSearch:
    """The settings that shape a competition's player ranges, as plain numbers a tuning run can search.

    Named and valued by the competition, so the search needs to know nothing
    about what each one means.
    """

    current: dict[str, float]
    """Each setting as the app runs with it."""

    grid: dict[str, tuple[float, ...]]
    """The values worth trying for each, the current one among them."""


class MarginRange(BaseModel):
    """How the margin falls across the simulated weeks: positive is a win."""

    low: float = Field(description="Tenth percentile: four weeks in five end above it.")
    median: float
    high: float = Field(description="Ninetieth percentile: four weeks in five end below it.")


class Forecast(BaseModel):
    """The week played many times over, and what each move does to it."""

    win: float = Field(description="Chance of winning, a tie counting half.")
    margin: MarginRange
    simulations: int
    moves: dict[str, float] = Field(
        default_factory=dict, description="Each move's key, and the chance of winning with it."
    )
    best_move: str = Field(
        default="", description="The move that most raises the chance, if any does; empty otherwise."
    )
    categories: dict[str, float] = Field(
        default_factory=dict,
        description="Each category's name and your chance of winning it, in a week won on categories; empty otherwise.",
    )
    provisional: bool = Field(
        default=False,
        description="Whether the week's schedule is not final yet, so the games it was played over are short.",
    )


class PickupChance(BaseModel):
    """What one available player would do to this week's chance of winning.

    Priced at his best legal start: every slot he could fill, against whoever
    he would push out, and the one that helps most — or hurts least, since a
    deep league's wire mostly hurts, and by how much is still the question.
    """

    player_id: str
    win_change: float = Field(description="The chance of winning with him started, less the chance without.")
    title: str = Field(description="The start that gets it, in the manager's words: 'Start X over Y'.")
