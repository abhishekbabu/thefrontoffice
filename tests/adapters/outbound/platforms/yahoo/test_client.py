"""Tests for YahooClient, the reader of one Yahoo league.

The client builds Yahoo's query strings by hand and walks the XML it gets back,
so both are ours to get right. A fake context stands in for the SDK's HTTP and
answers in Yahoo's own XML, which the real parser reads.
"""

import threading
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import requests
from support.http import NO_WAIT, http_error

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.yahoo.client import YahooClient, translate
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import (
    YahooAPIError,
    YahooAuthError,
    YahooLoginRequiredError,
    YahooUnavailableError,
)
from thefrontoffice.domain.errors import TeamNotFoundError

STATS = {"PTS": "12", "REB": "15", "BLK": "18"}
"""Three of a sport's stat ids, named the way the caller names them."""


def players_xml(*names: str) -> str:
    """A league's players response, as Yahoo serves it."""
    rows = "".join(
        f"<player><name><full>{name}</full></name><display_position>PF</display_position>"
        f"<editorial_team_abbr>LAL</editorial_team_abbr></player>"
        for name in names
    )
    return (
        '<fantasy_content xmlns="http://fantasysports.yahooapis.com/fantasy/v2/base.rng">'
        f'<league><players count="{len(names)}">{rows}</players></league></fantasy_content>'
    )


class FakeContext:
    """Stands in for yahoofantasy's Context.

    `make_request` is the only fetch the client makes through the SDK for
    itself. `_load_or_fetch` survives for the scoreboard alone, where `Week.sync`
    reads the SDK's own store and pre-warming that key is the only way to force
    a refresh.
    """

    def __init__(self, response: Any = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.fail_first: list[Exception] = []
        """Raised one per request, before any answer."""
        self.requests: list[tuple[str, Any]] = []
        self.barrier: threading.Barrier | None = None
        """Held by each request until all its parties arrive, so serial requests never finish."""
        self.refresh_ttls: list[int] = []

    def _load_or_fetch(self, cache_key: str, query: str, **kwargs: Any) -> Any:
        self.refresh_ttls.append(kwargs.get("persist_ttl", 3600))
        if self.error:
            raise self.error
        return self.response

    def make_request(self, query: str, league: Any = False) -> Any:
        self.requests.append((query, league))
        if self.fail_first:
            raise self.fail_first.pop(0)
        if self.error:
            raise self.error
        if self.barrier:
            self.barrier.wait()
        return self.response

    @property
    def queries(self) -> list[str]:
        return [query for query, _ in self.requests]


def _client(
    tmp_path: Path, response: Any = None, error: Exception | None = None, teams: list[Any] | None = None
) -> tuple[YahooClient, FakeContext]:
    ctx = FakeContext(response, error)
    league = SimpleNamespace(id="466.l.123", name="My League", ctx=ctx, teams=lambda: teams or [])
    return YahooClient(league, cache=JsonDiskCache(tmp_path / "cache"), retry=NO_WAIT), ctx


# ── fetch_top_by_stat ───────────────────────────────────────────────────


def test_one_request_per_stat_asked_for_keyed_as_asked(tmp_path: Path) -> None:
    client, ctx = _client(tmp_path, players_xml("A B"))

    results = client.fetch_top_by_stat(STATS, per_stat=4)

    assert {name: [p.name.full for p in players] for name, players in results.items()} == {
        name: ["A B"] for name in STATS
    }
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
    assert client.fetch_top_by_stat(STATS, per_stat=4)["PTS"][0].name.full == "A B"


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

    assert [p.name.full for p in available] == ["A B", "C D"]
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

    assert [p.name.full for p in client.fetch_available()] == ["A B"]
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
    assert [p.name.full for p in results] == ["LeBron James"]


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


def test_the_owned_team_is_returned(tmp_path: Path) -> None:
    mine = SimpleNamespace(name="Mine", is_owned_by_current_login=1)
    theirs = SimpleNamespace(name="Theirs")
    client, _ = _client(tmp_path, teams=[theirs, mine])
    assert client.get_user_team() is mine


def test_owning_no_team_raises_with_the_league_name(tmp_path: Path) -> None:
    client, _ = _client(tmp_path, teams=[SimpleNamespace(name="Theirs", is_owned_by_current_login=0)])
    with pytest.raises(TeamNotFoundError) as caught:
        client.get_user_team()
    assert caught.value.league_name == "My League"


def test_a_refused_team_list_names_the_missing_permission(tmp_path: Path) -> None:
    """The SDK fetches teams itself, and fails in requests' terms."""
    client, ctx = _client(tmp_path)

    def _refused() -> list[Any]:
        raise http_error(403)

    client.league = SimpleNamespace(id="466.l.123", name="My League", ctx=ctx, teams=_refused)
    with pytest.raises(YahooAuthError):
        client.teams()


# ── the matchup ─────────────────────────────────────────────────────────


class FakeWeek:
    """Stands in for yahoofantasy's Week, which the client builds itself."""

    def __init__(self, matchups: list[Any], error: Exception | None = None) -> None:
        self.matchups = matchups
        self.error = error

    def sync(self) -> None:
        if self.error:
            raise self.error


def _fake_team(team_key: str) -> Any:
    """A duck-typed Team; the client only reads .team_key off it."""
    return SimpleNamespace(team_key=team_key)


def _stat(stat_id: str, value: str) -> Any:
    return SimpleNamespace(stat_id=stat_id, value=value)


def _team_data(points: str, stats: list[Any]) -> Any:
    return SimpleNamespace(
        team_stats=SimpleNamespace(stats=SimpleNamespace(stat=stats)),
        team_points=SimpleNamespace(total=points),
    )


def _matchup(my_key: str = "t1") -> Any:
    mine = SimpleNamespace(team_key=my_key, name="Mine", players=lambda: [])
    theirs = SimpleNamespace(
        team_key="t2",
        name="Theirs",
        players=lambda: [SimpleNamespace(name=SimpleNamespace(full="Star Player"), display_position="PG")],
    )
    return SimpleNamespace(
        team1=mine,
        team2=theirs,
        week_start="2026-02-09",
        week_end="2026-02-15",
        teams=SimpleNamespace(team=[_team_data("50", [_stat("18", "12")]), _team_data("60", [_stat("18", "17")])]),
    )


def _matchup_client(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *matchups: Any,
    week: int | None = 5,
    sync_error: Exception | None = None,
) -> tuple[YahooClient, FakeContext]:
    import thefrontoffice.adapters.outbound.platforms.yahoo.client as mod

    monkeypatch.setattr(mod, "Week", lambda ctx, league, week_num: FakeWeek(list(matchups), sync_error))
    client, ctx = _client(tmp_path, "")
    client.league.current_week = week
    return client, ctx


def test_the_matchup_is_read_into_both_sides_by_stat_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client, _ = _matchup_client(monkeypatch, tmp_path, _matchup())
    info = client.get_matchup(_fake_team("t1"))

    assert info is not None
    assert (info.start, info.end) == (date(2026, 2, 9), date(2026, 2, 15))
    assert (info.mine.name, info.mine.points, info.mine.stats) == ("Mine", "50", {"18": "12"})
    assert (info.opponent.name, info.opponent.points, info.opponent.stats) == ("Theirs", "60", {"18": "17"})
    assert [(p.name, p.position) for p in info.opponent_roster] == [("Star Player", "PG")]


def test_the_second_team_listed_still_reads_as_mine(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client, _ = _matchup_client(monkeypatch, tmp_path, _matchup())
    info = client.get_matchup(_fake_team("t2"))

    assert info is not None
    assert (info.mine.name, info.mine.stats) == ("Theirs", {"18": "17"})
    assert info.opponent.name == "Mine"


def test_no_matchup_this_week_is_an_answer_not_a_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    client, _ = _matchup_client(monkeypatch, tmp_path, _matchup())
    assert client.get_matchup(_fake_team("t9")) is None
    client, _ = _matchup_client(monkeypatch, tmp_path, _matchup(), week=None)
    assert client.get_matchup(_fake_team("t1")) is None


def test_the_scoreboard_is_refreshed_on_a_short_ttl(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An hour-old scoreboard would misstate every category margin."""
    import thefrontoffice.adapters.outbound.platforms.yahoo.client as mod

    client, ctx = _matchup_client(monkeypatch, tmp_path, _matchup())
    client.get_matchup(_fake_team("t1"))

    assert ctx.refresh_ttls == [mod.SCOREBOARD_TTL_SECONDS]
    assert mod.SCOREBOARD_TTL_SECONDS < 3600


def test_a_failed_scoreboard_refresh_falls_back_to_the_persisted_copy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, ctx = _matchup_client(monkeypatch, tmp_path, _matchup())
    ctx.error = RuntimeError("yahoo down")

    info = client.get_matchup(_fake_team("t1"))

    assert info is not None
    assert info.start == date(2026, 2, 9)  # still served from Week.sync


def test_a_failed_scoreboard_raises_rather_than_reading_as_no_matchup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client, _ = _matchup_client(monkeypatch, tmp_path, _matchup(), sync_error=requests.ConnectionError("yahoo down"))

    with pytest.raises(YahooUnavailableError):
        client.get_matchup(_fake_team("t1"))


def test_an_unreadable_matchup_date_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    odd = _matchup()
    odd.week_start = "someday"
    client, _ = _matchup_client(monkeypatch, tmp_path, odd)

    with pytest.raises(YahooAPIError):
        client.get_matchup(_fake_team("t1"))


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
