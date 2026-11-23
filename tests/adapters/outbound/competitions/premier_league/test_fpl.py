"""Tests for the Fantasy Premier League provider.

The assertions are mostly on what the prompt carries — the squad, the
fixtures, the market and the figures the provider computed — since a report
missing the captaincy or the transfer allowance is wrong however well it renders.
"""

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from support.fpl import (
    ENTRY_ID,
    H2H_LEAGUE_ID,
    LEAGUE_ID,
    MARKET,
    SQUAD_PLAYERS,
    WITH_CITY,
    FakeFPL,
    game,
    player,
    provider,
)

from thefrontoffice.adapters.outbound.competitions.premier_league.fpl import FPLProvider
from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLAPIError
from thefrontoffice.adapters.outbound.platforms.fpl.types import (
    ChipPlay,
    Club,
    Fixture,
    H2HMatch,
    Pick,
    Player,
    Squad,
    TableRow,
    TransferMade,
)
from thefrontoffice.domain.errors import InvalidRequestError, TeamNotFoundError
from thefrontoffice.domain.models import PlayerQuery

# ── configuration ───────────────────────────────────────────────────────


# ── leagues ─────────────────────────────────────────────────────────────


def test_only_invitational_leagues_are_listed() -> None:
    """Everyone is in Overall and in one league per gameweek; nobody competes there."""
    refs = provider().list_leagues()
    assert [ref.name for ref in refs] == ["Work League", "Hood h2h"]
    assert refs[0].league_id == LEAGUE_ID
    assert "3 of 12" in refs[0].detail


def test_a_manager_in_no_private_league_still_has_something_to_scout() -> None:
    refs = provider(leagues=[]).list_leagues()
    assert refs[0].league_id == str(ENTRY_ID)
    assert "overall rank 340,112" in refs[0].detail


# ── the squad ───────────────────────────────────────────────────────────


def test_the_squad_read_is_the_last_completed_gameweek() -> None:
    """Picks are published only once a deadline passes."""
    client = FakeFPL()
    FPLProvider(ENTRY_ID, client=client).roster(LEAGUE_ID)
    assert client.squad_requests == [4]


def test_before_the_season_there_is_no_squad_to_read() -> None:
    with pytest.raises(FPLAPIError):
        provider(upcoming=1).roster(LEAGUE_ID)


# ── the prompt ──────────────────────────────────────────────────────────


def test_the_prompt_shows_the_eleven_that_is_set_not_the_best_one() -> None:
    """Otherwise the changes block recommends starting someone already listed."""
    prompt = provider().build_context(LEAGUE_ID).prompt
    eleven = prompt.split("YOUR CURRENT ELEVEN")[1].split("BENCH")[0]
    assert "- P7 " in eleven
    assert "- P15 " not in eleven


def test_the_bench_keeps_its_substitution_order() -> None:
    """Auto-subs come on in the order the manager listed, so it is a decision."""
    bench = provider().build_context(LEAGUE_ID).prompt.split("BENCH (in substitution")[1].split("TO DO")[0]
    listed = [line.split()[1] for line in bench.splitlines() if line.startswith("- ")]
    assert listed == ["P2", "P12", "P14", "P15"]


def test_the_allowance_counts_from_the_week_after_the_squad_was_picked() -> None:
    """GW1 is picked free; GW2-4 each bank one on top of the first, so GW5 opens with four."""
    assert _headline()["Free transfers"] == "4"


def test_an_unused_allowance_rolls_up_to_its_cap() -> None:
    assert _headline(provider(upcoming=8))["Free transfers"] == "5"


def test_a_wildcard_week_neither_spends_nor_earns_a_transfer() -> None:
    assert _headline(provider(chips_played=[ChipPlay(name="wildcard", event=4)]))["Free transfers"] == "3"


def test_without_the_chips_played_the_allowance_falls_to_the_floor_of_one() -> None:
    """A Wildcard week would otherwise read as a week of no transfers, in the manager's favor."""
    assert _headline(provider(chips_error=FPLAPIError("down")))["Free transfers"] == "1"


def _bought(element_in: int, cost: int, event: int = 3) -> TransferMade:
    return TransferMade(
        element_in=element_in,
        element_in_cost=cost,
        element_out=500,
        event=event,
        time=datetime(2026, 8, 20, tzinfo=UTC),
    )


def test_a_transfer_is_priced_at_the_outgoing_players_selling_price() -> None:
    """P7 was bought at £4.0m and is now £5.0m, so he sells for £4.5m: the £5.5m P100 costs £1.0m, not £0.5m."""
    prompt = provider(transfers={ENTRY_ID: [_bought(7, 40)]}).build_context(LEAGUE_ID).prompt
    line = next(line for line in prompt.splitlines() if line.startswith("- P100 ") and "for P7 " in line)

    assert "sells for £4.5m" in line
    assert "costs £1.0m" in line


def test_without_the_transfer_history_a_sale_is_priced_at_the_current_price() -> None:
    prompt = provider(transfers_error=FPLAPIError("down")).build_context(LEAGUE_ID).prompt
    line = next(line for line in prompt.splitlines() if line.startswith("- P100 ") and "for P7 " in line)

    assert "sells for £5.0m" in line


def test_the_prompt_states_the_bank_in_the_games_own_units() -> None:
    assert "£3.0m" in provider(bank=30).build_context(LEAGUE_ID).situation


def test_the_constraints_quantify_what_the_best_shape_would_add() -> None:
    """A 4-4-2 starting P15 for P7 is the best shape, at the total the header shows."""
    context = provider(fixtures=WITH_CITY).build_context(LEAGUE_ID)
    lineup = next(stat for stat in context.headline if stat.label == "Lineup")
    best = lineup.value.split("best ")[1].removesuffix(" pts")

    assert "4-4-2" in context.constraints
    assert f"expecting {best}" in context.constraints


def test_a_chip_played_last_gameweek_is_flagged() -> None:
    assert "bboost" in provider(active_chip="bboost").build_context(LEAGUE_ID).constraints


def test_no_chip_is_flagged_when_none_was_played() -> None:
    assert "bboost" not in provider().build_context(LEAGUE_ID).constraints


def test_points_left_on_the_bench_are_flagged() -> None:
    assert "7 points" in provider(points_on_bench=7).build_context(LEAGUE_ID).situation


def test_the_mini_league_standing_is_carried() -> None:
    situation = provider().build_context(LEAGUE_ID).situation
    assert "Work League" in situation
    assert "3 of 12" in situation


# ── fixtures ────────────────────────────────────────────────────────────


def test_a_fixture_carries_its_difficulty_and_whether_it_is_at_home() -> None:
    prompt = provider().build_context(LEAGUE_ID).prompt
    arsenal = next(line for line in prompt.splitlines() if line.startswith("- ARS:"))

    assert "vs LIV" in arsenal and "2" in arsenal  # at home, to a difficulty of 2


def test_two_fixtures_in_one_gameweek_are_called_a_double() -> None:
    doubled = [
        Fixture(event=5, home="ARS", away="LIV", home_difficulty=2, away_difficulty=4),
        Fixture(event=5, home="MCI", away="ARS", home_difficulty=3, away_difficulty=5),
    ]
    [arsenal] = provider(fixtures=doubled).summary(LEAGUE_ID).fixtures

    assert arsenal.label == "ARS" and "double gameweek" in arsenal.value


@pytest.mark.parametrize(
    "read",
    [
        lambda fpl: fpl.build_context(LEAGUE_ID),
        lambda fpl: fpl.summary(LEAGUE_ID),
        lambda fpl: fpl.schedule(H2H_LEAGUE),
    ],
    ids=["report", "week", "season"],
)
def test_failed_fixtures_fail_the_page_rather_than_reading_as_blanks(read: Callable[[FPLProvider], object]) -> None:
    """A blank is the one thing the page most needs told; an outage must not pass for one."""
    with pytest.raises(FPLAPIError):
        read(provider(fixtures_error=FPLAPIError("down")))


# ── the market ──────────────────────────────────────────────────────────


def test_owned_players_are_not_offered_in_the_market() -> None:
    market = provider().build_context(LEAGUE_ID).candidate_lines
    assert "P8" not in market
    assert "P101" in market


def test_an_unavailable_player_is_not_offered() -> None:
    assert "P103" not in provider().build_context(LEAGUE_ID).candidate_lines


def _with_doubtful_target() -> dict[int, Player]:
    return {
        **SQUAD_PLAYERS,
        **MARKET,
        104: player(104, "MID", 9.2, cost=60, team="LIV", status="d", chance_of_playing=75),
    }


def test_a_doubtful_player_is_offered_in_the_market_as_he_is_counted_in_a_lineup() -> None:
    """One availability rule: a doubt is flagged, not ruled out, wherever a player is weighed."""
    market = provider(players=_with_doubtful_target()).free_agents(H2H_LEAGUE, PlayerQuery()).players
    doubtful = next(card for card in market if card.player_id == "104")

    assert (doubtful.columns["Status"], doubtful.ruled_out) == ("doubtful 75%", False)


def test_a_doubtful_player_is_in_the_prompts_market() -> None:
    assert "P104" in provider(players=_with_doubtful_target()).build_context(LEAGUE_ID).candidate_lines


def test_an_injured_player_is_kept_out_of_the_market_page() -> None:
    market = provider().free_agents(H2H_LEAGUE, PlayerQuery()).players
    assert "103" not in {card.player_id for card in market}


def test_a_list_of_the_market_fpl_does_not_offer_is_refused() -> None:
    with pytest.raises(InvalidRequestError):
        provider().free_agents(H2H_LEAGUE, PlayerQuery(view="Trending"))


def _headline(over: FPLProvider | None = None) -> dict[str, str]:
    context = (over or provider()).build_context(LEAGUE_ID)
    return {stat.label: stat.value for stat in context.headline}


def test_the_gameweeks_header_carries_its_money() -> None:
    assert _headline()["Bank"] == "£3.0m"


def test_the_gameweeks_header_leaves_the_seasons_points_to_the_league_view() -> None:
    """Points and rank answer how the season is going, which is the league view's question."""
    assert "Points" not in _headline()


def test_the_seasons_header_carries_its_standing() -> None:
    season = {stat.label: stat.value for stat in provider().schedule(LEAGUE_ID).headline}

    assert (season["Points"], season["Overall rank"], season["Mini-league"]) == ("412", "340,112", "3 of 12")


def test_points_left_on_the_bench_are_the_figure_that_warns() -> None:
    """The only entry that is a mistake rather than a fact."""
    context = provider().build_context(LEAGUE_ID)
    lineup = next(stat for stat in context.headline if stat.label == "Lineup")
    assert lineup.tone == "warning"


def test_an_optimal_eleven_leaves_nothing_on_the_bench_to_report() -> None:
    from support.fpl import effective_points

    from thefrontoffice.adapters.outbound.competitions.premier_league.rules import best_lineup

    best = best_lineup(list(SQUAD_PLAYERS.values()), effective_points)
    # Captained, because FPL always is — and the comparison only holds between
    # two elevens that each count a captain twice.
    picks = [
        Pick(element=p.id, position=i, multiplier=2 if p is best.captain else 1, is_captain=p is best.captain)
        for i, p in enumerate(best.starters, start=1)
    ]
    picks += [Pick(element=p.id, position=i, multiplier=0) for i, p in enumerate(best.bench, start=12)]
    squad = Squad(gameweek=4, picks=picks, bank=30, value=1004)

    context = FPLProvider(ENTRY_ID, client=FakeFPL(squad=squad, fixtures=WITH_CITY)).build_context(LEAGUE_ID)
    lineup = next(stat for stat in context.headline if stat.label == "Lineup")
    assert lineup.tone == "neutral"


def test_a_manager_in_no_mini_league_gets_no_mini_league_figure() -> None:
    season = provider(leagues=[]).schedule(LEAGUE_ID).headline

    assert "Mini-league" not in {stat.label for stat in season}


def test_the_header_says_when_the_gameweek_locks() -> None:
    """A transfer after the deadline counts for the week after it. The gameweek itself is in the page's title."""
    labels = _headline()

    assert labels["Deadline"].endswith("UTC") and "Gameweek" not in labels


# ── the league beyond this gameweek ─────────────────────────────────────

H2H_LEAGUE = "950"


def test_the_season_lists_every_gameweek_with_its_deadline() -> None:
    """A gameweek is bounded by its deadline: after it nothing can change."""
    season = provider().schedule(H2H_LEAGUE).season

    assert [row.label for row in season[:3]] == ["Gameweek 1", "Gameweek 2", "Gameweek 3"]
    assert season[0].date == "Sat 8 Aug, 17:30"


def test_a_played_gameweek_carries_its_tie_and_whether_it_was_won() -> None:
    season = {row.label: row for row in provider(finished=3).schedule(H2H_LEAGUE).season}

    assert season["Gameweek 1"].result == "60-44"
    assert season["Gameweek 1"].outcome == "won"
    assert season["Gameweek 2"].outcome == "lost"


def test_the_row_marked_now_is_the_one_being_played() -> None:
    """Not the next deadline. The week view and the season table have to agree
    about which row is "now", or one of them is describing a different week."""
    season = {row.label: row for row in provider().schedule(H2H_LEAGUE).season}
    current = [row.label for row in season.values() if row.is_current]

    assert current == ["Gameweek 4"]
    assert season["Gameweek 4"].result == ""  # in progress is not a result


def test_a_finished_gameweek_has_its_result_and_the_next_is_now() -> None:
    """FPL keeps a finished gameweek current until the next deadline; its result is in, and the row
    marked now is the next one."""
    fake = FakeFPL(
        finished=4, h2h_season={4: H2HMatch(opponent_entry=99, opponent_name="R", my_points=40, opponent_points=61)}
    )
    season = {row.label: row for row in FPLProvider(ENTRY_ID, client=fake).schedule(H2H_LEAGUE).season}

    assert (season["Gameweek 4"].result, season["Gameweek 4"].outcome) == ("40-61", "lost")
    assert [label for label, row in season.items() if row.is_current] == ["Gameweek 5"]


def test_a_tie_in_a_gameweek_not_yet_finished_has_no_result() -> None:
    """A 0-0 for a week nobody has kicked a ball in is not a draw."""
    season = {row.label: row for row in provider(finished=2).schedule(H2H_LEAGUE).season}

    assert season["Gameweek 3"].result == ""


def test_a_classic_league_has_deadlines_but_no_opponents() -> None:
    """It is a running table, not a set of fixtures — and the calendar is
    still what somebody came for."""
    season = provider().schedule("900").season

    assert all(row.opponent == "" for row in season)
    assert all(row.date for row in season)


def test_the_table_says_which_row_is_yours() -> None:
    standings = provider().schedule(H2H_LEAGUE).standings

    assert [row.name for row in standings] == ["Rival FC", "Front Office FC"]
    assert [row.is_mine for row in standings] == [False, True]


def test_an_h2h_table_shows_league_points_and_the_tiebreak() -> None:
    """The table is on league points; the FPL total decides ties."""
    standings = provider().schedule(H2H_LEAGUE).standings

    assert standings[0].points == "6 (104 pts)"
    assert standings[0].record == "2W 0D 0L"


def test_a_classic_table_is_just_the_points() -> None:
    standings = provider().schedule("900").standings

    assert standings[0].points == "6"


def test_the_matches_carry_a_difficulty_for_each_side() -> None:
    """A fixture is easy for one of these clubs and hard for the other."""
    matches = provider().schedule(H2H_LEAGUE).matches

    assert matches
    assert all("FDR" in m.detail for m in matches)


@pytest.mark.parametrize(
    "read", [lambda fpl: fpl.schedule(H2H_LEAGUE), lambda fpl: fpl.teams(H2H_LEAGUE)], ids=["season", "teams"]
)
def test_a_failed_table_is_an_error_not_an_empty_league(read: Callable[[FPLProvider], object]) -> None:
    """The table is the membership list, and nobody in it is not the same as not knowing who is."""
    with pytest.raises(FPLAPIError):
        read(provider(standings_error=FPLAPIError("down")))


def test_a_failed_h2h_season_still_lists_the_gameweeks() -> None:
    schedule = provider(h2h_season_error=FPLAPIError("down")).schedule(H2H_LEAGUE)

    assert schedule.season
    assert all(row.opponent == "" for row in schedule.season)


def test_the_week_view_shows_the_gameweek_being_played_until_its_deadline() -> None:
    """The bug this distinction exists for: on a Saturday in August the week
    you can still act on is next week's, and the one being played — where the
    points are landing — is this one."""
    assert provider().summary(H2H_LEAGUE).window == "Gameweek 4 · deadline Tue 11 Aug, 17:30"


# ── the rest of the league ──────────────────────────────────────────────


def test_the_teams_list_puts_you_first() -> None:
    teams = provider().teams(H2H_LEAGUE)

    assert teams[0].is_mine
    assert teams[0].name == "Front Office FC"


def test_the_overall_standing_has_no_teams_to_browse() -> None:
    """Offered to a manager in no private league: a place in a field of millions, not a table."""
    assert provider(leagues=[]).teams(str(ENTRY_ID)) == []


def test_another_managers_squad_comes_back_in_your_own_columns() -> None:
    p = provider()

    mine = p.roster(H2H_LEAGUE)
    theirs = p.roster_of(H2H_LEAGUE, "99")

    assert set(theirs[0].columns) == set(mine[0].columns)


def test_a_team_id_that_is_not_an_entry_is_refused() -> None:
    with pytest.raises(TeamNotFoundError):
        provider().roster_of(H2H_LEAGUE, "not-a-number")


def test_the_market_excludes_what_you_already_own() -> None:
    """FPL has no waiver wire — every player is buyable — so the question is
    not who is free but who is worth the money."""
    owned = {int(card.player_id) for card in provider().roster(H2H_LEAGUE)}

    market = {int(card.player_id) for card in provider().free_agents(H2H_LEAGUE, PlayerQuery()).players}

    assert not (owned & market)


def test_the_market_is_ranked_on_worth_not_on_the_games_projection() -> None:
    """P104 projects lower than P102, but at home to an easy side where P102 is away at a hard one."""
    players = {**SQUAD_PLAYERS, **MARKET, 104: player(104, "FWD", 7.5, cost=60, team="ARS")}
    market = provider(players=players).free_agents(H2H_LEAGUE, PlayerQuery()).players
    worths = [card.values["Worth"] for card in market]
    order = [card.player_id for card in market]

    assert worths == sorted(worths, reverse=True)
    assert order.index("104") < order.index("102")


def test_the_market_has_no_lineup_column() -> None:
    """A player you do not own is not in a lineup of yours."""
    assert "Slot" not in provider().free_agents(H2H_LEAGUE, PlayerQuery()).players[0].columns


# ── the way across to the platform ──────────────────────────────────────


def test_a_head_to_head_league_links_to_its_own_kind_of_table() -> None:
    """The two formats are different pages: a h2h league opened as a classic
    one shows a table it does not play by."""
    refs = {ref.name: ref.url for ref in provider().list_leagues()}

    assert refs["Hood h2h"].endswith("/leagues/950/standings/h")
    assert refs["Work League"].endswith("/leagues/900/standings/c")


def test_a_team_links_to_that_managers_entry() -> None:
    teams = {t.name: t.url for t in provider().teams(H2H_LEAGUE)}

    assert teams["Rival FC"] == "https://fantasy.premierleague.com/entry/99/event/4"


def test_a_gameweeks_matches_carry_their_score_once_kicked_off() -> None:
    fake = FakeFPL(
        fixtures=[
            Fixture(
                event=3,
                home="ARS",
                away="LIV",
                home_difficulty=2,
                away_difficulty=4,
                started=True,
                home_score=2,
                away_score=1,
            ),
            Fixture(event=3, home="TOT", away="CHE", home_difficulty=3, away_difficulty=3),
        ]
    )
    games = {
        (m.home, m.away): (m.home_score, m.away_score)
        for m in FPLProvider(ENTRY_ID, client=fake).games_of("900", 3).games
    }

    assert games == {("ARS", "LIV"): (2, 1), ("TOT", "CHE"): (None, None)}


def test_a_gameweeks_blanks_are_the_clubs_with_no_match_in_it() -> None:
    fake = FakeFPL(
        clubs=[Club(short_name=c, name=c, code=i) for i, c in enumerate(("ARS", "TOT", "CHE", "LIV"))],
        fixtures=[Fixture(event=3, home="ARS", away="LIV", home_difficulty=2, away_difficulty=4)],
    )

    assert FPLProvider(ENTRY_ID, client=fake).games_of("900", 3).byes == ["CHE", "TOT"]


def test_a_gameweek_with_no_matches_listed_has_no_blanks_either() -> None:
    assert FPLProvider(ENTRY_ID, client=FakeFPL(fixtures=[])).games_of("900", 3).byes == []


# ── who is in each match ────────────────────────────────────────────────


def test_a_match_names_your_players_in_it_starters_first() -> None:
    [game] = provider().games_of(H2H_LEAGUE, 4).games
    yours = [ref.name for ref in game.yours]

    assert yours[:2] == ["P1", "P3"]  # the keeper and the first defender, as picked
    assert "P15" not in yours  # MCI, not in this match
    assert game.theirs  # the opponent fields the same fake fifteen


def test_a_classic_league_match_names_only_your_players() -> None:
    [game] = provider().games_of(LEAGUE_ID, 4).games

    assert game.yours and not game.theirs


def test_the_schedules_matches_name_your_players_too() -> None:
    assert any(m.yours for m in provider().schedule(H2H_LEAGUE).matches)


# ── the league's transfers ──────────────────────────────────────────────


def _moved(element_in: int, element_out: int, event: int, day: int) -> TransferMade:
    return TransferMade(
        element_in=element_in,
        element_in_cost=50,
        element_out=element_out,
        event=event,
        time=datetime(2026, 8, day, 12, tzinfo=UTC),
    )


TRANSFERS = {
    ENTRY_ID: [_moved(100, 7, event=3, day=20), _moved(101, 12, event=3, day=20)],
    99: [_moved(102, 14, event=4, day=27), _moved(13, 101, event=1, day=2)],
}


def test_the_activity_is_each_managers_transfers_one_row_per_gameweek_newest_first() -> None:
    activity = provider(transfers=TRANSFERS).schedule(H2H_LEAGUE).activity

    assert [(row.who, row.what, row.is_mine) for row in activity] == [
        ("Rival FC", "GW4 · 1 transfer", False),
        ("Front Office FC", "GW3 · 2 transfers", True),
    ]
    assert activity[1].detail == "+P100, +P101, -P7, -P12"
    assert [(m.player_id, m.change) for m in activity[0].moves] == [("102", "added"), ("14", "dropped")]


def test_a_wildcards_transfers_are_called_one() -> None:
    activity = (
        provider(transfers=TRANSFERS, chips_played=[ChipPlay(name="wildcard", event=3)]).schedule(H2H_LEAGUE).activity
    )

    assert activity[-1].what == "GW3 · Wildcard"


def test_a_manager_whose_transfers_will_not_load_is_left_out_not_the_page() -> None:
    assert provider(transfers_error=FPLAPIError("down")).schedule(H2H_LEAGUE).activity == []


def test_a_classic_leagues_activity_covers_its_table() -> None:
    table = [TableRow(rank=1, entry=ENTRY_ID, entry_name="Front Office FC", manager="Me", total=412)]
    activity = provider(transfers=TRANSFERS, standings=table).schedule(LEAGUE_ID).activity

    assert [row.who for row in activity] == ["Front Office FC"]


# ── what degrades and what fails ────────────────────────────────────────


def test_matches_without_a_squad_to_read_still_list_the_games() -> None:
    games = provider(squad_error=FPLAPIError("down")).games_of(H2H_LEAGUE, 4).games

    assert games and not games[0].yours and not games[0].theirs


# ── finding a player ────────────────────────────────────────────────────


def test_any_player_in_the_game_is_found_by_name_the_most_owned_first() -> None:
    catalog = {
        **SQUAD_PLAYERS,
        200: replace(player(200, "DEF", 5.0, team="ARS"), name="Saliba", full_name="William Saliba", selected_by=30.0),
        201: replace(player(201, "FWD", 4.0, team="NEW"), name="Salia", full_name="Vakhtang Salía", selected_by=0.1),
    }
    found = provider(players=catalog).search_players(H2H_LEAGUE_ID, "sali")

    assert [(r.player_id, r.name, r.detail) for r in found] == [
        ("200", "William Saliba", "DEF · ARS · £5.0m"),
        ("201", "Vakhtang Salía", "FWD · NEW · £5.0m"),
    ]


def test_a_search_too_short_to_mean_anyone_finds_nobody() -> None:
    assert provider().search_players(LEAGUE_ID, "p") == []


def test_a_search_is_capped_at_the_limit() -> None:
    assert len(provider().search_players(LEAGUE_ID, "player", limit=3)) == 3


# ── the weeks ahead ─────────────────────────────────────────────────────


def test_the_weeks_ahead_read_five_gameweeks_from_the_next_deadline() -> None:
    season = [Fixture(event=w, home="ARS", away="LIV", home_difficulty=2, away_difficulty=4) for w in range(5, 12)]
    found = provider(season_fixtures=season).weeks_ahead(LEAGUE_ID)

    assert found.run_weeks == [5, 6, 7, 8, 9]
    # Man City's two blank every week of a list that has only Arsenal in it.
    assert {run.player for run in found.runs} == {"P2", "P15"}
    assert found.clear == 13


def test_another_managers_weeks_ahead_are_his_own_squad() -> None:
    fake = FakeFPL()
    FPLProvider(ENTRY_ID, client=fake).weeks_ahead(LEAGUE_ID, "99")
    assert fake.squad_requests  # read a squad, not refused


def test_a_team_id_that_is_no_entry_is_refused() -> None:
    with pytest.raises(TeamNotFoundError):
        provider().weeks_ahead(LEAGUE_ID, "nope")


def test_nothing_is_ahead_once_every_gameweek_is_finished() -> None:
    assert provider(finished=38).weeks_ahead(LEAGUE_ID).run_weeks == []


# ── the tie, simulated ──────────────────────────────────────────────────


def test_a_head_to_head_tie_is_simulated_from_both_squads() -> None:
    fake = FakeFPL(games={8: [game(3, 10), game(4, 2)]})
    found = FPLProvider(ENTRY_ID, client=fake).matchup_input(H2H_LEAGUE_ID)

    assert found is not None
    assert [o.player_id for o in found.mine].count("8") == 2  # the captain, twice
    assert len(found.theirs) >= 11
    assert [sorted(ids) for ids in fake.summary_requests] == [sorted(SQUAD_PLAYERS)]  # one read, everyone once


def test_the_same_tie_is_the_same_simulation_between_reloads() -> None:
    first = provider().matchup_input(H2H_LEAGUE_ID)
    again = provider().matchup_input(H2H_LEAGUE_ID)
    assert first is not None and again is not None
    assert first.seed == again.seed


def test_a_classic_league_has_no_tie_to_simulate() -> None:
    assert provider().matchup_input(LEAGUE_ID) is None


def test_a_gameweek_without_a_tie_is_not_simulated() -> None:
    assert provider(h2h_match_error=FPLAPIError("down")).matchup_input(H2H_LEAGUE_ID) is None


def test_the_market_is_not_priced_against_one_tie() -> None:
    assert provider().matchup_input(H2H_LEAGUE_ID, candidates=["100"]) is None


def test_no_played_gameweek_is_rebuilt_for_a_backtest() -> None:
    fpl = provider()
    assert fpl.played_weeks(H2H_LEAGUE_ID) == []
    assert fpl.played_matchups(H2H_LEAGUE_ID, 3) == []


# ── the to-do list in the prompt ────────────────────────────────────────


def test_the_prompt_numbers_the_same_to_do_list_the_page_shows() -> None:
    fake = provider(fixtures=WITH_CITY)
    context = fake.build_context(LEAGUE_ID)
    shown = fake.summary(LEAGUE_ID).actions or []

    assert [task.key for task in context.tasks] == [item.key for item in shown]
    assert all(f"T{i} " in context.prompt for i in range(1, len(context.tasks) + 1))


def test_a_player_a_to_do_item_moves_is_listed_so_a_model_move_does_not_repeat_it() -> None:
    context = provider(fixtures=WITH_CITY).build_context(LEAGUE_ID)

    assert {"P15", "P7"} <= context.listed


def test_every_squad_line_carries_his_worth_beside_fpls_projection() -> None:
    context = provider(fixtures=WITH_CITY).build_context(LEAGUE_ID)

    assert "worth 9.9" in context.roster_lines["P15"]  # 9.0 at home to a difficulty-2 side
    assert "FPL xPts 9.0" in context.roster_lines["P15"]


def test_the_header_names_the_captain_at_double_his_worth_with_his_vice() -> None:
    assert _headline(provider(fixtures=WITH_CITY))["Captain"] == "P15 19.8 · vice P8"


def test_a_search_puts_the_player_worth_more_first_however_few_own_him() -> None:
    catalog = {
        **SQUAD_PLAYERS,
        200: replace(player(200, "DEF", 2.0, team="ARS"), name="Saliba", full_name="William Saliba", selected_by=30.0),
        201: replace(player(201, "DEF", 6.0, team="LIV"), name="Salia", full_name="Vakhtang Salía", selected_by=0.1),
    }

    found = provider(players=catalog).search_players(H2H_LEAGUE_ID, "sali")

    assert [r.player_id for r in found] == ["201", "200"]


def test_a_tie_still_to_come_is_simulated_around_each_players_worth() -> None:
    """GW4 is over, so the tie is GW5's: P8's range keeps its spread and moves to his worth a match.

    His worth does not read his log, so a log twice as hot draws the same mean — only the spread is his own.
    """

    def captain(log: list[int]) -> tuple[float, ...]:
        fake = FakeFPL(finished=4, live={}, games={8: [game(3 + i, p) for i, p in enumerate(log)]})
        found = FPLProvider(ENTRY_ID, client=fake).matchup_input(H2H_LEAGUE_ID)
        assert found is not None
        return next(o for o in found.mine if o.player_id == "8").samples

    cold, hot = captain([4, 12]), captain([8, 24])

    assert sum(cold) / 2 == pytest.approx(sum(hot) / 2, abs=0.01)
    assert sum(cold) / 2 != pytest.approx(8.0)  # not the mean of his log
    assert cold[1] == pytest.approx(3 * cold[0], abs=0.05)  # 12 against 4, as he scored them
