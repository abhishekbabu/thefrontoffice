"""Tests for YahooClient, the reader of one Yahoo league.

The client builds Yahoo's query strings by hand and walks the XML it gets back,
and reads what it gets back into its own types, so both are ours to get right.
A fake context stands in for the SDK's HTTP and answers in Yahoo's own XML,
which the real parser reads.
"""

import threading
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest
import requests
from support.http import NO_WAIT, http_error
from support.yahoo import SDK_STORE_TTL, FakeContext

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.yahoo.client import SCOREBOARD_TTL_SECONDS, YahooClient, translate
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import (
    YahooAPIError,
    YahooAuthError,
    YahooLoginRequiredError,
    YahooUnavailableError,
)
from thefrontoffice.adapters.outbound.platforms.yahoo.types import TeamStanding, YahooLeague, YahooPlayer
from thefrontoffice.domain.errors import TeamNotFoundError

STATS = {"PTS": "12", "REB": "15", "BLK": "18"}
"""Three of a sport's stat ids, named the way the caller names them."""


def players_xml(*names: str) -> str:
    """A league's players response, as Yahoo serves it."""
    rows = "".join(
        f"<player><player_key>466.p.{i}</player_key><name><full>{name}</full></name><display_position>PF</display_position>"
        f"<editorial_team_abbr>LAL</editorial_team_abbr></player>"
        for i, name in enumerate(names)
    )
    return (
        '<fantasy_content xmlns="http://fantasysports.yahooapis.com/fantasy/v2/base.rng">'
        f'<league><players count="{len(names)}">{rows}</players></league></fantasy_content>'
    )


def teams_xml(*teams: str) -> str:
    return f"<fantasy_content><league><teams>{''.join(teams)}</teams></league></fantasy_content>"


def team_xml(key: str, name: str, *, mine: bool = False, adds: int = 0, standings: str = "") -> str:
    owned = "<is_owned_by_current_login>1</is_owned_by_current_login>" if mine else ""
    return (
        f"<team><team_key>{key}</team_key><name>{name}</name>{owned}"
        f"<roster_adds><value>{adds}</value></roster_adds>{standings}</team>"
    )


def standings_xml(rank: int, wins: int, losses: int, ties: int, points: str) -> str:
    return (
        f"<team_standings><rank>{rank}</rank><points_for>{points}</points_for><outcome_totals>"
        f"<wins>{wins}</wins><losses>{losses}</losses><ties>{ties}</ties></outcome_totals></team_standings>"
    )


def roster_xml(*players: str) -> str:
    return f"<fantasy_content><team><roster><players>{''.join(players)}</players></roster></team></fantasy_content>"


def rostered_xml(name: str, slot: str, status: str = "", note: str = "") -> str:
    return (
        f"<player><player_key>466.p.{len(name)}</player_key><name><full>{name}</full></name>"
        f"<display_position>PG,SG</display_position><editorial_team_abbr>BOS</editorial_team_abbr>"
        f"<status>{status}</status><injury_note>{note}</injury_note>"
        f"<selected_position><position>{slot}</position></selected_position></player>"
    )


LEAGUE = YahooLeague(league_key="466.l.123", name="My League", current_week=5)


def _client(
    tmp_path: Path,
    response: str = "<fantasy_content/>",
    error: Exception | None = None,
    answers: dict[str, str] | None = None,
    league: YahooLeague = LEAGUE,
) -> tuple[YahooClient, FakeContext]:
    ctx = FakeContext(response, error, answers)
    return YahooClient(league, context=ctx, cache=JsonDiskCache(tmp_path / "cache"), retry=NO_WAIT), ctx


# ── fetch_top_by_stat ───────────────────────────────────────────────────


def test_one_request_per_stat_asked_for_keyed_as_asked(tmp_path: Path) -> None:
    client, ctx = _client(tmp_path, players_xml("A B"))

    results = client.fetch_top_by_stat(STATS, per_stat=4)

    assert {name: [p.name for p in players] for name, players in results.items()} == {name: ["A B"] for name in STATS}
    assert all("count=4" in q and "status=A" in q for q in ctx.queries)
    assert {q.split("sort=")[1].split(";")[0] for q in ctx.queries} == set(STATS.values())
    assert {league for _, league in ctx.requests} == {"466.l.123"}


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


def test_available_players_include_those_on_waivers_by_season_rank(tmp_path: Path) -> None:
    client, ctx = _client(tmp_path, players_xml("A B", "C D", "E F"))

    available = client.fetch_available(count=2)

    assert [p.name for p in available] == ["A B", "C D"]
    assert ctx.queries == ["players;count=2;status=A;sort=AR;sort_type=season"]


def test_a_refused_available_list_names_the_missing_permission(tmp_path: Path) -> None:
    """Untranslated, requests' own error escapes as a 500 with nothing to render."""
    client, _ = _client(tmp_path, error=http_error(403))
    with pytest.raises(YahooAuthError):
        client.fetch_available()


# ── transient failures ──────────────────────────────────────────────────


def test_a_transient_failure_is_retried(tmp_path: Path) -> None:
    client, ctx = _client(tmp_path, players_xml("A B"))
    ctx.fail_first = [requests.exceptions.Timeout()]

    assert [p.name for p in client.fetch_available()] == ["A B"]
    assert len(ctx.requests) == 2


def test_yahoo_staying_down_says_to_wait(tmp_path: Path) -> None:
    client, ctx = _client(tmp_path, error=http_error(503))

    with pytest.raises(YahooUnavailableError):
        client.fetch_available()
    assert len(ctx.requests) == NO_WAIT.attempts


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


def test_a_roster_failure_is_ours_to_render_not_requests(tmp_path: Path) -> None:
    """The SDK's own roster fetch failed in requests' terms, and escaped as a 500."""
    client, _ = _client(tmp_path, error=requests.ConnectionError("down"))
    with pytest.raises(YahooUnavailableError):
        client.roster("t.1")


# ── the matchup ─────────────────────────────────────────────────────────


def _side_xml(key: str, name: str, points: str, blocks: str) -> str:
    return (
        f"<team><team_key>{key}</team_key><name>{name}</name><team_points><total>{points}</total></team_points>"
        f"<team_stats><stats><stat><stat_id>18</stat_id><value>{blocks}</value></stat></stats></team_stats></team>"
    )


def scoreboard_xml(start: str = "2026-02-09", end: str = "2026-02-15") -> str:
    matchup = (
        f"<matchup><week_start>{start}</week_start><week_end>{end}</week_end>"
        f"<teams>{_side_xml('t1', 'Mine', '50', '12')}{_side_xml('t2', 'Theirs', '60', '17')}</teams></matchup>"
    )
    return (
        f"<fantasy_content><league><scoreboard><matchups>{matchup}</matchups></scoreboard></league></fantasy_content>"
    )


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


def test_between_seasons_there_is_no_week_to_ask_about(tmp_path: Path) -> None:
    client, ctx = _client(tmp_path, league=replace(LEAGUE, current_week=None))

    assert client.get_matchup("t1") is None
    assert ctx.store_ttls == []


def test_the_scoreboard_is_refreshed_on_a_short_ttl(tmp_path: Path) -> None:
    """An hour-old scoreboard would misstate every category margin."""
    client, ctx = _matchup_client(tmp_path)
    client.get_matchup("t1")

    assert ctx.store_ttls == [SCOREBOARD_TTL_SECONDS]
    assert SCOREBOARD_TTL_SECONDS < SDK_STORE_TTL


def test_a_failed_scoreboard_refresh_falls_back_to_the_persisted_copy(tmp_path: Path) -> None:
    client, ctx = _matchup_client(tmp_path, fail_first=[RuntimeError("yahoo down")])

    info = client.get_matchup("t1")

    assert info is not None
    assert info.start == date(2026, 2, 9)
    assert ctx.store_ttls == [SCOREBOARD_TTL_SECONDS, SDK_STORE_TTL]


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
