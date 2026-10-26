"""Fantasy Premier League API client.

The official game at fantasy.premierleague.com serves everything read-only over
plain JSON: no key, no OAuth, no per-user token. One endpoint —
`bootstrap-static` — carries the whole player universe, the clubs and all 38
gameweeks in a single ~1MB response, so almost every question is answered from
one cached fetch.

The one endpoint that does need a logged-in session is `my-team/{id}`, which
holds pending state: the bank before this week's transfers, and the free
transfers remaining. It is deliberately not used. Reaching it means scraping a
session cookie out of a browser, which breaks whenever the login flow changes,
and everything it holds can be derived from the public history instead — see
`free_transfers`.
"""

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from tenacity import Retrying

from thefrontoffice.adapters.outbound.platforms.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLAPIError, FPLUnavailableError
from thefrontoffice.adapters.outbound.platforms.fpl.types import (
    MAX_FREE_TRANSFERS,
    POSITIONS,
    Chip,
    ChipPlay,
    Club,
    Entry,
    Fixture,
    Gameweek,
    GameweekResult,
    H2HMatch,
    LiveStat,
    MiniLeague,
    PastSeason,
    Pick,
    Player,
    Squad,
    TableRow,
)
from thefrontoffice.adapters.outbound.platforms.http import JsonApiClient
from thefrontoffice.adapters.outbound.platforms.retry import build_retry, is_transient
from thefrontoffice.adapters.outbound.platforms.timestamps import parse_utc
from thefrontoffice.config.settings import settings

logger = logging.getLogger(__name__)

BASE_URL = "https://fantasy.premierleague.com/api"

REQUEST_TIMEOUT_SECONDS = 30
RETRY_MAX_ATTEMPTS = 3

# TTLs from how quickly each endpoint actually moves. Prices change once a day
# just after 01:30 UTC; a squad changes only when its manager acts.
BOOTSTRAP_TTL = timedelta(hours=6)
FIXTURES_TTL = timedelta(hours=6)
ENTRY_TTL = timedelta(minutes=10)
HISTORY_TTL = timedelta(hours=1)
# The only figure here that moves while somebody is watching it.
LIVE_TTL = timedelta(minutes=2)
# A finished season cannot change, and the current one only moves when a match
# is played, so this is the slowest-moving thing the client reads.
PLAYER_HISTORY_TTL = timedelta(hours=12)

# The game returns 429 when a client is hammering it, same as Sleeper.
RETRYABLE_STATUS = frozenset({429})


def _is_retryable(exc: BaseException) -> bool:
    """Whether an FPL failure is transient. A 404 is a missing entry, forever."""
    return is_transient(exc, RETRYABLE_STATUS)


def _retry() -> Retrying:
    return build_retry(attempts=RETRY_MAX_ATTEMPTS, multiplier=2, min_wait=2, max_wait=20, predicate=_is_retryable)


def _order(value: Any) -> int | None:
    """A set-piece order, or None for a player not on them.

    Zero is not a rank, so it means the same as absent — and a `0` rendered
    beside "penalties" reads like first choice."""
    try:
        rank = int(value)
    except TypeError, ValueError:
        return None
    return rank or None


def _number(value: Any, default: float = 0.0) -> float:
    """Coerce a value the API sends as a string, or as null, to a float.

    Percentages, form and expected goals all arrive quoted, and any of them can
    be null for a player who has not featured.
    """
    try:
        return float(value)
    except TypeError, ValueError:
        return default


def free_transfers(history: list[GameweekResult], upcoming: int) -> int:
    """How many free transfers are available going into gameweek `upcoming`.

    The public API does not expose this — only `my-team`, which needs a login —
    but it is fully determined by the rules and by transfers already made. One
    is earned per gameweek, unused ones roll over, and the total is capped.

    Falls back to a single transfer when the history is missing, which is the
    floor: it is never wrong in the manager's favor.
    """
    played = {row.event: row for row in history}
    available = 1
    for event in range(1, upcoming):
        row = played.get(event)
        if row is None:
            continue
        available = min(MAX_FREE_TRANSFERS, max(1, available - row.transfers_made + 1))
    return available


class FPLSource(Protocol):
    """What a provider reads the Fantasy Premier League game through. See `SleeperNFLSource` in platforms/sleeper/client.py for why it exists."""

    def current_gameweek(self) -> Gameweek | None:
        """The gameweek being played, as the game itself marks it."""
        ...

    def get_chips(self) -> list[Chip]:
        """Every chip the game issues this season, with the window for each."""
        ...

    def get_chips_played(self, entry_id: int) -> list[ChipPlay]:
        """The chips this manager has already spent, and when."""
        ...

    def get_clubs(self) -> dict[str, Club]:
        """Abbreviation -> the club in full, keyed the way a player names it."""
        ...

    def get_entry(self, entry_id: int) -> Entry:
        """A manager's team, with the mini-leagues they are in."""
        ...

    def get_fixtures(self, gameweek: int) -> list[Fixture]:
        """Every match in one gameweek, with both difficulty ratings."""
        ...

    def get_gameweeks(self) -> list[Gameweek]: ...

    def get_h2h_match(self, league_id: int, entry_id: int, gameweek: int) -> H2HMatch | None:
        """The tie this entry is in for `gameweek`, if there is one."""
        ...

    def get_h2h_season(self, league_id: int, entry_id: int) -> dict[int, H2HMatch]:
        """Every tie this entry has in the league, keyed by gameweek."""
        ...

    def get_history(self, entry_id: int) -> list[GameweekResult]:
        """Every gameweek this manager has played, in order."""
        ...

    def get_live(self, gameweek: int) -> dict[int, LiveStat]:
        """What every player has done in the gameweek being played."""
        ...

    def get_past_seasons(self, element_id: int) -> list[PastSeason]:
        """Every finished season this player has a record for, oldest first."""
        ...

    def get_players(self) -> dict[int, Player]:
        """Every player in the game, keyed by element id."""
        ...

    def get_squad(self, entry_id: int, gameweek: int) -> Squad:
        """The fifteen a manager fielded in `gameweek`."""
        ...

    def get_standings(self, league_id: int, is_h2h: bool) -> list[TableRow]:
        """The league table. The two formats are different endpoints entirely."""
        ...

    def upcoming_gameweek(self, now: datetime | None = None) -> Gameweek:
        """The gameweek a manager can still act on."""
        ...


class FPLClient:
    """Read-only access to the Fantasy Premier League game."""

    def __init__(self, cache: JsonDiskCache | None = None, session: Any = None) -> None:
        self._api = JsonApiClient(
            name="FPL",
            cache=cache or JsonDiskCache(Path(settings.fpl_cache_dir)),
            retry=lambda: _retry(),
            error=FPLAPIError,
            unavailable=FPLUnavailableError,
            session=session,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        self._bootstrap: dict[str, Any] | None = None

    # ── the one big payload ─────────────────────────────────────────

    def _get_bootstrap(self) -> dict[str, Any]:
        """Players, clubs and gameweeks in one response, memoised per instance.

        Held in memory as well as on disk because a single report reads it four
        or five times, and re-parsing a megabyte of JSON each time is pure waste.
        """
        if self._bootstrap is None:
            data = self._api.cached("bootstrap", f"{BASE_URL}/bootstrap-static/", BOOTSTRAP_TTL)
            if not isinstance(data, dict) or not data.get("elements"):
                raise FPLAPIError("FPL returned no player data.")
            self._bootstrap = data
        return self._bootstrap

    def get_teams(self) -> dict[int, str]:
        """Club id -> three-letter abbreviation."""
        return {int(t["id"]): str(t["short_name"]) for t in self._get_bootstrap()["teams"]}

    def get_clubs(self) -> dict[str, Club]:
        """Abbreviation -> the club in full, keyed the way a player names it.

        Keyed on `short_name` rather than id because that is what `Player.team`
        carries: a caller holding a player has the abbreviation, not the id.
        Read off the same bootstrap as everything else, so it costs nothing.
        """
        return {
            str(t["short_name"]): Club(
                short_name=str(t["short_name"]),
                name=str(t["name"]),
                code=int(t.get("code") or 0),
            )
            for t in self._get_bootstrap()["teams"]
        }

    def get_gameweeks(self) -> list[Gameweek]:
        return [
            Gameweek(
                id=int(e["id"]),
                name=str(e.get("name") or f"Gameweek {e['id']}"),
                deadline=parse_utc(str(e["deadline_time"])),
                is_current=bool(e.get("is_current")),
                is_next=bool(e.get("is_next")),
                finished=bool(e.get("finished")),
                average_score=int(e.get("average_entry_score") or 0),
            )
            for e in self._get_bootstrap()["events"]
        ]

    def upcoming_gameweek(self, now: datetime | None = None) -> Gameweek:
        """The gameweek a manager can still act on.

        Defined by the deadline rather than by the API's `is_next` flag: once a
        deadline passes, that gameweek's team is locked, so advice about it is
        advice about a decision already made. The final gameweek is returned
        once the season has run out of future deadlines.
        """
        moment = now or datetime.now(UTC)
        gameweeks = self.get_gameweeks()
        future = [gw for gw in gameweeks if gw.deadline > moment]
        if future:
            return min(future, key=lambda gw: gw.deadline)
        return max(gameweeks, key=lambda gw: gw.id)

    def current_gameweek(self) -> Gameweek | None:
        """The gameweek being played, as the game itself marks it.

        Distinct from `upcoming_gameweek`, and the distinction matters: on a
        Saturday in August the gameweek you can still act on is next week's,
        while the one being *played* — where points are landing right now — is
        this one. A week view that shows the next deadline is a week view
        showing a week nobody is watching.

        None before the season opens, when no gameweek is current yet.
        """
        return next((gw for gw in self.get_gameweeks() if gw.is_current), None)

    def get_live(self, gameweek: int) -> dict[int, LiveStat]:
        """What every player has done in the gameweek being played.

        Updated as matches are played, so it is the one thing on the page that
        moves on its own. Not from the catalog: `total_points` there is a season
        total, which is a different question from "how is my team doing".
        """
        data = self._api.cached(f"live_{gameweek}", f"{BASE_URL}/event/{gameweek}/live/", LIVE_TTL)
        live: dict[int, LiveStat] = {}
        for element in (data or {}).get("elements") or []:
            if element.get("id") is None:
                continue
            stats = element.get("stats") or {}
            live[int(element["id"])] = LiveStat(
                points=int(stats.get("total_points") or 0),
                minutes=int(stats.get("minutes") or 0),
            )
        return live

    def get_players(self) -> dict[int, Player]:
        """Every player in the game, keyed by element id."""
        teams = self.get_teams()
        players: dict[int, Player] = {}
        for e in self._get_bootstrap()["elements"]:
            element_id = int(e["id"])
            full_name = " ".join(filter(None, [e.get("first_name"), e.get("second_name")]))
            players[element_id] = Player(
                id=element_id,
                code=int(e.get("code") or 0),
                name=str(e.get("web_name") or full_name or element_id),
                full_name=full_name or str(e.get("web_name") or ""),
                position=POSITIONS.get(int(e.get("element_type") or 0), ""),
                team=teams.get(int(e.get("team") or 0), "???"),
                cost=int(e.get("now_cost") or 0),
                expected_points=_number(e.get("ep_next")),
                form=_number(e.get("form")),
                points_per_game=_number(e.get("points_per_game")),
                total_points=int(e.get("total_points") or 0),
                selected_by=_number(e.get("selected_by_percent")),
                status=str(e.get("status") or "a"),
                news=str(e.get("news") or ""),
                chance_of_playing=(
                    None if e.get("chance_of_playing_next_round") is None else int(e["chance_of_playing_next_round"])
                ),
                minutes=int(e.get("minutes") or 0),
                starts=int(e.get("starts") or 0),
                goals=int(e.get("goals_scored") or 0),
                assists=int(e.get("assists") or 0),
                clean_sheets=int(e.get("clean_sheets") or 0),
                goals_conceded=int(e.get("goals_conceded") or 0),
                saves=int(e.get("saves") or 0),
                bonus=int(e.get("bonus") or 0),
                bonus_points=int(e.get("bps") or 0),
                yellow_cards=int(e.get("yellow_cards") or 0),
                red_cards=int(e.get("red_cards") or 0),
                penalties_order=_order(e.get("penalties_order")),
                corners_order=_order(e.get("corners_and_indirect_freekicks_order")),
                freekicks_order=_order(e.get("direct_freekicks_order")),
                price_change=int(e.get("cost_change_event") or 0),
                transfers_in=int(e.get("transfers_in_event") or 0),
                transfers_out=int(e.get("transfers_out_event") or 0),
                expected_goals=_number(e.get("expected_goals")),
                expected_assists=_number(e.get("expected_assists")),
                expected_goal_involvements=_number(e.get("expected_goal_involvements")),
                expected_goals_conceded=_number(e.get("expected_goals_conceded")),
                ict_index=_number(e.get("ict_index")),
            )
        return players

    # ── one manager ─────────────────────────────────────────────────

    def get_entry(self, entry_id: int) -> Entry:
        """A manager's team, with the mini-leagues they are in.

        FPL has no public username lookup, so the entry id — the number in the
        URL of your own points page — is the only way in.
        """
        data = self._api.cached(f"entry_{entry_id}", f"{BASE_URL}/entry/{entry_id}/", ENTRY_TTL)
        if not isinstance(data, dict) or "id" not in data:
            raise FPLAPIError(f"No FPL entry with id {entry_id}.")
        leagues = data.get("leagues") or {}
        return Entry(
            entry_id=int(data["id"]),
            name=str(data.get("name") or f"Entry {entry_id}"),
            manager=" ".join(filter(None, [data.get("player_first_name"), data.get("player_last_name")])),
            overall_points=int(data.get("summary_overall_points") or 0),
            overall_rank=int(data.get("summary_overall_rank") or 0),
            current_event=int(data.get("current_event") or 0),
            # Both formats, because they are separate lists and a manager whose
            # only invitational league is head-to-head has nothing in the other.
            leagues=[
                MiniLeague(
                    id=int(lg["id"]),
                    name=str(lg.get("name") or lg["id"]),
                    rank=int(lg.get("entry_rank") or 0),
                    # Null for head-to-head, which ranks by match record rather
                    # than by position in a field.
                    rank_count=int(lg["rank_count"]) if lg.get("rank_count") else None,
                    # 'x' is an invitational league someone created; 's' is one
                    # of the game's own — Overall, your country, each gameweek.
                    is_private=str(lg.get("league_type") or "") == "x",
                    is_h2h=kind == "h2h",
                )
                for kind in ("classic", "h2h")
                for lg in (leagues.get(kind) or [])
                if lg.get("id") is not None
            ],
        )

    def get_squad(self, entry_id: int, gameweek: int) -> Squad:
        """The fifteen a manager fielded in `gameweek`.

        Only published once that gameweek's deadline has passed, which is why
        the scout reads the last completed gameweek and reasons forward.
        """
        data = self._api.cached(
            f"picks_{entry_id}_{gameweek}",
            f"{BASE_URL}/entry/{entry_id}/event/{gameweek}/picks/",
            ENTRY_TTL,
        )
        if not isinstance(data, dict) or not data.get("picks"):
            raise FPLAPIError(f"No FPL squad for entry {entry_id} in gameweek {gameweek}.")
        history = data.get("entry_history") or {}
        return Squad(
            gameweek=gameweek,
            picks=[
                Pick(
                    element=int(p["element"]),
                    position=int(p.get("position") or 0),
                    multiplier=int(p.get("multiplier") or 0),
                    is_captain=bool(p.get("is_captain")),
                    is_vice_captain=bool(p.get("is_vice_captain")),
                )
                for p in data["picks"]
            ],
            bank=int(history.get("bank") or 0),
            value=int(history.get("value") or 0),
            transfers_made=int(history.get("event_transfers") or 0),
            transfers_cost=int(history.get("event_transfers_cost") or 0),
            points_on_bench=int(history.get("points_on_bench") or 0),
            active_chip=str(data.get("active_chip") or ""),
        )

    def get_past_seasons(self, element_id: int) -> list[PastSeason]:
        """Every finished season this player has a record for, oldest first.

        A separate request per player rather than part of the catalog, which is
        why it is made only when someone actually opens one.
        """
        data = self._api.cached(
            f"player_history_{element_id}",
            f"{BASE_URL}/element-summary/{element_id}/",
            PLAYER_HISTORY_TTL,
        )
        return [
            PastSeason(
                season=str(row.get("season_name") or ""),
                total_points=int(row.get("total_points") or 0),
                minutes=int(row.get("minutes") or 0),
                starts=int(row.get("starts") or 0),
                goals=int(row.get("goals_scored") or 0),
                assists=int(row.get("assists") or 0),
                clean_sheets=int(row.get("clean_sheets") or 0),
                goals_conceded=int(row.get("goals_conceded") or 0),
                saves=int(row.get("saves") or 0),
                bonus=int(row.get("bonus") or 0),
                expected_goals=_number(row.get("expected_goals")),
                expected_assists=_number(row.get("expected_assists")),
                start_cost=int(row.get("start_cost") or 0),
                end_cost=int(row.get("end_cost") or 0),
            )
            for row in data.get("history_past") or []
        ]

    def get_history(self, entry_id: int) -> list[GameweekResult]:
        """Every gameweek this manager has played, in order."""
        data = self._api.cached(f"history_{entry_id}", f"{BASE_URL}/entry/{entry_id}/history/", HISTORY_TTL)
        rows = (data or {}).get("current") or []
        return [
            GameweekResult(
                event=int(row["event"]),
                points=int(row.get("points") or 0),
                transfers_made=int(row.get("event_transfers") or 0),
                transfers_cost=int(row.get("event_transfers_cost") or 0),
            )
            for row in rows
            if row.get("event") is not None
        ]

    def get_chips(self) -> list[Chip]:
        """Every chip the game issues this season, with the window for each.

        Published on the same bootstrap call everything else reads, so this
        costs nothing extra.
        """
        return [
            Chip(
                name=str(c.get("name") or ""),
                start_event=int(c.get("start_event") or 0),
                stop_event=int(c.get("stop_event") or 0),
            )
            for c in self._get_bootstrap().get("chips") or []
            if c.get("name")
        ]

    def get_chips_played(self, entry_id: int) -> list[ChipPlay]:
        """The chips this manager has already spent, and when."""
        data = self._api.cached(f"history_{entry_id}", f"{BASE_URL}/entry/{entry_id}/history/", HISTORY_TTL)
        return [
            ChipPlay(name=str(c.get("name") or ""), event=int(c.get("event") or 0))
            for c in (data or {}).get("chips") or []
            if c.get("name")
        ]

    def get_h2h_match(self, league_id: int, entry_id: int, gameweek: int) -> H2HMatch | None:
        """The tie this entry is in for `gameweek`, if there is one.

        Head-to-head leagues pair managers per gameweek, so the opponent is a
        property of the week rather than of the league. Returns None for a week
        with no tie — a bye, or a league that has not drawn its fixtures.
        """
        data = self._api.cached(
            f"h2h_{league_id}_{gameweek}",
            f"{BASE_URL}/leagues-h2h-matches/league/{league_id}/?event={gameweek}",
            ENTRY_TTL,
        )
        for match in (data or {}).get("results") or []:
            for mine, theirs in (("1", "2"), ("2", "1")):
                if match.get(f"entry_{mine}_entry") == entry_id and match.get(f"entry_{theirs}_entry"):
                    return H2HMatch(
                        opponent_entry=int(match[f"entry_{theirs}_entry"]),
                        opponent_name=str(match.get(f"entry_{theirs}_name") or "Opponent"),
                        my_points=int(match.get(f"entry_{mine}_points") or 0),
                        opponent_points=int(match.get(f"entry_{theirs}_points") or 0),
                    )
        return None

    def get_h2h_season(self, league_id: int, entry_id: int) -> dict[int, H2HMatch]:
        """Every tie this entry has in the league, keyed by gameweek.

        One request for the whole season rather than one per gameweek: FPL
        returns the league's full fixture list already paginated by 50, and a
        38-week season in a small league fits in the first page.
        """
        data = self._api.cached(
            f"h2h_season_{league_id}",
            f"{BASE_URL}/leagues-h2h-matches/league/{league_id}/",
            ENTRY_TTL,
        )
        season: dict[int, H2HMatch] = {}
        for match in (data or {}).get("results") or []:
            event = match.get("event")
            if event is None:
                continue
            for mine, theirs in (("1", "2"), ("2", "1")):
                if match.get(f"entry_{mine}_entry") == entry_id and match.get(f"entry_{theirs}_entry"):
                    season[int(event)] = H2HMatch(
                        opponent_entry=int(match[f"entry_{theirs}_entry"]),
                        opponent_name=str(match.get(f"entry_{theirs}_name") or "Opponent"),
                        my_points=int(match.get(f"entry_{mine}_points") or 0),
                        opponent_points=int(match.get(f"entry_{theirs}_points") or 0),
                    )
        return season

    def get_standings(self, league_id: int, is_h2h: bool) -> list[TableRow]:
        """The league table. The two formats are different endpoints entirely."""
        kind = "leagues-h2h" if is_h2h else "leagues-classic"
        data = self._api.cached(
            f"standings_{kind}_{league_id}",
            f"{BASE_URL}/{kind}/{league_id}/standings/",
            ENTRY_TTL,
        )
        return [
            TableRow(
                rank=int(row.get("rank") or 0),
                entry=int(row.get("entry") or 0),
                entry_name=str(row.get("entry_name") or ""),
                manager=str(row.get("player_name") or ""),
                total=int(row.get("total") or 0),
                played=int(row.get("matches_played") or 0),
                won=int(row.get("matches_won") or 0),
                drawn=int(row.get("matches_drawn") or 0),
                lost=int(row.get("matches_lost") or 0),
                points_for=int(row.get("points_for") or 0),
            )
            for row in ((data or {}).get("standings") or {}).get("results") or []
        ]

    # ── fixtures ────────────────────────────────────────────────────

    def get_fixtures(self, gameweek: int) -> list[Fixture]:
        """Every match in one gameweek, with both difficulty ratings."""
        teams = self.get_teams()
        data = self._api.cached(f"fixtures_{gameweek}", f"{BASE_URL}/fixtures/?event={gameweek}", FIXTURES_TTL)
        return [
            Fixture(
                event=None if f.get("event") is None else int(f["event"]),
                home=teams.get(int(f.get("team_h") or 0), "???"),
                away=teams.get(int(f.get("team_a") or 0), "???"),
                home_difficulty=int(f.get("team_h_difficulty") or 0),
                away_difficulty=int(f.get("team_a_difficulty") or 0),
                kickoff=parse_utc(str(f["kickoff_time"])) if f.get("kickoff_time") else None,
            )
            for f in data or []
        ]
