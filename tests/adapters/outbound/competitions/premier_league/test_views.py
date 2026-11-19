"""Tests for how an FPL player reads: a squad or market row, and the drawer that opens on him."""

from dataclasses import replace

import pytest
from support.fpl import (
    DOUBTFUL_P3,
    LEAGUE_ID,
    MARKET,
    SQUAD_PLAYERS,
    player,
    provider,
)

from thefrontoffice.adapters.outbound.competitions.premier_league.fpl import FPLProvider
from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLAPIError
from thefrontoffice.domain.errors import PlayerNotFoundError

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


def test_a_player_on_no_set_pieces_says_so_once() -> None:
    pieces = next(g for g in provider().player(LEAGUE_ID, "8").groups if g.title == "Set pieces")
    assert [s.value for s in pieces.stats] == ["none"]


def test_a_keeper_gets_the_numbers_only_a_keeper_has() -> None:
    """Saves on an attacker is a zero nobody asked for."""
    labels = {row.label for row in provider().player(LEAGUE_ID, "1").tables[0].rows}
    assert {"Saves", "Clean sheets", "Conceded"} <= labels


def test_an_attacker_is_not_given_a_keepers_line() -> None:
    labels = {row.label for row in provider().player(LEAGUE_ID, "13").tables[0].rows}
    assert "Saves" not in labels


# ── the seasons behind the price ────────────────────────────────────────


def _season_table(over: FPLProvider | None = None) -> dict[str, list[str]]:
    """The by-season table as {row label: values}, columns newest first."""
    detail = (over or provider()).player(LEAGUE_ID, "8")
    table = detail.tables[0]
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
    detail = provider(past_seasons_error=FPLAPIError("down")).player(LEAGUE_ID, "8")

    assert detail.name
    assert detail.tables[0].columns == ["This season"]


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
