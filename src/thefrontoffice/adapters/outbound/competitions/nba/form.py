"""Recent form, read from Sleeper.

Basketball reads its projections from Sleeper; this is the other half — what a
player has actually been doing lately. How many games his club has left in the
matchup period is the week's to say (`week.SleeperNBASchedule`).

Form is per game rather than per week on purpose: a category league is won over
a matchup period, and "the last ten games" is a window a weekly bucket of three
or four cannot be cut at.
"""

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, NamedTuple, Protocol, TypedDict

from thefrontoffice.adapters.outbound.competitions.names import NameIndex
from thefrontoffice.adapters.outbound.competitions.nba.rules import BOX_SCORE, Line, line
from thefrontoffice.adapters.outbound.platforms.sleeper.client import SleeperNBASource
from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog, PlayerMeta

logger = logging.getLogger(__name__)

# Enough weeks that fifteen games are in reach for anyone playing regularly:
# clubs play three or four a week, so six covers about twenty.
FORM_WEEKS = 6

Window = Literal["last_5", "last_10", "last_15"]
"""A `PlayerStats` key: the averages over a player's last few games."""

WINDOWS: dict[int, Window] = {5: "last_5", 10: "last_10", 15: "last_15"}

RECENT_GAMES = max(WINDOWS)
"""The widest run a table or drawer averages over: the last fifteen games."""

MIN_FORM_GAMES = 3
"""Fewest games worth averaging. Early in a season, or back from injury, a
player has fewer than fifteen; their last few still say something, but one or
two games is a single hot or cold night reported as a rate."""

# A basketball regular season runs 25 Sleeper weeks; week 26 comes back empty.
# Only used to reach back into the season just finished.
SEASON_WEEKS = 25


class RecentForm(NamedTuple):
    """The widest run a player has: their last fifteen games, or all of them while fewer."""

    games: int
    """How many games the line averages, which is what its label must say."""

    line: Line


class PlayerStats(TypedDict, total=False):
    last_5: Line
    last_10: Line
    last_15: Line
    recent: RecentForm
    minutes: tuple[float, ...]
    """The minutes he played in each game of `recent`, newest first: how steady his role is."""


def nine_cat(games: list[NBAGameLog]) -> Line:
    """Average a run of games into a nine-category line."""
    totals = {key: sum(g.get(key) for g in games) for key in BOX_SCORE}
    return line(totals, games=len(games))


@dataclass(frozen=True)
class BoxScores:
    """Every game in the form window, and who played it: what a teammate split reads (`teammates.py`)."""

    logs: Mapping[str, Sequence[NBAGameLog]] = field(default_factory=dict)
    """Each player's games, newest first, by Sleeper's id."""
    players: Mapping[str, PlayerMeta] = field(default_factory=dict)
    """Sleeper's catalog, by its id: a teammate's name, and ESPN's id for him."""
    index: NameIndex[str] = field(default_factory=NameIndex)
    """Sleeper's id by a player's name, refusing ambiguity: how a Yahoo player is found in `logs`."""


class FormSource(Protocol):
    """What the basketball provider reads recent form through. See `SleeperNBASource` for why it exists."""

    def get_player_stats(self, full_name: str) -> PlayerStats | None:
        """A player's last 5, 10 and 15 games, or nothing where there are none."""
        ...

    def box_scores(self) -> BoxScores:
        """Every game in the window, by player, and who each player is; empty where they would not load."""
        ...

    def recent_games(self, full_name: str) -> list[NBAGameLog]:
        """A player's last fifteen games, newest first; none where there are none."""
        ...


class SleeperNBAForm:
    """Recent form for basketball.

    Loads each of the two things it reads once and keeps them: a report asks
    about every player on a roster, and refetching the catalog per question
    would be the whole cost of the page.
    """

    def __init__(self, client: SleeperNBASource, season: str | None = None) -> None:
        self.client = client
        self._season = season
        self._logs: dict[str, list[NBAGameLog]] | None = None
        self._by_name: NameIndex[str] | None = None
        self._catalog: dict[str, PlayerMeta] | None = None

    def get_player_stats(self, full_name: str) -> PlayerStats | None:
        """A player's last 5, 10 and 15 games, or nothing where there are none.

        A fixed window is reported only once enough games exist to fill it:
        five games averaged into a "last fifteen" is a different number wearing
        the same label. `recent` is the widest run there is — the last fifteen,
        or every game while fewer — once there are `MIN_FORM_GAMES`, and says
        how many it averages, so a player twelve games in is not left blank.
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
        if len(games) >= MIN_FORM_GAMES:
            run = games[:RECENT_GAMES]
            stats["recent"] = RecentForm(games=len(run), line=nine_cat(run))
            stats["minutes"] = tuple(game.minutes for game in run)
        return stats or None

    def box_scores(self) -> BoxScores:
        """Every game in the window, by player, and who each player is; empty where they would not load."""
        return BoxScores(logs=self._game_logs(), players=self._players(), index=self._name_index())

    def recent_games(self, full_name: str) -> list[NBAGameLog]:
        """A player's last fifteen games, newest first, box score by box score — the run his form averages.

        None where the catalog cannot place his name: an unmatched player
        carries no games rather than borrowing someone else's.
        """
        player_id = self._name_index().lookup(full_name)
        if player_id is None:
            return []
        return self._game_logs().get(player_id, [])[:RECENT_GAMES]

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

        state = self.client.get_nba_state()
        if state.week >= 1:
            return state.season, list(range(max(1, state.week - FORM_WEEKS + 1), state.week + 1))
        previous = str(int(state.season) - 1)
        return previous, list(range(SEASON_WEEKS - FORM_WEEKS + 1, SEASON_WEEKS + 1))

    def _players(self) -> dict[str, PlayerMeta]:
        if self._catalog is None:
            try:
                self._catalog = self.client.get_nba_players()
            except SleeperAPIError as e:
                logger.warning(f"Continuing without the basketball catalog: {e}")
                self._catalog = {}
        return self._catalog

    def _name_index(self) -> NameIndex[str]:
        if self._by_name is None:
            index: NameIndex[str] = NameIndex()
            for player_id, meta in self._players().items():
                if name := meta.name:
                    index.add(name, player_id)
            self._by_name = index
        return self._by_name
