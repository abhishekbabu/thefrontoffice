"""Every request the app makes of Yahoo, and how long its answer holds.

Built in one place so that everything naming a Yahoo response names it alike:
the reader asks for it, the browser capture plans and stores it, the session
reader fetches it, and all of them key the cache by its path — the path Yahoo
serves it at, below `/fantasy/v2/`, on the API host and on the host Yahoo's own
pages read.
"""

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta, tzinfo

from thefrontoffice.adapters.outbound.platforms.yahoo.types import Average, PlayerStat, PlayerStatus, Timeframe
from thefrontoffice.domain.errors import FrontOfficeError

logger = logging.getLogger(__name__)

# TTLs from how fast each answer actually goes stale. Waiver leaders move as
# the league claims players; a name search resolves to the same player for as
# long as anyone is looking.
LEADERS_TTL = timedelta(minutes=30)
"""Also how long a waiver clear date on the first page holds: a claim, or a drop putting a player on waivers,
shows within it."""
DEEP_TTL = timedelta(hours=6)
"""The wire past its first page: who sits 200th by season rank moves slowly, and is rarely the one claimed."""
SEARCH_TTL = timedelta(hours=6)
TEAMS_TTL = timedelta(hours=1)
"""Short for what it is, because the team list carries each team's adds used this week."""
STANDINGS_TTL = timedelta(hours=1)
ROSTER_TTL = timedelta(hours=1)
LEAGUES_TTL = timedelta(hours=1)
"""The league list carries the week being played, which has to turn over with the week."""
# A league's scoring is set before the season and almost never changes during it.
SETTINGS_TTL = timedelta(days=1)
SCOREBOARD_TTL = timedelta(minutes=2)
"""The week being played while games are on: it drives the "which categories
are close" analysis and goes stale within a game night."""
QUIET_SCOREBOARD_TTL = timedelta(minutes=30)
"""The week being played when no game can be on: nothing in it moves but a stat correction."""
SETTLING_TTL = timedelta(hours=6)
"""Last week's, while the stat corrections Yahoo applies after a week closes still land."""
AHEAD_TTL = timedelta(days=7)
"""A week to come: only who plays whom, which is set until the playoff bracket is drawn."""
FINAL_TTL = timedelta(days=365)
"""A week closed and settled: it will never change, so it is never asked for again this season."""
AVERAGES_TTL = timedelta(hours=3)
"""A player's averages move once a game night, and only for those who played in it."""
TRANSACTIONS_TTL = timedelta(hours=1)
"""The league's moves: one request carries the season's, read only when a player's history is opened."""
PLAYED_TTL = timedelta(days=7)
"""A week once played stands, bar the stat corrections Yahoo makes in the days after it."""

API = "https://fantasysports.yahooapis.com/fantasy/v2/"
"""Yahoo's Fantasy API, which the SDK asks with an OAuth token."""

FRONTEND = "https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2/"
"""The read-only host Yahoo's own pages fetch from: it answers their session cookie, and nothing writes through it."""

PAGE = 25
"""The most players Yahoo's API lists in one response; a deeper list is read a page at a time."""

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
    def servable(self) -> timedelta:
        """How old a copy may be and still be served while a fresh one is fetched behind it: twice its TTL.

        Bounded by the TTL itself, so a page is never more than one refresh
        behind: a two-minute score is at most four minutes old, a roster two hours.
        """
        return self.ttl * 2

    @property
    def path(self) -> str:
        """Where Yahoo serves it, and the key it is kept under."""
        return served_at(self.query, self.league)

    @property
    def lookup(self) -> bool:
        """Whether it asks for players by key or by name, which no plan can know in advance."""
        return bool(self.player_keys or self.search)


def served_at(query: str, league: str = "") -> str:
    """Where Yahoo serves `query`: below `league/<key>/` where it names a league, as the SDK asks for it."""
    return f"league/{league}/{query}" if league else query


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
    return YahooRead("standings", STANDINGS_TTL, league=league_key)


def transactions(league_key: str) -> YahooRead:
    """Every move the league has made this season, newest first: adds, drops and trades, in one response."""
    return YahooRead("transactions", TRANSACTIONS_TTL, league=league_key)


def roster(team_key: str) -> YahooRead:
    return YahooRead(f"team/{team_key}/roster", ROSTER_TTL)


def played_roster(team_key: str, week: int) -> YahooRead:
    """A team's roster as it ended a week already played, each player with his line over that week.

    Asked for only once the week is over, so no copy held was read while it was being played.
    """
    return YahooRead(f"team/{team_key}/roster;week={week}/players/stats;type=week;week={week}", PLAYED_TTL)


def day_roster(team_key: str, day: date) -> YahooRead:
    """A team's roster as slotted on `day`, each player with his line from that day's game.

    Asked for the day being played, whose lines move with every basket while
    games are on: held as briefly as the scoreboard that totals them.
    """
    on = day.isoformat()
    return YahooRead(f"team/{team_key}/roster;date={on}/players/stats;type=date;date={on}", SCOREBOARD_TTL)


def roster_averages(team_key: str, average: Average) -> YahooRead:
    """A team's roster, each player with his averages over `average`: one read for the whole roster."""
    return YahooRead(f"team/{team_key}/roster/players/stats;type={average}", AVERAGES_TTL)


@dataclass(frozen=True)
class ScoreboardPace:
    """Whether a league's scores can be moving right now, so the week being played is asked for no oftener than that.

    Games are played inside daily hours on the league's own clock, and only on
    days with games: outside either, the scoreboard waits for a stat correction
    at most. Hours that run past midnight belong to the day they opened on.
    Which hours, which zone and which days are the competition's to say, so
    the composition root supplies them.
    """

    zone: tzinfo
    opens: time
    closes: time
    games_on: Callable[[date], bool] = field(default=lambda _: True)
    """Whether the league plays on a day; a schedule that will not load is read as yes."""
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))

    def live(self) -> bool:
        local = self.clock().astimezone(self.zone)
        now, today = local.time(), local.date()
        if self.opens <= self.closes:
            day = today if self.opens <= now < self.closes else None
        elif now >= self.opens:
            day = today
        else:
            day = today - timedelta(days=1) if now < self.closes else None
        if day is None:
            return False
        try:
            return self.games_on(day)
        except FrontOfficeError as e:
            logger.warning(f"Reading the scoreboard as live, with no schedule to say otherwise: {e}")
            return True


def scoreboard(league_key: str, week: int, current: int | None = None, live: bool = True) -> YahooRead:
    """One week's matchups, every pairing in the league: the only place Yahoo lists a head-to-head season.

    How long it holds follows where `week` sits against `current`, the week
    being played: settled weeks never change, a week to come changes rarely,
    and the week being played only while games are `live`. Where the week
    being played is not known, any week is read as that one.
    """
    if current is None or week == current:
        ttl = SCOREBOARD_TTL if live else QUIET_SCOREBOARD_TTL
    elif week > current:
        ttl = AHEAD_TTL
    else:
        ttl = SETTLING_TTL if week == current - 1 else FINAL_TTL
    return YahooRead(f"scoreboard;week={week}", ttl, league=league_key, keep_on_failure=True)


def player_page(
    league_key: str,
    count: int,
    status: PlayerStatus,
    sort: PlayerStat | str | None,
    sort_type: Timeframe | None,
    ttl: timedelta = LEADERS_TTL,
    start: int = 0,
    average: Average | None = None,
) -> YahooRead:
    """A page of the league's players, filtered and sorted, `start` places down the order.

    Each player carries his ownership (`out=ownership`), which is where Yahoo
    says the day one on waivers clears them: no read beyond the page. With
    `average`, he carries his averages over it, in the same response.
    """
    params: dict[str, str] = {"count": str(count), "status": status.value}
    if sort is not None:
        params["sort"] = str(sort)
    if sort_type is not None:
        params["sort_type"] = sort_type.value
    if start:
        params["start"] = str(start)
    params["out"] = "ownership"
    stats = f"/stats;type={average}" if average else ""
    return YahooRead("players;" + ";".join(f"{k}={v}" for k, v in params.items()) + stats, ttl, league=league_key)


RECENT_AVERAGE = Average.LAST_MONTH
"""The span a table of players shows averages over, on the wire and on a roster alike."""


def available(league_key: str, depth: int, sort_type: Timeframe = Timeframe.SEASON) -> list[YahooRead]:
    """The best available players, however they became free, by Yahoo's rank over `sort_type`: a read per `PAGE`.

    ALL_AVAILABLE rather than FREE_AGENT: somebody sitting on waivers is still
    a decision to be made about. The first page holds the players most likely
    to be claimed, so it is asked for oftenest; the rest hold for `DEEP_TTL`.
    Each player carries his averages over the last month, which is what the
    wire's table shows: no request beyond the page.
    """
    return [
        player_page(
            league_key,
            min(PAGE, depth - start),
            PlayerStatus.ALL_AVAILABLE,
            PlayerStat.ACTUAL_RANK,
            sort_type,
            ttl=DEEP_TTL if start else LEADERS_TTL,
            start=start,
            average=RECENT_AVERAGE,
        )
        for start in range(0, depth, PAGE)
    ]


def leaders(
    league_key: str, stats: Mapping[str, str], per_stat: int, sort_type: Timeframe = Timeframe.LAST_WEEK
) -> dict[str, YahooRead]:
    """The top available players for each stat id in `stats`, keyed as `stats` keys them."""
    return {
        name: player_page(league_key, per_stat, PlayerStatus.ALL_AVAILABLE, stat_id, sort_type)
        for name, stat_id in stats.items()
    }


_PATH_SYNTAX = re.compile(r"[;/?#&=,]")
"""What would end the search term and start another part of the path; no name holds any of it."""


def search(league_key: str, query: str) -> YahooRead:
    """Players whose name holds `query`, rostered or not."""
    term = " ".join(_PATH_SYNTAX.sub(" ", query).split())
    return YahooRead(f"players;search={term}", SEARCH_TTL, league=league_key, search=term)


def by_keys(league_key: str, player_keys: list[str]) -> YahooRead:
    """These players, whoever holds them, each with whose roster he is on: the ownership rides the same read."""
    keys = ",".join(player_keys)
    return YahooRead(
        f"players;player_keys={keys}/ownership", ROSTER_TTL, league=league_key, player_keys=tuple(player_keys)
    )


def averages(league_key: str, player_keys: list[str], average: Average) -> list[YahooRead]:
    """These players' averages over `average`, whoever holds them: a read per `PAGE` of keys."""
    return [
        YahooRead(
            f"players;player_keys={','.join(batch)}/stats;type={average}",
            AVERAGES_TTL,
            league=league_key,
            player_keys=tuple(batch),
        )
        for batch in (player_keys[i : i + PAGE] for i in range(0, len(player_keys), PAGE))
    ]
