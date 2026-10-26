"""The week as a manager reads it: a competition's own summary, with what the generic engines add to it.

The provider describes the week; the forecast says how likely it is to be
won and what each move does to that; the season says what it is worth to the
playoffs; the manager's own decisions say which items to hide. Put together
here, once, rather than by whichever entry point is showing it — the order
matters (the forecast ranks the to-do list before the decisions mark it), and
so does what to do when one of them fails, which is to show the week without
it: a page that failed over a forecast would show nothing.
"""

import logging
from dataclasses import dataclass, field

from thefrontoffice.application.forecasting import ForecastEngine, ranked
from thefrontoffice.application.items import ItemDecisions
from thefrontoffice.application.season import SeasonEngine
from thefrontoffice.domain.errors import FrontOfficeError
from thefrontoffice.domain.models import (
    Forecast,
    LeagueSchedule,
    MatchupInput,
    PickupChance,
    PlayerPage,
    PlayerQuery,
    PlayoffOdds,
    Summary,
)
from thefrontoffice.domain.ports import WeekProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WeekView:
    """The week, and what each engine made of it: figures, for an entry point to put into words."""

    summary: Summary
    """The provider's week, its to-do list ranked by the forecast and marked with the manager's decisions."""
    forecast: Forecast | None = None
    odds: PlayoffOdds | None = None


@dataclass(frozen=True)
class SeasonView:
    """The league beyond this week, with every team's playoff chance and this week's chance of winning."""

    schedule: LeagueSchedule
    odds: PlayoffOdds | None = None
    win: float | None = None


@dataclass(frozen=True)
class WirePage:
    """A page of free agents, and what each would do to this week's chance of winning."""

    page: PlayerPage
    chances: list[PickupChance] = field(default_factory=list)
    priced: bool = False
    """Whether the page was put to the forecast at all: a page priced to no effect — every game
    under way — still has a chance column to show, with nothing in it."""


class WeekEngine:
    """One competition's week, season and wire, with the generic engines' answers attached.

    `forecast` and `season` are None for a competition that cannot be
    simulated; the week is then the provider's alone.
    """

    def __init__(
        self,
        provider: WeekProvider,
        *,
        decisions: ItemDecisions,
        forecast: ForecastEngine | None,
        season: SeasonEngine | None,
    ):
        self.provider = provider
        self.decisions = decisions
        self.forecast = forecast
        self.season_engine = season

    def week(self, league_id: str) -> WeekView:
        """The week as it stands, with the chance of winning it and what it is worth to the playoffs."""
        summary = self.provider.summary(league_id)
        forecast = self._forecast(league_id)
        if forecast is not None:
            summary = summary.model_copy(update={"actions": ranked(summary.actions, *forecast)})
        if summary.actions is not None:
            summary = summary.model_copy(
                update={"actions": self.decisions.apply(self.provider.label, league_id, summary.actions)}
            )
        return WeekView(summary=summary, forecast=forecast[0] if forecast else None, odds=self._odds(league_id))

    def season(self, league_id: str) -> SeasonView:
        """The season, the table and the real games, with each team's playoff chance."""
        schedule = self.provider.schedule(league_id)
        odds = self._odds(league_id)
        if odds is None:
            return SeasonView(schedule=schedule)
        forecast = self._forecast(league_id)
        return SeasonView(schedule=schedule, odds=odds, win=forecast[0].win if forecast else None)

    def wire(self, league_id: str, query: PlayerQuery) -> WirePage:
        """One page of free agents, each priced at what he would do to this week's chance."""
        page = self.provider.free_agents(league_id, query)
        if self.forecast is None:
            return WirePage(page=page)
        try:
            chances = self.forecast.pickups(league_id, [p.player_id for p in page.players])
        except FrontOfficeError as e:
            logger.warning(f"Showing free agents without their chance of winning: {e}")
            return WirePage(page=page)
        return WirePage(page=page, chances=chances, priced=True)

    def _forecast(self, league_id: str) -> tuple[Forecast, MatchupInput] | None:
        if self.forecast is None:
            return None
        try:
            return self.forecast.forecast(league_id)
        except FrontOfficeError as e:
            logger.warning(f"Showing the week without a forecast: {e}")
            return None

    def _odds(self, league_id: str) -> PlayoffOdds | None:
        if self.season_engine is None:
            return None
        try:
            return self.season_engine.odds(league_id)
        except FrontOfficeError as e:
            logger.warning(f"Showing the league without playoff odds: {e}")
            return None
