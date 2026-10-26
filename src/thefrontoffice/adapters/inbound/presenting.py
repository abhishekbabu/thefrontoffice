"""The engines' figures, put into the words and columns the inbound adapters show.

The engines answer in numbers — a chance of winning, a playoff chance, what a
free agent would do to the week — and say nothing about how a header reads.
That is the inbound side's to decide, and the web page and the terminal
decide it the same way, here, so "1% · margin −36 to −6" reads alike in both.
Only the generic figures are written here: a competition's own vocabulary
(xPts, adds, "5th of 14") is its provider's.
"""

from thefrontoffice.application.season import chance_now
from thefrontoffice.application.week import SeasonView, WeekView, WirePage
from thefrontoffice.domain.models import (
    Forecast,
    LeagueSchedule,
    PickupChance,
    PlayerPage,
    PlayoffOdds,
    Stat,
    Summary,
    Tone,
)

WIN_COLUMN = "Win"
"""The column a free agent's chance is shown in — beside the competition's own columns."""

FIT_COLUMN = "Fits"
"""Where a competition says how a player fits your lineup: the chance reads best beside it."""


def week(view: WeekView) -> Summary:
    """The week's header with the chance of winning and what the week is worth to the playoffs."""
    summary = view.summary
    stats = [*summary.headline]
    if view.forecast is not None:
        stats.append(_win_chance(view.forecast))
    if view.odds is not None:
        stats.append(_stake(view.odds, view.forecast.win if view.forecast else None))
    return summary.model_copy(update={"forecast": view.forecast, "headline": stats})


def season(view: SeasonView) -> LeagueSchedule:
    """The league table with each team's playoff chance on its row, and yours in the season's header.

    Weighed by this week's forecast, as the week's header is: two figures for
    one chance reads as a bug.
    """
    schedule = view.schedule
    if view.odds is None:
        return schedule
    by_team = {t.team_id: t.playoffs for t in view.odds.teams}
    rows = [
        row.model_copy(update={"playoffs": f"{by_team[row.team_id]:.0%}"}) if row.team_id in by_team else row
        for row in schedule.standings
    ]
    chance = chance_now(view.odds, view.win)
    headline = [*schedule.headline, Stat(label="Playoffs", value=f"{chance:.0%}", tone=_playoff_tone(chance))]
    return schedule.model_copy(update={"standings": rows, "headline": headline})


def wire(view: WirePage, *, order: bool | None = None) -> PlayerPage:
    """The page with each priced player's chance in a column of its own; "—" for the rest.

    `order` re-sorts the page by it, descending when true, with the unpriced
    kept last either way. Only the page: what it would do is priced for the
    rows on screen, since pricing four thousand players is a minute nobody waits.
    """
    if not view.priced:
        return view.page
    by_player: dict[str, PickupChance] = {c.player_id: c for c in view.chances}
    cards = []
    for card in view.page.players:
        chance = by_player.get(card.player_id)
        columns = _beside(card.columns, FIT_COLUMN, f"{chance.win_change:+.1%}" if chance else "—")
        values = {**card.values, **({WIN_COLUMN: chance.win_change} if chance else {})}
        cards.append(card.model_copy(update={"columns": columns, "values": values}))
    if order is not None:
        priced = sorted((c for c in cards if WIN_COLUMN in c.values), key=lambda c: c.values[WIN_COLUMN], reverse=order)
        cards = priced + [c for c in cards if WIN_COLUMN not in c.values]
    return view.page.model_copy(update={"players": cards})


def _win_chance(forecast: Forecast) -> Stat:
    """One figure and its range: the chance alone hides how close it is."""
    tone: Tone = "good" if forecast.win >= 0.6 else "warning" if forecast.win <= 0.4 else "neutral"
    margin = forecast.margin
    return Stat(
        label="Win chance", value=f"{forecast.win:.0%} · margin {margin.low:+.0f} to {margin.high:+.0f}", tone=tone
    )


def _stake(odds: PlayoffOdds, win: float | None) -> Stat:
    """The playoff chance, with this week weighed by its own forecast, and what winning it is worth."""
    chance = chance_now(odds, win)
    stake = (
        f" · {odds.with_win:.0%} with a win, {odds.with_loss:.0%} without"
        if odds.with_win is not None and odds.with_loss is not None
        else ""
    )
    return Stat(label="Playoffs", value=f"{chance:.0%}{stake}", tone=_playoff_tone(chance))


def _playoff_tone(chance: float) -> Tone:
    return "good" if chance >= 0.75 else "warning" if chance <= 0.25 else "neutral"


def _beside(columns: dict[str, str], after: str, value: str) -> dict[str, str]:
    """`columns` with the chance placed right after `after`, or last where there is no such column."""
    if after not in columns:
        return {**columns, WIN_COLUMN: value}
    placed: dict[str, str] = {}
    for name, text in columns.items():
        placed[name] = text
        if name == after:
            placed[WIN_COLUMN] = value
    return placed
