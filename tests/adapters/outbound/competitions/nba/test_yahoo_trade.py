"""Tests for the Yahoo provider's trades: the context a proposal is judged in, and the market searched for them."""

import logging
from datetime import date
from typing import Any

import pytest
from support.logs import capture_logs
from support.nba import FakeNBA, FakeYahoo, make_player, nba_provider

from thefrontoffice.adapters.outbound.competitions.nba.form import PlayerStats, RecentForm, nine_cat
from thefrontoffice.adapters.outbound.competitions.nba.rules import POINTS
from thefrontoffice.adapters.outbound.competitions.nba.yahoo import ONE_WIN, YahooNBAProvider
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog, ScheduledGame
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooUnavailableError
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooLeague
from thefrontoffice.domain.errors import PlayerNotFoundError, UnsupportedError
from thefrontoffice.domain.models import CompetitionContext, TradeMarket, TradeProposal

POINTS_STAT = POINTS.yahoo_stat

# The module logs through `getLogger(__name__)`, so the class's module is the
# logger's name — and follows the module if it ever moves.
YAHOO_LOGGER = YahooNBAProvider.__module__


def _giving(yahoo: FakeYahoo, *names: str) -> str:
    """The prompt for giving `names` away for nothing, which names whom each resolved to."""
    return nba_provider(yahoo).build_trade_context("", TradeProposal(giving=list(names), receiving=[])).prompt


def _yahoo_with(*names: str) -> FakeYahoo:
    return FakeYahoo(search_results={n: [make_player(n)] for n in names})


# ── player resolution ───────────────────────────────────────────────────


def test_an_exact_match_resolves() -> None:
    assert "LeBron James" in _giving(_yahoo_with("LeBron James"), "LeBron James")


def test_the_surname_is_tried_when_the_full_name_misses() -> None:
    """'Lebron James' (wrong casing) misses, but 'James' still finds him."""
    yahoo = FakeYahoo(search_results={"James": [make_player("LeBron James")]})
    assert "LeBron James" in _giving(yahoo, "Lebron James")


def test_the_exact_name_wins_among_several_matches() -> None:
    """Yahoo's search matches substrings, so a name can bring others with it."""
    yahoo = FakeYahoo(
        search_results={"James": [make_player("Jalen James"), make_player("LeBron James"), make_player("Mike James")]}
    )
    prompt = _giving(yahoo, "Lebron James")
    assert "LeBron James" in prompt
    assert "Jalen James" not in prompt


def test_an_ambiguous_surname_resolves_to_nobody_rather_than_the_first() -> None:
    """Pricing whichever Williams Yahoo listed first would evaluate a trade
    nobody proposed."""
    yahoo = FakeYahoo(search_results={"Williams": [make_player("Jalen Williams"), make_player("Jaylen Williams")]})
    with capture_logs(YAHOO_LOGGER, logging.WARNING) as logs, pytest.raises(PlayerNotFoundError) as excinfo:
        _giving(yahoo, "Williams")
    assert excinfo.value.names == ["Williams"]
    assert len(logs.at(logging.WARNING)) == 1


# ── trade context ───────────────────────────────────────────────────────


def _context(yahoo: FakeYahoo) -> CompetitionContext:
    proposal = TradeProposal(giving=["LeBron James"], receiving=["Jayson Tatum"])
    return nba_provider(yahoo).build_trade_context("", proposal)


def test_both_sides_and_the_roster_reach_the_prompt() -> None:
    yahoo = _yahoo_with("LeBron James", "Jayson Tatum")
    yahoo.roster_players = [make_player("Existing Starter")]
    prompt = _context(yahoo).prompt
    assert "LeBron James" in prompt
    assert "Jayson Tatum" in prompt
    assert "Existing Starter" in prompt  # the roster-awareness rule needs this


def test_the_matchup_is_carried_as_the_situation() -> None:
    situation = _context(_yahoo_with("LeBron James", "Jayson Tatum")).situation
    assert "Their Team" in situation
    assert "BLK: 12 vs 17" in situation


def test_the_roster_rides_along_for_the_follow_up_briefing() -> None:
    """A follow-up is seeded from the roster lines, not the generation prompt."""
    yahoo = FakeYahoo(
        search_results={n: [make_player(n)] for n in ("LeBron James", "Jayson Tatum")},
        roster=[make_player("Existing Starter")],
    )

    assert list(_context(yahoo).roster_lines) == ["Existing Starter"]


def test_a_roster_failure_fails_the_evaluation_rather_than_judging_without_it() -> None:
    """A trade is judged against the roster it changes; without it the answer is to a different question."""
    yahoo = FakeYahoo(
        search_results={n: [make_player(n)] for n in ("LeBron James", "Jayson Tatum")},
        roster=[make_player("Existing Starter")],
        roster_error=YahooUnavailableError("yahoo hiccup"),
    )

    with pytest.raises(YahooUnavailableError):
        _context(yahoo)


# ── the trade market ────────────────────────────────────────────────────

FEBRUARY = [date(2026, 2, d) for d in range(9, 16)]


def _market_league(scoring_type: str = ONE_WIN, current: int | None = 5) -> YahooLeague:
    return YahooLeague(
        league_key="466.l.1", name="One", current_week=current, start_week=1, end_week=20, scoring_type=scoring_type
    )


def _market_yahoo(**kwargs: Any) -> FakeYahoo:
    """You hold two starters and a third on the same nights; they hold one who plays the nights you field nobody."""
    yahoo = FakeYahoo(
        roster=[
            make_player("Mine One", team="LAL", key="m1", selected_position="PF"),
            make_player("Mine Two", team="LAL", key="m2", selected_position="C"),
            make_player("Mine Three", team="LAL", key="m3", selected_position="BN"),
        ],
        **kwargs,
    )
    yahoo.others = {"t.2": [make_player("Their One", team="BOS", key="b1", selected_position="PF")]}
    yahoo.slots = {"PF": 1, "C": 1, "BN": 2, "IL": 1}
    yahoo.trade_end = date(2099, 2, 25)
    return yahoo


MARKET_FORM = {
    "Mine One": {"pts": 30, "blk": 2},
    "Mine Two": {"pts": 30, "blk": 2},
    "Mine Three": {"pts": 20, "blk": 1},
    "Their One": {"pts": 15, "blk": 1},
}


def _played(**box: float) -> PlayerStats:
    games = [NBAGameLog(player_id="p", date=f"2026-01-{i + 1:02d}", opponent="BOS", stats=box) for i in range(10)]
    return PlayerStats(recent=RecentForm(games=10, line=nine_cat(games)))


def _market_nba() -> FakeNBA:
    slate = [ScheduledGame(week=0, date=day.isoformat(), home="LAL", away="NYK") for day in FEBRUARY[:3]] + [
        ScheduledGame(week=0, date=day.isoformat(), home="BOS", away="MIA") for day in FEBRUARY[3:6]
    ]
    form = {name: _played(**box) for name, box in MARKET_FORM.items()}
    return FakeNBA(stats=form, slate=slate, games={"LAL": 3, "BOS": 3})


def _trade_market(yahoo: FakeYahoo, league: YahooLeague | None = None) -> TradeMarket | None:
    return nba_provider(yahoo, nba=_market_nba(), league=league or _market_league()).trade_market("")


def test_a_one_win_category_league_is_searched_in_categories_up_to_its_deadline() -> None:
    market = _trade_market(_market_yahoo())

    assert market is not None
    assert (market.measure, market.deadline) == ("categories", date(2099, 2, 25))
    assert {t.team_id for t in market.season.teams} == {"t.1", "t.2"}
    assert market.season.fixtures and all(f.chances is not None for f in market.season.fixtures)


def test_a_points_league_is_searched_in_its_fantasy_points() -> None:
    market = _trade_market(_market_yahoo(weights={POINTS_STAT: 1.0}), _market_league("headpoint"))

    assert market is not None and market.measure == "points"
    assert market.season.scoring


def test_a_trade_both_sides_gain_on_is_found_from_the_leagues_own_rosters() -> None:
    market = _trade_market(_market_yahoo(weights={POINTS_STAT: 1.0}), _market_league("headpoint"))

    assert market is not None
    assert [(o.giving, o.receiving) for o in market.options][:1] == [(("Mine Three (PF)",), ("Their One (PF)",))]


def test_past_the_trade_deadline_there_is_no_market() -> None:
    yahoo = _market_yahoo()
    yahoo.trade_end = date(2020, 2, 25)

    assert _trade_market(yahoo) is None


def test_between_seasons_and_in_the_playoffs_there_is_no_market() -> None:
    assert _trade_market(_market_yahoo(), _market_league(current=None)) is None
    assert _trade_market(_market_yahoo(), _market_league(current=19)) is None


def test_a_season_without_this_weeks_matchup_has_no_market() -> None:
    assert _trade_market(_market_yahoo(matchup_dates=None)) is None


@pytest.mark.parametrize(
    ("scoring_type", "weights", "best_game"),
    [("head", None, False), ("headpoint", None, False), (ONE_WIN, None, True)],
    ids=["every category counts", "points without weights", "best game only"],
)
def test_a_league_the_season_cannot_settle_one_result_a_week_for_is_refused(
    scoring_type: str, weights: dict[str, float] | None, best_game: bool
) -> None:
    yahoo = _market_yahoo(weights=weights)
    yahoo.best_game = best_game

    with pytest.raises(UnsupportedError):
        _trade_market(yahoo, _market_league(scoring_type))


def test_trades_are_still_priced_when_the_wire_will_not_load() -> None:
    yahoo = _market_yahoo()
    yahoo.wire_error = YahooUnavailableError("down")

    with capture_logs(YAHOO_LOGGER, logging.WARNING) as logs:
        market = _trade_market(yahoo)

    assert market is not None
    assert len(logs.at(logging.WARNING)) == 1
