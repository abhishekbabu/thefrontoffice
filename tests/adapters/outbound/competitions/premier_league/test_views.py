"""Tests for how an FPL player reads: a squad or market row, and the drawer that opens on him."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from support.fpl import (
    DOUBTFUL_P3,
    LEAGUE_ID,
    MARKET,
    SQUAD_PLAYERS,
    game,
    player,
    provider,
)

from thefrontoffice.adapters.outbound.competitions.premier_league.fpl import FPLProvider
from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLAPIError
from thefrontoffice.adapters.outbound.platforms.fpl.types import Fixture, Player
from thefrontoffice.domain.errors import PlayerNotFoundError
from thefrontoffice.domain.models import PlayerDetail, Stat, StatTable


def _by_season(detail: PlayerDetail) -> StatTable:
    return next(t for t in detail.tables if t.title == "By season")


def _table(detail: PlayerDetail, title: str) -> StatTable:
    return next(t for t in detail.tables if t.title == title)


def _group(detail: PlayerDetail, title: str) -> dict[str, Stat]:
    return {s.label: s for s in next(g for g in detail.groups if g.title == title).stats}


# ── the squad ───────────────────────────────────────────────────────────


def test_roster_rows_mark_the_captain_and_the_bench() -> None:
    rows = {c.columns["Player"]: c.columns for c in provider().roster(LEAGUE_ID)}
    assert rows["P8"]["Slot"] == "C"
    assert rows["P3"]["Slot"] == "XI"
    assert rows["P15"]["Slot"] == "BN"
    assert rows["P3"]["Price"] == "£5.0m"


def test_roster_rows_report_a_doubt() -> None:
    cards = {c.columns["Player"]: c for c in provider(players=DOUBTFUL_P3).roster(LEAGUE_ID)}
    assert cards["P3"].columns["Status"] == "doubtful 50%"
    assert not cards["P3"].ruled_out  # a doubt is flagged, not counted out


def test_roster_rows_say_who_is_ruled_out() -> None:
    players = {**SQUAD_PLAYERS, 3: player(3, "DEF", 6.0, status="i", chance_of_playing=0), **MARKET}
    cards = {c.columns["Player"]: c for c in provider(players=players).roster(LEAGUE_ID)}
    assert cards["P3"].ruled_out


# ── one player ──────────────────────────────────────────────────────────


def test_a_player_carries_the_numbers_fpl_judges_them_on() -> None:
    """Expected goals arrive in the same payload as the price, which is why
    this sport needs no second stats provider."""
    detail = provider().player(LEAGUE_ID, "8")
    labels = {stat.label for group in detail.groups for stat in group.stats}

    assert detail.name == "Player 8"
    assert {"xG", "xA", "xGI", "Form", "Owned by", "Price"} <= labels


def test_a_players_fixture_is_for_the_gameweek_still_open() -> None:
    detail = provider().player(LEAGUE_ID, "8")
    assert any(stat.label == "Fixture" for group in detail.groups for stat in group.stats)


def test_a_flagged_player_is_toned_and_carries_the_news() -> None:
    hurt = player(3, "DEF", 6.0, status="i", chance_of_playing=0, news="Hamstring - expected back 12 Sep")
    detail = provider(players={**SQUAD_PLAYERS, 3: hurt, **MARKET}).player(LEAGUE_ID, "3")

    assert detail.tone == "warning"
    assert "Hamstring" in detail.note


def test_an_unknown_player_is_refused_by_name() -> None:
    with pytest.raises(PlayerNotFoundError, match="nope"):
        provider().player(LEAGUE_ID, "nope")


def test_a_players_numbers_are_grouped_rather_than_listed() -> None:
    """Twenty figures in one list is a wall; the same twenty under headings can
    be read without looking for anything."""
    titles = [group.title for group in provider().player(LEAGUE_ID, "8").groups]

    assert titles == ["This week", "Underlying", "Set pieces", "Market"]


def test_set_pieces_list_only_the_duties_actually_held() -> None:
    """ "Not on penalties" for every player who is not would be rows of nothing."""
    taker = player(8, "MID", 8.0, penalties_order=1, corners_order=2)
    detail = provider(players={**SQUAD_PLAYERS, 8: taker, **MARKET}).player(LEAGUE_ID, "8")
    pieces = next(g for g in detail.groups if g.title == "Set pieces")

    assert [(s.label, s.value) for s in pieces.stats] == [("Penalties", "#1"), ("Corners", "#2")]
    assert pieces.stats[0].tone == "good"  # first choice is worth noticing
    assert pieces.stats[0].better == "lower"  # and first beats second in a comparison


def test_a_player_on_no_set_pieces_says_so_once() -> None:
    pieces = next(g for g in provider().player(LEAGUE_ID, "8").groups if g.title == "Set pieces")
    assert [s.value for s in pieces.stats] == ["none"]


def test_a_keeper_gets_the_numbers_only_a_keeper_has() -> None:
    """Saves on an attacker is a zero nobody asked for."""
    labels = {row.label for row in _by_season(provider().player(LEAGUE_ID, "1")).rows}
    assert {"Saves", "Clean sheets", "Conceded"} <= labels


def test_an_attacker_is_not_given_a_keepers_line() -> None:
    labels = {row.label for row in _by_season(provider().player(LEAGUE_ID, "13")).rows}
    assert "Saves" not in labels


# ── the seasons behind the price ────────────────────────────────────────


def _season_table(over: FPLProvider | None = None) -> dict[str, list[str]]:
    """The by-season table as {row label: values}, columns newest first."""
    detail = (over or provider()).player(LEAGUE_ID, "8")
    table = _by_season(detail)
    return {"__columns__": table.columns, **{row.label: row.values for row in table.rows}}


def test_the_seasons_are_columns_so_they_can_be_read_across() -> None:
    """A stack makes you hold last year's goals in your head while scrolling
    to this year's."""
    table = _season_table()

    assert table["__columns__"] == ["2025/26", "2024/25", "2023/24"]


def test_a_season_nobody_has_played_yet_reports_nothing() -> None:
    """A column of noughts claims the season has answers it does not have."""
    table = _season_table()

    assert table["Points"][0] == "N/A"
    assert table["Goals"][0] == "N/A"


def test_a_finished_season_is_scored_per_start_not_per_appearance() -> None:
    """A substitute cameo and a full ninety are not the same denominator."""
    assert _season_table()["Per start"][1] == f"{210 / 33:.1f}"


def test_a_finished_season_carries_the_markets_verdict_on_it() -> None:
    """What the price did over it is the closest thing FPL has to one."""
    assert _season_table()["Price"][1] == "£11.8m → £12.4m"


def test_a_price_is_known_whether_or_not_the_season_has_started() -> None:
    """Unlike a total, it is a fact about today rather than an accumulation —
    N/A against a number the market view shows would be wrong."""
    assert _season_table()["Price"][0] == "£5.0m"


def test_a_player_with_no_history_still_gets_a_column_for_this_season() -> None:
    """A promoted club's signing has no FPL record, which is not an error."""
    table = _season_table(provider(past_seasons=[]))

    assert table["__columns__"] == ["This season"]


def test_a_failed_history_lookup_does_not_take_the_player_down() -> None:
    """Everything else on the page was already fetched and is still true."""
    detail = provider(summaries_error=FPLAPIError("down")).player(LEAGUE_ID, "8")

    assert detail.name
    assert _by_season(detail).columns == ["This season"]


def test_a_player_carries_a_portrait_keyed_by_optas_code() -> None:
    """Not the element id, which FPL reassigns between seasons."""
    catalog = {**SQUAD_PLAYERS, 8: replace(SQUAD_PLAYERS[8], code=223094), **MARKET}

    detail = provider(players=catalog).player(LEAGUE_ID, "8")
    assert detail.image_url.endswith("/p223094.png")


def test_a_player_with_no_photo_code_is_given_no_url() -> None:
    """An empty string is a missing photo; a URL built from zero is a 404."""
    catalog = {**SQUAD_PLAYERS, 8: replace(SQUAD_PLAYERS[8], code=0), **MARKET}

    detail = provider(players=catalog).player(LEAGUE_ID, "8")
    assert detail.image_url == ""


def test_the_drawer_names_the_club_in_full_with_its_crest() -> None:
    detail = provider().player(LEAGUE_ID, "1")
    assert detail.team_name == "Arsenal"
    # Filed under the club's media code, not its bootstrap id.
    assert detail.team_logo_url == "https://resources.premierleague.com/premierleague/badges/70/t3.png"


def test_a_club_that_will_not_load_falls_back_to_the_abbreviation() -> None:
    """Worse than the full name, no worse than before, and not a failed page."""
    detail = provider(clubs_error=FPLAPIError("down")).player(LEAGUE_ID, "1")
    assert detail.team_name == detail.team
    assert detail.team_logo_url == ""


# ── the drawer's tabs ───────────────────────────────────────────────────


def test_the_drawer_opens_on_the_week_with_the_log_fixtures_and_seasons_behind_it() -> None:
    detail = provider(games={8: [game(3, 10)]}).player(LEAGUE_ID, "8")

    assert detail.tabs == ["This week", "Game log", "Fixtures", "Seasons"]
    assert [(t.title, t.tab) for t in detail.tables] == [
        ("Game log", "Game log"),
        ("Fixtures", "Fixtures"),
        ("By season", "Seasons"),
    ]


def test_the_game_log_is_newest_first_in_what_his_position_scores() -> None:
    games = [game(3, 12, goals=1, clean_sheets=1, defensive_contribution=11), game(4, 1, minutes=20)]
    log = _table(provider(games={3: games}).player(LEAGUE_ID, "3"), "Game log")

    assert log.columns == ["Pts", "Min", "G", "A", "CS", "DC", "Bon"]
    assert [(r.label, r.values, r.tone) for r in log.rows] == [
        ("GW4 vs LIV", ["1", "20", "0", "0", "0", "0", "0"], "warning"),
        ("GW3 vs LIV", ["12", "90", "1", "0", "1", "11", "0"], "good"),
    ]


def test_a_keepers_log_reads_saves_and_conceded_and_a_forwards_reads_as_a_midfielders() -> None:
    assert _table(provider(games={1: [game(3, 6)]}).player(LEAGUE_ID, "1"), "Game log").columns == [
        "Pts",
        "Min",
        "CS",
        "GC",
        "Sv",
        "Bon",
    ]
    assert _table(provider(games={13: [game(3, 6)]}).player(LEAGUE_ID, "13"), "Game log").columns == [
        "Pts",
        "Min",
        "G",
        "A",
        "DC",
        "Bon",
    ]


def test_a_player_with_no_match_yet_has_no_log() -> None:
    assert "Game log" not in {t.title for t in provider().player(LEAGUE_ID, "8").tables}


def test_the_fixtures_tab_names_each_opponent_with_its_difficulty_a_blank_and_a_double_included() -> None:
    season = [
        Fixture(event=5, home="ARS", away="LIV", home_difficulty=2, away_difficulty=4),
        Fixture(event=7, home="TOT", away="ARS", home_difficulty=3, away_difficulty=5),
        Fixture(event=7, home="ARS", away="MCI", home_difficulty=3, away_difficulty=3),
    ]
    rows = _table(provider(season_fixtures=season).player(LEAGUE_ID, "8"), "Fixtures").rows

    assert [(r.label, r.values, r.tone) for r in rows][:4] == [
        ("GW5", ["vs LIV", "2"], "good"),  # a club the catalog cannot name in full keeps its three letters
        ("GW6", ["no fixture", "N/A"], "warning"),
        ("GW7 (double)", ["at Spurs", "5"], "warning"),
        ("GW7 (double)", ["vs MCI", "3"], "neutral"),
    ]


def test_fixtures_that_will_not_load_leave_the_rest_of_the_drawer() -> None:
    detail = provider(season_fixtures_error=FPLAPIError("down")).player(LEAGUE_ID, "8")
    assert "Fixtures" not in {t.title for t in detail.tables}
    assert detail.groups


def test_a_flagged_player_carries_an_injury_group_in_place_of_his_availability() -> None:
    hurt = player(
        3,
        "DEF",
        6.0,
        status="i",
        chance_of_playing=0,
        news="Knee injury - Expected back 28 Nov",
        news_added=datetime(2026, 11, 16, tzinfo=UTC),
    )
    detail = provider(players={**SQUAD_PLAYERS, 3: hurt, **MARKET}).player(LEAGUE_ID, "3")

    injury = _group(detail, "Injury")
    assert (injury["Status"].value, injury["Body part"].value) == ("injured 0%", "Knee injury")
    assert injury["Back"].value.startswith("~28 Nov")
    assert "Availability" not in _group(detail, "This week")  # said once, in the group


def test_a_fit_player_says_so_in_the_week() -> None:
    assert _group(provider().player(LEAGUE_ID, "8"), "This week")["Availability"].value == "fit"


def test_the_underlying_numbers_are_those_his_position_is_scored_on() -> None:
    keeper = _group(provider().player(LEAGUE_ID, "1"), "Underlying")
    defender = _group(
        provider(games={3: [game(3, 6, defensive_contribution=10), game(4, 2)]}).player(LEAGUE_ID, "3"), "Underlying"
    )
    forward = _group(provider().player(LEAGUE_ID, "13"), "Underlying")

    assert set(keeper) == {"xGC", "Saves/90"}
    assert set(defender) == {"xG", "xA", "xGC", "DC/90", "DC 10+"}
    assert defender["DC 10+"].value == "1 of 2"
    assert set(forward) == {"xG", "xA", "xGI", "DC/90", "DC 12+"}
    assert keeper["xGC"].better == "lower"


def test_a_keeper_has_no_set_pieces_group() -> None:
    assert "Set pieces" not in [g.title for g in provider().player(LEAGUE_ID, "1").groups]


P8 = SQUAD_PLAYERS[8]


@pytest.mark.parametrize(
    ("priced", "expected", "tone"),
    [
        (replace(P8, price_locked_until=datetime(2026, 11, 21, 18, tzinfo=UTC)), "locked until Sat 21 Nov", "neutral"),
        (replace(P8, price_progress=96.8, price_tonight=102.3), "rise likely tonight", "good"),
        (replace(P8, price_progress=-97.0, price_tonight=-101.6), "fall likely tonight", "warning"),
        (replace(P8, price_progress=31.0, price_tonight=30.0), "31% to a rise", "neutral"),
        (replace(P8, price_progress=-22.0), "22% to a fall", "neutral"),
        (P8, "none due", "neutral"),
    ],
)
def test_the_market_says_where_the_price_goes_next(priced: Player, expected: str, tone: str) -> None:
    catalog = {**SQUAD_PLAYERS, 8: priced, **MARKET}
    move = _group(provider(players=catalog).player(LEAGUE_ID, "8"), "Market")["Next move"]
    assert (move.value, move.tone) == (expected, tone)


def test_net_transfers_this_gameweek_drive_the_price_and_compare_most_first() -> None:
    catalog = {**SQUAD_PLAYERS, 8: replace(SQUAD_PLAYERS[8], transfers_in=50_000, transfers_out=8_000), **MARKET}
    net = _group(provider(players=catalog).player(LEAGUE_ID, "8"), "Market")["Net transfers"]
    assert (net.value, net.better) == ("+42,000", "higher")


def test_season_rows_say_which_way_they_improve_so_a_comparison_can_star_the_best() -> None:
    rows = {r.label: r for r in _by_season(provider().player(LEAGUE_ID, "3")).rows}
    assert rows["Points"].better == "higher"
    assert rows["Conceded"].better == "lower"
    assert rows["Price"].better is None
    assert "Def. contribution" in rows
