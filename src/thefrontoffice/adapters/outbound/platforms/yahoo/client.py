"""Yahoo Fantasy league data: rosters, matchups and player queries."""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from typing import Any

from yahoofantasy import Context, League, Player, Team, Week
from yahoofantasy.api.parse import as_list, from_response_object, get_value, parse_response

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.yahoo import oauth
from thefrontoffice.adapters.outbound.platforms.yahoo.constants import SCOUT_CATEGORIES, STAT_CATEGORIES
from thefrontoffice.adapters.outbound.platforms.yahoo.types import (
    MatchupInfo,
    PlayerStat,
    PlayerStatus,
    Timeframe,
)
from thefrontoffice.config.settings import settings
from thefrontoffice.domain.errors import (
    FrontOfficeError,
    TeamNotFoundError,
    YahooAPIError,
    YahooAuthError,
    YahooLoginRequiredError,
)

logger = logging.getLogger(__name__)

# yahoofantasy persists every response for an hour. That suits rosters, but the
# scoreboard drives the "which categories are close" analysis and goes stale
# within a game night.
SCOREBOARD_TTL_SECONDS = 120

# TTLs from how fast each answer actually goes stale. Waiver leaders move as
# the league claims players; a name search resolves to the same player for as
# long as anyone is looking.
LEADERS_TTL = timedelta(minutes=30)
SEARCH_TTL = timedelta(hours=6)
LEAGUES_TTL = timedelta(hours=1)

# The eight category queries are independent; Yahoo tolerates this easily and it
# is the dominant latency in a scout run.
MAX_PARALLEL_YAHOO_REQUESTS = 8


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
    return YahooAPIError(f"Yahoo request failed: {error}")


class YahooClient:
    @staticmethod
    def _token_exists() -> bool:
        """Check whether a cached OAuth2 token file already exists."""
        return Path(settings.yahoo_token_file).exists()

    @classmethod
    def ensure_authorized(cls) -> None:
        """Require a cached token without trying to obtain one.

        What every non-interactive caller wants. The handshake opens a browser
        and blocks until someone clicks it, so a server that attempted it would
        hang on a window nobody can see.

        Raises:
            YahooLoginRequiredError: no token has been cached yet.
        """
        if not cls._token_exists():
            raise YahooLoginRequiredError()

    @classmethod
    def login(cls, force: bool = False) -> None:
        """Run the OAuth2 handshake. Interactive: opens a browser and waits.

        Raises:
            YahooAPIError: credentials are missing.
            YahooLoginRequiredError: the handshake did not complete.
        """
        if cls._token_exists() and not force:
            return

        client_id, client_secret = settings.yahoo_client_id, settings.yahoo_client_secret
        if not client_id or not client_secret:
            raise YahooAPIError("YAHOO_CLIENT_ID and YAHOO_CLIENT_SECRET must be set before logging in.")

        oauth.authorize(client_id, client_secret, settings.yahoo_redirect_uri)
        logger.info("Yahoo login complete; token cached.")

    @classmethod
    def get_context(cls) -> Context:
        """Return an authorized yahoofantasy Context.

        Reports a missing token rather than starting the browser handshake: this
        runs inside a request handler as often as from a terminal.
        """
        cls.ensure_authorized()
        return Context()

    @classmethod
    def verify(cls) -> None:
        """Confirm the cached token can actually read Fantasy Sports.

        A Yahoo authorization can succeed and still grant nothing: the library
        requests no scope, so Yahoo derives it from whatever API permissions the
        app had *at that moment*. The resulting token authenticates — Yahoo
        answers 403 rather than 401 — and is refused by every endpoint. A
        refresh cannot repair it either, because a refresh token carries the
        grant it was issued with.

        Cheap enough to run after every login, which is the only way to tell
        someone their fresh token is inert before they go looking elsewhere.

        Raises:
            YahooAuthError: the token carries no Fantasy Sports permission.
            YahooAPIError: Yahoo could not be reached.
        """
        context = cls.get_context()
        try:
            context.make_request("users;use_login=1/games")
        except Exception as e:
            logger.error(f"Yahoo token verification failed: {e}")
            raise translate(e) from e

    @staticmethod
    def find_leagues(context: Context, game_code: str, season: int, cache: JsonDiskCache | None = None) -> list[League]:
        """Every league the login plays in for one game and season.

        Filters by game code and season rather than through the SDK's
        `get_leagues`, which resolves the season against a hardcoded table of
        Yahoo game keys and refuses any season newer than its last release —
        every October, until somebody publishes one.

        Raises:
            YahooAuthError: the app is not authorized for Fantasy Sports.
            YahooAPIError: Yahoo could not be reached, or answered unreadably.
        """
        store = cache or JsonDiskCache(Path(settings.yahoo_cache_dir))
        query = f"users;use_login=1/games;game_codes={game_code};seasons={season}/leagues"
        try:
            raw = store.cached(f"leagues_{game_code}_{season}", LEAGUES_TTL, lambda: context.make_request(query))
        except Exception as e:
            logger.error(f"Yahoo league lookup failed: {e}")
            raise translate(e) from e
        data: Any = parse_response(raw)
        try:
            games = data["fantasy_content"]["users"]["user"]["games"]
        except (KeyError, TypeError) as e:
            raise YahooAPIError(f"Yahoo returned an unreadable league list: {e}") from e

        # No game for the season (`<games count="0"/>`) and a game with no
        # leagues in it both mean the login plays nowhere — an answer, not a failure.
        game = games.get("game") if isinstance(games, dict) else None
        container = game.get("leagues") if isinstance(game, dict) else None
        if not isinstance(container, dict) or "league" not in container:
            return []

        leagues: list[League] = []
        for league_data in as_list(container["league"]):
            league = League(context, get_value(league_data["league_key"]))
            from_response_object(league, league_data)
            leagues.append(league)
        return leagues

    def __init__(self, league: League, cache: JsonDiskCache | None = None):
        self.league = league
        # Our own store rather than the SDK's. Two reasons beyond consistency:
        # the vendor persists into one shared pickle by read-modify-write, so
        # concurrent writes clobber each other, and its `_load` takes no expiry
        # at all — waiver leaders cached once stayed cached until the file was
        # deleted, which is exactly the data that goes stale fastest.
        self._cache = cache or JsonDiskCache(Path(settings.yahoo_cache_dir))

    def _player_query(
        self,
        count: int,
        status: PlayerStatus,
        sort: PlayerStat | None,
        sort_type: Timeframe | None,
        **extra_params: str,
    ) -> tuple[str, str]:
        """Build the Yahoo query string and its persistence key."""
        params: dict[str, str] = {"count": str(count), "status": status.value}
        if sort is not None:
            params["sort"] = sort.value
        if sort_type is not None:
            params["sort_type"] = sort_type.value
        params.update(extra_params)

        params_str = ";".join(f"{k}={v}" for k, v in params.items())
        return f"players;{params_str}", f"players_{self.league.id}_{'_'.join(params.values())}"

    def _parse_players(self, data: Any, count: int) -> list[Player]:
        """Walk a players response into Player objects."""
        players_container = data["fantasy_content"]["league"]["players"]
        if not players_container or isinstance(players_container, str):
            return []

        players: list[Player] = []
        if "player" in players_container:
            for player_data in as_list(players_container["player"]):
                p = Player(self.league)
                from_response_object(p, player_data)
                players.append(p)
        return players[:count]

    def fetch_top_by_stat(
        self,
        per_stat: int = 10,
        sort_type: Timeframe = Timeframe.LAST_WEEK,
    ) -> dict[str, list[Player]]:
        """Top available players per scoutable category, keyed by category name.

        One request per category in SCOUT_CATEGORIES, run concurrently.
        """
        specs = {
            stat_name: self._player_query(per_stat, PlayerStatus.ALL_AVAILABLE, stat, sort_type)
            for stat, stat_name in SCOUT_CATEGORIES.items()
        }

        cached: dict[str, Any] = {}
        misses: dict[str, tuple[str, str]] = {}
        for stat_name, (query, cache_key) in specs.items():
            raw = self._cache.get(cache_key, LEADERS_TTL)
            if raw is None:
                misses[stat_name] = (query, cache_key)
            else:
                cached[stat_name] = raw

        fetched = self._fetch_raw_parallel(misses) if misses else {}

        results: dict[str, list[Player]] = {}
        for stat_name in specs:
            raw = cached.get(stat_name, fetched.get(stat_name))
            if raw is None:
                results[stat_name] = []
                continue
            try:
                results[stat_name] = self._parse_players(parse_response(raw), per_stat)
            except Exception as e:
                logger.error(f"Could not parse {stat_name} leaders: {e}")
                raise YahooAPIError(f"Yahoo returned an unreadable {stat_name} response: {e}") from e
        return results

    def _fetch_raw_parallel(self, misses: dict[str, tuple[str, str]]) -> dict[str, Any]:
        """Fetch several player queries concurrently, then store them serially.

        Only the HTTP calls are parallel; `make_request` is the one part of the
        SDK that parallelises safely. The writes stay on this thread because the
        cache file is read-modify-written whole, same as the pickle was. A token
        refresh racing across threads is harmless (both get a valid token), but
        it is forced once up front rather than N times.
        """
        ctx = self.league.ctx
        # Refresh the token on this thread first. make_request would do it
        # lazily, but then every worker could trigger its own refresh.
        refresh = getattr(ctx, "_get_access_token", None)
        if refresh and not getattr(ctx, "_access_token", None):
            refresh()

        def _fetch(item: tuple[str, tuple[str, str]]) -> tuple[str, Any]:
            stat_name, (query, _) = item
            return stat_name, ctx.make_request(query, league=self.league.id)

        raw_by_stat: dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=min(len(misses), MAX_PARALLEL_YAHOO_REQUESTS)) as pool:
            for stat_name, raw in pool.map(_fetch, misses.items()):
                raw_by_stat[stat_name] = raw

        # Serial: one writer, so the cache file cannot be clobbered.
        for stat_name, raw in raw_by_stat.items():
            try:
                parse_response(raw)  # store only what parses, rather than caching a failure
                self._cache.set(misses[stat_name][1], raw)
            except Exception as e:
                logger.warning(f"Not storing unparseable {stat_name} response: {e}")
        return raw_by_stat

    def fetch_available(self, count: int = 100) -> list[Player]:
        """The best available players in the league, however they became free.

        ALL_AVAILABLE rather than FREE_AGENT: somebody sitting on waivers is
        still a decision to be made about, and a list that hides them is a list
        that goes quiet every Tuesday.
        """
        query, cache_key = self._player_query(
            count, PlayerStatus.ALL_AVAILABLE, PlayerStat.ACTUAL_RANK, Timeframe.SEASON
        )
        raw = self._cache.cached(
            cache_key,
            LEADERS_TTL,
            lambda: self.league.ctx.make_request(query, league=self.league.id),
        )
        return self._parse_players(parse_response(raw), count)

    def get_user_team(self) -> Team:
        """Identify the team owned by the current user.

        Raises:
            TeamNotFoundError: the login owns no team in this league.
        """
        for team in self.league.teams():
            if hasattr(team, "is_owned_by_current_login") and team.is_owned_by_current_login:
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

    def _find_matchup(self, week: Week, my_team: Team) -> Any:
        for m in week.matchups:
            if my_team.team_key in (m.team1.team_key, m.team2.team_key):
                return m
        return None

    def get_matchup(self, my_team: Team) -> MatchupInfo:
        """Fetch the current matchup once, returning both context and dates."""
        try:
            week = self._sync_current_week()
            if week is None:
                return MatchupInfo()

            matchup = self._find_matchup(week, my_team)
            if matchup is None:
                return MatchupInfo()

            return MatchupInfo(
                context=self._render_matchup(matchup, my_team),
                week_start=str(matchup.week_start),
                week_end=str(matchup.week_end),
            )
        except Exception as e:
            logger.warning(f"Could not fetch matchup: {e}")
            return MatchupInfo()

    def _render_matchup(self, matchup: Any, my_team: Team) -> str:
        """Format a matchup into the context block used in AI prompts."""
        is_team1 = matchup.team1.team_key == my_team.team_key
        opponent = matchup.team2 if is_team1 else matchup.team1

        teams_data = as_list(matchup.teams.team)
        my_data = teams_data[0] if is_team1 else teams_data[1]
        opp_data = teams_data[1] if is_team1 else teams_data[0]

        def get_stats(team_stats_obj: Any) -> dict[str, Any]:
            return {str(s.stat_id): s.value for s in as_list(team_stats_obj.stats.stat)}

        my_stats = get_stats(my_data.team_stats)
        opp_stats = get_stats(opp_data.team_stats)

        breakdown = "\nCATEGORY BREAKDOWN (Us vs Opponent):"
        for stat, cat_name in STAT_CATEGORIES.items():
            breakdown += f"\n- {cat_name}: {my_stats.get(stat.value, 'N/A')} vs {opp_stats.get(stat.value, 'N/A')}"

        opp_roster: list[Player] = opponent.players()
        opp_roster_str = ", ".join(f"{p.name.full} ({p.display_position})" for p in opp_roster[:12])

        return (
            f"\nCURRENT MATCHUP: Playing against {opponent.name}"
            f"\nMATCHUP SCORE: You {my_data.team_points.total} - {opp_data.team_points.total} Opponent"
            f"{breakdown}"
            f"\nOPPONENT KEY PLAYERS: {opp_roster_str}"
        )

    def search_players(self, query: str) -> list[Player]:
        """
        Search for players by name using the league context.
        Uses league/{id}/players;search={query}
        """
        try:
            league_key = self.league.league_key
            query_str = f"league/{league_key}/players;search={query}"
            cache_key = f"player_search_{league_key}_{query}"

            logger.debug(f"Searching players in league: {query_str}")

            data = self._cache.cached(
                cache_key,
                SEARCH_TTL,
                lambda: self.league.ctx.make_request(query_str, league=self.league.id),
            )

            try:
                base = data["fantasy_content"]["league"]
                players_container = base.get("players", {})
            except KeyError as e:
                raise YahooAPIError(f"Unexpected Yahoo response structure for search {query!r}") from e

            if not players_container or isinstance(players_container, str):
                return []

            results: list[Player] = []
            if "player" in players_container:
                for player_data in as_list(players_container["player"]):
                    p = Player(self.league)
                    from_response_object(p, player_data)
                    results.append(p)

            return results

        except YahooAPIError:
            raise
        except Exception as e:
            logger.error(f"Error searching for player '{query}': {e}")
            raise YahooAPIError(f"Yahoo player search failed for {query!r}: {e}") from e
