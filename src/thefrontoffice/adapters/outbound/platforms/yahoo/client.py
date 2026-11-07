"""Yahoo Fantasy league data: rosters, matchups and player queries, one league at a time.

Logging in and finding the leagues to read is `auth.py`'s; this reads one of them.
The SDK is a transport and an XML parser here and nothing more: every request
goes through `call`, and every response is read into this package's own types,
so nothing outside it touches an object whose attributes arrive by `setattr`.
"""

import logging
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from typing import Any, Protocol

from yahoofantasy.api.parse import as_list, parse_response

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
    TeamStanding,
    Timeframe,
    YahooLeague,
    YahooPlayer,
    YahooTeam,
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
# The hour the SDK's own store kept them for, when it fetched them.
TEAMS_TTL = timedelta(hours=1)
ROSTER_TTL = timedelta(hours=1)


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


class YahooContext(Protocol):
    """The SDK's authorized context: the two ways this package asks Yahoo anything."""

    def make_request(self, url: str, league: str | bool = False) -> str:
        """The raw XML for `url`, under `league/<key>/` when a league is named."""
        ...

    def _load_or_fetch(self, persist_path: str, query: str, *, league: str, persist_ttl: int = 3600) -> Any:
        """The parsed response, from the SDK's own store while it is younger than `persist_ttl`."""
        ...


class YahooSource(Protocol):
    """What the basketball provider reads Yahoo through. See `SleeperNFLSource` in platforms/sleeper/client.py for why it exists."""

    def fetch_available(self, count: int = 100) -> list[YahooPlayer]:
        """The best available players in the league, however they became free."""
        ...

    def fetch_top_by_stat(
        self, stats: Mapping[str, str], per_stat: int = 10, sort_type: Timeframe = Timeframe.LAST_WEEK
    ) -> dict[str, list[YahooPlayer]]:
        """Top available players for each Yahoo stat id in `stats`, keyed as `stats` keys them."""
        ...

    def get_matchup(self, team_key: str) -> Matchup | None:
        """This week's head-to-head for the team, or None when it has none this week."""
        ...

    def get_user_team(self) -> YahooTeam:
        """Identify the team owned by the current user."""
        ...

    def roster(self, team_key: str) -> list[YahooPlayer]:
        """The players a team holds, each in the slot their manager has them in."""
        ...

    def search_players(self, query: str) -> list[YahooPlayer]:
        """Players in the league whose name matches `query`."""
        ...

    def teams(self) -> list[YahooTeam]:
        """Every team in the league."""
        ...


class YahooClient:
    """Reads one Yahoo league.

    Responses go through our own cache rather than the SDK's store: the vendor
    persists into one shared pickle by read-modify-write, so concurrent writes
    clobber each other, and its `_load` takes no expiry at all — waiver leaders
    cached once stayed cached until the file was deleted.
    """

    def __init__(self, league: YahooLeague, *, context: YahooContext, cache: JsonDiskCache, retry: RetryPolicy) -> None:
        self.league = league
        self._context = context
        self._cache = cache
        self._retry = retry

    def _fetch(self, query: str) -> Any:
        """One request scoped to this league."""
        return request(self._retry, lambda: self._context.make_request(query, league=self.league.league_key))

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
        return f"players;{params_str}", f"players_{self.league.league_key}_{'_'.join(params.values())}"

    def _players(self, raw: Any, count: int | None = None) -> list[YahooPlayer]:
        """A league's players response, read; a league listing none is an empty answer."""
        return readable("player list", lambda: player_list(parse(raw)["fantasy_content"]["league"]))[:count]

    def fetch_top_by_stat(
        self,
        stats: Mapping[str, str],
        per_stat: int = 10,
        sort_type: Timeframe = Timeframe.LAST_WEEK,
    ) -> dict[str, list[YahooPlayer]]:
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

    def fetch_available(self, count: int = 100) -> list[YahooPlayer]:
        """The best available players in the league, however they became free.

        ALL_AVAILABLE rather than FREE_AGENT: somebody sitting on waivers is
        still a decision to be made about, and a list that hides them is a list
        that goes quiet every Tuesday.
        """
        query, key = self._player_query(count, PlayerStatus.ALL_AVAILABLE, PlayerStat.ACTUAL_RANK, Timeframe.SEASON)
        return self._players(self._cache.cached(key, LEADERS_TTL, lambda: self._fetch(query)), count)

    def search_players(self, query: str) -> list[YahooPlayer]:
        """Players in the league whose name matches `query`; no match is an empty answer."""
        raw = self._cache.cached(
            f"player_search_{self.league.league_key}_{query}",
            SEARCH_TTL,
            lambda: self._fetch(f"players;search={query}"),
        )
        return self._players(raw)

    def teams(self) -> list[YahooTeam]:
        """Every team in the league."""
        raw = self._cache.cached(f"teams_{self.league.league_key}", TEAMS_TTL, lambda: self._fetch("teams"))
        return readable("team list", lambda: team_list(parse(raw)["fantasy_content"]["league"]))

    def get_user_team(self) -> YahooTeam:
        """Identify the team owned by the current user.

        Raises:
            TeamNotFoundError: the login owns no team in this league.
        """
        for team in self.teams():
            if team.is_mine:
                return team
        raise TeamNotFoundError(self.league.name)

    def roster(self, team_key: str) -> list[YahooPlayer]:
        """The players a team holds today, each in the slot their manager has them in."""
        raw = self._cache.cached(
            f"roster_{team_key}",
            ROSTER_TTL,
            lambda: request(self._retry, lambda: self._context.make_request(f"team/{team_key}/roster")),
        )
        return readable("roster", lambda: player_list(parse(raw)["fantasy_content"]["team"]["roster"]))

    def get_matchup(self, team_key: str) -> Matchup | None:
        """This week's head-to-head for the team, or None when it has none this week.

        None is an answer — between seasons, or a week the team does not play.

        Raises:
            YahooAuthError: the app is not authorized for Fantasy Sports.
            YahooAPIError: Yahoo could not be reached, or answered unreadably.
        """
        week = self.league.current_week
        if not week:
            return None
        scoreboard = call(self._retry, lambda: self._scoreboard(week))
        found = readable("scoreboard", lambda: find_matchup(scoreboard, team_key))
        if found is None:
            return None
        start, end, mine, opponent = found
        return Matchup(
            start=start, end=end, mine=mine, opponent=opponent, opponent_roster=self.roster(opponent.team_key)
        )

    def _scoreboard(self, week: int) -> Any:
        """The week's scoreboard, as fresh as `SCOREBOARD_TTL_SECONDS` allows.

        Read through the SDK's store, keyed as the SDK keys it, so a refresh that
        fails can fall back to the copy persisted there — stale, but usable.
        """
        key, query = f"weeks.{self.league.league_key}.{week}", f"scoreboard;week={week}"
        try:
            return self._context._load_or_fetch(
                key, query, league=self.league.league_key, persist_ttl=SCOREBOARD_TTL_SECONDS
            )
        except Exception as e:
            logger.warning(f"Could not refresh scoreboard, using persisted copy: {e}")
            return self._context._load_or_fetch(key, query, league=self.league.league_key)


# ── reading responses ───────────────────────────────────────────────────
# The SDK parses Yahoo's XML into nested dicts (badgerfish: an element's text
# under `$`, a list of one as the element itself). These read those dicts once,
# here, so a missing element reads as empty rather than failing in a caller.


def readable[T](what: str, read: Callable[[], T]) -> T:
    """`read` over a parsed response, or the error saying Yahoo answered in a shape it did not expect."""
    try:
        return read()
    except (KeyError, TypeError, AttributeError, ValueError) as e:
        raise YahooAPIError(f"Yahoo returned an unreadable {what}: {e}") from e


def _node(data: Any, *path: str) -> Any:
    """The element at `path` in a parsed response, or None where the response stops short of it."""
    for key in path:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _value(data: Any, *path: str) -> Any:
    """The text of the element at `path`, or None where there is none."""
    node = _node(data, *path)
    return node.get("$") if isinstance(node, dict) else node


def _text(data: Any, *path: str) -> str:
    value = _value(data, *path)
    return "" if value is None else str(value)


def _number(data: Any, *path: str) -> int:
    value = _value(data, *path)
    return int(value) if value not in (None, "") else 0


def _items(container: Any, child: str) -> list[Any]:
    """The `child` elements of a list element: none, one or many, always as a list."""
    if not isinstance(container, dict) or child not in container:
        return []
    return as_list(container[child])


def player_list(parent: Any) -> list[YahooPlayer]:
    return [_player(p) for p in _items(_node(parent, "players"), "player")]


def _player(data: Any) -> YahooPlayer:
    return YahooPlayer(
        player_key=_text(data, "player_key"),
        name=_text(data, "name", "full"),
        position=_text(data, "display_position"),
        team=_text(data, "editorial_team_abbr"),
        status=_text(data, "status"),
        injury_note=_text(data, "injury_note"),
        slot=_text(data, "selected_position", "position"),
    )


def team_list(league: Any) -> list[YahooTeam]:
    return [_team(t) for t in _items(_node(league, "teams"), "team")]


def _team(data: Any) -> YahooTeam:
    standings = _node(data, "team_standings")
    return YahooTeam(
        team_key=_text(data, "team_key"),
        name=_text(data, "name"),
        is_mine=bool(_value(data, "is_owned_by_current_login")),
        adds_used=_number(data, "roster_adds", "value"),
        standing=_standing(standings) if isinstance(standings, dict) else None,
    )


def _standing(data: Any) -> TeamStanding:
    return TeamStanding(
        rank=_number(data, "rank"),
        wins=_number(data, "outcome_totals", "wins"),
        losses=_number(data, "outcome_totals", "losses"),
        ties=_number(data, "outcome_totals", "ties"),
        points_for=_text(data, "points_for"),
    )


def find_matchup(scoreboard: Any, team_key: str) -> tuple[date, date, MatchupSide, MatchupSide] | None:
    """The week's dates and both sides of the team's matchup, its own first; None where it plays nobody."""
    matchups = scoreboard["fantasy_content"]["league"]["scoreboard"]["matchups"]
    for matchup in _items(matchups, "matchup"):
        sides = [_side(team) for team in _items(_node(matchup, "teams"), "team")[:2]]
        keys = [side.team_key for side in sides]
        if team_key in keys and len(sides) == 2:
            mine, opponent = sides if keys[0] == team_key else sides[::-1]
            return _day(_value(matchup, "week_start")), _day(_value(matchup, "week_end")), mine, opponent
    return None


def _side(data: Any) -> MatchupSide:
    return MatchupSide(
        team_key=_text(data, "team_key"),
        name=_text(data, "name"),
        points=_text(data, "team_points", "total"),
        stats={_text(s, "stat_id"): _text(s, "value") for s in _items(_node(data, "team_stats", "stats"), "stat")},
    )


def _day(value: Any) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as e:
        raise YahooAPIError(f"Yahoo returned an unreadable matchup date: {value!r}") from e


def league_list(games: Any) -> list[YahooLeague]:
    """The leagues under a login's `games` element; none, where it plays in no game or no league."""
    game = _node(games, "game")
    return [_league(league) for league in _items(_node(game, "leagues"), "league")]


def _league(data: Any) -> YahooLeague:
    week = _value(data, "current_week")
    return YahooLeague(
        league_key=_text(data, "league_key"),
        name=_text(data, "name"),
        league_type=_text(data, "league_type"),
        current_week=int(week) if week not in (None, "") else None,
    )
