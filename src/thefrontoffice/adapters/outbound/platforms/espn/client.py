"""ESPN's public news feeds, and its live scoreboard.

Fantasy platforms publish a player's injury status but not the news behind
it — who is getting the work, who is back at practice, whose role changed.
ESPN's site API publishes headlines per club, with the players each one is
about tagged, and asks for no key.

One request per club rather than the league-wide feed: that feed holds the
latest fifty articles across every club, about a day of news, while a club's
own holds its last fifty, which reaches back a couple of weeks.

The injury report is read because a fantasy platform's designation is
whatever was set last: on the Tuesday after a game, a player ruled out of it
still reads Out. ESPN's is dated, and moves with the week's practices.

The scoreboard is read for the one thing the fantasy platforms leave out: how
far through a game is. Sleeper says a game is under way, and nothing about
whether that is the first minute or the last.
"""

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol

from tenacity import Retrying

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.espn.errors import ESPNAPIError, ESPNUnavailableError
from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport, NewsArticle, ScoreboardGame
from thefrontoffice.adapters.outbound.platforms.http import JsonApiClient
from thefrontoffice.adapters.outbound.platforms.retry import build_retry, is_transient
from thefrontoffice.adapters.outbound.platforms.timestamps import parse_utc
from thefrontoffice.config.settings import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"

# A club list changes when a franchise moves; news turns over within hours.
TEAMS_TTL = timedelta(days=1)
NEWS_TTL = timedelta(minutes=30)
INJURIES_TTL = timedelta(minutes=30)
SCOREBOARD_TTL = timedelta(minutes=1)
"""A clock that is a minute stale is a minute of a sixty-minute game."""
NEWS_LIMIT = 50
"""ESPN's own ceiling for one feed; asking for more returns the same fifty."""

RETRY_MAX_ATTEMPTS = 3
RETRYABLE_STATUS = frozenset({429})


def _retry() -> Retrying:
    return build_retry(
        attempts=RETRY_MAX_ATTEMPTS,
        multiplier=2,
        min_wait=2,
        max_wait=20,
        predicate=lambda e: is_transient(e, RETRYABLE_STATUS),
    )


class ESPNSource(Protocol):
    """What a provider reads ESPN through. See `SleeperNFLSource` in platforms/sleeper/client.py for why it exists."""

    def get_team_news(self, league: str, clubs: list[str]) -> dict[str, list[NewsArticle]]:
        """Each club's recent articles, newest first, keyed by ESPN's abbreviation."""
        ...

    def get_injuries(self, league: str) -> list[InjuryReport]:
        """Every player on every club's injury report, as it stands right now."""
        ...

    def get_scoreboard(self, league: str, season: str, week: int) -> list[ScoreboardGame]:
        """Every regular-season game of `week`, as it stands right now."""
        ...


class ESPNClient:
    """Read-only access to ESPN's per-club news."""

    def __init__(self, cache: JsonDiskCache | None = None, session: Any = None) -> None:
        self._api = JsonApiClient(
            name="ESPN",
            cache=cache or JsonDiskCache(Path(settings.espn_cache_dir)),
            retry=_retry,
            error=ESPNAPIError,
            unavailable=ESPNUnavailableError,
            session=session,
        )

    def get_teams(self, league: str) -> dict[str, str]:
        """ESPN's id for each club, keyed by the abbreviation ESPN uses."""
        data = self._api.cached(f"teams_{league.replace('/', '_')}", f"{BASE_URL}/{league}/teams", TEAMS_TTL)
        try:
            teams = data["sports"][0]["leagues"][0]["teams"]
        except (KeyError, IndexError, TypeError) as e:
            raise ESPNAPIError(f"ESPN returned an unreadable club list: {e}") from e
        return {
            str(t["team"]["abbreviation"]): str(t["team"]["id"])
            for t in teams
            if isinstance(t, dict) and t.get("team", {}).get("abbreviation")
        }

    def get_team_news(self, league: str, clubs: list[str]) -> dict[str, list[NewsArticle]]:
        """Each club's recent articles, newest first, keyed by ESPN's abbreviation.

        A club whose feed will not load is left out rather than failing the
        rest: news is enrichment, and thirty-one clubs of it beat none.
        """
        ids = self.get_teams(league)
        prefix = league.replace("/", "_")
        urls = {
            f"news_{prefix}_{club}": f"{BASE_URL}/{league}/news?team={ids[club]}&limit={NEWS_LIMIT}"
            for club in clubs
            if club in ids
        }
        raw = self._api.cached_many(urls, NEWS_TTL)
        news = {}
        for club in clubs:
            payload = raw.get(f"news_{prefix}_{club}")
            if isinstance(payload, dict):
                articles = [a for a in (_article(row) for row in payload.get("articles") or []) if a]
                news[club] = sorted(articles, key=lambda a: a.published, reverse=True)
        return news

    def get_injuries(self, league: str) -> list[InjuryReport]:
        """Every player on every club's injury report, as it stands right now.

        One league-wide request: unlike the news, the report is short enough
        that ESPN publishes it whole.
        """
        data = self._api.cached(f"injuries_{league.replace('/', '_')}", f"{BASE_URL}/{league}/injuries", INJURIES_TTL)
        if not isinstance(data, dict):
            raise ESPNAPIError("ESPN returned an unreadable injury report.")
        clubs = [club for club in data.get("injuries") or [] if isinstance(club, dict)]
        return [report for club in clubs for report in (_injury(row) for row in club.get("injuries") or []) if report]

    def get_scoreboard(self, league: str, season: str, week: int) -> list[ScoreboardGame]:
        """Every regular-season game of `week`, as it stands right now."""
        data = self._api.cached(
            f"scoreboard_{league.replace('/', '_')}_{season}_{week}",
            f"{BASE_URL}/{league}/scoreboard?seasontype=2&week={week}&dates={season}",
            SCOREBOARD_TTL,
        )
        if not isinstance(data, dict):
            raise ESPNAPIError("ESPN returned an unreadable scoreboard.")
        return [game for game in (_game(event) for event in data.get("events") or []) if game]


def _game(event: Any) -> ScoreboardGame | None:
    """One scoreboard event, or None for one missing either side."""
    try:
        competition = event["competitions"][0]
        sides = {c["homeAway"]: str(c["team"]["abbreviation"]) for c in competition["competitors"]}
        status = event.get("status") or {}
        return ScoreboardGame(
            home=sides["home"],
            away=sides["away"],
            state=str((status.get("type") or {}).get("state") or ""),
            period=int(status.get("period") or 0),
            clock=float(status.get("clock") or 0.0),
            label=str((status.get("type") or {}).get("shortDetail") or ""),
        )
    except KeyError, IndexError, TypeError, ValueError:
        logger.debug(f"Skipping an unreadable ESPN scoreboard event: {str(event)[:200]}")
        return None


def _injury(row: Any) -> InjuryReport | None:
    """One report row, or None for one missing who, which club, what or when."""
    try:
        athlete = row["athlete"]
        return InjuryReport(
            name=str(athlete["displayName"]),
            club=str(athlete["team"]["abbreviation"]),
            status=str(row["status"]),
            updated=parse_utc(str(row["date"])),
        )
    except KeyError, TypeError, ValueError:
        logger.debug(f"Skipping an unreadable ESPN injury row: {str(row)[:200]}")
        return None


def _article(row: Any) -> NewsArticle | None:
    """One feed row, or None for one that is missing what makes it news."""
    if not isinstance(row, dict) or not row.get("headline") or not row.get("published"):
        return None
    try:
        published = parse_utc(str(row["published"]))
    except ValueError:
        logger.debug(f"Skipping an ESPN article with an unreadable date: {row.get('published')!r}")
        return None
    return NewsArticle(
        article_id=str(row.get("id") or ""),
        published=published,
        headline=str(row["headline"]),
        summary=str(row.get("description") or ""),
        url=str(((row.get("links") or {}).get("web") or {}).get("href") or ""),
        athletes=[
            str(c["description"])
            for c in row.get("categories") or []
            if isinstance(c, dict) and c.get("type") == "athlete" and c.get("description")
        ],
    )
