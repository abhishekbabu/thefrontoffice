"""Every request the app makes of Yahoo, and how long its answer holds.

Built in one place so that everything naming a Yahoo response names it alike:
the reader asks for it, the browser capture plans and stores it, and both key
the cache by its path — the path Yahoo serves it at, below `/fantasy/v2/`, on
the API host and on the host Yahoo's own pages read.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta

from thefrontoffice.adapters.outbound.platforms.yahoo.types import PlayerStat, PlayerStatus, Timeframe

# TTLs from how fast each answer actually goes stale. Waiver leaders move as
# the league claims players; a name search resolves to the same player for as
# long as anyone is looking.
LEADERS_TTL = timedelta(minutes=30)
SEARCH_TTL = timedelta(hours=6)
TEAMS_TTL = timedelta(hours=1)
ROSTER_TTL = timedelta(hours=1)
LEAGUES_TTL = timedelta(hours=1)
# A league's scoring is set before the season and almost never changes during it.
SETTINGS_TTL = timedelta(hours=12)
SCOREBOARD_TTL = timedelta(minutes=2)
"""The scoreboard drives the "which categories are close" analysis and goes
stale within a game night."""

PROFILE = "users;use_login=1/profile"
"""Who is signed in: 401 without a session, so a capture checks it before anything else."""


@dataclass(frozen=True)
class YahooRead:
    """One Yahoo response the app reads, and how long it holds."""

    query: str
    """What the SDK is asked for, below the league where `league` names one."""

    ttl: timedelta
    league: str = ""
    """The league it is scoped to, or empty for a request naming its own subject."""

    keep_on_failure: bool = False
    """Serve the stored copy, however old, when a refresh fails: stale beats nothing for a score."""

    player_keys: tuple[str, ...] = ()
    """The players a lookup by key asks for; empty for any other read."""

    search: str = ""
    """The name a search asks for; empty for any other read."""

    @property
    def path(self) -> str:
        """Where Yahoo serves it, and the key it is kept under."""
        return f"league/{self.league}/{self.query}" if self.league else self.query

    @property
    def lookup(self) -> bool:
        """Whether it asks for players by key or by name, which no plan can know in advance."""
        return bool(self.player_keys or self.search)


def leagues(game_code: str, season: int) -> YahooRead:
    """Every league the login plays in for one game and season.

    Filtered by game code and season rather than by game key, which the SDK
    resolves against a hardcoded table that stops at its last release.
    """
    return YahooRead(f"users;use_login=1/games;game_codes={game_code};seasons={season}/leagues", LEAGUES_TTL)


def settings(league_key: str) -> YahooRead:
    return YahooRead("settings", SETTINGS_TTL, league=league_key)


def teams(league_key: str) -> YahooRead:
    return YahooRead("teams", TEAMS_TTL, league=league_key)


def standings(league_key: str) -> YahooRead:
    """The table: the teams list carries none, so a reader built from it ranks nobody."""
    return YahooRead("standings", TEAMS_TTL, league=league_key)


def roster(team_key: str) -> YahooRead:
    return YahooRead(f"team/{team_key}/roster", ROSTER_TTL)


def scoreboard(league_key: str, week: int) -> YahooRead:
    """One week's matchups, every pairing in the league: the only place Yahoo lists a head-to-head season."""
    return YahooRead(f"scoreboard;week={week}", SCOREBOARD_TTL, league=league_key, keep_on_failure=True)


def player_page(
    league_key: str,
    count: int,
    status: PlayerStatus,
    sort: PlayerStat | str | None,
    sort_type: Timeframe | None,
    ttl: timedelta = LEADERS_TTL,
) -> YahooRead:
    """A page of the league's players, filtered and sorted."""
    params: dict[str, str] = {"count": str(count), "status": status.value}
    if sort is not None:
        params["sort"] = str(sort)
    if sort_type is not None:
        params["sort_type"] = sort_type.value
    return YahooRead("players;" + ";".join(f"{k}={v}" for k, v in params.items()), ttl, league=league_key)


def available(league_key: str, count: int) -> YahooRead:
    """The best available players, however they became free, by season rank.

    ALL_AVAILABLE rather than FREE_AGENT: somebody sitting on waivers is still
    a decision to be made about.
    """
    return player_page(league_key, count, PlayerStatus.ALL_AVAILABLE, PlayerStat.ACTUAL_RANK, Timeframe.SEASON)


def leaders(
    league_key: str, stats: Mapping[str, str], per_stat: int, sort_type: Timeframe = Timeframe.LAST_WEEK
) -> dict[str, YahooRead]:
    """The top available players for each stat id in `stats`, keyed as `stats` keys them."""
    return {
        name: player_page(league_key, per_stat, PlayerStatus.ALL_AVAILABLE, stat_id, sort_type)
        for name, stat_id in stats.items()
    }


def search(league_key: str, query: str) -> YahooRead:
    return YahooRead(f"players;search={query}", SEARCH_TTL, league=league_key, search=query)


def by_keys(league_key: str, player_keys: list[str]) -> YahooRead:
    keys = ",".join(player_keys)
    return YahooRead(f"players;player_keys={keys}", ROSTER_TTL, league=league_key, player_keys=tuple(player_keys))
