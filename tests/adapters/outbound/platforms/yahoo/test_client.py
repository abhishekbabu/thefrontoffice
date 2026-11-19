"""Tests for YahooClient, the reader of one Yahoo league.

The client builds Yahoo's query strings by hand and walks the XML it gets back,
and reads what it gets back into its own types, so both are ours to get right.
A fake context stands in for the SDK's HTTP and answers in Yahoo's own XML,
which the real parser reads.
"""

import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import pytest
import requests
from support.http import NO_WAIT, http_error
from support.yahoo import (
    FakeContext,
    averaged_xml,
    league_players_xml,
    league_standings_xml,
    players_xml,
    roster_xml,
    rostered_xml,
    scoreboard_xml,
    standings_xml,
    team_xml,
    teams_xml,
)

from thefrontoffice.adapters.outbound.cache import DiskCache
from thefrontoffice.adapters.outbound.platforms.yahoo import paths
from thefrontoffice.adapters.outbound.platforms.yahoo.client import LiveResponses, YahooClient, full_size, translate
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import (
    YahooAPIError,
    YahooAuthError,
    YahooLoginRequiredError,
    YahooUnavailableError,
)
from thefrontoffice.adapters.outbound.platforms.yahoo.paths import ScoreboardPace
from thefrontoffice.adapters.outbound.platforms.yahoo.types import (
    Average,
    TeamStanding,
    Timeframe,
    YahooLeague,
    YahooLine,
    YahooPlayer,
)
from thefrontoffice.domain.errors import TeamNotFoundError

STATS = {"PTS": "12", "REB": "15", "BLK": "18"}
"""Three of a sport's stat ids, named the way the caller names them."""


LEAGUE = YahooLeague(league_key="466.l.123", name="My League", current_week=5)


def _client(
    tmp_path: Path,
    response: str = "<fantasy_content/>",
    error: Exception | None = None,
    answers: dict[str, str] | None = None,
    league: YahooLeague = LEAGUE,
) -> tuple[YahooClient, FakeContext]:
    ctx = FakeContext(response, error, answers)
    live = LiveResponses(ctx, cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT)
    return YahooClient(league, responses=live), ctx


def _stored(tmp_path: Path, path: str, xml: str, age: timedelta) -> None:
    """A response the cache already holds, kept `age` ago."""
    DiskCache(tmp_path / "cache").set(path, xml, now=datetime.now(UTC) - age)


# ── fetch_top_by_stat ───────────────────────────────────────────────────


def test_one_request_per_stat_asked_for_keyed_as_asked(tmp_path: Path) -> None:
    client, ctx = _client(tmp_path, players_xml("A B"))

    results = client.fetch_top_by_stat(STATS, per_stat=4)

    assert {name: [p.name for p in players] for name, players in results.items()} == {name: ["A B"] for name in STATS}
    assert all("count=4" in q and "status=A" in q for q in ctx.queries)
    assert {q.split("sort=")[1].split(";")[0] for q in ctx.queries} == set(STATS.values())
    assert {league for _, league in ctx.requests} == {"466.l.123"}


def test_asking_for_no_stats_asks_yahoo_nothing(tmp_path: Path) -> None:
    client, ctx = _client(tmp_path, players_xml("A B"))

    assert client.fetch_top_by_stat({}) == {}
    assert ctx.requests == []


def test_category_requests_run_concurrently(tmp_path: Path) -> None:
    """Eight independent queries were the dominant latency in a scout run."""
    client, ctx = _client(tmp_path, players_xml("A B"))
    ctx.barrier = threading.Barrier(len(STATS), timeout=5)

    client.fetch_top_by_stat(STATS, per_stat=4)

    assert not ctx.barrier.broken


def test_cached_categories_are_not_refetched(tmp_path: Path) -> None:
    client, ctx = _client(tmp_path, players_xml("A B"))
    client.fetch_top_by_stat(STATS, per_stat=4)
    before = len(ctx.requests)
    client.fetch_top_by_stat(STATS, per_stat=4)
    assert len(ctx.requests) == before


def test_a_category_with_nobody_available_is_empty(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, players_xml())
    assert client.fetch_top_by_stat(STATS)["PTS"] == []


def test_an_unparseable_response_raises_and_is_not_kept(tmp_path: Path) -> None:
    """A response we cannot read must neither become an empty category nor be served again."""
    client, ctx = _client(tmp_path, "<not xml")

    with pytest.raises(YahooAPIError):
        client.fetch_top_by_stat(STATS, per_stat=4)

    ctx.response = players_xml("A B")
    assert client.fetch_top_by_stat(STATS, per_stat=4)["PTS"][0].name == "A B"


def test_a_failing_category_fails_them_all(tmp_path: Path) -> None:
    """A category left empty would read as nobody worth adding in it."""
    client, _ = _client(tmp_path, error=http_error(404))
    with pytest.raises(YahooAPIError):
        client.fetch_top_by_stat(STATS, per_stat=4)


def test_a_403_on_the_leaders_names_the_missing_permission(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, error=http_error(403))
    with pytest.raises(YahooAuthError):
        client.fetch_top_by_stat(STATS, per_stat=4)


# ── fetch_available ─────────────────────────────────────────────────────


AVERAGED = "/stats;type=average_lastmonth"
SEASON_RANK = "players;count=25;status=A;sort=AR;sort_type=season"
WEEK_RANK = "players;count=25;status=A;sort=AR;sort_type=lastweek"


def test_the_wire_is_read_a_page_of_25_at_a_time_under_each_ranking(tmp_path: Path) -> None:
    """Yahoo lists 25 players a response; one request for more came back short."""
    client, ctx = _client(tmp_path, players_xml())

    client.fetch_available({Timeframe.SEASON: 60, Timeframe.LAST_WEEK: 25})

    assert sorted(ctx.queries) == sorted(
        [
            SEASON_RANK + AVERAGED,
            f"{SEASON_RANK};start=25{AVERAGED}",
            f"players;count=10;status=A;sort=AR;sort_type=season;start=50{AVERAGED}",
            WEEK_RANK + AVERAGED,
        ]
    )


def test_each_ranking_reads_its_pages_in_order_and_a_player_on_two_pages_once(tmp_path: Path) -> None:
    """Pages fetched a moment apart overlap when the order shifts between them."""
    answers = {
        f"{SEASON_RANK};start=25": players_xml("Shifted", "Third", first=1),
        SEASON_RANK: players_xml("First", "Shifted"),
        WEEK_RANK: players_xml("Riser", first=7),
    }
    client, _ = _client(tmp_path, answers=answers)

    wire = client.fetch_available({Timeframe.SEASON: 50, Timeframe.LAST_WEEK: 25})

    assert [p.name for p in wire[Timeframe.SEASON]] == ["First", "Shifted", "Third"]
    assert [p.name for p in wire[Timeframe.LAST_WEEK]] == ["Riser"]


def test_a_ranking_that_runs_out_early_is_shorter_not_a_failure(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, answers={f"{SEASON_RANK};start=25": players_xml(), SEASON_RANK: players_xml("Only")})

    assert [p.name for p in client.fetch_available({Timeframe.SEASON: 50})[Timeframe.SEASON]] == ["Only"]


def test_a_refused_available_list_names_the_missing_permission(tmp_path: Path) -> None:
    """Untranslated, requests' own error escapes as a 500 with nothing to render."""
    client, _ = _client(tmp_path, error=http_error(403))
    with pytest.raises(YahooAuthError):
        client.fetch_available({Timeframe.SEASON: 25})


# ── transient failures ──────────────────────────────────────────────────


def test_a_transient_failure_is_retried(tmp_path: Path) -> None:
    client, ctx = _client(tmp_path, players_xml("A B"))
    ctx.fail_first = [requests.exceptions.Timeout()]

    assert [p.name for p in client.fetch_available({Timeframe.SEASON: 25})[Timeframe.SEASON]] == ["A B"]
    assert len(ctx.requests) == 2


def test_yahoo_staying_down_says_to_wait(tmp_path: Path) -> None:
    client, ctx = _client(tmp_path, error=http_error(503))

    with pytest.raises(YahooUnavailableError):
        client.fetch_available({Timeframe.SEASON: 25})
    assert len(ctx.requests) == NO_WAIT.attempts


# ── players by key ──────────────────────────────────────────────────────


def test_players_are_looked_up_by_key_across_the_league(tmp_path: Path) -> None:
    """Not a roster read: the drawer opens on free agents and rivals' players too."""
    client, ctx = _client(tmp_path, players_xml("LeBron James"))

    found = client.players(["466.p.0"])

    assert ctx.requests == [("players;player_keys=466.p.0/ownership", "466.l.123")]
    assert [p.name for p in found] == ["LeBron James"]


def _owned_xml(ownership: str) -> str:
    resized = "https://s.yimg.com/iu/api/res/1.2/abc--~C/YXBw/https://s.yimg.com/xe/i/us/sp/v/nba_cutout/6169.1.png"
    return (
        "<fantasy_content><league><players><player><player_key>466.p.0</player_key><name><full>Coby White</full>"
        f"</name><image_url>{resized}</image_url><ownership>{ownership}</ownership></player></players></league>"
        "</fantasy_content>"
    )


def test_a_player_carries_his_full_size_headshot_and_whose_roster_he_is_on(tmp_path: Path) -> None:
    held = "<ownership_type>team</ownership_type><owner_team_name>Injury Prone</owner_team_name>"
    client, _ = _client(tmp_path, _owned_xml(held))

    [player] = client.players(["466.p.0"])

    assert player.image_url == "https://s.yimg.com/xe/i/us/sp/v/nba_cutout/6169.1.png"
    assert player.owner == "Injury Prone"


@pytest.mark.parametrize(("kind", "owner"), [("freeagents", "Free agent"), ("waivers", "Waivers"), ("other", "")])
def test_a_player_nobody_holds_reads_as_the_wire_he_is_on(tmp_path: Path, kind: str, owner: str) -> None:
    client, _ = _client(tmp_path, _owned_xml(f"<ownership_type>{kind}</ownership_type>"))

    assert client.players(["466.p.0"])[0].owner == owner


def test_a_headshot_yahoo_serves_unresized_is_kept_as_it_is() -> None:
    assert full_size("https://s.yimg.com/a.png") == "https://s.yimg.com/a.png"
    assert full_size("") == ""


def test_a_player_read_without_his_ownership_has_no_owner(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, players_xml("LeBron James"))

    assert client.players(["466.p.0"])[0].owner == ""


def test_a_key_yahoo_does_not_know_is_an_empty_answer(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, players_xml())
    assert client.players(["466.p.999"]) == []


# ── search_players ──────────────────────────────────────────────────────


def test_a_search_is_scoped_to_the_league_once(tmp_path: Path) -> None:
    """The SDK prefixes `league/{key}/` itself; naming the league in the query too
    asked Yahoo for a path that does not exist."""
    client, ctx = _client(tmp_path, players_xml("LeBron James"))

    results = client.search_players("LeBron James")

    assert ctx.requests == [("players;search=LeBron James", "466.l.123")]
    assert [p.name for p in results] == ["LeBron James"]


def test_a_search_is_served_from_cache_once_made(tmp_path: Path) -> None:
    client, ctx = _client(tmp_path, players_xml("LeBron James"))
    client.search_players("LeBron James")
    client.search_players("LeBron James")
    assert len(ctx.requests) == 1


def test_no_matches_is_an_empty_list_not_an_error(tmp_path: Path) -> None:
    """A name that does not exist is a valid answer; a failed request is not."""
    client, _ = _client(tmp_path, players_xml())
    assert client.search_players("Nobody") == []


def test_a_failed_search_raises(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, error=http_error(404))
    with pytest.raises(YahooAPIError):
        client.search_players("LeBron James")


def test_a_refused_search_names_the_missing_permission(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, error=http_error(403))
    with pytest.raises(YahooAuthError):
        client.search_players("LeBron James")


def test_a_search_on_an_unexpected_shape_raises(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, "<fantasy_content><error>?</error></fantasy_content>")
    with pytest.raises(YahooAPIError):
        client.search_players("LeBron James")


# ── teams ───────────────────────────────────────────────────────────────


def test_each_team_is_read_with_its_standing(tmp_path: Path) -> None:
    client, ctx = _client(
        tmp_path,
        teams_xml(
            team_xml("t.1", "Mine", mine=True, adds=2, standings=standings_xml(2, 4, 2, 1, "790")),
            team_xml("t.2", "Theirs"),
        ),
    )

    mine, theirs = client.teams()

    assert (mine.team_key, mine.name, mine.is_mine, mine.adds_used) == ("t.1", "Mine", True, 2)
    assert mine.standing == TeamStanding(rank=2, wins=4, losses=2, ties=1, points_for="790")
    assert (theirs.is_mine, theirs.standing) == (False, None)
    assert ctx.requests == [("teams", "466.l.123")]


def test_the_owned_team_is_returned(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, teams_xml(team_xml("t.2", "Theirs"), team_xml("t.1", "Mine", mine=True)))
    assert client.get_user_team().name == "Mine"


def test_owning_no_team_raises_with_the_league_name(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, teams_xml(team_xml("t.2", "Theirs")))
    with pytest.raises(TeamNotFoundError) as caught:
        client.get_user_team()
    assert caught.value.league_name == "My League"


def test_the_team_list_is_served_from_cache_once_fetched(tmp_path: Path) -> None:
    client, ctx = _client(tmp_path, teams_xml(team_xml("t.1", "Mine", mine=True)))
    client.teams()
    client.get_user_team()
    assert len(ctx.requests) == 1


def test_a_refused_team_list_names_the_missing_permission(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, error=http_error(403))
    with pytest.raises(YahooAuthError):
        client.teams()


def test_an_unrecognized_team_list_raises(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, "<fantasy_content><error>?</error></fantasy_content>")
    with pytest.raises(YahooAPIError):
        client.teams()


# ── rosters ─────────────────────────────────────────────────────────────


def test_a_roster_says_where_each_player_sits_and_what_ails_them(tmp_path: Path) -> None:
    client, ctx = _client(
        tmp_path, roster_xml(rostered_xml("A B", "IL", status="O", note="knee"), rostered_xml("C D", "BN"))
    )

    hurt, benched = client.roster("nba.l.123.t.1")

    assert hurt == YahooPlayer(
        player_key="466.p.3",
        name="A B",
        position="PG,SG",
        team="BOS",
        status="O",
        injury_note="knee",
        slot="IL",
    )
    assert (benched.slot, benched.status) == ("BN", "")
    assert ctx.requests == [("team/nba.l.123.t.1/roster", False)]


def test_a_week_played_reads_each_roster_as_it_ended_with_each_players_line(tmp_path: Path) -> None:
    played = {"12": "143", "18": "-"}
    answers = {
        paths.played_roster("t1", 3).query: roster_xml(rostered_xml("A B", "PG", stats=played, points="140.80")),
        paths.played_roster("t2", 3).query: roster_xml(rostered_xml("C D", "BN", stats={"12": "-"})),
    }
    client, ctx = _client(tmp_path, answers=answers)

    rosters = client.played_rosters(["t1", "t2"], 3)

    [mine], [theirs] = rosters["t1"], rosters["t2"]
    assert (mine.name, mine.slot, mine.stats, mine.points) == ("A B", "PG", played, "140.8")
    assert (theirs.stats, theirs.points) == ({"12": "-"}, "")
    assert sorted(path for path, _ in ctx.requests) == sorted(answers)


def test_every_teams_roster_is_read_together_by_team_key(tmp_path: Path) -> None:
    answers = {
        paths.roster("t1").query: roster_xml(rostered_xml("A B", "PG")),
        paths.roster("t2").query: roster_xml(rostered_xml("C D", "IL", status="O")),
    }
    client, ctx = _client(tmp_path, answers=answers)

    rosters = client.rosters(["t1", "t2"])

    assert {key: [(p.name, p.slot) for p in players] for key, players in rosters.items()} == {
        "t1": [("A B", "PG")],
        "t2": [("C D", "IL")],
    }
    assert sorted(path for path, _ in ctx.requests) == sorted(answers)


def test_a_roster_failure_is_ours_to_render_not_requests(tmp_path: Path) -> None:
    """The SDK's own roster fetch failed in requests' terms, and escaped as a 500."""
    client, _ = _client(tmp_path, error=requests.ConnectionError("down"))
    with pytest.raises(YahooUnavailableError):
        client.roster("t.1")


# ── the matchup ─────────────────────────────────────────────────────────


def _matchup_client(tmp_path: Path, scoreboard: str | None = None, **kwargs: object) -> tuple[YahooClient, FakeContext]:
    answers = {
        "scoreboard;week=5": scoreboard or scoreboard_xml(),
        "team/t2/roster": roster_xml(rostered_xml("Star Player", "PG")),
        "team/t1/roster": roster_xml(rostered_xml("My Player", "C")),
    }
    client, ctx = _client(tmp_path, answers=answers)
    for name, value in kwargs.items():
        setattr(ctx, name, value)
    return client, ctx


def test_the_matchup_is_read_into_both_sides_by_stat_id(tmp_path: Path) -> None:
    client, _ = _matchup_client(tmp_path)
    info = client.get_matchup("t1")

    assert info is not None
    assert (info.start, info.end) == (date(2026, 2, 9), date(2026, 2, 15))
    assert (info.mine.name, info.mine.points, info.mine.stats) == ("Mine", "50", {"18": "12"})
    assert (info.opponent.name, info.opponent.points, info.opponent.stats) == ("Theirs", "60", {"18": "17"})
    assert [(p.name, p.position) for p in info.opponent_roster] == [("Star Player", "PG,SG")]


def test_the_second_team_listed_still_reads_as_mine(tmp_path: Path) -> None:
    client, _ = _matchup_client(tmp_path)
    info = client.get_matchup("t2")

    assert info is not None
    assert (info.mine.name, info.mine.stats) == ("Theirs", {"18": "17"})
    assert info.opponent.name == "Mine"
    assert [p.name for p in info.opponent_roster] == ["My Player"]


def test_no_matchup_this_week_is_an_answer_not_a_failure(tmp_path: Path) -> None:
    client, _ = _matchup_client(tmp_path)
    assert client.get_matchup("t9") is None

    empty = "<fantasy_content><league><scoreboard><matchups count='0'/></scoreboard></league></fantasy_content>"
    client, _ = _matchup_client(tmp_path / "empty", empty)
    assert client.get_matchup("t1") is None


def test_any_week_of_the_season_is_read_from_that_weeks_scoreboard(tmp_path: Path) -> None:
    client, ctx = _client(tmp_path, answers={"scoreboard;week=2": scoreboard_xml(start="2026-01-19")})
    found = client.pairing("t1", 2)

    assert found is not None
    assert (found.start, found.mine.stats, found.opponent.name) == (date(2026, 1, 19), {"18": "12"}, "Theirs")


def _stat_xml(stat_id: str, name: str, sort_order: str, display_only: bool = False) -> str:
    only = "<is_only_display_stat>1</is_only_display_stat>" if display_only else ""
    return (
        f"<stat><stat_id>{stat_id}</stat_id><display_name>{name}</display_name>"
        f"<sort_order>{sort_order}</sort_order>{only}</stat>"
    )


def test_the_league_scores_the_categories_its_settings_list(tmp_path: Path) -> None:
    stats = (
        _stat_xml("9004003", "FGM/A", "1", display_only=True) + _stat_xml("5", "FG%", "1") + _stat_xml("19", "TO", "0")
    )
    settings = (
        "<fantasy_content><league><settings><stat_categories><stats>"
        f"{stats}</stats></stat_categories></settings></league></fantasy_content>"
    )
    client, _ = _client(tmp_path, answers={"settings": settings})

    read = client.settings()

    assert [(c.stat_id, c.name, c.fewer_wins) for c in read.categories] == [
        ("5", "FG%", False),
        ("19", "TO", True),
    ]
    assert (read.weights, read.max_weekly_adds) == ({}, None)  # a category league naming no limit


def test_a_points_league_carries_its_weights_and_its_add_limit(tmp_path: Path) -> None:
    modifiers = "".join(
        f"<stat><stat_id>{stat}</stat_id><value>{value}</value></stat>" for stat, value in (("15", "1.2"), ("19", "-1"))
    )
    settings = (
        f"<fantasy_content><league><settings><stat_modifiers><stats>{modifiers}</stats></stat_modifiers>"
        "<max_weekly_adds>4</max_weekly_adds></settings></league></fantasy_content>"
    )
    client, _ = _client(tmp_path, answers={"settings": settings})

    read = client.settings()

    assert (read.weights, read.max_weekly_adds) == ({"15": 1.2, "19": -1.0}, 4)


def test_a_side_carries_yahoos_projected_final(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, answers={"scoreboard;week=2": scoreboard_xml(projected=("896.45", "1107.37"))})
    found = client.pairing("t1", 2)

    assert found is not None
    assert (found.mine.points, found.mine.projected, found.opponent.projected) == ("50", "896.45", "1107.37")


def test_the_settings_list_the_leagues_lineup_slots(tmp_path: Path) -> None:
    slots = "".join(
        f"<roster_position><position>{slot}</position><count>1</count></roster_position>" for slot in ("PG", "G", "BN")
    )
    settings = (
        f"<fantasy_content><league><settings><roster_positions>{slots}</roster_positions>"
        "</settings></league></fantasy_content>"
    )
    client, _ = _client(tmp_path, answers={"settings": settings})

    assert client.settings().positions == ["PG", "G", "BN"]


def test_the_settings_say_where_the_bracket_starts(tmp_path: Path) -> None:
    settings = (
        "<fantasy_content><league><settings><uses_playoff>1</uses_playoff>"
        "<playoff_start_week>19</playoff_start_week><num_playoff_teams>6</num_playoff_teams>"
        "<has_multiweek_championship>1</has_multiweek_championship></settings></league></fantasy_content>"
    )
    client, _ = _client(tmp_path, answers={"settings": settings})

    rules = client.settings()

    assert (rules.playoff_start_week, rules.playoff_teams, rules.multiweek_final) == (19, 6, True)


def test_the_settings_say_how_lineups_are_set_and_whether_only_a_best_game_scores(tmp_path: Path) -> None:
    settings = (
        "<fantasy_content><league><roster_type>week</roster_type><is_highscore>1</is_highscore>"
        "<settings/></league></fantasy_content>"
    )
    client, _ = _client(tmp_path, answers={"settings": settings})
    daily, _ = _client(
        tmp_path / "daily",
        answers={
            "settings": "<fantasy_content><league><roster_type>date</roster_type><settings/></league></fantasy_content>"
        },
    )

    assert (client.settings().weekly_lineups, client.settings().best_game) == (True, True)
    assert (daily.settings().weekly_lineups, daily.settings().best_game) == (False, False)


def test_the_settings_say_when_trading_ends_and_what_a_roster_holds(tmp_path: Path) -> None:
    positions = "".join(
        f"<roster_position><position>{slot}</position><count>{count}</count></roster_position>"
        for slot, count in (("PG", 1), ("Util", 2), ("BN", 3), ("IL", 2))
    )
    settings = (
        "<fantasy_content><league><settings><trade_end_date>2027-02-25</trade_end_date>"
        f"<roster_positions>{positions}</roster_positions></settings></league></fantasy_content>"
    )
    client, _ = _client(tmp_path, answers={"settings": settings})

    rules = client.settings()

    assert rules.trade_end == date(2027, 2, 25)
    assert (rules.starting, rules.roster_size) == (3, 6)


def test_settings_without_a_trade_deadline_or_positions_name_neither(tmp_path: Path) -> None:
    settings = (
        "<fantasy_content><league><settings><trade_end_date>soon</trade_end_date></settings></league></fantasy_content>"
    )
    client, _ = _client(tmp_path, answers={"settings": settings})

    rules = client.settings()

    assert (rules.trade_end, rules.starting, rules.roster_size) == (None, 0, 0)


def test_a_league_with_playoffs_off_has_no_bracket(tmp_path: Path) -> None:
    settings = (
        "<fantasy_content><league><settings><uses_playoff>0</uses_playoff>"
        "<playoff_start_week>19</playoff_start_week><num_playoff_teams>6</num_playoff_teams>"
        "</settings></league></fantasy_content>"
    )
    client, _ = _client(tmp_path, answers={"settings": settings})

    rules = client.settings()

    assert (rules.playoff_start_week, rules.playoff_teams) == (0, 0)


def test_the_table_is_read_from_the_standings_which_the_team_list_lacks(tmp_path: Path) -> None:
    standings = standings_xml(
        1, 10, 2, 1, "812", extra="<points_against>700.5</points_against><playoff_seed>2</playoff_seed>"
    )
    waivers = "<waiver_priority>3</waiver_priority><faab_balance>73</faab_balance>"
    client, ctx = _client(
        tmp_path,
        answers={
            "standings": league_standings_xml(
                team_xml("t.1", "Mine", mine=True, standings=standings, extra=waivers), team_xml("t.2", "Theirs")
            )
        },
    )

    mine, theirs = client.standings()

    assert mine.standing == TeamStanding(
        rank=1, wins=10, losses=2, ties=1, points_for="812", points_against="700.5", playoff_seed=2
    )
    assert (mine.is_mine, mine.waiver_priority, mine.faab_balance) == (True, 3, "73")
    assert (theirs.standing, theirs.waiver_priority, theirs.faab_balance) == (None, 0, "")
    assert ctx.requests == [("standings", "466.l.123")]


SETTLED = (
    "<fantasy_content><league><scoreboard><matchups><matchup>"
    "<week_start>2026-03-08</week_start><week_end>2026-03-14</week_end><status>postevent</status>"
    "<is_playoffs>1</is_playoffs><is_consolation>1</is_consolation><is_tied>0</is_tied>"
    "<winner_team_key>t2</winner_team_key><stat_winners>"
    "<stat_winner><stat_id>5</stat_id><winner_team_key>t2</winner_team_key></stat_winner>"
    "<stat_winner><stat_id>12</stat_id><is_tied>1</is_tied></stat_winner>"
    "<stat_winner><stat_id>18</stat_id><is_tied>1</is_tied></stat_winner>"
    "</stat_winners><teams>"
    "<team><team_key>t1</team_key><name>Mine</name><team_points><total>3</total></team_points></team>"
    "<team><team_key>t2</team_key><name>Theirs</name><team_points><total>4</total></team_points></team>"
    "</teams></matchup></matchups></scoreboard></league></fantasy_content>"
)


def test_a_settled_week_says_who_won_and_how_many_categories_neither_side_did(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, SETTLED)

    found = client.pairing("t1", 19)

    assert found is not None
    assert (found.settled, found.winner, found.tied, found.tied_categories) == (True, "t2", False, 2)
    assert (found.playoffs, found.consolation) == (True, True)


def test_a_season_reads_every_weeks_scoreboard_and_a_week_without_you_is_none(tmp_path: Path) -> None:
    empty = "<fantasy_content><league><scoreboard><matchups count='0'/></scoreboard></league></fantasy_content>"
    client, ctx = _client(tmp_path, scoreboard_xml(), answers={"scoreboard;week=3": empty})

    weeks = client.season("t1", [1, 2, 3])

    assert [week for week, found in weeks.items() if found is not None] == [1, 2]
    assert weeks[3] is None
    assert sorted(ctx.queries) == [f"scoreboard;week={week}" for week in (1, 2, 3)]


def test_every_matchup_of_a_week_is_read_and_a_week_not_yet_drawn_has_none(tmp_path: Path) -> None:
    empty = "<fantasy_content><league><scoreboard><matchups count='0'/></scoreboard></league></fantasy_content>"
    client, _ = _client(tmp_path, scoreboard_xml(), answers={"scoreboard;week=20": empty})

    weeks = client.matchups([6, 20])

    assert [(p.mine.team_key, p.opponent.team_key, p.start) for p in weeks[6]] == [("t1", "t2", date(2026, 2, 9))]
    assert weeks[20] == []


def test_between_seasons_there_is_no_week_to_ask_about(tmp_path: Path) -> None:
    client, ctx = _client(tmp_path, league=replace(LEAGUE, current_week=None))

    assert client.get_matchup("t1") is None
    assert ctx.requests == []


SCOREBOARD = paths.scoreboard(LEAGUE.league_key, 5).path


def test_the_scoreboard_is_refreshed_once_minutes_old(tmp_path: Path) -> None:
    """An hour-old scoreboard would misstate every category margin."""
    _stored(tmp_path, SCOREBOARD, scoreboard_xml(start="2026-01-01"), timedelta(minutes=5))
    client, ctx = _matchup_client(tmp_path)

    info = client.get_matchup("t1")

    assert info is not None and info.start == date(2026, 2, 9)
    assert "scoreboard;week=5" in ctx.queries


def test_a_scoreboard_a_minute_old_is_not_asked_again(tmp_path: Path) -> None:
    _stored(tmp_path, SCOREBOARD, scoreboard_xml(), timedelta(minutes=1))
    client, ctx = _matchup_client(tmp_path)

    client.get_matchup("t1")

    assert "scoreboard;week=5" not in ctx.queries


def test_a_failed_scoreboard_refresh_falls_back_to_the_stored_copy(tmp_path: Path) -> None:
    _stored(tmp_path, SCOREBOARD, scoreboard_xml(start="2026-01-05"), timedelta(days=1))
    client, ctx = _matchup_client(tmp_path)
    ctx.answers.pop("scoreboard;week=5")
    ctx.response = "<not xml"

    info = client.get_matchup("t1")

    assert info is not None
    assert info.start == date(2026, 1, 5)


def test_a_failed_scoreboard_raises_rather_than_reading_as_no_matchup(tmp_path: Path) -> None:
    client, _ = _matchup_client(tmp_path, error=requests.ConnectionError("yahoo down"))

    with pytest.raises(YahooUnavailableError):
        client.get_matchup("t1")


def test_an_unreadable_matchup_date_raises(tmp_path: Path) -> None:
    client, _ = _matchup_client(tmp_path, scoreboard_xml(start="someday"))

    with pytest.raises(YahooAPIError):
        client.get_matchup("t1")


def test_an_unrecognized_scoreboard_raises(tmp_path: Path) -> None:
    client, _ = _matchup_client(tmp_path, "<fantasy_content><error>?</error></fantasy_content>")

    with pytest.raises(YahooAPIError):
        client.get_matchup("t1")


def test_a_season_asks_only_for_the_weeks_that_can_still_have_changed(tmp_path: Path) -> None:
    """A day-old settled week holds for the season; the week being played does not hold five minutes."""
    _stored(tmp_path, paths.scoreboard(LEAGUE.league_key, 2).path, scoreboard_xml(), timedelta(days=1))
    _stored(tmp_path, paths.scoreboard(LEAGUE.league_key, 4).path, scoreboard_xml(), timedelta(hours=1))
    _stored(tmp_path, paths.scoreboard(LEAGUE.league_key, 6).path, scoreboard_xml(), timedelta(days=1))
    _stored(tmp_path, SCOREBOARD, scoreboard_xml(), timedelta(minutes=5))
    client, ctx = _client(tmp_path, scoreboard_xml())

    client.season("t1", [2, 4, 5, 6])

    assert ctx.queries == ["scoreboard;week=5"]


def test_the_week_being_played_holds_longer_while_no_game_can_be_on(tmp_path: Path) -> None:
    _stored(tmp_path, SCOREBOARD, scoreboard_xml(), timedelta(minutes=5))
    ctx = FakeContext(scoreboard_xml())
    quiet = ScoreboardPace(UTC, time(0), time(23, 59), games_on=lambda _: False)
    live = LiveResponses(ctx, cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT)

    YahooClient(LEAGUE, responses=live, pace=quiet).pairing("t1", 5)

    assert ctx.requests == []


class RecordingRefresh:
    """Stands in for the background refresher: keeps what it was asked to refresh, runs nothing until told."""

    def __init__(self) -> None:
        self.asked: dict[str, Callable[[], Any]] = {}

    def refresh(self, key: str, fetch: Callable[[], Any]) -> None:
        self.asked[key] = fetch


def _refreshing(tmp_path: Path, response: str) -> tuple[YahooClient, FakeContext, RecordingRefresh]:
    ctx, refresher = FakeContext(response), RecordingRefresh()
    live = LiveResponses(ctx, cache=DiskCache(tmp_path / "cache"), retry=NO_WAIT, refresher=refresher)
    return YahooClient(LEAGUE, responses=live), ctx, refresher


TEAMS = teams_xml(team_xml("t1", "Mine", mine=True))


def test_a_copy_just_past_its_ttl_is_served_at_once_and_refreshed_behind_it(tmp_path: Path) -> None:
    teams = paths.teams(LEAGUE.league_key)
    _stored(tmp_path, teams.path, TEAMS, paths.TEAMS_TTL + timedelta(minutes=30))
    client, ctx, refresher = _refreshing(tmp_path, teams_xml(team_xml("t1", "Renamed", mine=True)))

    assert [team.name for team in client.teams()] == ["Mine"]
    assert ctx.requests == []
    assert list(refresher.asked) == [teams.path]

    assert "Renamed" in refresher.asked[teams.path]()
    assert ctx.queries == ["teams"]


def test_a_copy_past_twice_its_ttl_is_fetched_before_it_is_served(tmp_path: Path) -> None:
    teams = paths.teams(LEAGUE.league_key)
    _stored(tmp_path, teams.path, TEAMS, 2 * paths.TEAMS_TTL + timedelta(minutes=1))
    client, ctx, refresher = _refreshing(tmp_path, teams_xml(team_xml("t1", "Renamed", mine=True)))

    assert [team.name for team in client.teams()] == ["Renamed"]
    assert (ctx.queries, refresher.asked) == (["teams"], {})


def test_a_batch_serves_its_stale_copies_and_fetches_only_what_it_has_none_of(tmp_path: Path) -> None:
    _stored(tmp_path, SCOREBOARD, scoreboard_xml(start="2026-01-05"), timedelta(minutes=3))
    client, ctx, refresher = _refreshing(tmp_path, scoreboard_xml())

    weeks = client.season("t1", [5, 6])

    assert weeks[5] is not None and weeks[5].start == date(2026, 1, 5)
    assert ctx.queries == ["scoreboard;week=6"]
    assert list(refresher.asked) == [SCOREBOARD]


# ── translating transport failures ──────────────────────────────────────


def test_a_403_names_the_permission_that_is_actually_missing() -> None:
    """Yahoo says only "not authorized to perform this action", which reads like
    a bad token — and re-authorizing a token that was never the problem is an
    afternoon. The scope on the developer app is the fix."""
    error = translate(http_error(403))

    assert isinstance(error, YahooAuthError)
    assert error.code == "access_not_approved"


@pytest.mark.parametrize("error", [http_error(500), requests.exceptions.Timeout()], ids=["5xx", "timeout"])
def test_yahoo_not_answering_is_an_outage(error: Exception) -> None:
    assert isinstance(translate(error), YahooUnavailableError)


@pytest.mark.parametrize("error", [http_error(404), ValueError("unparseable")], ids=["404", "no-response"])
def test_any_other_failure_stays_a_generic_api_error(error: Exception) -> None:
    """yahoofantasy raises requests' exceptions, and not all carry a response."""
    translated = translate(error)
    assert isinstance(translated, YahooAPIError)
    assert not isinstance(translated, (YahooAuthError, YahooUnavailableError))


def test_conditions_an_adapter_can_offer_to_fix_carry_a_code() -> None:
    """Message text is free to change; a client matching on it would break.

    The remedy differs by adapter — a terminal names a command, the web offers a
    button — so neither belongs in the error and both need to recognize it.
    """
    assert YahooLoginRequiredError().code == "login_required"
    assert YahooAuthError().code == "access_not_approved"


def test_no_error_message_names_a_command_or_a_button() -> None:
    """The same text is read in a terminal and in a browser."""
    for error in (YahooLoginRequiredError(), YahooAuthError()):
        assert "just " not in str(error)
        assert "click" not in str(error).lower()


def test_averages_by_key_are_read_for_each_span_together_as_yahoo_prints_them(tmp_path: Path) -> None:
    season = league_players_xml(averaged_xml("466.p.1", "average_season", {"12": "15.7"}, "32.67"))
    month = league_players_xml(averaged_xml("466.p.1", "average_lastmonth", {"12": "17.7"}))
    client, ctx = _client(
        tmp_path,
        answers={"players;player_keys=466.p.1/stats;type=average_season": season, "players;player_keys": month},
    )

    found = client.averages(["466.p.1", "466.p.1"], (Average.SEASON, Average.LAST_MONTH))

    assert found == {
        Average.SEASON: {"466.p.1": YahooLine(stats={"12": "15.7"}, points="32.67")},
        Average.LAST_MONTH: {"466.p.1": YahooLine(stats={"12": "17.7"})},
    }
    assert len(ctx.queries) == 2


def test_a_player_yahoo_carries_no_line_for_has_no_averages(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, players_xml("Nobody"))

    assert client.averages(["466.p.0"], (Average.SEASON,)) == {Average.SEASON: {}}


def test_a_rosters_averages_are_one_read_by_player(tmp_path: Path) -> None:
    roster = roster_xml(averaged_xml("466.p.3", "average_lastmonth", {"15": "8.7"}))
    client, ctx = _client(tmp_path, roster)

    assert client.roster_averages("466.l.1.t.2", Average.LAST_MONTH) == {"466.p.3": YahooLine(stats={"15": "8.7"})}
    assert ctx.queries == ["team/466.l.1.t.2/roster/players/stats;type=average_lastmonth"]


def test_a_wire_page_says_which_span_its_players_lines_cover(tmp_path: Path) -> None:
    page = league_players_xml(averaged_xml("466.p.9", "average_lastmonth", {"12": "9.5"}))
    client, _ = _client(tmp_path, page)

    [player] = client.fetch_available({Timeframe.SEASON: 1})[Timeframe.SEASON]

    assert (player.coverage, player.line) == ("average_lastmonth", YahooLine(stats={"12": "9.5"}))
