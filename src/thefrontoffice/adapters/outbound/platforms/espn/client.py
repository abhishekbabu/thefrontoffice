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

That report is short: ESPN keeps the latest twenty-five entries a club has,
newest first, and a player cleared to play still takes a slot — so a starter
put on injured reserve in September has fallen off it by November. ESPN's core
API keeps each player's own injury entry for the season, with the same
estimated return, but it is one request per player and asks for his ESPN id;
each club's roster is where that id is found by name.

The scoreboard is read for the one thing the fantasy platforms leave out: how
far through a game is. Sleeper says a game is under way, and nothing about
whether that is the first minute or the last.
"""

import logging
import re
from collections.abc import Sequence
from datetime import date, timedelta
from typing import Any, Protocol

from thefrontoffice.adapters.outbound.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.espn.errors import ESPNAPIError, ESPNUnavailableError
from thefrontoffice.adapters.outbound.platforms.espn.types import Athlete, InjuryReport, NewsArticle, ScoreboardGame
from thefrontoffice.adapters.outbound.platforms.http import JsonApiClient
from thefrontoffice.adapters.outbound.platforms.retry import RetryPolicy
from thefrontoffice.adapters.outbound.platforms.timestamps import parse_utc

logger = logging.getLogger(__name__)

BASE_URL = "https://site.api.espn.com/apis/site/v2/sports"
CORE_URL = "https://sports.core.api.espn.com/v2/sports"
"""ESPN's core API: per-athlete records the site API's league-wide views cut short."""

# A club list changes when a franchise moves; news turns over within hours.
TEAMS_TTL = timedelta(days=1)
ROSTERS_TTL = timedelta(days=1)
"""A roster changes with a signing, and a day-old one still names everyone hurt for longer than that."""
NEWS_TTL = timedelta(minutes=30)
INJURIES_TTL = timedelta(minutes=30)
SCOREBOARD_TTL = timedelta(minutes=1)
"""A clock that is a minute stale is a minute of a sixty-minute game."""
NEWS_LIMIT = 50
"""ESPN's own ceiling for one feed; asking for more returns the same fifty."""
HISTORY_LIMIT = 5
"""A player's injury entries this season, of which the newest is read. ESPN keeps one per player
and updates it in place, so five is room to spare rather than a page of history."""


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

    def get_rosters(self, league: str) -> list[Athlete]:
        """Everyone on every club's roster, with ESPN's id for him."""
        ...

    def get_athlete_injuries(self, league: str, season: str, athletes: Sequence[Athlete]) -> dict[str, InjuryReport]:
        """Each athlete's latest injury this season, keyed by his ESPN id; nobody ESPN has none for."""
        ...


class ESPNClient:
    """Read-only access to ESPN's per-club news, live scoreboard and injury report."""

    def __init__(self, *, cache: JsonDiskCache, retry: RetryPolicy, session: Any = None) -> None:
        self._api = JsonApiClient(
            name="ESPN",
            cache=cache,
            retry=retry,
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
        raw = self._api.cached_many(urls, NEWS_TTL).values
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

    def get_rosters(self, league: str) -> list[Athlete]:
        """Everyone on every club's roster, with ESPN's id for him.

        A club whose roster will not load is left out rather than failing the
        rest, as its news is: its players simply go unfound.
        """
        ids = self.get_teams(league)
        prefix = league.replace("/", "_")
        urls = {f"roster_{prefix}_{club}": f"{BASE_URL}/{league}/teams/{team}/roster" for club, team in ids.items()}
        raw = self._api.cached_many(urls, ROSTERS_TTL, keep=_roster).values
        return [
            Athlete(athlete_id=row["id"], name=row["name"], club=club)
            for club in ids
            for row in raw.get(f"roster_{prefix}_{club}") or []
        ]

    def get_athlete_injuries(self, league: str, season: str, athletes: Sequence[Athlete]) -> dict[str, InjuryReport]:
        """Each athlete's latest injury this season, keyed by his ESPN id; nobody ESPN has none for.

        One request per athlete, in parallel and cached as long as the
        league-wide report is. One that fails is left out, like a club's news.
        """
        sport, name = league.split("/")
        keys = {f"athlete_injuries_{sport}_{name}_{season}_{a.athlete_id}": a for a in athletes}
        urls = {
            key: f"{CORE_URL}/{sport}/leagues/{name}/seasons/{season}/athletes/{a.athlete_id}/injuries"
            f"?limit={HISTORY_LIMIT}"
            for key, a in keys.items()
        }
        raw = self._api.cached_many(urls, INJURIES_TTL).values
        found = {}
        for key, athlete in keys.items():
            payload = raw.get(key)
            rows = payload.get("items") if isinstance(payload, dict) else None
            entries = [e for e in (_entry(row, athlete, name) for row in rows or []) if e]
            if entries:
                found[athlete.athlete_id] = max(entries, key=lambda e: e.updated)
        return found

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
        # A string on the wire, and absent before kickoff.
        scores = {c["homeAway"]: int(c.get("score") or 0) for c in competition["competitors"]}
        status = event.get("status") or {}
        return ScoreboardGame(
            home=sides["home"],
            away=sides["away"],
            state=str((status.get("type") or {}).get("state") or ""),
            period=int(status.get("period") or 0),
            clock=float(status.get("clock") or 0.0),
            label=str((status.get("type") or {}).get("shortDetail") or ""),
            home_score=scores["home"],
            away_score=scores["away"],
            kickoff=parse_utc(str(event["date"])) if event.get("date") else None,
        )
    except KeyError, IndexError, TypeError, ValueError:
        logger.debug(f"Skipping an unreadable ESPN scoreboard event: {str(event)[:200]}")
        return None


ATHLETE_ID = re.compile(r"/id/(\d+)")
"""ESPN's athlete id, which its injury rows carry only inside the links to his pages."""

UNSPECIFIED = "Not Specified"
"""ESPN's word for a detail it does not know, which reads as nothing at all."""


def _injury(row: Any) -> InjuryReport | None:
    """One report row, or None for one missing who, which club, what or when."""
    try:
        athlete = row["athlete"]
        details = row.get("details") or {}
        links = [link for link in athlete.get("links") or [] if isinstance(link, dict)]
        return InjuryReport(
            name=str(athlete["displayName"]),
            club=str(athlete["team"]["abbreviation"]),
            status=str(row["status"]),
            updated=parse_utc(str(row["date"])),
            athlete_id=_athlete_id(links),
            returns=_return_date(details.get("returnDate")),
            injury=_what(details),
            comment=str(row.get("shortComment") or ""),
            url=_link(links, "news"),
        )
    except KeyError, TypeError, ValueError, AttributeError:
        logger.debug(f"Skipping an unreadable ESPN injury row: {str(row)[:200]}")
        return None


def _roster(payload: Any) -> list[dict[str, str]]:
    """A club's roster cut to each player's id and name: the rest is a third of a megabyte nobody reads."""
    groups = payload.get("athletes") if isinstance(payload, dict) else None
    return [
        {"id": str(row["id"]), "name": str(row["fullName"])}
        for group in groups or []
        if isinstance(group, dict)
        for row in group.get("items") or []
        if isinstance(row, dict) and row.get("id") and row.get("fullName")
    ]


def _entry(row: Any, athlete: Athlete, league: str) -> InjuryReport | None:
    """One entry of a player's injury history, or None for one missing what or when."""
    try:
        details = row.get("details") or {}
        return InjuryReport(
            name=athlete.name,
            club=athlete.club,
            status=str(row["status"]),
            updated=parse_utc(str(row["date"])),
            athlete_id=athlete.athlete_id,
            returns=_return_date(details.get("returnDate")),
            injury=_what(details),
            comment=str(row.get("shortComment") or ""),
            url=f"https://www.espn.com/{league}/player/news/_/id/{athlete.athlete_id}",
        )
    except KeyError, TypeError, ValueError, AttributeError:
        logger.debug(f"Skipping an unreadable ESPN injury history entry: {str(row)[:200]}")
        return None


def _athlete_id(links: list[dict[str, Any]]) -> str:
    """His ESPN id, out of the first link to one of his pages that carries it."""
    for link in links:
        if found := ATHLETE_ID.search(str(link.get("href") or "")):
            return found.group(1)
    return ""


def _link(links: list[dict[str, Any]], rel: str) -> str:
    """The web page of his that `rel` names, never the app's own URL scheme."""
    return next(
        (
            str(link["href"])
            for link in links
            if rel in (link.get("rel") or []) and str(link.get("href") or "").startswith("https://")
        ),
        "",
    )


def _return_date(label: Any) -> date | None:
    """ESPN's estimated return, or None where it is missing or unreadable — an estimate, not worth the row."""
    try:
        return date.fromisoformat(str(label)[:10]) if label else None
    except ValueError:
        return None


def _what(details: dict[str, Any]) -> str:
    """'Right elbow, surgery', leaving out whatever ESPN did not specify."""
    part = " ".join(
        str(details[key]) for key in ("side", "type") if details.get(key) and details[key] != UNSPECIFIED
    ).capitalize()
    detail = str(details.get("detail") or "")
    if detail and detail != UNSPECIFIED:
        return f"{part}, {detail.lower()}" if part else detail
    return part


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
