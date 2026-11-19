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
`free_transfers` in `premier_league/rules.py`.
"""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from thefrontoffice.adapters.outbound.cache import DiskCache
from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLAPIError, FPLUnavailableError
from thefrontoffice.adapters.outbound.platforms.fpl.types import (
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
    PlayerGame,
    PlayerSummary,
    Squad,
    TableRow,
    TransferMade,
)
from thefrontoffice.adapters.outbound.platforms.http import Batch, JsonApiClient
from thefrontoffice.adapters.outbound.platforms.retry import RetryPolicy
from thefrontoffice.adapters.outbound.platforms.timestamps import parse_utc

logger = logging.getLogger(__name__)

BASE_URL = "https://fantasy.premierleague.com/api"

REQUEST_TIMEOUT_SECONDS = 30

# TTLs from how quickly each endpoint actually moves. Prices change once a day
# just after 01:30 UTC; a squad changes only when its manager acts.
BOOTSTRAP_TTL = timedelta(hours=6)
# Short, because a fixture says whether its match has kicked off or finished, which is what
# a lineup row reads to know whether its number is a guess, a live score or a final one.
FIXTURES_TTL = timedelta(minutes=2)
ENTRY_TTL = timedelta(minutes=10)
HISTORY_TTL = timedelta(hours=1)
# The only figure here that moves while somebody is watching it.
LIVE_TTL = timedelta(minutes=2)
# A player's own page: the seasons before cannot change, but this season's log gains a
# row with every match he plays, and a log a match behind is the one thing it must not be.
PLAYER_SUMMARY_TTL = timedelta(hours=1)
# The season's fixture list moves only when a match is moved: what the weeks ahead are read from.
SEASON_FIXTURES_TTL = timedelta(hours=1)


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


def _when(value: Any) -> datetime | None:
    """An instant the API may leave null or empty, as aware UTC."""
    return parse_utc(str(value)) if value else None


def _price_tonight(projections: Any) -> float | None:
    """Where FPL projects a player's price progress after the next overnight update: its offset-0 projection."""
    for row in projections or []:
        if isinstance(row, dict) and row.get("offset") == 0 and row.get("projected_percent") is not None:
            return _number(row["projected_percent"])
    return None


def _club(short_names: dict[int, str], club_id: Any) -> str:
    """The abbreviation for a club id, refusing one the bootstrap does not list.

    Every player and fixture names a club the same payload lists, so a miss is
    a payload this client does not understand rather than a club to guess at.
    """
    try:
        return short_names[int(club_id)]
    except (KeyError, TypeError, ValueError) as e:
        logger.error(f"FPL named a club it does not list: {club_id!r}")
        raise FPLAPIError(f"FPL named a club it does not list: {club_id!r}.") from e


def _tie(match: dict[str, Any], entry_id: int) -> H2HMatch | None:
    """One head-to-head result read from this entry's side, or None when it is not in it.

    FPL puts an entry in slot 1 or slot 2 with no regard for who is asking.
    """
    for mine, theirs in (("1", "2"), ("2", "1")):
        if match.get(f"entry_{mine}_entry") == entry_id and match.get(f"entry_{theirs}_entry"):
            return H2HMatch(
                opponent_entry=int(match[f"entry_{theirs}_entry"]),
                opponent_name=str(match.get(f"entry_{theirs}_name") or "Opponent"),
                my_points=int(match.get(f"entry_{mine}_points") or 0),
                opponent_points=int(match.get(f"entry_{theirs}_points") or 0),
            )
    return None


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

    def get_player_summaries(self, element_ids: Sequence[int]) -> Batch[int, PlayerSummary]:
        """Each player's season match by match and the seasons before; why each that would not load did not."""
        ...

    def get_players(self) -> dict[int, Player]:
        """Every player in the game, keyed by element id."""
        ...

    def get_season_fixtures(self) -> list[Fixture]:
        """Every match of the season, in one list: the weeks ahead read from it."""
        ...

    def get_squad(self, entry_id: int, gameweek: int) -> Squad:
        """The fifteen a manager fielded in `gameweek`."""
        ...

    def get_standings(self, league_id: int, is_h2h: bool) -> list[TableRow]:
        """The league table. The two formats are different endpoints entirely."""
        ...

    def get_transfers(self, entry_id: int) -> list[TransferMade]:
        """Every transfer this manager has made this season, newest first."""
        ...

    def upcoming_gameweek(self, now: datetime | None = None) -> Gameweek:
        """The gameweek a manager can still act on."""
        ...


class FPLClient:
    """Read-only access to the Fantasy Premier League game."""

    def __init__(self, *, cache: DiskCache, retry: RetryPolicy, session: Any = None) -> None:
        self._api = JsonApiClient(
            name="FPL",
            cache=cache,
            retry=retry,
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

    def _short_names(self) -> dict[int, str]:
        """Club id -> the three letters a player and a fixture are named by."""
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
        short_names = self._short_names()
        players: dict[int, Player] = {}
        for e in self._get_bootstrap()["elements"]:
            element_id = int(e["id"])
            full_name = " ".join(filter(None, [e.get("first_name"), e.get("second_name")]))
            players[element_id] = Player(
                id=element_id,
                code=int(e.get("code") or 0),
                # `cost_change_start` is how far the price has moved since the season opened.
                start_cost=(
                    None
                    if e.get("now_cost") is None or e.get("cost_change_start") is None
                    else int(e["now_cost"]) - int(e["cost_change_start"])
                ),
                name=str(e.get("web_name") or full_name or element_id),
                full_name=full_name or str(e.get("web_name") or ""),
                position=POSITIONS.get(int(e.get("element_type") or 0), ""),
                team=_club(short_names, e.get("team")),
                cost=int(e.get("now_cost") or 0),
                expected_points=_number(e.get("ep_next")),
                expected_this=_number(e.get("ep_this")),
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
                news_added=_when(e.get("news_added")),
                defensive_contribution=int(e.get("defensive_contribution") or 0),
                defensive_contribution_per_90=_number(e.get("defensive_contribution_per_90")),
                price_progress=_number(e.get("price_change_percent")),
                price_tonight=_price_tonight(e.get("price_change_projections")),
                price_locked_until=_when(e.get("price_change_locked_until")),
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

    def get_player_summaries(self, element_ids: Sequence[int]) -> Batch[int, PlayerSummary]:
        """Each player's season match by match and the seasons before; why each that would not load did not.

        A request per player rather than part of the catalog, made only for the
        players a page names — the one opened, or the two squads a forecast plays —
        and in parallel. A promoted club's signing has no past seasons at all.
        """
        short_names = self._short_names()
        keys = {pid: f"player_summary_{pid}" for pid in dict.fromkeys(element_ids)}
        batch = self._api.cached_many(
            {key: f"{BASE_URL}/element-summary/{pid}/" for pid, key in keys.items()},
            PLAYER_SUMMARY_TTL,
            keep=_summary_kept,
        )
        rekeyed = batch.rekeyed(keys)
        summaries: Batch[int, PlayerSummary] = Batch(failures=dict(rekeyed.failures))
        for pid, data in rekeyed.values.items():
            summaries.values[pid] = PlayerSummary(
                games=[_game(row, short_names) for row in data.get("history") or [] if row.get("round")],
                past=[_past_season(row) for row in data.get("history_past") or []],
            )
        return summaries

    def _history(self, entry_id: int) -> dict[str, Any]:
        """The one payload behind a manager's gameweeks and the chips they spent."""
        return self._api.cached(f"history_{entry_id}", f"{BASE_URL}/entry/{entry_id}/history/", HISTORY_TTL) or {}

    def get_history(self, entry_id: int) -> list[GameweekResult]:
        """Every gameweek this manager has played, in order."""
        rows = self._history(entry_id).get("current") or []
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

    def get_transfers(self, entry_id: int) -> list[TransferMade]:
        """Every transfer this manager has made this season, newest first.

        Public, unlike the pending state behind `my-team`, and it carries the price each
        player was bought at — which is what the game's selling price is figured from.
        A Wildcard's or a Free Hit's transfers are listed like any other.
        """
        data = self._api.cached(f"transfers_{entry_id}", f"{BASE_URL}/entry/{entry_id}/transfers/", HISTORY_TTL)
        return [
            TransferMade(
                element_in=int(row["element_in"]),
                element_in_cost=int(row.get("element_in_cost") or 0),
                element_out=int(row["element_out"]),
                event=int(row["event"]),
                time=parse_utc(str(row["time"])),
            )
            for row in data or []
            if row.get("element_in") is not None
            and row.get("element_out") is not None
            and row.get("event") is not None
            and row.get("time")
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
        return [
            ChipPlay(name=str(c.get("name") or ""), event=int(c.get("event") or 0))
            for c in self._history(entry_id).get("chips") or []
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
        ties = (_tie(match, entry_id) for match in (data or {}).get("results") or [])
        return next((tie for tie in ties if tie), None)

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
            if match.get("event") is not None and (tie := _tie(match, entry_id)):
                season[int(match["event"])] = tie
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
        data = self._api.cached(f"fixtures_{gameweek}", f"{BASE_URL}/fixtures/?event={gameweek}", FIXTURES_TTL)
        return self._fixtures(data)

    def get_season_fixtures(self) -> list[Fixture]:
        """Every match of the season, in one list: the weeks ahead read from it.

        One request for all 380 rather than one per gameweek, trimmed of the
        per-match player stats that are most of its size. A match not yet given
        a gameweek — postponed, waiting on a cup run — has none.
        """
        data = self._api.cached("fixtures_season", f"{BASE_URL}/fixtures/", SEASON_FIXTURES_TTL, keep=_fixtures_kept)
        return self._fixtures(data)

    def _fixtures(self, data: Any) -> list[Fixture]:
        short_names = self._short_names()
        return [
            Fixture(
                event=None if f.get("event") is None else int(f["event"]),
                home=_club(short_names, f.get("team_h")),
                away=_club(short_names, f.get("team_a")),
                home_difficulty=int(f.get("team_h_difficulty") or 0),
                away_difficulty=int(f.get("team_a_difficulty") or 0),
                kickoff=parse_utc(str(f["kickoff_time"])) if f.get("kickoff_time") else None,
                started=bool(f.get("started")),
                # Over once the whistle goes. `finished` waits for the bonus to be confirmed, which
                # can take days, and a row reading live for a match two days gone is the worse error.
                finished=bool(f.get("finished_provisional") or f.get("finished")),
                # Null until kickoff.
                home_score=int(f.get("team_h_score") or 0),
                away_score=int(f.get("team_a_score") or 0),
            )
            for f in data or []
        ]


_FIXTURE_FIELDS = (
    "event",
    "team_h",
    "team_a",
    "team_h_difficulty",
    "team_a_difficulty",
    "kickoff_time",
    "started",
    "finished",
    "finished_provisional",
    "team_h_score",
    "team_a_score",
)


def _fixtures_kept(raw: Any) -> list[dict[str, Any]]:
    """A fixture list without the per-match player stats, which no reader here reads."""
    return [{k: f.get(k) for k in _FIXTURE_FIELDS} for f in raw or [] if isinstance(f, dict)]


_GAME_FIELDS = (
    "round",
    "opponent_team",
    "was_home",
    "total_points",
    "minutes",
    "goals_scored",
    "assists",
    "clean_sheets",
    "goals_conceded",
    "saves",
    "bonus",
    "defensive_contribution",
    "expected_goals",
    "expected_assists",
)


def _summary_kept(raw: Any) -> dict[str, Any]:
    """A player's page without its upcoming fixtures — the season list has them — or the match fields left unread."""
    data = raw if isinstance(raw, dict) else {}
    return {
        "history": [{k: row.get(k) for k in _GAME_FIELDS} for row in data.get("history") or []],
        "history_past": data.get("history_past") or [],
    }


def _game(row: dict[str, Any], short_names: dict[int, str]) -> PlayerGame:
    return PlayerGame(
        event=int(row["round"]),
        opponent=_club(short_names, row.get("opponent_team")),
        home=bool(row.get("was_home")),
        points=int(row.get("total_points") or 0),
        minutes=int(row.get("minutes") or 0),
        goals=int(row.get("goals_scored") or 0),
        assists=int(row.get("assists") or 0),
        clean_sheets=int(row.get("clean_sheets") or 0),
        goals_conceded=int(row.get("goals_conceded") or 0),
        saves=int(row.get("saves") or 0),
        bonus=int(row.get("bonus") or 0),
        defensive_contribution=int(row.get("defensive_contribution") or 0),
        expected_goals=_number(row.get("expected_goals")),
        expected_assists=_number(row.get("expected_assists")),
    )


def _past_season(row: dict[str, Any]) -> PastSeason:
    return PastSeason(
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
        defensive_contribution=int(row.get("defensive_contribution") or 0),
    )
