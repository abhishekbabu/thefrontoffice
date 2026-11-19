"""A basketball week, as the matchup page reads it: each side, and the score.

A category league is scored category by category. Yahoo's scoreboard carries
each side's totals by stat id, as it prints them; these read them into the
shared shapes. Who leads a category is worked out here rather than taken from
Yahoo's own winners, so a week still being played reads the same way as one
that has finished.

A points league is scored in fantasy points, which Yahoo totals for each side
and projects to the week's end; the categories behind them win nothing.
"""

from collections.abc import Mapping, Sequence
from typing import Literal

from thefrontoffice.adapters.outbound.competitions.dates import parse_day, weekday_day_month
from thefrontoffice.adapters.outbound.competitions.nba.rules import INJURED_SLOTS, ruled_out
from thefrontoffice.adapters.outbound.platforms.sleeper.types import ScheduledGame
from thefrontoffice.adapters.outbound.platforms.yahoo.types import MatchupSide, StatCategory, YahooPlayer
from thefrontoffice.domain.models import CategoryLine, Match, PlayerRef, Side, Spot, Stat, Tone

BENCH = "BN"
"""Yahoo's slot for a player on the roster but not in the day's lineup."""


def categories(
    scored: Sequence[StatCategory], mine: Mapping[str, str], theirs: Mapping[str, str]
) -> list[CategoryLine]:
    """One line per category the league scores, in its settings' order, each side's figure by stat id.

    The league's own list rather than the nine this app prices players by: a
    league scoring double-doubles shows them, and one without free throws does not.
    """
    return [
        CategoryLine(
            name=category.name,
            mine=mine.get(category.stat_id, ""),
            theirs=theirs.get(category.stat_id, ""),
            lead=_lead(category, mine.get(category.stat_id, ""), theirs.get(category.stat_id, "")),
        )
        for category in scored
    ]


Lead = Literal["mine", "theirs", "even"]


def _lead(category: StatCategory, mine: str, theirs: str) -> Lead | None:
    """Who is ahead, or None where either figure is not a number yet: a week to come prints a dash."""
    try:
        ours, other = float(mine), float(theirs)
    except ValueError:
        return None
    if ours == other:
        return "even"
    return "mine" if (ours < other) == category.fewer_wins else "theirs"


def score(lines: Sequence[CategoryLine]) -> tuple[int, int, int] | None:
    """Categories won, lost and level, from your side; None where nothing has been recorded."""
    leads = [line.lead for line in lines if line.lead is not None]
    if not leads:
        return None
    return leads.count("mine"), leads.count("theirs"), leads.count("even")


def headline(score: tuple[int, int, int]) -> Stat:
    """The week's score in categories, which is how a category week is won."""
    won, lost, _ = score
    tone: Tone = "good" if won > lost else "warning" if won < lost else "neutral"
    return Stat(label="Categories", value=written(score), tone=tone)


def written(score: tuple[int, int, int]) -> str:
    """'5-3-1': won, lost, level."""
    return "-".join(str(n) for n in score)


Stage = Literal["played", "playing", "to come"]
"""Where a week sits against the one being played."""


def stage(week: int, current: int) -> Stage:
    return "played" if week < current else "playing" if week == current else "to come"


def points(mine: MatchupSide, theirs: MatchupSide, when: Stage) -> list[Stat]:
    """A points week's score in fantasy points, as Yahoo totals them, and its projected final while games are left.

    A week to come has no score, only a projection, which each side's card
    carries already. Toned by who is ahead, since the week is won on the total.
    """
    stats: list[Stat] = []
    if when != "to come" and (score := _versus(mine.points, theirs.points)):
        stats.append(score.model_copy(update={"label": "Final" if when == "played" else "Live"}))
    if when == "playing" and (projected := _versus(mine.projected, theirs.projected)):
        stats.append(projected.model_copy(update={"label": "Projected"}))
    return stats


def _versus(mine: str, theirs: str) -> Stat | None:
    """Two totals side by side, toned for yours; None where either is not a number."""
    try:
        margin = float(mine) - float(theirs)
    except ValueError:
        return None
    tone: Tone = "good" if margin > 0 else "warning" if margin < 0 else "neutral"
    return Stat(label="", value=f"{mine} – {theirs}", tone=tone)


def total(side: MatchupSide, when: Stage) -> str:
    """One side's fantasy points as its card heads them: scored, then Yahoo's projection while games are left."""
    scored = f"{side.points} pts" if side.points and when != "to come" else ""
    projected = f"{side.projected} proj" if side.projected and when != "played" else ""
    return " · ".join(part for part in (scored, projected) if part)


def side(name: str, detail: str, points: str, roster: Sequence[YahooPlayer] | None) -> Side:
    """One team in the week, its roster parted as Yahoo slots it: the lineup, the bench, the injured list.

    `roster` is None for a week already played: Yahoo sets a basketball lineup
    day by day, so no one roster is the one that played the week, and today's
    would claim one that did not.
    """
    rows = list(roster or [])
    return Side(
        name=name,
        detail=detail,
        points=points,
        lineup=[_spot(p) for p in rows if p.slot not in INJURED_SLOTS and p.slot != BENCH],
        bench=[_spot(p).model_copy(update={"slot": ""}) for p in rows if p.slot == BENCH],
        # A player on the injured list was never going to play: no warning on his row.
        reserve=[_spot(p).model_copy(update={"slot": "", "tone": "neutral"}) for p in rows if p.slot in INJURED_SLOTS],
    )


def _spot(player: YahooPlayer) -> Spot:
    """A player as his row reads: where he is slotted, his positions and club, and any status he carries."""
    return Spot(
        player_id=player.player_key,
        slot=player.slot,
        player=player.name,
        detail=f"{player.position} · {player.team}",
        value=player.status,
        tone="warning" if ruled_out(player.status) else "neutral",
    )


STATUS = {"in_game": "live", "complete": "final"}
"""Sleeper's game status, in the word a fixture row shows; a game still to come shows none."""


def match(game: ScheduledGame, roster: Sequence[YahooPlayer]) -> Match:
    """One real game, with your players in it.

    Sleeper publishes the day and a status, and no score.
    """
    day = parse_day(game.date)
    clubs = {game.home.upper(), game.away.upper()}
    yours = [
        PlayerRef(player_id=p.player_key, name=p.name, detail=f"{p.position} · {p.slot or 'bench'}")
        for p in roster
        if p.team.upper() in clubs
    ]
    return Match(
        label=weekday_day_month(day) if day else game.date,
        home=game.home,
        away=game.away,
        # Who has players in it is said by name, from `yours`.
        detail=STATUS.get(game.status, ""),
        yours=yours,
    )
