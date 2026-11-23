"""Yahoo read from what a browser captured of it, while Yahoo's API refuses this app.

Yahoo reviews each application before its Fantasy API answers it, and until
then every request is a 403. Yahoo's own pages read the same data from a
read-only host with the person's session cookie. A bookmark run on one of those
pages fetches what this plans, with that session, and hands the bodies back;
they are stored under the same keys the reader looks them up by, so the reader
cannot tell a captured response from a fetched one.

Undocumented and temporary: the host is Yahoo's frontend's, and may change
without notice. Nothing of the session reaches this side — only response bodies.
"""

import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from xml.sax.saxutils import escape

from thefrontoffice.adapters.outbound.cache import DiskCache
from thefrontoffice.adapters.outbound.platforms.yahoo import paths
from thefrontoffice.adapters.outbound.platforms.yahoo.client import (
    WAIVERS,
    find_matchup,
    leagues_in,
    parse,
    player_list,
    readable,
    team_list,
)
from thefrontoffice.adapters.outbound.platforms.yahoo.errors import YahooAPIError, YahooCaptureMissingError
from thefrontoffice.adapters.outbound.platforms.yahoo.paths import YahooRead
from thefrontoffice.adapters.outbound.platforms.yahoo.session import SessionState
from thefrontoffice.adapters.outbound.platforms.yahoo.types import Timeframe, YahooLeague, YahooPlayer, YahooTeam
from thefrontoffice.domain.errors import InvalidRequestError
from thefrontoffice.domain.models import (
    Capture,
    CapturedResponse,
    CapturePlan,
    CaptureReceipt,
    CaptureStatus,
    CaptureStep,
)

logger = logging.getLogger(__name__)

CAPTURE_TTL = timedelta(days=30)
"""How long a captured response stands in for Yahoo. Long, because nothing
refreshes it but another sync; Settings says how old it is."""

SYNCED = "capture"
"""The entry whose age is when a sync last stored anything. No Yahoo path has this shape."""


@dataclass(frozen=True)
class YahooGame:
    """What a competition reads of one Yahoo game, so a capture plans exactly that and no more.

    The provider reads Yahoo with these same values, so the two cannot ask for
    different pages of players.
    """

    code: str
    """Yahoo's game code: 'nba'."""

    season: Callable[[], int]
    """The season being played, as the provider finds its leagues by."""

    available: Mapping[Timeframe, int]
    """How deep the wire is read under each of Yahoo's rankings."""

    leaders: Mapping[str, str]
    """The stat ids the free-agent scout ranks by, keyed as it names them."""

    per_stat: int
    """How many leaders it reads per stat."""


class YahooCapture:
    """Plans a browser sync, stores what it hands over, and answers the reader from it."""

    def __init__(
        self,
        cache: DiskCache,
        *,
        games: Sequence[YahooGame],
        active: bool,
        session: SessionState | None = None,
    ) -> None:
        """
        Args:
            cache: the same cache the live reader keeps Yahoo's responses in.
            games: what each competition on Yahoo reads.
            active: whether the app reads Yahoo from here rather than its API.
            session: how reading with the session cookie is going, where the app reads Yahoo that way.
        """
        self._cache = cache
        self._games = tuple(games)
        self._active = active
        self._session = session

    # ── answering the reader ─────────────────────────────────────────────

    def _stored(self, read: YahooRead) -> str | None:
        hit = self._cache.lookup(read.path, CAPTURE_TTL)
        return hit.value if hit is not None else None

    def raw(self, read: YahooRead) -> str:
        """The captured response to `read`; a lookup by key or name is answered from what the league's captures name.

        Raises:
            YahooCaptureMissingError: no sync carried it, or the one that did is too old to stand in for Yahoo.
        """
        stored = self._stored(read)
        if stored is not None:
            return stored
        if read.lookup:
            return self._lookup(read)
        raise self._missing(read.path)

    def many(self, reads: Mapping[str, YahooRead]) -> dict[str, str]:
        return {name: self.raw(read) for name, read in reads.items()}

    def find_leagues(self, game_code: str, season: int) -> list[YahooLeague]:
        """Every league the captured league list names for one game and season.

        Raises:
            YahooCaptureMissingError: no sync has carried that list.
        """
        return leagues_in(self.raw(paths.leagues(game_code, season)))

    def ensure_captured(self) -> None:
        """Require a sync recent enough to stand in for Yahoo. Cheap: one file.

        Raises:
            YahooCaptureMissingError: there has been none, or the last is too old.
        """
        synced = self._cache.lookup(SYNCED, timedelta.max)
        if synced is None:
            raise YahooCaptureMissingError()
        if datetime.now(UTC) - synced.stored_at > CAPTURE_TTL:
            raise YahooCaptureMissingError(
                f"The last Yahoo sync is over {CAPTURE_TTL.days} days old. Run the sync bookmark again."
            )

    def _missing(self, path: str) -> YahooCaptureMissingError:
        if self._cache.lookup(SYNCED, timedelta.max) is None:
            return YahooCaptureMissingError()
        return YahooCaptureMissingError(
            f"The last Yahoo sync has no current copy of {path}. Run the sync bookmark again."
        )

    def _lookup(self, read: YahooRead) -> str:
        """A players response for a lookup no plan could make, built from every player the league's captures name.

        Yahoo matches a search as a substring of the name, so this does too. A
        player the captures never named is left out, as Yahoo leaves out a key
        it does not know.
        """
        found = self._game_league(read.league)
        if found is None:
            raise self._missing(read.path)
        known = self._players(*found)
        if read.player_keys:
            chosen = [known[key] for key in read.player_keys if key in known]
        else:
            wanted = read.search.casefold()
            chosen = [player for player in known.values() if wanted in player.name.casefold()]
        return _players_xml(chosen)

    def _players(self, game: YahooGame, league: YahooLeague) -> dict[str, YahooPlayer]:
        """Every player the league's captured rosters and player pages name, by key, off any roster slot."""
        known: dict[str, YahooPlayer] = {}
        for read in self._reads(game, league):
            raw = self._stored(read)
            if raw is None or not (read.query.startswith("players;") or read.query.endswith("/roster")):
                continue
            content = parse(raw)["fantasy_content"]
            parent = content["team"]["roster"] if "team" in content else content["league"]
            for player in readable("player list", lambda parent=parent: player_list(parent)):
                known.setdefault(player.player_key, replace(player, slot=""))
        return known

    # ── planning ─────────────────────────────────────────────────────────

    def _leagues(self, game: YahooGame) -> list[YahooLeague]:
        """The game's leagues this season as last captured; none before the list has been."""
        raw = self._stored(paths.leagues(game.code, game.season()))
        return leagues_in(raw) if raw is not None else []

    def _game_league(self, league_key: str) -> tuple[YahooGame, YahooLeague] | None:
        return next(
            (
                (game, league)
                for game in self._games
                for league in self._leagues(game)
                if league.league_key == league_key
            ),
            None,
        )

    def _teams(self, league_key: str) -> list[YahooTeam]:
        raw = self._stored(paths.teams(league_key))
        return readable("team list", lambda: team_list(parse(raw)["fantasy_content"]["league"])) if raw else []

    def _reads(self, game: YahooGame, league: YahooLeague) -> list[YahooRead]:
        """Everything the app reads of one league that can be planned from what is held.

        The scoreboard of every week of the season, since any can be opened, and
        the league's moves, which a player's history reads. A
        roster for every team the held team list names, and its players' recent
        averages, which the first sync of a league has to learn before it can ask. Both rosters of your matchup in
        each week played, as it ended, once that week's scoreboard is held and
        until they are.
        """
        key = league.league_key
        reads = [
            paths.settings(key),
            paths.teams(key),
            paths.standings(key),
            paths.transactions(key),
            *(read for sort_type, depth in game.available.items() for read in paths.available(key, depth, sort_type)),
            *paths.leaders(key, game.leaders, game.per_stat).values(),
        ]
        current = league.current_week
        if current:
            reads.extend(
                paths.scoreboard(key, week, current) for week in range(league.first_week, league.last_week(current) + 1)
            )
        for team in self._teams(key):
            reads.extend((paths.roster(team.team_key), paths.roster_averages(team.team_key, paths.RECENT_AVERAGE)))
        reads.extend(read for read in self._played(league) if self._stored(read) is None)
        return reads

    def _played(self, league: YahooLeague) -> list[YahooRead]:
        """Both rosters of your matchup in each week played whose scoreboard is held, as they ended it."""
        mine = next((team.team_key for team in self._teams(league.league_key) if team.is_mine), None)
        if mine is None:
            return []
        reads = []
        for week in range(league.first_week, league.current_week or 0):
            raw = self._stored(paths.scoreboard(league.league_key, week))
            found = readable("scoreboard", lambda raw=raw: find_matchup(parse(raw), mine)) if raw else None
            if found is not None:
                reads.extend(paths.played_roster(side.team_key, week) for side in (found.mine, found.opponent))
        return reads

    def plan(self, leagues: Sequence[str]) -> CapturePlan:
        """Each game's league list, and whatever else each of `leagues` needs that is not held fresh.

        A league is planned only once its list has been captured, since that is
        where its weeks come from; a key the list does not name is ignored.
        Anything held within its own TTL is left out — a settled week, today's
        settings — so a sync asks Yahoo only for what has moved since the last.
        """
        return self._plan(leagues, held=lambda read: self._cache.lookup(read.path, read.ttl) is not None)

    def _plan(self, leagues: Sequence[str], held: Callable[[YahooRead], bool] = lambda _: False) -> CapturePlan:
        steps = [CaptureStep(path=paths.leagues(game.code, game.season()).path) for game in self._games]
        wanted = set(leagues)
        for game in self._games:
            for league in self._leagues(game):
                if league.league_key in wanted:
                    reads = [read for read in self._reads(game, league) if not held(read)]
                    steps.extend(CaptureStep(path=read.path, league=league.league_key) for read in reads)
        return CapturePlan(base=paths.FRONTEND, probe=paths.PROFILE, steps=steps)

    # ── storing ──────────────────────────────────────────────────────────

    def ingest(self, capture: Capture) -> CaptureReceipt:
        """Store each response a plan would ask for, under the key the reader looks it up by.

        League lists first, since they decide what else a plan holds. A
        response no plan asks for, one Yahoo refused, or one that is not
        readable XML is refused and said so; nothing else is stored, and
        nothing of the request beyond the bodies is kept.

        Raises:
            InvalidRequestError: the browser was not signed in to Yahoo.
        """
        if capture.profile.status != 200:
            raise InvalidRequestError(
                [f"Yahoo was not signed in when this was fetched (its profile answered {capture.profile.status})."]
            )
        lists = {step.path for step in self._plan(()).steps}
        first = [r for r in capture.responses if r.path in lists]
        rest = [r for r in capture.responses if r.path not in lists]

        receipt = CaptureReceipt(stored=0)
        for response in first:
            self._store(response, "", receipt)
        # Everything a plan could have asked for, fresh or not: what was fresh when planned may not be now.
        planned = {step.path: step.league for step in self._plan(self._known_keys()).steps}
        for response in rest:
            if response.path in planned:
                self._store(response, planned[response.path], receipt)
            else:
                receipt.errors.append(f"{response.path}: not something the app asked for")

        if receipt.stored:
            self._cache.set(SYNCED, receipt.stored)
        receipt.leagues.sort()
        logger.info(f"Yahoo capture stored {receipt.stored} responses, refused {len(receipt.errors)}")
        return receipt

    def _known_keys(self) -> list[str]:
        return [league.league_key for game in self._games for league in self._leagues(game)]

    def _store(self, response: CapturedResponse, league: str, receipt: CaptureReceipt) -> None:
        if response.status != 200:
            receipt.errors.append(f"{response.path}: Yahoo answered {response.status}")
            return
        try:
            parse(response.body)
        except YahooAPIError as e:
            receipt.errors.append(f"{response.path}: {e}")
            return
        self._cache.set(response.path, response.body)
        receipt.stored += 1
        if league and league not in receipt.leagues:
            receipt.leagues.append(league)

    def status(self) -> CaptureStatus:
        synced = self._cache.lookup(SYNCED, timedelta.max)
        return CaptureStatus(
            active=self._active,
            synced_at=synced.stored_at if synced else None,
            leagues=[league.name for game in self._games for league in self._leagues(game)],
            session=self._session.status() if self._session is not None else None,
        )


def _players_xml(players: list[YahooPlayer]) -> str:
    """A league's players response, as Yahoo would serve one listing `players`: on waivers, until when."""
    rows = "".join(
        f"<player><player_key>{escape(p.player_key)}</player_key><name><full>{escape(p.name)}</full></name>"
        f"<display_position>{escape(p.position)}</display_position>"
        f"<editorial_team_abbr>{escape(p.team)}</editorial_team_abbr><status>{escape(p.status)}</status>"
        f"<injury_note>{escape(p.injury_note)}</injury_note>{_ownership(p)}</player>"
        for p in players
    )
    return f"<fantasy_content><league><players>{rows}</players></league></fantasy_content>"


def _ownership(player: YahooPlayer) -> str:
    """His ownership as Yahoo writes it, where a page had him on waivers; nothing otherwise, as a roster carries none."""
    if player.waiver_date is None:
        return ""
    return (
        f"<ownership><ownership_type>{WAIVERS}</ownership_type>"
        f"<waiver_date>{player.waiver_date.isoformat()}</waiver_date></ownership>"
    )
