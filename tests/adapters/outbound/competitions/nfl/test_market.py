"""Tests for finding trades worth offering: `nfl/market.py`."""

from dataclasses import replace

from support.nfl import SLEEPER_USER_ID, FakeSleeper, game_line, nfl_provider, proj

from thefrontoffice.adapters.outbound.platforms.sleeper.types import PlayerMeta, SleeperMatchup, SleeperRoster
from thefrontoffice.domain.models import TradeMarket, TradeOption

# You hold two quarterbacks and no receiver; they hold receivers and no quarterback.
PROJECTIONS = {
    "qb1": proj("qb1", "Star QB", "QB", 22.0),
    "qb2": proj("qb2", "Spare QB", "QB", 15.0),
    "rb1": proj("rb1", "Good RB", "RB", 18.0),
    "wr1": proj("wr1", "Top WR", "WR", 14.0),
    "wr2": proj("wr2", "Next WR", "WR", 12.0),
    "wr3": proj("wr3", "Third WR", "WR", 10.0),
    "k1": proj("k1", "Big Leg", "K", 9.0),
    "k2": proj("k2", "Short Leg", "K", 7.0),
}


def _client(week: int = 7, deadline: int = 11, playoff_teams: int = 1, **mine: list[str]) -> FakeSleeper:
    client = FakeSleeper(
        projections=PROJECTIONS,
        rosters=[
            SleeperRoster(
                roster_id=1,
                owner_id=SLEEPER_USER_ID,
                player_ids=["qb1", "qb2", "rb1", "k2"],
                starter_ids=["qb1", "rb1"],
                reserve_ids=mine.get("reserve", []),
                wins=3,
            ),
            SleeperRoster(
                roster_id=2, owner_id="user-2", player_ids=["wr1", "wr2", "wr3", "k1"], starter_ids=[], wins=3
            ),
        ],
        matchups=[SleeperMatchup(roster_id=1, matchup_id=1), SleeperMatchup(roster_id=2, matchup_id=1)],
    )
    client.players_catalog = {
        pid: PlayerMeta(player_id=pid, name=p.name, position=p.position) for pid, p in PROJECTIONS.items()
    }
    client.week = week
    client.league = replace(client.league, playoff_teams=playoff_teams, playoff_week_start=10, trade_deadline=deadline)
    return client


def _add(client: FakeSleeper, pid: str, name: str, position: str, points: float) -> None:
    """A player the platform knows and projects; on nobody's roster unless a test puts him there."""
    client.players_catalog = {
        **(client.players_catalog or {}),
        pid: PlayerMeta(player_id=pid, name=name, position=position),
    }
    client.projections = {**client.projections, pid: proj(pid, name, position, points)}


def _market(client: FakeSleeper) -> TradeMarket:
    market = nfl_provider(client).trade_market("L1")
    assert market is not None
    return market


def test_a_spare_at_one_position_is_offered_for_what_they_have_at_another() -> None:
    best, *_ = _market(_client()).options

    assert (best.giving, best.receiving, best.team_id) == (("Spare QB (QB)",), ("Top WR (WR)",), "2")
    assert best.points > 0 and best.their_points > 0


def test_every_trade_offered_helps_your_lineup_and_the_best_for_you_comes_first() -> None:
    options = _market(_client()).options

    assert options and all(o.points > 0 for o in options)
    assert [o.points for o in options] == sorted((o.points for o in options), reverse=True)


def test_a_trade_rescores_both_teams_from_the_week_after_this_one() -> None:
    """It lands after the league's review, by which time this week's lineups are set."""
    option, *_ = _market(_client()).options

    assert {(row.team_id, row.week) for row in option.scoring} == {(t, w) for t in ("1", "2") for w in (8, 9)}


def test_a_kicker_is_never_traded_for() -> None:
    """Both sides stream one from the wire, so the better kicker is not on offer."""
    options = _market(_client()).options

    assert not any("(K)" in name for option in options for name in option.giving + option.receiving)


def test_a_player_in_injured_reserve_is_not_offered() -> None:
    options = _market(_client(reserve=["qb2"])).options

    assert not any("Spare QB (QB)" in option.giving for option in options)


def test_a_trade_that_does_nothing_for_their_lineup_is_still_found_and_says_so() -> None:
    """Whether they take it depends on whether they are still chasing a place, which the season engine knows."""
    client = _client()
    # With a quarterback of their own, your spare does nothing for them.
    client.rosters[1] = replace(client.rosters[1], player_ids=[*client.rosters[1].player_ids, "qb9"])
    _add(client, "qb9", "Their QB", "QB", 20.0)

    spare = [o for o in _market(client).options if o.giving == ("Spare QB (QB)",)]

    assert spare and all(o.their_points <= 0 for o in spare)


def test_a_player_in_their_reserve_slot_does_not_fill_their_lineup() -> None:
    """Their quarterback is on injured reserve, so your spare one still starts for them."""
    client = _client()
    client.rosters[1] = replace(
        client.rosters[1], player_ids=[*client.rosters[1].player_ids, "qb9"], reserve_ids=["qb9"]
    )
    _add(client, "qb9", "Their QB", "QB", 20.0)

    assert any(option.giving == ("Spare QB (QB)",) and option.their_points > 0 for option in _market(client).options)


def test_past_the_deadline_there_is_no_market() -> None:
    assert nfl_provider(_client(week=8, deadline=7)).trade_market("L1") is None


def test_the_last_week_before_the_playoffs_has_nothing_left_for_a_trade_to_change() -> None:
    assert nfl_provider(_client(week=9)).trade_market("L1") is None


def test_a_trade_worth_far_less_than_it_costs_them_is_not_offered() -> None:
    """A quarterback nearly as good sits on the wire, so your spare is worth a point a week, not a top receiver."""
    client = _client()
    _add(client, "qb8", "Wire QB", "QB", 14.0)

    assert not any(option.giving == ("Spare QB (QB)",) for option in _market(client).options)


# ── two for one ─────────────────────────────────────────────────────────


def _star_on_offer() -> FakeSleeper:
    """They hold a receiver worth more than any one player of yours, and you hold two who come near him together."""
    client = _client()
    _add(client, "wr0", "Star WR", "WR", 30.0)
    _add(client, "rb2", "Spare RB", "RB", 16.0)
    client.rosters[0] = replace(client.rosters[0], player_ids=[*client.rosters[0].player_ids, "rb2"])
    client.rosters[1] = replace(client.rosters[1], player_ids=[*client.rosters[1].player_ids, "wr0"])
    return client


def _for_the_star(client: FakeSleeper) -> dict[tuple[str, ...], TradeOption]:
    return {o.giving: o for o in _market(client).options if o.receiving == ("Star WR (WR)",)}


def test_two_for_one_is_offered_where_no_one_player_is_enough() -> None:
    star = _for_the_star(_star_on_offer())

    assert star and all(len(giving) == 2 for giving in star)
    assert ("Spare QB (QB)", "Spare RB (RB)") in star


def test_two_for_one_is_not_offered_where_one_would_do() -> None:
    """Throwing in a second player for a trade one already makes fair is giving him away."""
    options = _market(_client()).options

    assert not any(len(o.giving) > 1 and o.receiving == ("Next WR (WR)",) for o in options)


def test_the_spot_two_for_one_frees_names_the_free_agent_who_helps_most() -> None:
    client = _star_on_offer()
    _add(client, "rb9", "Wire RB", "RB", 9.0)

    options = _market(client).options

    assert {o.pickup for o in options if len(o.giving) == 2} == {"Wire RB (RB)"}
    assert all(o.pickup == "" for o in options if len(o.giving) == 1)


def test_the_free_agent_is_named_but_not_counted_in_what_the_trade_is_worth() -> None:
    """A drop could open the spot anyway, so the pickup is not something only the trade allows."""
    client = _star_on_offer()
    _add(client, "rb9", "Wire RB", "RB", 9.0)

    before, after = _for_the_star(_star_on_offer()), _for_the_star(client)

    # A running back on the wire also makes yours worth less to them, so compare the offers both find.
    both = before.keys() & after.keys()
    assert both and all(after[g].points == before[g].points for g in both)


# ── the playoff weeks ───────────────────────────────────────────────────


def test_a_trade_says_what_it_does_to_your_lineup_in_the_playoff_weeks() -> None:
    best, *_ = _market(_client(playoff_teams=4)).options

    assert best.playoff_points is not None and best.playoff_points > 0


def test_the_playoff_weeks_never_enter_the_season_simulated_for_the_table() -> None:
    option, *_ = _market(_client(playoff_teams=4)).options

    assert {row.week for row in option.scoring} == {8, 9}


def test_playoff_weeks_nobody_has_projected_yet_leave_the_playoff_figure_out() -> None:
    client = _client(playoff_teams=4)
    client.weekly_projections = {10: {}, 11: {}}

    assert all(o.playoff_points is None for o in _market(client).options)


def test_a_league_whose_playoffs_are_one_round_still_prices_them() -> None:
    """Two teams, one week of playoffs: the bracket is the final."""
    best, *_ = _market(_client(playoff_teams=2)).options

    assert best.playoff_points is not None


# ── form ────────────────────────────────────────────────────────────────


def _hot(client: FakeSleeper, pid: str, points: float) -> FakeSleeper:
    """He has scored `points` in every game this season, whatever he is projected."""
    client.game_lines = [
        game_line(pid, week, off_snp=50, tm_off_snp=60, rec_tgt=8, pts_ppr=points) for week in range(1, client.week)
    ]
    return client


def _top_wr(market: TradeMarket) -> TradeOption:
    return next(o for o in market.options if o.receiving == ("Top WR (WR)",))


def test_a_player_scoring_past_his_projection_is_priced_by_his_games_and_says_so() -> None:
    plain, hot = _top_wr(_market(_client())), _top_wr(_market(_hot(_client(), "wr1", 24.0)))

    assert hot.points > plain.points
    [line] = hot.form
    assert line.label == "Top WR" and "projected 14.0" in line.value
    assert not plain.form


def test_the_season_a_trade_is_measured_against_is_priced_by_form_too() -> None:
    """A league priced by projection and a trade by form would credit the trade with the difference."""

    def theirs(market: TradeMarket) -> float:
        return next(row.mean for row in market.season.scoring if (row.team_id, row.week) == ("2", 8))

    assert theirs(_market(_hot(_client(), "wr1", 24.0))) > theirs(_market(_client()))
