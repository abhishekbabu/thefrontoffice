"""Tests for the basketball trades worth offering: `nba/market.py`.

Leagues here are built by hand: who plays which nights, and what a game of each
player gives. Two slots a night, so a third player on the same nights as two
better ones sits — the lineup fit most basketball trades are made of.
"""

from dataclasses import replace
from datetime import date, timedelta

import pytest
from support.nba import make_player

from thefrontoffice.adapters.outbound.competitions.nba.market import THEIR_GAIN, League, Week, build
from thefrontoffice.adapters.outbound.competitions.nba.rules import BLOCKS
from thefrontoffice.adapters.outbound.competitions.nba.strength import POINTS, Profile, Scored, Totals, Uncertainty
from thefrontoffice.adapters.outbound.platforms.yahoo.types import YahooPlayer
from thefrontoffice.domain.models import Stat, TeamRecord, TradeMarket, TradeOption

EARLY, LATE = "early", "late"
"""Clubs that play the first three nights of every week, and the next three."""

VALUES = {"m1": 30.0, "m2": 30.0, "m3": 20.0, "b1": 25.0, "b2": 15.0, "b3": 5.0, "c1": 10.0, "fa": 8.0}
"""A game of each, in fantasy points: yours (m), your partner's (b), the third team's (c), a free agent."""

EXACT = Uncertainty(missed=0.0, form={}, rate={}, game={})
"""A week that is exactly its games: what a trade's arithmetic here is checked under."""

CLUBS = {"m1": EARLY, "m2": EARLY, "m3": EARLY, "b1": LATE, "b2": LATE, "b3": LATE, "c1": EARLY, "fa": LATE}


def _player(key: str, slot: str = "BN", status: str = "") -> YahooPlayer:
    return make_player(key.upper(), position="SF", team=CLUBS[key], key=key, selected_position=slot, status=status)


def _nights(week: int, club: str) -> frozenset[date]:
    monday = date(2026, 11, 16) + timedelta(weeks=week - 5)
    first = 0 if club == EARLY else 3
    return frozenset(monday + timedelta(days=first + n) for n in range(3))


def _week(week: int, pairs: list[tuple[str, str]], keys: list[str]) -> Week:
    return Week(week=week, days={key: _nights(week, CLUBS[key]) for key in keys}, pairs=pairs)


def _points(value: float) -> Profile:
    return Profile(value=value, mean={POINTS: value}, variance={POINTS: 4.0})


def _league(
    rosters: dict[str, list[YahooPlayer]] | None = None,
    *,
    wire: list[YahooPlayer] | None = None,
    roster_size: int = 0,
    profiles: dict[str, Profile] | None = None,
    categories: tuple[Scored, ...] = (),
    current: int = 5,
    banked: dict[str, Totals] | None = None,
    uncertainty: Uncertainty = EXACT,
) -> League:
    rosters = rosters or {
        "a": [_player("m1"), _player("m2"), _player("m3")],
        "b": [_player("b1"), _player("b2"), _player("b3")],
        "c": [_player("c1")],
    }
    wire = wire or []
    keys = [p.player_key for players in [*rosters.values(), wire] for p in players]
    pairs = {5: [("a", "c")], 6: [("a", "b")], 7: [("a", "c")], 8: []}
    return League(
        mine="a",
        teams=[TeamRecord(team, team.upper(), 2, 2, 0, 0.0) for team in rosters],
        rosters=rosters,
        profiles=profiles or {key: _points(VALUES[key]) for key in keys},
        weeks=[_week(week, pairs[week], keys) for week in range(current, 9)],
        playoff_start=8,
        spots=2,
        slots=2,
        roster_size=roster_size,
        categories=categories,
        banked=banked or {},
        wire=wire,
        seed=1,
        uncertainty=uncertainty,
    )


def _market(league: League) -> TradeMarket:
    market = build(league)
    assert market is not None
    return market


def _trade(market: TradeMarket, give: str, get: str) -> TradeOption | None:
    return next((o for o in market.options if o.giving == (f"{give} (SF)",) and o.receiving == (f"{get} (SF)",)), None)


# ── what a trade does ───────────────────────────────────────────────────


def test_a_player_your_lineup_sits_is_traded_for_one_who_plays_your_empty_nights() -> None:
    """M3 sits behind two better players on the same nights; B2 plays the nights you field nobody."""
    trade = _trade(_market(_league()), "M3", "B2")

    assert trade is not None
    assert trade.points == pytest.approx(3 * 15.0)
    assert trade.playoff_points == pytest.approx(3 * 15.0)


def test_the_other_side_gains_too_or_the_trade_is_not_offered() -> None:
    """B gets nights it fields nobody on for a player it can replace; without that gain it says no."""
    market = _market(_league())
    trade = _trade(market, "M3", "B2")

    assert trade is not None and trade.their_points >= THEIR_GAIN["points"]
    assert all(o.their_points >= THEIR_GAIN["points"] for o in market.options)


def test_a_trade_that_only_moves_points_from_them_to_you_is_not_offered() -> None:
    """B3 never starts for B, and gaining him helps you; giving nothing B can use for him is no trade."""
    rosters = {
        "a": [_player("m1"), _player("m2"), _player("m3")],
        "b": [_player("b1"), _player("b2"), _player("b3")],
        "c": [_player("c1")],
    }
    profiles = {key: _points(VALUES[key]) for key in VALUES} | {"m3": _points(0.0)}

    market = _market(_league(rosters, profiles=profiles))

    assert _trade(market, "M3", "B2") is None


def test_an_untouchable_player_is_never_given_away() -> None:
    market = _market(replace(_league(), untouchable=frozenset({"m3"})))

    assert market.options
    assert not any("m3" in o.giving_ids for o in market.options)


def test_a_player_on_an_injured_slot_neither_moves_nor_is_moved_for() -> None:
    rosters = {
        "a": [_player("m1"), _player("m2"), _player("m3", slot="IL", status="O")],
        "b": [_player("b1"), _player("b2", slot="IL", status="O"), _player("b3")],
        "c": [_player("c1")],
    }

    market = _market(_league(rosters))

    named = {name for o in market.options for name in (*o.giving, *o.receiving)}
    assert not named & {"M3 (SF)", "B2 (SF)"}


PAIRED = {key: _points(VALUES[key]) for key in VALUES} | {"m2": _points(18.0), "m3": _points(18.0)}
"""Neither of M2 and M3 alone is worth B1 over the free agent; the two together are."""


def _two_for_one(market: TradeMarket) -> TradeOption:
    return next(o for o in market.options if o.giving == ("M2 (SF)", "M3 (SF)") and o.receiving == ("B1 (SF)",))


def test_a_full_roster_taking_two_for_one_drops_its_least_valuable_player() -> None:
    """B holds three of three: given M2 and M3 for B1, it cuts B3, whose three late nights it then goes without."""
    roomy = _two_for_one(_market(_league(wire=[_player("fa")], profiles=PAIRED)))
    full = _two_for_one(_market(_league(wire=[_player("fa")], profiles=PAIRED, roster_size=3)))

    assert roomy.their_points - full.their_points == pytest.approx(3 * VALUES["b3"])


def test_a_trade_names_its_players_by_id_too_in_the_same_order() -> None:
    trade = _two_for_one(_market(_league(wire=[_player("fa")], profiles=PAIRED)))

    assert (trade.giving_ids, trade.receiving_ids) == (("m2", "m3"), ("b1",))


def test_a_two_for_one_names_the_free_agent_for_the_spot_it_frees() -> None:
    market = _market(_league(wire=[_player("fa")], profiles=PAIRED))

    pairs = [o for o in market.options if len(o.giving) == 2]
    assert pairs
    assert {o.pickup for o in pairs} == {"FA (SF)"}
    assert all(o.pickup == "" for o in market.options if len(o.giving) == 1)


def test_a_points_trade_carries_both_teams_weeks_after_this_one() -> None:
    trade = _trade(_market(_league()), "M3", "B2")

    assert trade is not None
    assert {(row.team_id, row.week) for row in trade.scoring} == {(t, w) for t in "ab" for w in (6, 7)}
    assert trade.fixtures == ()


# ── the season it is measured against ───────────────────────────────────


def test_the_season_is_the_regular_season_left_with_this_weeks_banked_points() -> None:
    market = _market(_league(banked={"a": Totals(mean={POINTS: 100.0})}))

    season = market.season
    assert {(f.week, f.home, f.away) for f in season.fixtures} == {(5, "a", "c"), (6, "a", "b"), (7, "a", "c")}
    this_week = {row.team_id: row.mean for row in season.scoring if row.week == 5}
    assert this_week["a"] == pytest.approx(100.0 + 3 * 60.0)
    assert (season.mine, season.week, season.spots) == ("a", 5, 2)
    assert season.strength_error > 0


def test_the_market_counts_the_weeks_a_trade_changes_and_its_scale() -> None:
    market = _market(_league())

    assert (market.regular_weeks, market.playoff_weeks, market.measure) == (2, 1, "points")
    assert market.least_their_gain == THEIR_GAIN["points"]


def test_once_the_regular_season_is_over_there_is_no_market() -> None:
    assert build(_league(current=8)) is None


# ── a league won on categories ──────────────────────────────────────────


def _blocks(value: float) -> Profile:
    return Profile(value=value, mean={BLOCKS.label: value / 10}, variance={BLOCKS.label: 1.0})


def _category_league() -> League:
    """Blocks alone, C far ahead of you on them, so the nights a trade adds move your chance of the week."""
    values = VALUES | {"c1": 50.0, "m3": 28.0}
    return _league(profiles={key: _blocks(value) for key, value in values.items()}, categories=(Scored(BLOCKS.label),))


def test_a_category_season_is_settled_on_each_sides_chance_of_the_week() -> None:
    season = _market(_category_league()).season

    assert season.fixtures and all(f.chances is not None for f in season.fixtures)
    assert season.scoring == () and season.strength_error == 0.0


def test_a_category_trade_is_counted_in_categories_expected_and_replaces_the_chances_of_its_weeks() -> None:
    market = _market(_category_league())
    trade = _trade(market, "M3", "B2")

    assert market.measure == "categories"
    assert trade is not None and 0 < trade.points <= 1
    assert {(f.week, f.home, f.away) for f in trade.fixtures} == {(6, "a", "b"), (7, "a", "c")}
    assert trade.scoring == ()


def test_a_playoff_week_is_measured_against_the_field() -> None:
    """Nobody is drawn for week 8 yet, so it counts against B and C alike."""
    trade = _trade(_market(_category_league()), "M3", "B2")

    assert trade is not None and trade.playoff_points is not None


ROUNDED = ("BLK", "STL", "REB")


def _all_round(value: float) -> Profile:
    """A game giving a tenth of `value` in each of three counts."""
    return Profile(value=value, mean=dict.fromkeys(ROUNDED, value / 10), variance=dict.fromkeys(ROUNDED, 4.0))


def _chance_of_week_5(spreads: Uncertainty) -> float:
    profiles = {key: _all_round(value) for key, value in VALUES.items()}
    categories = tuple(Scored(label) for label in ROUNDED)
    league = _league(profiles=profiles, categories=categories, uncertainty=spreads)
    fixture = next(f for f in _market(league).season.fixtures if f.week == 5)
    assert fixture.chances is not None
    return fixture.chances[0]


def test_a_side_ahead_in_every_category_is_less_sure_of_the_week_when_they_move_together() -> None:
    """You lead C in all three; a week your roster plays more lifts all three at once, as one it plays less sinks
    them, so the week is a sweep or a wipe-out more often than independent categories would be."""
    independent = _chance_of_week_5(EXACT)
    together = _chance_of_week_5(replace(EXACT, loadings=dict.fromkeys(ROUNDED, 0.7)))

    assert 0.5 < together < independent


def test_a_trade_says_its_players_pricing_and_the_trade_talk_of_the_one_you_would_take_on() -> None:
    """M3 for B2: both priced off their blend; B2 in trade talk is said, M3's talk is no matter — he is moving."""
    league = replace(
        _league(),
        form={"m3": Stat(label="M3", value="priced 9.0 · Slump"), "b2": Stat(label="B2", value="priced 15.0 · Hot")},
        talk={"b2": "Fri 21 Nov: B2 a trade candidate", "m3": "Fri 21 Nov: M3 on the block"},
    )

    trade = _trade(_market(league), "M3", "B2")

    assert trade is not None
    lines = {line.label: line.value for line in trade.form}
    assert lines["M3"] == "priced 9.0 · Slump"
    assert "Hot" in lines["B2"] and "B2 a trade candidate" in lines["B2"]


def test_a_player_you_would_take_on_in_trade_talk_is_said_with_no_pricing_line_of_his_own() -> None:
    league = replace(_league(), talk={"b2": "Fri 21 Nov: B2 a trade candidate"})

    trade = _trade(_market(league), "M3", "B2")

    assert trade is not None
    assert [(line.label, "B2 a trade candidate" in line.value) for line in trade.form] == [("B2", True)]
