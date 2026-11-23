"""Fantasy basketball in its own terms: what the NBA's rules read, whatever platform the league is on.

The registry is keyed by competition and platform because one competition can
run on several. The rules here — the week's worth, the to-do list, the
forecast, the weeks ahead, the trade search — are the competition's, and they
describe what they need rather than naming a platform's types: a player, his
line as the league prints it, the categories it scores, a team, a week's
head-to-head, a move. Yahoo's own types already have these shapes, so the
provider hands them over as they stand; a second platform's would, by the
same members, with no rule rewritten.

Structural on purpose, as `nfl/model.py` is: a Protocol states what is read,
and anything with those members is one.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Protocol

INJURED_SLOTS = frozenset({"IL", "IL+"})
"""Roster slots that hold an injured player outside the active roster.

The platform's client names its own, and cannot import this; the two are kept
equal by `test_model.py`."""

UNSTARTED_SLOTS = INJURED_SLOTS | {"BN"}
"""Roster slots whose players score nothing: the bench and the injured ones."""


class PrintedLine(Protocol):
    """A player's line over some span, as the league prints it."""

    @property
    def stats(self) -> Mapping[str, str]:
        """The platform's stat id -> its figure: '15.7', '.536', '6.0/11.2'; '-' where he has none."""
        ...

    @property
    def points(self) -> str:
        """His fantasy points over the same span, in a points league; empty in a category one."""
        ...


@dataclass(frozen=True)
class Unprinted:
    """No line at all: what a player reads as where the league printed none for the span."""

    stats: Mapping[str, str] = field(default_factory=dict)
    points: str = ""


NO_LINE = Unprinted()


class Player(Protocol):
    """What the rules read about a player on the league's platform."""

    @property
    def player_key(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def position(self) -> str:
        """Every position he is eligible at, as the league prints it: 'PF,C'."""
        ...

    @property
    def team(self) -> str:
        """His NBA club's abbreviation."""
        ...

    @property
    def status(self) -> str:
        """'O', 'GTD', 'INJ'; empty for a player with nothing reported."""
        ...

    @property
    def injury_note(self) -> str: ...
    @property
    def slot(self) -> str:
        """Where his manager has him this week: 'PG', 'BN', 'IL'. Empty off a roster."""
        ...

    @property
    def stats(self) -> Mapping[str, str]:
        """The platform's stat id -> his line over `coverage`, as printed; empty unless asked for."""
        ...

    @property
    def points(self) -> str: ...
    @property
    def coverage(self) -> str:
        """The span `stats` and `points` cover; empty where they carry nothing."""
        ...

    @property
    def image_url(self) -> str: ...
    @property
    def owner(self) -> str:
        """Whose roster he is on — a team's name, 'Free agent' or 'Waivers' — where asked for; empty otherwise."""
        ...

    @property
    def waiver_date(self) -> date | None:
        """The day he clears waivers, while he sits on them; None otherwise."""
        ...

    @property
    def rostered(self) -> float | None:
        """The share of the platform's leagues that roster him, in percent; None where not asked for."""
        ...

    @property
    def rostered_change(self) -> float | None:
        """How far `rostered` moved over the last week, in points; None where not asked for."""
        ...

    @property
    def line(self) -> PrintedLine: ...


class LeagueCategory(Protocol):
    """One category the league scores, as its settings name it."""

    @property
    def stat_id(self) -> str: ...
    @property
    def name(self) -> str:
        """What the league displays it as: 'PTS', 'FG%'."""
        ...

    @property
    def fewer_wins(self) -> bool:
        """Won by the side with less of it: turnovers, in most leagues."""
        ...


class WeekSide(Protocol):
    """One team's side of a head-to-head week."""

    @property
    def team_key(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def points(self) -> str:
        """The side's score as printed: categories won in a category league, fantasy points in a points one."""
        ...

    @property
    def stats(self) -> Mapping[str, str]:
        """The platform's stat id -> the side's value, as printed."""
        ...

    @property
    def projected(self) -> str:
        """The projected final score, as printed; empty where none is given."""
        ...


class HeadToHead(Protocol):
    """One week's head-to-head as the scoreboard has it: its dates, and each side."""

    @property
    def start(self) -> date: ...
    @property
    def end(self) -> date: ...
    @property
    def mine(self) -> WeekSide: ...
    @property
    def opponent(self) -> WeekSide: ...
    @property
    def status(self) -> str:
        """'preevent', 'midevent' or 'postevent': not started, being played, or settled."""
        ...

    @property
    def winner(self) -> str:
        """The winning team's key once settled; empty before, and for a tie."""
        ...

    @property
    def tied(self) -> bool: ...
    @property
    def tied_categories(self) -> int: ...
    @property
    def playoffs(self) -> bool: ...
    @property
    def consolation(self) -> bool: ...
    @property
    def settled(self) -> bool: ...


class WeekMatchup(Protocol):
    """This week's head-to-head, read once for its score, its categories, its dates and the opponent's roster."""

    @property
    def start(self) -> date: ...
    @property
    def end(self) -> date: ...
    @property
    def mine(self) -> WeekSide: ...
    @property
    def opponent(self) -> WeekSide: ...
    @property
    def opponent_roster(self) -> Sequence[Player]: ...


class Standing(Protocol):
    """A team's place in the league table."""

    @property
    def rank(self) -> int: ...
    @property
    def wins(self) -> int: ...
    @property
    def losses(self) -> int: ...
    @property
    def ties(self) -> int: ...
    @property
    def points_for(self) -> str: ...
    @property
    def points_against(self) -> str: ...
    @property
    def playoff_seed(self) -> int:
        """Zero until the regular season has seeded the bracket."""
        ...

    @property
    def record(self) -> str: ...


class Team(Protocol):
    """One team in the league."""

    @property
    def team_key(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def is_mine(self) -> bool: ...
    @property
    def adds_used(self) -> int:
        """Adds made this week, against the league's weekly limit."""
        ...

    @property
    def standing(self) -> Standing | None: ...
    @property
    def waiver_priority(self) -> int: ...
    @property
    def faab_balance(self) -> str:
        """Waiver budget left, as printed; empty in a league without FAAB."""
        ...


class LeagueRules(Protocol):
    """What a league's settings say about how it is scored, how often a team may add, and how its season ends."""

    @property
    def categories(self) -> Sequence[LeagueCategory]: ...
    @property
    def positions(self) -> Sequence[str]: ...
    @property
    def weights(self) -> Mapping[str, float]:
        """The platform's stat id -> fantasy points per unit, in a points league; empty in a category one."""
        ...

    @property
    def max_weekly_adds(self) -> int | None: ...
    @property
    def playoff_start_week(self) -> int: ...
    @property
    def playoff_teams(self) -> int: ...
    @property
    def multiweek_final(self) -> bool: ...
    @property
    def weekly_lineups(self) -> bool: ...
    @property
    def best_game(self) -> bool: ...
    @property
    def trade_end(self) -> date | None: ...
    @property
    def slots(self) -> Mapping[str, int]: ...
    @property
    def starting(self) -> int: ...
    @property
    def roster_size(self) -> int: ...


class MovedPlayer(Protocol):
    """One player a league move moved, and which way."""

    @property
    def player_key(self) -> str: ...
    @property
    def name(self) -> str: ...
    @property
    def position(self) -> str: ...
    @property
    def team(self) -> str: ...
    @property
    def kind(self) -> str:
        """What happened to him: 'add', 'drop', 'trade'."""
        ...

    @property
    def source(self) -> str: ...
    @property
    def destination(self) -> str: ...


class LeagueMove(Protocol):
    """One move the league made: an add, a drop, both at once, or a trade."""

    @property
    def kind(self) -> str: ...
    @property
    def timestamp(self) -> int:
        """When it went through, in epoch seconds."""
        ...

    @property
    def players(self) -> Sequence[MovedPlayer]: ...
    @property
    def bid(self) -> str: ...
