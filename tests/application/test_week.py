"""Tests for the week as a manager reads it: `application/week.py`.

The provider and the simulations are stood in for, so each test can say what
the week must come back as when one of its parts is missing or fails.
"""

from datetime import UTC, datetime
from typing import Any

from support.simulation import outcome
from support.stores import FakeItemStates

from thefrontoffice.application.forecasting import ForecastEngine
from thefrontoffice.application.items import ItemDecisions, item_scope
from thefrontoffice.application.season import SeasonEngine
from thefrontoffice.application.week import WeekEngine
from thefrontoffice.domain.errors import FrontOfficeError
from thefrontoffice.domain.models import (
    Action,
    ItemState,
    LeagueSchedule,
    LineupMove,
    MatchupInput,
    PlayerCard,
    PlayerPage,
    PlayerQuery,
    SeasonInput,
    Summary,
    TeamRecord,
)

SWAP = Action(
    kind="lineup", urgency="soon", title="Start X over W", reason="", key="swap:x:w", player_id="x", replaces="w"
)
DEADLINE = Action(kind="trade", urgency="soon", title="Trade by week 11", reason="", key="deadline:11")


class _Provider:
    """A competition whose week, season and wire are fixed, and whose simulations can be made to fail."""

    label = "Test"

    def __init__(self, *, forecast_error: Exception | None = None, season_error: Exception | None = None) -> None:
        self.forecast_error = forecast_error
        self.season_error = season_error
        self.matchups_asked = 0

    def summary(self, league_id: str) -> Summary:
        return Summary(actions=[DEADLINE, SWAP])

    def schedule(self, league_id: str) -> LeagueSchedule:
        return LeagueSchedule()

    def free_agents(self, league_id: str, query: PlayerQuery) -> PlayerPage:
        return PlayerPage(players=[PlayerCard(player_id="x", columns={"Player": "X"})])

    def matchup_input(self, league_id: str, candidates: Any = ()) -> MatchupInput | None:
        self.matchups_asked += 1
        if self.forecast_error:
            raise self.forecast_error
        move = LineupMove(key="x>w", title="Start X over W", out=("w",), into=(outcome("x", 20, 25, 30),))
        return MatchupInput(mine=(outcome("w", 0, 5, 10),), theirs=(outcome("t", 10, 20, 30),), moves=(move,), seed=1)

    def played_matchups(self, league_id: str, week: int) -> list:
        return []

    def season_input(self, league_id: str) -> SeasonInput | None:
        if self.season_error:
            raise self.season_error
        teams = (TeamRecord("1", "Me", 6, 0, 0, 900.0), TeamRecord("2", "Them", 0, 6, 0, 500.0))
        return SeasonInput(teams=teams, fixtures=(), scoring=(), spots=1, mine="1", week=7)


def _engine(provider: _Provider, *, simulated: bool = True, store: FakeItemStates | None = None) -> WeekEngine:
    return WeekEngine(
        provider,
        decisions=ItemDecisions(store or FakeItemStates(), clock=lambda: datetime(2026, 10, 25, tzinfo=UTC)),
        forecast=ForecastEngine(provider) if simulated else None,
        season=SeasonEngine(provider) if simulated else None,
    )


def test_the_to_do_list_is_ranked_by_what_each_move_does_to_the_chance() -> None:
    """Same urgency, so the swap that helps comes before the deadline that moves nobody."""
    view = _engine(_Provider()).week("L1")

    assert [a.key for a in view.summary.actions or []] == [SWAP.key, DEADLINE.key]


def test_the_managers_decisions_are_applied_after_the_ranking() -> None:
    store = FakeItemStates()
    store.save(item_scope("Test", "L1"), {SWAP.key: ItemState(key=SWAP.key, dismissed_as=SWAP.fingerprint)})

    actions = _engine(_Provider(), store=store).week("L1").summary.actions or []

    assert {a.key: a.hidden for a in actions}[SWAP.key] == "dismissed"


def test_a_forecast_that_fails_still_leaves_the_week() -> None:
    view = _engine(_Provider(forecast_error=FrontOfficeError("down"))).week("L1")

    assert view.forecast is None and [a.key for a in view.summary.actions or []] == [DEADLINE.key, SWAP.key]


def test_playoff_odds_that_fail_still_leave_the_week() -> None:
    assert _engine(_Provider(season_error=FrontOfficeError("down"))).week("L1").odds is None


def test_a_competition_that_cannot_be_simulated_is_its_providers_week() -> None:
    view = _engine(_Provider(), simulated=False).week("L1")

    assert (view.forecast, view.odds) == (None, None)


def test_the_season_carries_this_weeks_chance_to_weigh_the_playoffs_by() -> None:
    view = _engine(_Provider()).season("L1")

    assert view.odds is not None and view.win is not None


def test_a_season_with_no_odds_does_not_simulate_the_week_for_nothing() -> None:
    provider = _Provider(season_error=FrontOfficeError("down"))

    view = _engine(provider).season("L1")

    assert view.odds is None and provider.matchups_asked == 0


def test_the_wire_is_priced() -> None:
    priced = _engine(_Provider()).wire("L1", PlayerQuery())
    assert priced.chances and priced.priced


def test_a_failed_pricing_still_leaves_the_wire_page_unpriced() -> None:
    failed = _engine(_Provider(forecast_error=FrontOfficeError("down"))).wire("L1", PlayerQuery())
    assert failed.chances == [] and not failed.priced and failed.page.players
