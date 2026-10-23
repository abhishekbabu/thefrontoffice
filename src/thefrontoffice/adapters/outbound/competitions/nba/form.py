"""Recent form and remaining games, read from Sleeper.

Basketball reads its projections from Sleeper; this is the other half — what a
player has actually been doing lately, and how many games their club has left
inside the matchup period.

Form is per game rather than per week on purpose: a category league is won over
a matchup period, and "the last ten games" is a window a weekly bucket of three
or four cannot be cut at.
"""

import logging
from datetime import date, datetime
from typing import Literal, Protocol, TypedDict
from zoneinfo import ZoneInfo

from thefrontoffice.adapters.outbound.competitions.names import NameIndex
from thefrontoffice.adapters.outbound.platforms.sleeper.client import NBA, SleeperClient, SleeperNBASource
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog, ScheduledGame
from thefrontoffice.domain.errors import SleeperAPIError

logger = logging.getLogger(__name__)

PACIFIC = ZoneInfo("America/Los_Angeles")
"""The league schedules by Pacific, so a day boundary is decided there rather
than on whatever clock this happens to be running on."""

# Enough weeks that fifteen games are in reach for anyone playing regularly:
# clubs play three or four a week, so six covers about twenty.
FORM_WEEKS = 6

Window = Literal["last_5", "last_10", "last_15"]
"""A `PlayerStats` key: the averages over a player's last few games."""

WINDOWS: dict[int, Window] = {5: "last_5", 10: "last_10", 15: "last_15"}

# A basketball regular season runs 25 Sleeper weeks; week 26 comes back empty.
# Only used to reach back into the season just finished.
SEASON_WEEKS = 25


class NineCatStats(TypedDict):
    PTS: float
    REB: float
    AST: float
    STL: float
    BLK: float
    TOV: float
    FG3M: float
    FG_PCT: float
    FT_PCT: float


class PlayerStats(TypedDict, total=False):
    last_5: NineCatStats
    last_10: NineCatStats
    last_15: NineCatStats


def nine_cat(games: list[NBAGameLog]) -> NineCatStats:
    """Average a run of games into a nine-category line.

    Percentages come from summed makes and attempts rather than averaged
    per-game percentages: the two differ whenever attempts vary between games,
    which is exactly when the number matters.
    """
    n = len(games)
    total = lambda key: sum(g.get(key) for g in games)  # noqa: E731
    fga, fgm = total("fga"), total("fgm")
    fta, ftm = total("fta"), total("ftm")
    return NineCatStats(
        PTS=round(total("pts") / n, 1),
        REB=round(total("reb") / n, 1),
        AST=round(total("ast") / n, 1),
        STL=round(total("stl") / n, 1),
        BLK=round(total("blk") / n, 1),
        TOV=round(total("to") / n, 1),
        FG3M=round(total("tpm") / n, 1),
        FG_PCT=round(fgm / fga, 3) if fga else 0.0,
        FT_PCT=round(ftm / fta, 3) if fta else 0.0,
    )


class FormSource(Protocol):
    """What the basketball provider reads recent form and remaining games through.
    See `SleeperNBASource` for why it exists.
    """

    def get_player_stats(self, full_name: str) -> PlayerStats | None:
        """A player's last 5, 10 and 15 games, or nothing where there are none."""
        ...

    def get_remaining_games(self, team_abbr: str, start_date: date, end_date: date, now: datetime | None = None) -> int:
        """Count a club's not-yet-played games inside a matchup window."""
        ...

    def get_remaining_games_bulk(
        self, team_abbrs: list[str], start_date: date, end_date: date, now: datetime | None = None
    ) -> dict[str, int]:
        """One schedule load and one `now` for every club asked about."""
        ...


class SleeperNBAForm:
    """Recent form and remaining games for basketball.

    Loads each of the three things it reads once and keeps them: a report asks
    about every player on a roster and every club in a matchup, and refetching
    the catalog per question would be the whole cost of the page.
    """

    def __init__(self, client: SleeperNBASource | None = None, season: str | None = None) -> None:
        self.client = client or SleeperClient()
        self._season = season
        self._logs: dict[str, list[NBAGameLog]] | None = None
        self._by_name: NameIndex[str] | None = None
        self._schedule: dict[str, list[ScheduledGame]] | None = None

    # ── recent form ─────────────────────────────────────────────────

    def get_player_stats(self, full_name: str) -> PlayerStats | None:
        """A player's last 5, 10 and 15 games, or nothing where there are none.

        A window is reported only once enough games exist to fill it: five
        games averaged into a "last fifteen" is a different number wearing the
        same label.
        """
        player_id = self._name_index().lookup(full_name)
        if player_id is None:
            return None
        games = self._game_logs().get(player_id)
        if not games:
            return None

        stats = PlayerStats()
        for count, window in WINDOWS.items():
            if len(games) >= count:
                stats[window] = nine_cat(games[:count])
        return stats or None

    # ── remaining games ─────────────────────────────────────────────

    def get_remaining_games(self, team_abbr: str, start_date: date, end_date: date, now: datetime | None = None) -> int:
        """Count a club's not-yet-played games inside a matchup window.

        Two notions of time, kept apart the same way they always were: the
        window test compares date labels, which is what Yahoo's matchup dates
        also are, and the has-it-happened test is decided on the day in
        Pacific — the zone the league schedules by.

        Sleeper publishes a date and a status but no tip-off instant, so a game
        today counts only while its status still says it has not started, and a
        stale status on a past date cannot resurrect a played game.
        """
        today = self._today(now)
        return sum(
            1
            for game in self._team_schedule().get(team_abbr.upper(), [])
            if self._is_remaining(game, start_date, end_date, today)
        )

    def get_remaining_games_bulk(
        self, team_abbrs: list[str], start_date: date, end_date: date, now: datetime | None = None
    ) -> dict[str, int]:
        """One schedule load and one `now` for every club asked about."""
        moment = now or datetime.now(tz=PACIFIC)
        return {
            abbr.upper(): self.get_remaining_games(abbr, start_date, end_date, now=moment) for abbr in set(team_abbrs)
        }

    @staticmethod
    def _is_remaining(game: ScheduledGame, start: date, end: date, today: date) -> bool:
        played = _parse(game.date)
        if played is None or not (start <= played <= end):
            return False
        if played < today:
            return False
        # Today's game turns on the status; a future one is remaining whatever
        # a possibly-stale status says.
        return played > today or game.status == "pre_game"

    # ── loading, once ───────────────────────────────────────────────

    def _game_logs(self) -> dict[str, list[NBAGameLog]]:
        if self._logs is None:
            try:
                season, weeks = self._form_window()
                self._logs = self.client.get_nba_game_logs(season, weeks) if weeks else {}
            except SleeperAPIError as e:
                # Form is enrichment: a report without it is thinner, not wrong.
                logger.warning(f"Continuing without recent form: {e}")
                self._logs = {}
        return self._logs

    def _form_window(self) -> tuple[str, list[int]]:
        """Which season and weeks the last fifteen games could be in.

        Between seasons the last games a player played are last season's, and
        that is exactly what "their last ten" means to somebody drafting in
        October — so the window reaches back rather than reporting nothing.
        """
        if self._season is not None:
            return self._season, list(range(1, SEASON_WEEKS + 1))

        state = self.client.get_state(NBA)
        if state.week >= 1:
            return state.season, list(range(max(1, state.week - FORM_WEEKS + 1), state.week + 1))
        previous = str(int(state.season) - 1)
        return previous, list(range(SEASON_WEEKS - FORM_WEEKS + 1, SEASON_WEEKS + 1))

    def _name_index(self) -> NameIndex[str]:
        if self._by_name is None:
            index: NameIndex[str] = NameIndex()
            try:
                for player_id, meta in self.client.get_players(NBA).items():
                    if name := str(meta.get("name") or ""):
                        index.add(name, player_id)
            except SleeperAPIError as e:
                logger.warning(f"Continuing without the basketball catalog: {e}")
            self._by_name = index
        return self._by_name

    def _team_schedule(self) -> dict[str, list[ScheduledGame]]:
        if self._schedule is None:
            by_team: dict[str, list[ScheduledGame]] = {}
            try:
                for game in self.client.get_nba_schedule(self._schedule_season()):
                    for club in (game.home, game.away):
                        if club:
                            by_team.setdefault(club, []).append(game)
            except SleeperAPIError as e:
                logger.warning(f"Continuing without the basketball schedule: {e}")
            self._schedule = by_team
        return self._schedule

    def _schedule_season(self) -> str:
        """The season whose fixtures are still to be played, which is the one
        the game itself is pointing at even while it has not started."""
        return self._season or self.client.get_state(NBA).season

    @staticmethod
    def _today(now: datetime | None) -> date:
        moment = now or datetime.now(tz=PACIFIC)
        return moment.astimezone(PACIFIC).date()


def _parse(iso: str) -> date | None:
    try:
        return date.fromisoformat(iso[:10])
    except ValueError, TypeError:
        return None
