"""Yahoo Fantasy league data: rosters, matchups and player queries, one league at a time.

Logging in and finding the leagues to read is `auth.py`'s; this reads one of them.
The SDK is a transport and an XML parser here and nothing more: every request
goes through `call`, and every response is read into this package's own types,
so nothing outside it touches an object whose attributes arrive by `setattr`.

Where the responses come from is the `YahooResponses` the reader is handed:
Yahoo itself (`LiveResponses`), or what a browser captured of it (`capture.py`).
"""

import logging
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date, timedelta
from typing import Any, Protocol

from yahoofantasy.api.parse import as_list, parse_response

from thefrontoffice.adapters.outbound.cache import DiskCache
from thefrontoffice.adapters.outbound.platforms.http import fetch_many
from thefrontoffice.adapters.outbound.platforms.retry import RetryPolicy, outage
from thefrontoffice.adapters.outbound.platforms.yahoo import paths
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import (
    YahooAPIError,
    YahooAuthError,
    YahooUnavailableError,
)
from thefrontoffice.adapters.outbound.platforms.yahoo.paths import ScoreboardPace, YahooRead
from thefrontoffice.adapters.outbound.platforms.yahoo.types import (
    Average,
    LeagueSettings,
    Matchup,
    MatchupSide,
    Pairing,
    StatCategory,
    TeamStanding,
    Timeframe,
    YahooLeague,
    YahooLine,
    YahooPlayer,
    YahooTeam,
)
from thefrontoffice.domain.errors import FrontOfficeError, TeamNotFoundError

logger = logging.getLogger(__name__)


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
        return YahooUnavailableError(down)
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
    """The SDK's authorized context: how this package asks Yahoo anything."""

    def make_request(self, url: str, league: str | bool = False) -> str:
        """The raw XML for `url`, under `league/<key>/` when a league is named."""
        ...


class YahooResponses(Protocol):
    """Where a Yahoo reader's responses come from: Yahoo itself, or what a browser captured of it."""

    def raw(self, read: YahooRead) -> str:
        """The XML Yahoo answers `read` with.

        Raises:
            YahooAPIError: it could not be had.
        """
        ...

    def many(self, reads: Mapping[str, YahooRead]) -> dict[str, str]:
        """Each read's XML, keyed as `reads` keys them; one that cannot be had fails them all."""
        ...


class Refresh(Protocol):
    """Fetches a key again behind the caller's back, and stores it: how a stale copy is served without a wait."""

    def refresh(self, key: str, fetch: Callable[[], Any]) -> None: ...


class LiveResponses:
    """Yahoo's answers, asked of Yahoo through the SDK and kept in our own cache.

    Our cache rather than the SDK's store: the vendor persists into one shared
    pickle by read-modify-write, so concurrent writes clobber each other, and
    its `_load` takes no expiry at all — waiver leaders cached once stayed
    cached until the file was deleted.

    Given a `refresher`, a copy past its TTL but within `YahooRead.servable` is
    served at once and fetched again in the background; without one, every
    expired read waits on Yahoo.
    """

    def __init__(
        self, context: YahooContext, *, cache: DiskCache, retry: RetryPolicy, refresher: Refresh | None = None
    ) -> None:
        self._context = context
        self._cache = cache
        self._retry = retry
        self._refresher = refresher

    def _fetch(self, read: YahooRead) -> str:
        return request(self._retry, lambda: self._context.make_request(read.query, league=read.league or False))

    def _held(self, read: YahooRead) -> str | None:
        """The copy to serve without waiting: fresh, or stale within bounds with a refresh started behind it."""
        hit = self._cache.lookup(read.path, read.ttl)
        if hit is not None:
            return hit.value
        if self._refresher is None:
            return None
        stale = self._cache.lookup(read.path, read.servable)
        if stale is None:
            return None
        self._refresher.refresh(read.path, lambda: self._fetch(read))
        return stale.value

    def raw(self, read: YahooRead) -> str:
        """`read` from the cache while it holds, from Yahoo once it does not.

        A read that keeps its copy on failure — the scoreboard — falls back to
        the stored one, stale but usable, when the refresh fails.
        """
        held = self._held(read)
        if held is not None:
            return held
        try:
            value = self._fetch(read)
        except FrontOfficeError as e:
            kept = self._cache.lookup(read.path, timedelta.max) if read.keep_on_failure else None
            if kept is None:
                raise
            logger.warning(f"Could not refresh {read.path}, using the stored copy: {e}")
            return kept.value
        self._cache.set(read.path, value)
        return value

    def many(self, reads: Mapping[str, YahooRead]) -> dict[str, str]:
        """Each read, each by its own TTL, the misses fetched concurrently: run one after another they were the
        dominant latency."""
        held = {read.path: value for read in reads.values() if (value := self._held(read)) is not None}
        missing = {read.path: read for read in reads.values() if read.path not in held}
        fetches = {path: (lambda read=read: self._fetch(read)) for path, read in missing.items()}
        batch = fetch_many(self._cache, fetches, {path: read.ttl for path, read in missing.items()})
        for error in batch.failures.values():
            raise error
        found = held | batch.values
        return {name: found[read.path] for name, read in reads.items()}


class YahooSource(Protocol):
    """What the basketball provider reads Yahoo through. See `SleeperNFLSource` in platforms/sleeper/client.py for why it exists."""

    def fetch_available(self, depths: Mapping[Timeframe, int]) -> dict[Timeframe, list[YahooPlayer]]:
        """The best available players in the league, however they became free, by Yahoo's rank over each timeframe."""
        ...

    def fetch_top_by_stat(
        self, stats: Mapping[str, str], per_stat: int = 10, sort_type: Timeframe = Timeframe.LAST_WEEK
    ) -> dict[str, list[YahooPlayer]]:
        """Top available players for each Yahoo stat id in `stats`, keyed as `stats` keys them."""
        ...

    def pairing(self, team_key: str, week: int) -> Pairing | None:
        """The team's head-to-head in any week of the season, or None where it plays nobody that week.

        Raises:
            YahooAuthError: the app is not authorized for Fantasy Sports.
            YahooAPIError: Yahoo could not be reached, or answered unreadably.
        """
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

    def played_rosters(self, team_keys: list[str], week: int) -> dict[str, list[YahooPlayer]]:
        """Each team's roster as it ended a week already played, each player with his line over it, by team key."""
        ...

    def search_players(self, query: str) -> list[YahooPlayer]:
        """Players in the league whose name matches `query`."""
        ...

    def averages(self, player_keys: list[str], spans: Sequence[Average]) -> dict[Average, dict[str, YahooLine]]:
        """These players' averages over each of `spans`, by key; a key Yahoo does not know is left out."""
        ...

    def roster_averages(self, team_key: str, average: Average) -> dict[str, YahooLine]:
        """The averages over `average` of every player a team holds, by key."""
        ...

    def players(self, player_keys: list[str]) -> list[YahooPlayer]:
        """The players with these keys, whoever holds them; a key Yahoo does not know is left out."""
        ...

    def teams(self) -> list[YahooTeam]:
        """Every team in the league."""
        ...

    def standings(self) -> list[YahooTeam]:
        """Every team in the league, each with its place in the table."""
        ...

    def season(self, team_key: str, weeks: list[int]) -> dict[int, Pairing | None]:
        """The team's head-to-head in each of `weeks`, None where it plays nobody."""
        ...

    def settings(self) -> LeagueSettings:
        """How the league is scored, how often a team may add, and where its playoffs start."""
        ...


class YahooClient:
    """Reads one Yahoo league, from whichever `YahooResponses` it is handed."""

    def __init__(self, league: YahooLeague, *, responses: YahooResponses, pace: ScoreboardPace | None = None) -> None:
        """`pace` says when the week being played can be moving; without one it is always read as moving."""
        self.league = league
        self._responses = responses
        self._pace = pace

    def _scoreboard(self, week: int) -> YahooRead:
        live = self._pace.live() if self._pace is not None else True
        return paths.scoreboard(self.league.league_key, week, self.league.current_week, live=live)

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

        One request per stat, run concurrently. Which stats a sport scores is
        the sport's to say, so the caller names them. One failing fails them
        all — a category left empty would read as nobody worth adding in it.
        """
        raws = self._responses.many(paths.leaders(self.league.league_key, stats, per_stat, sort_type))
        return {name: self._players(raw, per_stat) for name, raw in raws.items()}

    def fetch_available(self, depths: Mapping[Timeframe, int]) -> dict[Timeframe, list[YahooPlayer]]:
        """The best available players, however they became free, by Yahoo's rank over each timeframe, that deep.

        Every page of every ranking in one batch, fetched concurrently. Pages
        fetched a moment apart can overlap as the order shifts, so a player is
        kept once, where he first appears; a ranking that runs out early is
        shorter, not a failure.
        """
        key = self.league.league_key
        reads = {sort_type: paths.available(key, depth, sort_type) for sort_type, depth in depths.items()}
        raws = self._responses.many({read.path: read for pages in reads.values() for read in pages})
        return {
            sort_type: once(p for read in pages for p in self._players(raws[read.path]))
            for sort_type, pages in reads.items()
        }

    def search_players(self, query: str) -> list[YahooPlayer]:
        """Players in the league whose name matches `query`; no match is an empty answer."""
        return self._players(self._responses.raw(paths.search(self.league.league_key, query)))

    def players(self, player_keys: list[str]) -> list[YahooPlayer]:
        """The players with these keys, whoever holds them — yours, a rival's or nobody's.

        A key Yahoo does not know is left out, so asking for one that is gone
        is an empty answer rather than a failure.
        """
        return self._players(self._responses.raw(paths.by_keys(self.league.league_key, player_keys)))

    def averages(self, player_keys: list[str], spans: Sequence[Average]) -> dict[Average, dict[str, YahooLine]]:
        """These players' averages over each of `spans`, by key: a read per 25 of them a span, all fetched together.

        A key Yahoo does not know is left out, as is a player it carries no line for.
        """
        keys = list(dict.fromkeys(player_keys))
        reads = {span: paths.averages(self.league.league_key, keys, span) for span in spans}
        raws = self._responses.many({read.path: read for batch in reads.values() for read in batch})
        return {
            span: {p.player_key: p.line for read in batch for p in self._players(raws[read.path]) if p.coverage}
            for span, batch in reads.items()
        }

    def roster_averages(self, team_key: str, average: Average) -> dict[str, YahooLine]:
        """The averages over `average` of every player a team holds, by key: one read."""
        raw = self._responses.raw(paths.roster_averages(team_key, average))
        players = readable("roster", lambda: player_list(parse(raw)["fantasy_content"]["team"]["roster"]))
        return {p.player_key: p.line for p in players if p.coverage}

    def teams(self) -> list[YahooTeam]:
        """Every team in the league."""
        raw = self._responses.raw(paths.teams(self.league.league_key))
        return readable("team list", lambda: team_list(parse(raw)["fantasy_content"]["league"]))

    def standings(self) -> list[YahooTeam]:
        """Every team in the league, each with its place in the table: the teams list carries none.

        Raises:
            YahooCaptureMissingError: read from a browser sync that has not carried the table yet.
            YahooAPIError: Yahoo could not be reached, or answered unreadably.
        """
        raw = self._responses.raw(paths.standings(self.league.league_key))
        return readable("standings", lambda: team_list(parse(raw)["fantasy_content"]["league"]["standings"]))

    def season(self, team_key: str, weeks: list[int]) -> dict[int, Pairing | None]:
        """The team's head-to-head in each of `weeks`, None where it plays nobody.

        Every week's scoreboard in one batch, fetched concurrently where they are fetched at all.
        """
        raws = self._responses.many({str(week): self._scoreboard(week) for week in weeks})
        return {
            int(week): readable("scoreboard", lambda raw=raw: find_matchup(parse(raw), team_key))
            for week, raw in raws.items()
        }

    def settings(self) -> LeagueSettings:
        """How the league is scored, how often a team may add and where its playoffs start, as its settings say.

        Display-only stats (FGM/A beside FG%) are left out of the categories: they score nothing.

        Raises:
            YahooAuthError: the app is not authorized for Fantasy Sports.
            YahooAPIError: Yahoo could not be reached, or answered unreadably.
        """
        raw = self._responses.raw(paths.settings(self.league.league_key))
        return readable("league settings", lambda: league_settings(parse(raw)["fantasy_content"]["league"]))

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
        raw = self._responses.raw(paths.roster(team_key))
        return readable("roster", lambda: player_list(parse(raw)["fantasy_content"]["team"]["roster"]))

    def played_rosters(self, team_keys: list[str], week: int) -> dict[str, list[YahooPlayer]]:
        """Each team's roster as it ended a week already played, each player with his line over it, by team key.

        Slotted as the week's last day had them: a basketball lineup is set day
        by day, and Yahoo keeps no one lineup for the week. Fetched together.
        """
        raws = self._responses.many({key: paths.played_roster(key, week) for key in team_keys})
        return {
            key: readable("roster", lambda raw=raw: player_list(parse(raw)["fantasy_content"]["team"]["roster"]))
            for key, raw in raws.items()
        }

    def get_matchup(self, team_key: str) -> Matchup | None:
        """This week's head-to-head for the team, or None when it has none this week.

        None is an answer — between seasons, or a week the team does not play.

        Raises:
            YahooAuthError: the app is not authorized for Fantasy Sports.
            YahooAPIError: Yahoo could not be reached, or answered unreadably.
        """
        week = self.league.current_week
        found = self.pairing(team_key, week) if week else None
        if found is None:
            return None
        return Matchup(
            start=found.start,
            end=found.end,
            mine=found.mine,
            opponent=found.opponent,
            opponent_roster=self.roster(found.opponent.team_key),
        )

    def pairing(self, team_key: str, week: int) -> Pairing | None:
        """The team's head-to-head in any week of the season, or None where it plays nobody that week.

        Raises:
            YahooAuthError: the app is not authorized for Fantasy Sports.
            YahooAPIError: Yahoo could not be reached, or answered unreadably.
        """
        raw = self._responses.raw(self._scoreboard(week))
        return readable("scoreboard", lambda: find_matchup(parse(raw), team_key))


def once(players: Iterable[YahooPlayer]) -> list[YahooPlayer]:
    """`players` in order, each kept where he first appears."""
    seen: dict[str, YahooPlayer] = {}
    for player in players:
        seen.setdefault(player.player_key, player)
    return list(seen.values())


def leagues_in(raw: Any) -> list[YahooLeague]:
    """The leagues a login's league list names; none, where it plays in no game or no league."""
    return readable("league list", lambda: league_list(parse(raw)["fantasy_content"]["users"]["user"]["games"]))


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
        stats={_text(s, "stat_id"): _text(s, "value") for s in _items(_node(data, "player_stats", "stats"), "stat")},
        points=_text(data, "player_points", "total"),
        coverage=_text(data, "player_stats", "coverage_type"),
        image_url=full_size(_text(data, "image_url")),
        owner=_owner(_node(data, "ownership")),
    )


RESIZER = "https://"
"""Where the real image begins inside Yahoo's resizer URL, which serves a 46x60 thumbnail of it."""


def full_size(url: str) -> str:
    """A headshot at full size: Yahoo's resizer URL carries the original after it, from its last scheme on."""
    start = url.rfind(RESIZER)
    return url[start:] if start > 0 else url


OWNERSHIP = {"freeagents": "Free agent", "waivers": "Waivers"}
"""Yahoo's ownership types for a player nobody holds, in the words a chip shows."""


def _owner(ownership: Any) -> str:
    """Whose roster he is on, from his `ownership`: the team's name, 'Free agent' or 'Waivers'; empty without it."""
    if not isinstance(ownership, dict):
        return ""
    held = _text(ownership, "owner_team_name")
    return held or OWNERSHIP.get(_text(ownership, "ownership_type"), "")


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
        waiver_priority=_number(data, "waiver_priority"),
        faab_balance=_text(data, "faab_balance"),
    )


def _standing(data: Any) -> TeamStanding:
    return TeamStanding(
        rank=_number(data, "rank"),
        wins=_number(data, "outcome_totals", "wins"),
        losses=_number(data, "outcome_totals", "losses"),
        ties=_number(data, "outcome_totals", "ties"),
        points_for=_text(data, "points_for"),
        points_against=_text(data, "points_against"),
        playoff_seed=_number(data, "playoff_seed"),
    )


def find_matchup(scoreboard: Any, team_key: str) -> Pairing | None:
    """The week's dates and both sides of the team's matchup, its own first; None where it plays nobody."""
    matchups = scoreboard["fantasy_content"]["league"]["scoreboard"]["matchups"]
    for matchup in _items(matchups, "matchup"):
        sides = [_side(team) for team in _items(_node(matchup, "teams"), "team")[:2]]
        keys = [side.team_key for side in sides]
        if team_key in keys and len(sides) == 2:
            mine, opponent = sides if keys[0] == team_key else sides[::-1]
            return Pairing(
                _day(_value(matchup, "week_start")),
                _day(_value(matchup, "week_end")),
                mine,
                opponent,
                status=_text(matchup, "status"),
                winner=_text(matchup, "winner_team_key"),
                tied=_text(matchup, "is_tied") == "1",
                tied_categories=sum(
                    _text(won, "is_tied") == "1" for won in _items(_node(matchup, "stat_winners"), "stat_winner")
                ),
                playoffs=_text(matchup, "is_playoffs") == "1",
                consolation=_text(matchup, "is_consolation") == "1",
            )
    return None


def league_settings(league: Any) -> LeagueSettings:
    """A league's `settings`: its categories, its points weights, its weekly add limit and its bracket.

    A league with playoffs off has no bracket.
    """
    settings = _node(league, "settings")
    playoffs = _text(settings, "uses_playoff") == "1"
    return LeagueSettings(
        categories=category_list(league),
        positions=[_text(slot, "position") for slot in _items(_node(settings, "roster_positions"), "roster_position")],
        weights={
            _text(stat, "stat_id"): float(_text(stat, "value"))
            for stat in _items(_node(settings, "stat_modifiers", "stats"), "stat")
        },
        max_weekly_adds=_whole(settings, "max_weekly_adds"),
        playoff_start_week=_number(settings, "playoff_start_week") if playoffs else 0,
        playoff_teams=_number(settings, "num_playoff_teams") if playoffs else 0,
        multiweek_final=_text(settings, "has_multiweek_championship") == "1",
        weekly_lineups=_text(league, "roster_type") == "week",
        best_game=_text(league, "is_highscore") == "1",
    )


def category_list(league: Any) -> list[StatCategory]:
    """The scored categories under a league's `settings`; sort order 0 is Yahoo's "lower wins"."""
    stats = _node(league, "settings", "stat_categories", "stats")
    return [
        StatCategory(
            stat_id=_text(stat, "stat_id"),
            name=_text(stat, "display_name"),
            fewer_wins=_text(stat, "sort_order") == "0",
        )
        for stat in _items(stats, "stat")
        if _text(stat, "is_only_display_stat") != "1"
    ]


def _side(data: Any) -> MatchupSide:
    return MatchupSide(
        team_key=_text(data, "team_key"),
        name=_text(data, "name"),
        points=_text(data, "team_points", "total"),
        projected=_text(data, "team_projected_points", "total"),
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
    return YahooLeague(
        league_key=_text(data, "league_key"),
        name=_text(data, "name"),
        league_type=_text(data, "league_type"),
        current_week=_whole(data, "current_week"),
        start_week=_whole(data, "start_week"),
        end_week=_whole(data, "end_week"),
        scoring_type=_text(data, "scoring_type"),
    )


def _whole(data: Any, name: str) -> int | None:
    """A whole number the league carries — a week, a limit — or None where it carries none."""
    week = _value(data, name)
    return int(week) if week not in (None, "") else None
