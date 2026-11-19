"""Tests for the Yahoo paths every reader and the capture name a response by."""

from thefrontoffice.adapters.outbound.platforms.yahoo import paths
from thefrontoffice.adapters.outbound.platforms.yahoo.types import PlayerStatus, Timeframe


def test_a_league_read_is_kept_under_the_path_yahoo_serves_it_at() -> None:
    read = paths.settings("466.l.1")

    assert (read.query, read.league, read.path) == ("settings", "466.l.1", "league/466.l.1/settings")
    assert paths.standings("466.l.1").path == "league/466.l.1/standings"


def test_a_read_naming_its_own_subject_is_its_own_path() -> None:
    assert paths.roster("466.l.1.t.2").path == "team/466.l.1.t.2/roster"
    assert paths.leagues("nba", 2026).path == "users;use_login=1/games;game_codes=nba;seasons=2026/leagues"


def test_available_players_include_those_on_waivers_by_season_rank() -> None:
    [read] = paths.available("466.l.1", 25)

    assert read.query == "players;count=25;status=A;sort=AR;sort_type=season"


def test_a_deeper_wire_is_a_page_of_25_per_read_the_last_only_as_long_as_needed() -> None:
    reads = paths.available("466.l.1", 60, Timeframe.LAST_WEEK)

    assert [read.query for read in reads] == [
        "players;count=25;status=A;sort=AR;sort_type=lastweek",
        "players;count=25;status=A;sort=AR;sort_type=lastweek;start=25",
        "players;count=10;status=A;sort=AR;sort_type=lastweek;start=50",
    ]


def test_a_search_cannot_reach_past_its_term_into_the_rest_of_the_path() -> None:
    read = paths.search("466.l.1", "  O'Neale;start=5/x ")

    assert read.query == "players;search=O'Neale start 5 x"
    assert read.search == "O'Neale start 5 x"


def test_a_page_with_no_sort_says_none() -> None:
    assert paths.player_page("466.l.1", 5, PlayerStatus.FREE_AGENT, None, None).query == "players;count=5;status=FA"


def test_leaders_are_one_read_per_stat_keyed_as_asked() -> None:
    reads = paths.leaders("466.l.1", {"PTS": "12", "BLK": "18"}, per_stat=3)

    assert {name: read.query for name, read in reads.items()} == {
        "PTS": "players;count=3;status=A;sort=12;sort_type=lastweek",
        "BLK": "players;count=3;status=A;sort=18;sort_type=lastweek",
    }


def test_only_a_lookup_by_key_or_name_is_one_no_plan_could_make() -> None:
    assert paths.by_keys("466.l.1", ["466.p.1"]).lookup
    assert paths.search("466.l.1", "James").lookup
    assert not paths.teams("466.l.1").lookup
    assert not paths.standings("466.l.1").lookup


def test_only_the_scoreboard_keeps_its_copy_when_a_refresh_fails() -> None:
    assert paths.scoreboard("466.l.1", 3).keep_on_failure
    assert not paths.roster("466.l.1.t.1").keep_on_failure


def test_a_week_played_is_read_with_each_players_line_over_it_and_kept_long() -> None:
    read = paths.played_roster("466.l.1.t.2", 3)

    assert read.path == "team/466.l.1.t.2/roster;week=3/players/stats;type=week;week=3"
    assert read.ttl > paths.ROSTER_TTL
