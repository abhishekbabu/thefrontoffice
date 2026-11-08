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
from collections.abc import Callable, Collection
from dataclasses import asdict
from datetime import timedelta
from typing import Any, Protocol

from thefrontoffice.adapters.outbound.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.http import Batch, JsonApiClient
from thefrontoffice.adapters.outbound.platforms.retry import RetryPolicy
from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError, SleeperUnavailableError
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    EMPTY_SLOT,
    FREE_AGENT,
    NBA_STAT_KEYS,
    NFL_LINE_KEYS,
    SCORING_FORMATS,
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
    SleeperMatchup,
    SleeperRoster,
    SleeperUser,
    Transaction,
    TrendingPlayer,
    WeeklyProjection,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://api.sleeper.app/v1"
PROJECTIONS_URL = "https://api.sleeper.app/projections"
# Not under /v1, unlike everything else here.
SCHEDULE_URL = "https://api.sleeper.app/schedule"
# Per-game logs live off the same un-versioned root as projections.
STATS_URL = "https://api.sleeper.app/stats"

# Sleeper serves several sports off the same shape. Each public reader names its
# sport, so no caller reaches one sport's data by forgetting to name the other.
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
GAME_ROWS_TTL = timedelta(hours=3)
TRANSACTIONS_TTL = timedelta(minutes=15)


class SleeperNFLSource(Protocol):
    """What the NFL provider reads Sleeper through: every call it makes, and nothing else.

    Providers ask for an interface like this rather than `SleeperClient` so a
    test hands them a fake that is checked against it — a fake whose signature
    drifts from the real client's then fails the type check instead of passing
    quietly. One per reader, so each fake implements only what its reader calls.
    """

    def get_league_users(self, league_id: str) -> dict[str, str]: ...

    def get_leagues(self, user_id: str, season: str) -> list[SleeperLeague]: ...

    def get_matchups(self, league_id: str, week: int) -> list[SleeperMatchup]: ...

    def get_matchups_bulk(self, league_id: str, weeks: list[int]) -> Batch[int, list[SleeperMatchup]]: ...

    def get_nfl_game_lines(
        self, season: str, weeks: list[int], positions: Collection[str]
    ) -> Batch[int, list[NFLGameLine]]: ...

    def get_nfl_players(self) -> dict[str, PlayerMeta]: ...

    def get_nfl_schedule(self, season: str) -> list[ScheduledGame]: ...

    def get_nfl_state(self) -> SeasonState: ...

    def get_projections(
        self, season: str, week: int, scoring: ScoringFormat, positions: Collection[str]
    ) -> dict[str, WeeklyProjection]: ...

    def get_rosters(self, league_id: str) -> list[SleeperRoster]: ...

    def get_season_stats(self, season: str) -> dict[str, SeasonStats]: ...

    def get_transactions(self, league_id: str, week: int) -> list[Transaction]: ...

    def get_trending(self, kind: str = "add", lookback_hours: int = 24, limit: int = 25) -> list[TrendingPlayer]: ...

    def get_user(self, username: str) -> SleeperUser: ...


class SleeperNBASource(Protocol):
    """What basketball's recent-form reader reads Sleeper through. See `SleeperNFLSource`."""

    def get_nba_game_logs(self, season: str, weeks: list[int]) -> dict[str, list[NBAGameLog]]: ...

    def get_nba_players(self) -> dict[str, PlayerMeta]: ...

    def get_nba_schedule(self, season: str) -> list[ScheduledGame]: ...

    def get_nba_state(self) -> SeasonState: ...


class SleeperProjectionSource(Protocol):
    """What the basketball provider reads Sleeper's projections through. See `SleeperNFLSource`."""

    def get_nba_projections(self, season: str, week: int) -> list[GameProjection]: ...

    def get_nba_state(self) -> SeasonState: ...


class SleeperClient:
    """Read-only access to Sleeper's fantasy and NFL data."""

    def __init__(self, *, cache: JsonDiskCache, retry: RetryPolicy, session: Any = None) -> None:
        self._api = JsonApiClient(
            name="Sleeper",
            cache=cache,
            retry=retry,
            error=SleeperAPIError,
            unavailable=SleeperUnavailableError,
            session=session,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    # ── league state ────────────────────────────────────────────────

    def get_nfl_state(self) -> SeasonState:
        """The football season's current week and type."""
        return self._state(NFL)

    def get_nba_state(self) -> SeasonState:
        """The basketball season's current week and type."""
        return self._state(NBA)

    def _state(self, sport: str) -> SeasonState:
        data = self._api.cached(f"state_{sport}", f"{BASE_URL}/state/{sport}", STATE_TTL)
        return SeasonState(
            week=int(data.get("week", 0)),
            season=str(data.get("season", "")),
            season_type=str(data.get("season_type", "")),
        )

    def get_user(self, username: str) -> SleeperUser:
        """Resolve a username to a user. Usernames change; user_ids do not."""
        data = self._api.get(f"{BASE_URL}/user/{username}")
        if not data:
            raise SleeperAPIError(f"No Sleeper user named {username!r}.")
        return SleeperUser(
            user_id=str(data["user_id"]),
            username=str(data.get("username") or username),
            display_name=str(data.get("display_name") or username),
        )

    def get_leagues(self, user_id: str, season: str) -> list[SleeperLeague]:
        """Every NFL league a user is in for a season."""
        data = self._api.cached(
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
        """Every team in the league: who it holds, its record, and the lineup its roster carries.

        That lineup can lag a change by days; the week's matchup has the one set now.
        """
        data = self._api.cached(f"rosters_{league_id}", f"{BASE_URL}/league/{league_id}/rosters", ROSTERS_TTL)
        rosters = []
        for item in data or []:
            record = item.get("settings") or {}
            rosters.append(
                SleeperRoster(
                    roster_id=int(item.get("roster_id", 0)),
                    owner_id=str(item.get("owner_id") or ""),
                    player_ids=[str(p) for p in item.get("players") or []],
                    starter_ids=[str(p) for p in item.get("starters") or []],
                    reserve_ids=[str(p) for p in (item.get("reserve") or []) + (item.get("taxi") or [])],
                    wins=int(record.get("wins", 0)),
                    losses=int(record.get("losses", 0)),
                    ties=int(record.get("ties", 0)),
                    points_for=float(record.get("fpts", 0)) + float(record.get("fpts_decimal", 0)) / 100,
                )
            )
        return rosters

    def get_league_users(self, league_id: str) -> dict[str, str]:
        """Map user_id -> display name, for labelling opponents."""
        data = self._api.cached(f"users_{league_id}", f"{BASE_URL}/league/{league_id}/users", LEAGUE_TTL)
        return {str(u["user_id"]): str(u.get("display_name") or u.get("username") or "Unknown") for u in data or []}

    def get_matchups(self, league_id: str, week: int) -> list[SleeperMatchup]:
        """A week's matchups, one entry per team; two teams sharing a `matchup_id` play each other."""
        url = f"{BASE_URL}/league/{league_id}/matchups/{week}"
        return _matchups(self._api.cached(f"matchups_{league_id}_{week}", url, MATCHUPS_TTL))

    def get_matchups_bulk(self, league_id: str, weeks: list[int]) -> Batch[int, list[SleeperMatchup]]:
        """Every requested week's matchups, fetched concurrently, with why each that would not load did not.

        The season view needs all eighteen; asked one at a time they are the
        whole wait on the page. A week that would not load is a failure rather
        than empty: an empty week is a bye, and a failed request is not one.
        """
        batch = self._weekly(
            weeks, lambda w: f"matchups_{league_id}_{w}", lambda w: f"{BASE_URL}/league/{league_id}/matchups/{w}"
        )
        return Batch(values={w: _matchups(raw) for w, raw in batch.values.items()}, failures=batch.failures)

    # ── player data ─────────────────────────────────────────────────

    def get_nfl_players(self) -> dict[str, PlayerMeta]:
        """The football player catalog, trimmed to the fields we use."""
        return self._players(NFL)

    def get_nba_players(self) -> dict[str, PlayerMeta]:
        """The basketball player catalog, trimmed to the fields we use."""
        return self._players(NBA)

    def _players(self, sport: str) -> dict[str, PlayerMeta]:
        """A sport's catalog, stored trimmed.

        The raw response is ~14MB across 12k players and only a handful of
        fields matter, so the cache keeps the trimmed form — keeping the rest
        would cost a re-parse on every read for fields nothing asks for.
        """
        stored = self._api.cached(
            f"players_{sport}",
            f"{BASE_URL}/players/{sport}",
            PLAYERS_TTL,
            timeout=CATALOG_TIMEOUT_SECONDS,
            keep=_trim_catalog,
        )
        return {pid: PlayerMeta(**row) for pid, row in (stored or {}).items()}

    def get_season_stats(self, season: str) -> dict[str, SeasonStats]:
        """A whole NFL season's production, keyed by player_id.

        Trimmed before caching for the same reason the catalog is: the raw
        response is ~1.9MB of mostly kicking and defensive splits, and none of
        it is read back.
        """
        stored = self._api.cached(
            f"season_stats_{NFL}_{season}",
            f"{BASE_URL}/stats/{NFL}/regular/{season}",
            SEASON_STATS_TTL,
            timeout=CATALOG_TIMEOUT_SECONDS,
            keep=_trim_season_stats,
        )
        return {
            pid: SeasonStats(
                player_id=pid,
                season=season,
                games=int(row.get("gp") or 0),
                points={fmt: float(row.get(fmt) or 0.0) for fmt in SCORING_FORMATS},
                position_rank=int(row.get("pos_rank_ppr") or 0),
                splits={k: float(v) for k, v in row.items() if k in SPLIT_KEYS},
            )
            for pid, row in (stored or {}).items()
        }

    def get_nfl_schedule(self, season: str) -> list[ScheduledGame]:
        """Every real-world NFL game of the season, with the day it is played.

        The dates behind a fantasy week, which the fantasy endpoints do not
        carry: a matchup knows it is week 3 and not that week 3 is a Sunday.
        """
        return self._schedule(NFL, season, lambda side: str(side or ""))

    def get_nba_schedule(self, season: str) -> list[ScheduledGame]:
        """The basketball season's games, in the same shape football uses.

        Sleeper nests each club one level deeper here than it does for football.
        """
        return self._schedule(NBA, season, lambda side: str((side or {}).get("team") or ""))

    def _schedule(self, sport: str, season: str, club: Callable[[Any], str]) -> list[ScheduledGame]:
        data = self._api.cached(
            f"schedule_{sport}_{season}", f"{SCHEDULE_URL}/{sport}/regular/{season}", SEASON_SCHEDULE_TTL
        )
        return [
            ScheduledGame(
                week=int(g.get("week") or 0),
                date=str(g.get("date") or ""),
                home=club(g.get("home")),
                away=club(g.get("away")),
                status=str(g.get("status") or ""),
            )
            for g in (data or [])
            if isinstance(g, dict)
        ]

    def get_nba_game_logs(self, season: str, weeks: list[int]) -> dict[str, list[NBAGameLog]]:
        """Every player's game-by-game lines over `weeks`, keyed by player_id.

        Sleeper publishes one row per player per game, which is the shape a
        "last ten games" window actually needs — weekly buckets hold three or
        four games and cannot be cut at ten.

        Trimmed before caching for the same reason the catalog is: six weeks of
        raw rows is ~9MB of quarter splits and plus-minus, and the cache is one
        file shared with everything else the client reads.

        Raises:
            SleeperAPIError: any week would not load — a window with a week
                missing from its middle reads the games either side of the gap
                as consecutive, which is not anybody's recent form.
        """
        batch = self._game_rows(NBA, season, weeks)
        for error in batch.failures.values():
            raise error
        logs: dict[str, list[NBAGameLog]] = {}
        for player_id, row in (pair for rows in batch.values.values() for pair in rows):
            stats = row.get("stats") or {}
            # Sleeper files a row for every game a player was scheduled for,
            # carrying no stats at all where they did not appear. A game
            # somebody sat out is not a game they played, and averaging it in
            # as a line of noughts is how a run of five DNPs becomes "recent form".
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

    def get_nfl_game_lines(
        self, season: str, weeks: list[int], positions: Collection[str]
    ) -> Batch[int, list[NFLGameLine]]:
        """Every line from each game in `weeks` by a player at one of `positions`, by week.

        The raw material for both a player's role — snaps, targets, carries —
        and what each defense gives up to each position, which no endpoint
        publishes directly. Linemen and defensive players ride in the same
        feed, which is why a caller names the positions it scores.

        A week that would not load is a failure, not empty: a week with no line
        for a player is a game he missed, and a failed request is not one.
        """
        batch = self._game_rows(NFL, season, weeks)
        return Batch(
            values={
                week: [line for player_id, row in rows if (line := _nfl_line(week, player_id, row, positions))]
                for week, rows in batch.values.items()
            },
            failures=batch.failures,
        )

    def _game_rows(self, sport: str, season: str, weeks: list[int]) -> Batch[int, list[tuple[str, dict[str, Any]]]]:
        """Each player's row from each game in `weeks`, with his player id, by week; the weeks fetched in parallel.

        Team totals ride in the same feed under a prefixed id, and a team's
        points are not a player's line.
        """
        batch = self._weekly(
            weeks,
            lambda w: f"game_rows_{sport}_{season}_{w}",
            lambda w: f"{STATS_URL}/{sport}/{season}/{w}?season_type=regular",
            GAME_ROWS_TTL,
        )
        return Batch(
            values={
                week: [
                    (player_id, row)
                    for row in raw or []
                    if isinstance(row, dict)
                    and (player_id := str(row.get("player_id") or ""))
                    and not player_id.startswith(TEAM_ROW_PREFIX)
                ]
                for week, raw in batch.values.items()
            },
            failures=batch.failures,
        )

    def _weekly(
        self, weeks: list[int], key: Callable[[int], str], url: Callable[[int], str], ttl: timedelta = MATCHUPS_TTL
    ) -> Batch[int, Any]:
        """One cached GET per week, run in parallel, keyed by week number."""
        keys = {w: key(w) for w in weeks}
        return self._api.cached_many({keys[w]: url(w) for w in weeks}, ttl).rekeyed(keys)

    def get_transactions(self, league_id: str, week: int) -> list[Transaction]:
        """What the league did in one week: waivers, free agents and trades.

        Sleeper files these by week rather than by date, so a caller wanting
        recent activity asks for the last few weeks and concatenates.
        """
        data = self._api.cached(
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

    def get_projections(
        self, season: str, week: int, scoring: ScoringFormat, positions: Collection[str]
    ) -> dict[str, WeeklyProjection]:
        """Weekly projections for the players at `positions`, keyed by player_id.

        This is the forward-looking number the whole football report rests on:
        start/sit and waiver value are both "who will score most this week".
        """
        # The sport segment is required, and its absence is not an error: the
        # path without it answers 200 with an empty list, so every projection
        # silently became a zero and every player read as having no game.
        asked = sorted(positions)
        url = f"{PROJECTIONS_URL}/{NFL}/{season}/{week}?season_type=regular&order_by={scoring}" + "".join(
            f"&position[]={p}" for p in asked
        )
        data = self._api.cached(f"proj_{NFL}_{season}_{week}_{scoring}_{'-'.join(asked)}", url, PROJECTIONS_TTL)

        projections: dict[str, WeeklyProjection] = {}
        for row in data or []:
            player = row.get("player") or {}
            stats = row.get("stats") or {}
            points = stats.get(scoring)
            if points is None:
                continue
            player_id = str(row.get("player_id") or "")
            projections[player_id] = WeeklyProjection(
                player_id=player_id,
                name=_full_name(player) or player_id,
                position=str(player.get("position") or ""),
                team=str(player.get("team") or row.get("team") or FREE_AGENT),
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
        data = self._api.cached(f"proj_{NBA}_{season}_{week}", url, PROJECTIONS_TTL)

        projections: list[GameProjection] = []
        for row in data or []:
            stats = row.get("stats") or {}
            if stats.get("pts") is None:
                continue
            player = row.get("player") or {}
            projections.append(
                GameProjection(
                    player_id=str(row.get("player_id") or ""),
                    name=_full_name(player),
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
        data = self._api.cached(f"trending_{kind}_{lookback_hours}_{limit}", url, TRENDING_TTL)
        return [
            TrendingPlayer(player_id=str(item["player_id"]), count=int(item.get("count", 0)))
            for item in data or []
            if item.get("player_id")
        ]


def _trim_catalog(raw: Any) -> dict[str, dict[str, Any]]:
    """Sleeper's catalog cut to the fields a `PlayerMeta` holds, in the form it is stored in."""
    return {
        str(player_id): asdict(
            PlayerMeta(
                player_id=str(player_id),
                name=str(p.get("full_name") or _full_name(p) or player_id),
                position=str(p.get("position") or ""),
                team=str(p.get("team") or FREE_AGENT),
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
        )
        for player_id, p in (raw or {}).items()
        if isinstance(p, dict)
    }


def _trim_season_stats(raw: Any) -> dict[str, dict[str, Any]]:
    """A season's rows cut to `SEASON_STAT_KEYS`."""
    return {
        str(pid): {k: v for k, v in row.items() if k in SEASON_STAT_KEYS}
        for pid, row in (raw or {}).items()
        if isinstance(row, dict)
    }


def _full_name(player: dict[str, Any]) -> str:
    """'First Last', from whichever halves Sleeper sent."""
    return " ".join(filter(None, [player.get("first_name"), player.get("last_name")]))


def _nfl_line(week: int, player_id: str, row: dict[str, Any], positions: Collection[str]) -> NFLGameLine | None:
    """A player's line from one game; None for a position nobody scores or a row with no game behind it."""
    position = str((row.get("player") or {}).get("position") or "")
    opponent = str(row.get("opponent") or "")
    if position not in positions or not opponent:
        return None
    stats = row.get("stats") or {}
    return NFLGameLine(
        player_id=player_id,
        week=week,
        team=str(row.get("team") or ""),
        opponent=opponent,
        position=position,
        stats={k: float(v) for k in NFL_LINE_KEYS if (v := stats.get(k)) is not None},
    )


def _matchups(data: Any) -> list[SleeperMatchup]:
    """A week's matchup rows as each team's side of it."""
    return [
        SleeperMatchup(
            roster_id=int(entry.get("roster_id") or 0),
            matchup_id=int(entry["matchup_id"]) if entry.get("matchup_id") is not None else None,
            points=float(entry.get("points") or 0),
            starters=["" if str(p) == EMPTY_SLOT else str(p) for p in entry.get("starters") or []],
            players_points={
                str(pid): float(scored or 0) for pid, scored in (entry.get("players_points") or {}).items()
            },
        )
        for entry in data or []
        if isinstance(entry, dict)
    ]
