"""Sleeper API client.

Sleeper is public and read-only: no OAuth, no API key. The whole surface is
plain GETs, which is why the football path has nothing resembling the Yahoo
login flow.

Sleeper asks callers to stay under 1000 requests/minute and to fetch the player
catalog "once per day at most". Everything cacheable is cached on disk with a
TTL chosen per endpoint: the catalog daily, projections for a settled week
effectively forever, trending for an hour.
"""

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

from tenacity import Retrying

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.http import JsonApiClient
from thefrontoffice.adapters.outbound.platforms.retry import build_retry, is_transient
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    FANTASY_POSITIONS,
    NBA_STAT_KEYS,
    NFL_LINE_KEYS,
    SEASON_STAT_KEYS,
    SPLIT_KEYS,
    TEAM_ROW_PREFIX,
    GameProjection,
    NBAGameLog,
    NFLGameLine,
    PlayerMeta,
    ScheduledGame,
    ScoringFormat,
    SeasonState,
    SeasonStats,
    SleeperLeague,
    SleeperRoster,
    SleeperUser,
    Transaction,
    TrendingPlayer,
    WeeklyProjection,
)
from thefrontoffice.config.settings import settings
from thefrontoffice.domain.errors import SleeperAPIError

logger = logging.getLogger(__name__)

BASE_URL = "https://api.sleeper.app/v1"
PROJECTIONS_URL = "https://api.sleeper.app/projections"
# Not under /v1, unlike everything else here.
SCHEDULE_URL = "https://api.sleeper.app/schedule"
# Per-game logs live off the same un-versioned root as projections.
STATS_URL = "https://api.sleeper.app/stats"

# Sleeper serves several sports off the same shape. The football path uses "nfl";
# the basketball projections the NBA scout reads use "nba".
NFL = "nfl"
NBA = "nba"

REQUEST_TIMEOUT_SECONDS = 30
CATALOG_TIMEOUT_SECONDS = 90  # the player catalog is ~14MB

# TTLs, chosen from how quickly each endpoint's data actually changes.
PLAYERS_TTL = timedelta(days=1)  # the docs ask for at most one fetch per day
PROJECTIONS_TTL = timedelta(hours=6)
TRENDING_TTL = timedelta(hours=1)
LEAGUE_TTL = timedelta(hours=6)
ROSTERS_TTL = timedelta(minutes=10)  # changes on every waiver claim
MATCHUPS_TTL = timedelta(minutes=2)  # live scores during games
STATE_TTL = timedelta(hours=1)
# A season's totals move only when a game is played, and a finished season
# never moves again. This is the slowest-changing thing Sleeper serves.
SEASON_STATS_TTL = timedelta(hours=12)
# A published season schedule barely moves — flexed games are the exception,
# not the rule — and a transaction feed only grows.
SEASON_SCHEDULE_TTL = timedelta(hours=12)
# A finished game's line never changes; only the newest week is still moving.
NBA_LOGS_TTL = timedelta(hours=3)
NFL_LINES_TTL = timedelta(hours=3)
TRANSACTIONS_TTL = timedelta(minutes=15)

RETRY_MAX_ATTEMPTS = 3

# Sleeper documents 429 for rate limiting; everything else transient is common.
RETRYABLE_STATUS = frozenset({429})


def _is_retryable(exc: BaseException) -> bool:
    """Whether a Sleeper failure is transient.

    A 404 means the league or user does not exist and will never succeed.
    """
    return is_transient(exc, RETRYABLE_STATUS)


def _retry() -> Retrying:
    return build_retry(attempts=RETRY_MAX_ATTEMPTS, multiplier=2, min_wait=2, max_wait=20, predicate=_is_retryable)


class SleeperClient:
    """Read-only access to Sleeper's fantasy and NFL data."""

    def __init__(self, cache: JsonDiskCache | None = None, session: Any = None) -> None:
        self._api = JsonApiClient(
            name="Sleeper",
            cache=cache or JsonDiskCache(Path(settings.sleeper_cache_dir)),
            # Read through the module global rather than binding it here, so the
            # policy stays one thing a test can replace.
            retry=lambda: _retry(),
            error=SleeperAPIError,
            session=session,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    # ── transport ───────────────────────────────────────────────────

    def _get(self, url: str, timeout: int = REQUEST_TIMEOUT_SECONDS) -> Any:
        return self._api.get(url, timeout=timeout)

    def _cached(self, key: str, url: str, ttl: timedelta, timeout: int = REQUEST_TIMEOUT_SECONDS) -> Any:
        return self._api.cached(key, url, ttl, timeout=timeout)

    # ── league state ────────────────────────────────────────────────

    def get_state(self, sport: str = NFL) -> SeasonState:
        """Current week and season type for a sport."""
        data = self._cached(f"state_{sport}", f"{BASE_URL}/state/{sport}", STATE_TTL)
        return SeasonState(
            week=int(data.get("week", 0)),
            season=str(data.get("season", "")),
            season_type=str(data.get("season_type", "")),
        )

    def get_nfl_state(self) -> SeasonState:
        """Current NFL week and season type."""
        return self.get_state(NFL)

    def get_user(self, username: str) -> SleeperUser:
        """Resolve a username to a user. Usernames change; user_ids do not."""
        data = self._get(f"{BASE_URL}/user/{username}")
        if not data:
            raise SleeperAPIError(f"No Sleeper user named {username!r}.")
        return SleeperUser(
            user_id=str(data["user_id"]),
            username=str(data.get("username") or username),
            display_name=str(data.get("display_name") or username),
        )

    def get_leagues(self, user_id: str, season: str) -> list[SleeperLeague]:
        """Every NFL league a user is in for a season."""
        data = self._cached(
            f"leagues_{user_id}_{season}",
            f"{BASE_URL}/user/{user_id}/leagues/nfl/{season}",
            LEAGUE_TTL,
        )
        return [self._to_league(item) for item in data or []]

    @staticmethod
    def _to_league(data: dict[str, Any]) -> SleeperLeague:
        settings_blob = data.get("scoring_settings") or {}
        return SleeperLeague(
            league_id=str(data["league_id"]),
            name=str(data.get("name", "Unnamed league")),
            season=str(data.get("season", "")),
            total_rosters=int(data.get("total_rosters", 0)),
            scoring_format=SleeperClient.detect_scoring_format(settings_blob),
            roster_positions=[str(p) for p in data.get("roster_positions") or []],
            trade_deadline=int((data.get("settings") or {}).get("trade_deadline") or 0),
            playoff_teams=int((data.get("settings") or {}).get("playoff_teams") or 0),
            playoff_week_start=int((data.get("settings") or {}).get("playoff_week_start") or 0),
        )

    @staticmethod
    def detect_scoring_format(scoring_settings: dict[str, Any]) -> ScoringFormat:
        """Infer PPR / half-PPR / standard from the league's per-reception value.

        Sleeper does not label the format; it exposes the `rec` setting, which is
        points per reception. Everything downstream reads the matching projection
        field, so getting this wrong would silently rank players by the wrong
        currency.
        """
        rec = float(scoring_settings.get("rec", 0) or 0)
        if rec >= 0.75:
            return "pts_ppr"
        if rec >= 0.25:
            return "pts_half_ppr"
        return "pts_std"

    def get_rosters(self, league_id: str) -> list[SleeperRoster]:
        data = self._cached(f"rosters_{league_id}", f"{BASE_URL}/league/{league_id}/rosters", ROSTERS_TTL)
        rosters = []
        for item in data or []:
            record = item.get("settings") or {}
            rosters.append(
                SleeperRoster(
                    roster_id=int(item.get("roster_id", 0)),
                    owner_id=str(item.get("owner_id") or ""),
                    player_ids=[str(p) for p in item.get("players") or []],
                    starter_ids=[str(p) for p in item.get("starters") or []],
                    wins=int(record.get("wins", 0)),
                    losses=int(record.get("losses", 0)),
                    ties=int(record.get("ties", 0)),
                    points_for=float(record.get("fpts", 0)) + float(record.get("fpts_decimal", 0)) / 100,
                )
            )
        return rosters

    def get_league_users(self, league_id: str) -> dict[str, str]:
        """Map user_id -> display name, for labelling opponents."""
        data = self._cached(f"users_{league_id}", f"{BASE_URL}/league/{league_id}/users", LEAGUE_TTL)
        return {str(u["user_id"]): str(u.get("display_name") or u.get("username") or "Unknown") for u in data or []}

    def get_matchups(self, league_id: str, week: int) -> list[dict[str, Any]]:
        """Raw matchup entries for a week — one per roster, paired by matchup_id."""
        return (
            self._cached(
                f"matchups_{league_id}_{week}",
                f"{BASE_URL}/league/{league_id}/matchups/{week}",
                MATCHUPS_TTL,
            )
            or []
        )

    # ── player data ─────────────────────────────────────────────────

    def get_players(self, sport: str = NFL) -> dict[str, PlayerMeta]:
        """The player catalog, trimmed to the fields we use.

        The raw response is ~14MB across 12k players. Only a handful of fields
        matter here, so the cache stores the trimmed form — keeping the rest
        would cost a re-parse on every read for fields nothing asks for.
        """
        cached = self._api.cache_get(f"players_{sport}", PLAYERS_TTL)
        if cached is not None:
            return cached

        raw = self._get(f"{BASE_URL}/players/{sport}", timeout=CATALOG_TIMEOUT_SECONDS)
        trimmed: dict[str, PlayerMeta] = {}
        for player_id, p in (raw or {}).items():
            if not isinstance(p, dict):
                continue
            name = p.get("full_name") or " ".join(filter(None, [p.get("first_name"), p.get("last_name")]))
            trimmed[str(player_id)] = PlayerMeta(
                player_id=str(player_id),
                name=str(name or player_id),
                position=str(p.get("position") or ""),
                team=str(p.get("team") or "FA"),
                status=str(p.get("status") or ""),
                injury_status=str(p.get("injury_status") or ""),
                depth_chart_order=int(p.get("depth_chart_order") or 0),
                years_exp=int(p.get("years_exp") or 0),
                age=int(p.get("age") or 0),
                college=str(p.get("college") or ""),
                number=int(p.get("number") or 0),
                injury_body_part=str(p.get("injury_body_part") or ""),
                injury_notes=str(p.get("injury_notes") or ""),
            )
        self._api.cache_set(f"players_{sport}", trimmed)
        logger.debug(f"Cached {len(trimmed)} {sport} players from Sleeper")
        return trimmed

    def get_season_stats(self, season: str, sport: str = NFL) -> dict[str, SeasonStats]:
        """A whole season's production, keyed by player_id.

        Trimmed before caching for the same reason the catalog is: the raw
        response is ~1.9MB of mostly kicking and defensive splits, and none of
        it is read back.
        """
        key = f"season_stats_{sport}_{season}"
        cached = self._api.cache_get(key, SEASON_STATS_TTL)
        if cached is None:
            raw = self._get(f"{BASE_URL}/stats/{sport}/regular/{season}", timeout=CATALOG_TIMEOUT_SECONDS)
            cached = {
                str(pid): {k: v for k, v in row.items() if k in SEASON_STAT_KEYS}
                for pid, row in (raw or {}).items()
                if isinstance(row, dict)
            }
            self._api.cache_set(key, cached)
            logger.debug(f"Cached {len(cached)} {sport} season totals for {season}")

        return {
            pid: SeasonStats(
                player_id=pid,
                season=season,
                games=int(row.get("gp") or 0),
                points={fmt: float(row.get(fmt) or 0.0) for fmt in ("pts_ppr", "pts_half_ppr", "pts_std")},
                position_rank=int(row.get("pos_rank_ppr") or 0),
                splits={k: float(v) for k, v in row.items() if k in SPLIT_KEYS},
            )
            for pid, row in cached.items()
        }

    def get_season_schedule(self, season: str, sport: str = NFL) -> list[ScheduledGame]:
        """Every real-world game of the season, with the day it is played.

        The dates behind a fantasy week, which the fantasy endpoints do not
        carry: a matchup knows it is week 3 and not that week 3 is a Sunday.
        """
        data = self._cached(
            f"schedule_{sport}_{season}",
            f"{SCHEDULE_URL}/{sport}/regular/{season}",
            SEASON_SCHEDULE_TTL,
        )
        return [
            ScheduledGame(
                week=int(g.get("week") or 0),
                date=str(g.get("date") or ""),
                home=str(g.get("home") or ""),
                away=str(g.get("away") or ""),
                status=str(g.get("status") or ""),
            )
            for g in (data or [])
            if isinstance(g, dict)
        ]

    def get_matchups_bulk(self, league_id: str, weeks: list[int]) -> dict[int, list[dict[str, Any]]]:
        """Every requested week's matchups, fetched concurrently.

        The season view needs all eighteen; asked one at a time they are the
        whole wait on the page.
        """
        urls = {f"matchups_{league_id}_{w}": f"{BASE_URL}/league/{league_id}/matchups/{w}" for w in weeks}
        raw = self._api.cached_many(urls, MATCHUPS_TTL)
        return {w: raw.get(f"matchups_{league_id}_{w}") or [] for w in weeks}

    def get_nba_game_logs(self, season: str, weeks: list[int]) -> dict[str, list[NBAGameLog]]:
        """Every player's game-by-game lines over `weeks`, keyed by player_id.

        Sleeper publishes one row per player per game, which is the shape a
        "last ten games" window actually needs — weekly buckets hold three or
        four games and cannot be cut at ten.

        Trimmed before caching for the same reason the catalog is: six weeks of
        raw rows is ~9MB of quarter splits and plus-minus, and the cache is one
        file shared with everything else the client reads.
        """
        urls = {f"nba_logs_{season}_{w}": f"{STATS_URL}/{NBA}/{season}/{w}?season_type=regular" for w in weeks}
        raw = self._api.cached_many(urls, NBA_LOGS_TTL)

        logs: dict[str, list[NBAGameLog]] = {}
        for week in weeks:
            for row in raw.get(f"nba_logs_{season}_{week}") or []:
                if not isinstance(row, dict):
                    continue
                player_id = str(row.get("player_id") or "")
                # Team totals ride in the same feed under a prefixed id, and a
                # team's 146 points is not a player's line.
                if not player_id or player_id.startswith(TEAM_ROW_PREFIX):
                    continue
                stats = row.get("stats") or {}
                # Sleeper files a row for every game a player was scheduled
                # for, carrying no stats at all where they did not appear. A
                # game somebody sat out is not a game they played, and
                # averaging it in as a line of noughts is how a run of five
                # DNPs becomes "recent form".
                if not stats:
                    continue
                logs.setdefault(player_id, []).append(
                    NBAGameLog(
                        player_id=player_id,
                        date=str(row.get("date") or ""),
                        opponent=str(row.get("opponent") or ""),
                        stats={k: float(v) for k in NBA_STAT_KEYS if (v := stats.get(k)) is not None},
                    )
                )
        # Newest first, so a caller takes the first N rather than sorting again.
        for runs in logs.values():
            runs.sort(key=lambda g: g.date, reverse=True)
        return logs

    def get_nfl_game_lines(self, season: str, weeks: list[int]) -> list[NFLGameLine]:
        """Every fantasy-relevant player's line from each game in `weeks`.

        The raw material for both a player's role — snaps, targets, carries —
        and what each defense gives up to each position, which no endpoint
        publishes directly. Linemen, defensive players and team totals ride in
        the same feed and are dropped: none of them is anybody's starter.
        """
        urls = {f"nfl_lines_{season}_{w}": f"{STATS_URL}/{NFL}/{season}/{w}?season_type=regular" for w in weeks}
        raw = self._api.cached_many(urls, NFL_LINES_TTL)

        lines: list[NFLGameLine] = []
        for week in weeks:
            for row in raw.get(f"nfl_lines_{season}_{week}") or []:
                if not isinstance(row, dict):
                    continue
                player_id = str(row.get("player_id") or "")
                position = str((row.get("player") or {}).get("position") or "")
                opponent = str(row.get("opponent") or "")
                if not player_id or player_id.startswith(TEAM_ROW_PREFIX) or position not in FANTASY_POSITIONS:
                    continue
                if not opponent:
                    continue
                stats = row.get("stats") or {}
                lines.append(
                    NFLGameLine(
                        player_id=player_id,
                        week=week,
                        team=str(row.get("team") or ""),
                        opponent=opponent,
                        position=position,
                        stats={k: float(v) for k in NFL_LINE_KEYS if (v := stats.get(k)) is not None},
                    )
                )
        return lines

    def get_nba_schedule(self, season: str) -> list[ScheduledGame]:
        """The basketball season's games, in the same shape football uses.

        Sleeper nests the clubs one level deeper here than it does for
        football, which is the only difference worth a separate reader.
        """
        data = self._cached(f"schedule_{NBA}_{season}", f"{SCHEDULE_URL}/{NBA}/regular/{season}", SEASON_SCHEDULE_TTL)
        return [
            ScheduledGame(
                week=int(g.get("week") or 0),
                date=str(g.get("date") or ""),
                home=str((g.get("home") or {}).get("team") or ""),
                away=str((g.get("away") or {}).get("team") or ""),
                status=str(g.get("status") or ""),
            )
            for g in (data or [])
            if isinstance(g, dict)
        ]

    def get_transactions(self, league_id: str, week: int) -> list[Transaction]:
        """What the league did in one week: waivers, free agents and trades.

        Sleeper files these by week rather than by date, so a caller wanting
        recent activity asks for the last few weeks and concatenates.
        """
        data = self._cached(
            f"transactions_{league_id}_{week}",
            f"{BASE_URL}/league/{league_id}/transactions/{week}",
            TRANSACTIONS_TTL,
        )
        return [
            Transaction(
                kind=str(t.get("type") or ""),
                roster_ids=[int(r) for r in (t.get("roster_ids") or [])],
                adds={str(k): int(v) for k, v in (t.get("adds") or {}).items()},
                drops={str(k): int(v) for k, v in (t.get("drops") or {}).items()},
                when=int(t.get("status_updated") or 0),
            )
            for t in (data or [])
            # A failed waiver claim is not something that happened.
            if isinstance(t, dict) and t.get("status") == "complete"
        ]

    def get_projections(self, season: str, week: int, scoring: ScoringFormat) -> dict[str, WeeklyProjection]:
        """Weekly projections keyed by player_id.

        This is the forward-looking number the whole football report rests on:
        start/sit and waiver value are both "who will score most this week".
        """
        # The sport segment is required, and its absence is not an error: the
        # path without it answers 200 with an empty list, so every projection
        # silently became a zero and every player read as having no game.
        url = f"{PROJECTIONS_URL}/{NFL}/{season}/{week}?season_type=regular&order_by={scoring}" + "".join(
            f"&position[]={p}" for p in ("QB", "RB", "WR", "TE", "K", "DEF")
        )
        data = self._cached(f"proj_{NFL}_{season}_{week}_{scoring}", url, PROJECTIONS_TTL)

        projections: dict[str, WeeklyProjection] = {}
        for row in data or []:
            player = row.get("player") or {}
            stats = row.get("stats") or {}
            points = stats.get(scoring)
            if points is None:
                continue
            player_id = str(row.get("player_id") or "")
            name = " ".join(filter(None, [player.get("first_name"), player.get("last_name")]))
            projections[player_id] = WeeklyProjection(
                player_id=player_id,
                name=name or player_id,
                position=str(player.get("position") or ""),
                team=str(player.get("team") or row.get("team") or "FA"),
                opponent=str(row.get("opponent") or ""),
                points=float(points),
                injury_status=str(player.get("injury_status") or ""),
                stats={k: float(v) for k, v in stats.items() if isinstance(v, int | float)},
            )
        return projections

    def get_nba_projections(self, season: str, week: int) -> list[GameProjection]:
        """Per-game NBA projections for a Sleeper week.

        One row per player per game, each carrying a date, an opponent and the
        full nine-category line. Summing a player's rows across a matchup period
        gives projected category totals — which is what a category league
        actually needs, and what the NBA scout had no source for.

        Returns an empty list out of season: Sleeper publishes nothing before
        opening night, and the scout falls back to recent form alone.
        """
        url = f"{PROJECTIONS_URL}/{NBA}/{season}/{week}?season_type=regular&order_by=pts" + "".join(
            f"&position[]={p}" for p in ("PG", "SG", "SF", "PF", "C")
        )
        data = self._cached(f"proj_{NBA}_{season}_{week}", url, PROJECTIONS_TTL)

        projections: list[GameProjection] = []
        for row in data or []:
            stats = row.get("stats") or {}
            if stats.get("pts") is None:
                continue
            player = row.get("player") or {}
            name = " ".join(filter(None, [player.get("first_name"), player.get("last_name")]))
            projections.append(
                GameProjection(
                    player_id=str(row.get("player_id") or ""),
                    name=name,
                    team=str(player.get("team") or row.get("team") or ""),
                    opponent=str(row.get("opponent") or ""),
                    date=str(row.get("date") or "")[:10],
                    stats={k: float(v) for k, v in stats.items() if isinstance(v, int | float)},
                )
            )
        return projections

    def get_trending(self, kind: str = "add", lookback_hours: int = 24, limit: int = 25) -> list[TrendingPlayer]:
        """Most-added or most-dropped players across all of Sleeper.

        A useful independent signal: the crowd often reacts to a depth-chart
        change or an injury before projections catch up.
        """
        url = f"{BASE_URL}/players/nfl/trending/{kind}?lookback_hours={lookback_hours}&limit={limit}"
        data = self._cached(f"trending_{kind}_{lookback_hours}_{limit}", url, TRENDING_TTL)
        return [
            TrendingPlayer(player_id=str(item["player_id"]), count=int(item.get("count", 0)))
            for item in data or []
            if item.get("player_id")
        ]
