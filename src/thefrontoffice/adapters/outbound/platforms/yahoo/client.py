"""Yahoo Fantasy league data: rosters, matchups and player queries, one league at a time.

Logging in and finding the leagues to read is `auth.py`'s; this reads one of them.
"""

import logging
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from typing import Any, Protocol

from yahoofantasy import League, Player, Team, Week
from yahoofantasy.api.parse import as_list, from_response_object, parse_response

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.http import fetch_many
from thefrontoffice.adapters.outbound.platforms.retry import RetryPolicy, outage
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import (
    YahooAPIError,
    YahooAuthError,
    YahooUnavailableError,
)
from thefrontoffice.adapters.outbound.platforms.yahoo.types import (
    Matchup,
    MatchupSide,
    PlayerStat,
    PlayerStatus,
    RosteredPlayer,
    Timeframe,
)
from thefrontoffice.domain.errors import FrontOfficeError, TeamNotFoundError

logger = logging.getLogger(__name__)

SCOREBOARD_TTL_SECONDS = 120
"""yahoofantasy persists every response for an hour. That suits rosters, but the
scoreboard drives the "which categories are close" analysis and goes stale
within a game night."""

# TTLs from how fast each answer actually goes stale. Waiver leaders move as
# the league claims players; a name search resolves to the same player for as
# long as anyone is looking.
LEADERS_TTL = timedelta(minutes=30)
SEARCH_TTL = timedelta(hours=6)


def translate(error: Exception) -> FrontOfficeError:
    """Turn a yahoofantasy transport failure into something a user can act on.

    A 403 from Yahoo Fantasy means one specific thing — the developer app lacks
    the Fantasy Sports scope — and saying so is the difference between a
    two-minute fix and an afternoon spent re-authorizing a token that was never
    the problem.
    """
    response = getattr(error, "response", None)
    # 403 rather than 401 is the tell: Yahoo authenticated the token and then
    # refused it, which means the grant is empty rather than the token bad.
    if response is not None and getattr(response, "status_code", None) == 403:
        return YahooAuthError()
    down = outage(error)
    if down:
        return YahooUnavailableError("Yahoo", down)
    return YahooAPIError(f"Yahoo request failed: {error}")


def call[T](retry: RetryPolicy, fetch: Callable[[], T]) -> T:
    """`fetch` against Yahoo through the SDK: retried while it fails transiently, then translated.

    The SDK raises requests' own exceptions, and some of its own when a response
    is not the shape it expects; either escapes as a 500 unless it passes through here.
    """
    try:
        return retry.call(fetch)
    except FrontOfficeError:
        raise
    except Exception as e:
        logger.error(f"Yahoo request failed: {e}")
        raise translate(e) from e


def parse(raw: Any) -> Any:
    """A Yahoo XML response as the nested dicts the SDK reads, or the error saying it was not one."""
    try:
        return parse_response(raw)
    except Exception as e:
        raise YahooAPIError(f"Yahoo returned an unreadable response: {e}") from e


def request(retry: RetryPolicy, send: Callable[[], Any]) -> Any:
    """One request through the SDK, returned only if it parses, so a failure is never cached as an answer."""
    raw = call(retry, send)
    parse(raw)
    return raw


class YahooSource(Protocol):
    """What the basketball provider reads Yahoo through. See `SleeperNFLSource` in platforms/sleeper/client.py for why it exists."""

    def fetch_available(self, count: int = 100) -> list[Player]:
        """The best available players in the league, however they became free."""
        ...

    def fetch_top_by_stat(
        self, stats: Mapping[str, str], per_stat: int = 10, sort_type: Timeframe = Timeframe.LAST_WEEK
    ) -> dict[str, list[Player]]:
        """Top available players for each Yahoo stat id in `stats`, keyed as `stats` keys them."""
        ...

    def get_matchup(self, my_team: Team) -> Matchup | None:
        """This week's head-to-head for `my_team`, or None when it has none this week."""
        ...

    def get_user_team(self) -> Team:
        """Identify the team owned by the current user."""
        ...

    def search_players(self, query: str) -> list[Player]:
        """Players in the league whose name matches `query`."""
        ...

    def teams(self) -> list[Team]:
        """Every team in the league."""
        ...


class YahooClient:
    """Reads one Yahoo league.

    Responses go through our own cache rather than the SDK's store: the vendor
    persists into one shared pickle by read-modify-write, so concurrent writes
    clobber each other, and its `_load` takes no expiry at all — waiver leaders
    cached once stayed cached until the file was deleted.
    """

    def __init__(self, league: League, *, cache: JsonDiskCache, retry: RetryPolicy) -> None:
        self.league = league
        self._cache = cache
        self._retry = retry

    def _fetch(self, query: str) -> Any:
        """One request scoped to this league."""
        return request(self._retry, lambda: self.league.ctx.make_request(query, league=self.league.id))

    def _player_query(
        self,
        count: int,
        status: PlayerStatus,
        sort: PlayerStat | str | None,
        sort_type: Timeframe | None,
    ) -> tuple[str, str]:
        """The Yahoo query string for a page of players, and the key it is cached under."""
        params: dict[str, str] = {"count": str(count), "status": status.value}
        if sort is not None:
            params["sort"] = str(sort)
        if sort_type is not None:
            params["sort_type"] = sort_type.value

        params_str = ";".join(f"{k}={v}" for k, v in params.items())
        return f"players;{params_str}", f"players_{self.league.id}_{'_'.join(params.values())}"

    def _players(self, raw: Any, count: int | None = None) -> list[Player]:
        """Walk a players response into Player objects; a league listing none is an empty answer."""
        try:
            container = parse(raw)["fantasy_content"]["league"].get("players")
        except (KeyError, TypeError, AttributeError) as e:
            raise YahooAPIError(f"Yahoo returned an unreadable player list: {e}") from e
        if not isinstance(container, dict) or "player" not in container:
            return []

        players: list[Player] = []
        for player_data in as_list(container["player"]):
            player = Player(self.league)
            from_response_object(player, player_data)
            players.append(player)
        return players[:count]

    def fetch_top_by_stat(
        self,
        stats: Mapping[str, str],
        per_stat: int = 10,
        sort_type: Timeframe = Timeframe.LAST_WEEK,
    ) -> dict[str, list[Player]]:
        """Top available players for each Yahoo stat id in `stats`, keyed as `stats` keys them.

        One request per stat, run concurrently: they are independent, and run one
        after another they were the dominant latency in a scout run. Which stats
        a sport scores is the sport's to say, so the caller names them. One
        failing fails them all — a category left empty would read as nobody
        worth adding in it.
        """
        queries = {
            name: self._player_query(per_stat, PlayerStatus.ALL_AVAILABLE, stat_id, sort_type)
            for name, stat_id in stats.items()
        }
        batch = fetch_many(
            self._cache, {key: (lambda query=query: self._fetch(query)) for query, key in queries.values()}, LEADERS_TTL
        )
        for error in batch.failures.values():
            raise error
        return {name: self._players(batch.values[key], per_stat) for name, (_, key) in queries.items()}

    def fetch_available(self, count: int = 100) -> list[Player]:
        """The best available players in the league, however they became free.

        ALL_AVAILABLE rather than FREE_AGENT: somebody sitting on waivers is
        still a decision to be made about, and a list that hides them is a list
        that goes quiet every Tuesday.
        """
        query, key = self._player_query(count, PlayerStatus.ALL_AVAILABLE, PlayerStat.ACTUAL_RANK, Timeframe.SEASON)
        return self._players(self._cache.cached(key, LEADERS_TTL, lambda: self._fetch(query)), count)

    def search_players(self, query: str) -> list[Player]:
        """Players in the league whose name matches `query`; no match is an empty answer."""
        raw = self._cache.cached(
            f"player_search_{self.league.id}_{query}", SEARCH_TTL, lambda: self._fetch(f"players;search={query}")
        )
        return self._players(raw)

    def teams(self) -> list[Team]:
        """Every team in the league, read through the SDK's own store."""
        return call(self._retry, self.league.teams)

    def get_user_team(self) -> Team:
        """Identify the team owned by the current user.

        Raises:
            TeamNotFoundError: the login owns no team in this league.
        """
        for team in self.teams():
            if getattr(team, "is_owned_by_current_login", False):
                return team
        raise TeamNotFoundError(self.league.name)

    def _sync_current_week(self) -> Week | None:
        """Fetch the current week's scoreboard, once and freshly.

        The SDK persists every response for an hour, which is far too long for
        the scoreboard the "which categories are close" analysis rests on.
        Pre-warming the same persistence key with a short TTL forces a refetch,
        and Week.sync then reads the value just refreshed.
        """
        current_week = getattr(self.league, "current_week", None)
        if not current_week:
            return None

        ctx = self.league.ctx
        try:
            ctx._load_or_fetch(
                f"weeks.{self.league.id}.{current_week}",
                f"scoreboard;week={current_week}",
                league=self.league.id,
                persist_ttl=SCOREBOARD_TTL_SECONDS,
            )
        except Exception as e:
            # A refresh failure is not fatal — Week.sync falls back to whatever
            # is persisted, which is stale but usable.
            logger.warning(f"Could not refresh scoreboard, using persisted copy: {e}")

        week = Week(ctx, self.league, current_week)
        week.sync()
        return week

    def get_matchup(self, my_team: Team) -> Matchup | None:
        """This week's head-to-head for `my_team`, or None when it has none this week.

        None is an answer — between seasons, or a week the team does not play.

        Raises:
            YahooAuthError: the app is not authorized for Fantasy Sports.
            YahooAPIError: Yahoo could not be reached, or answered unreadably.
        """
        return call(self._retry, lambda: self._matchup(my_team))

    def _matchup(self, my_team: Team) -> Matchup | None:
        week = self._sync_current_week()
        if week is None:
            return None
        found = next(
            (m for m in week.matchups if my_team.team_key in (m.team1.team_key, m.team2.team_key)),
            None,
        )
        return _read_matchup(found, my_team) if found is not None else None


def _read_matchup(matchup: Any, my_team: Team) -> Matchup:
    is_first = matchup.team1.team_key == my_team.team_key
    mine, opponent = (matchup.team1, matchup.team2) if is_first else (matchup.team2, matchup.team1)
    first, second = as_list(matchup.teams.team)[:2]
    mine_data, opponent_data = (first, second) if is_first else (second, first)
    return Matchup(
        start=_day(matchup.week_start),
        end=_day(matchup.week_end),
        mine=_side(mine, mine_data),
        opponent=_side(opponent, opponent_data),
        opponent_roster=[
            RosteredPlayer(name=str(p.name.full), position=str(p.display_position)) for p in opponent.players()
        ],
    )


def _side(team: Any, data: Any) -> MatchupSide:
    return MatchupSide(
        team_key=str(team.team_key),
        name=str(team.name),
        points=str(data.team_points.total),
        stats={str(s.stat_id): str(s.value) for s in as_list(data.team_stats.stats.stat)},
    )


def _day(value: Any) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as e:
        raise YahooAPIError(f"Yahoo returned an unreadable matchup date: {value!r}") from e
