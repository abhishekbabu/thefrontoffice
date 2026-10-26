"""Fantasy basketball on Yahoo, standing in: the league platform, Sleeper's form and projections beside it."""

from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

from thefrontoffice.adapters.outbound.competitions.nba.yahoo import YahooNBAProvider
from thefrontoffice.adapters.outbound.platforms.sleeper.types import SeasonState
from thefrontoffice.adapters.outbound.platforms.yahoo.types import Timeframe


def make_player(
    name: str,
    position: str = "PF",
    team: str = "LAL",
    key: str | None = None,
    status: str | None = None,
    selected_position: str | None = None,
) -> Any:
    """A duck-typed stand-in for a yahoofantasy Player."""
    player = SimpleNamespace(
        name=SimpleNamespace(full=name),
        display_position=position,
        editorial_team_abbr=team,
        player_key=key or name.lower().replace(" ", "-"),
    )
    if status:
        player.status = status
    if selected_position:
        player.selected_position = SimpleNamespace(position=selected_position)
    return player


def yahoo_team(
    name: str,
    key: str,
    rank: int,
    wins: int,
    losses: int,
    ties: int = 0,
    points: str = "",
    roster: list[Any] | None = None,
) -> Any:
    """A yahoofantasy Team, which sets its attributes by setattr at runtime."""
    return SimpleNamespace(
        name=name,
        team_key=key,
        players=lambda: roster if roster is not None else [make_player(f"{name} One")],
        team_standings=SimpleNamespace(
            rank=rank,
            points_for=points,
            outcome_totals=SimpleNamespace(wins=wins, losses=losses, ties=ties),
        ),
    )


DEFAULT_TEAMS = [
    yahoo_team("Their Team", "t.2", rank=1, wins=5, losses=1, points="812"),
    yahoo_team("My Team", "t.1", rank=2, wins=4, losses=2, ties=1, points="790"),
]


class FakeYahoo:
    """Stands in for YahooClient."""

    def __init__(
        self,
        roster: list[Any] | None = None,
        stat_leaders: dict[str, list[Any]] | None = None,
        matchup_dates: tuple[str, str] = ("2026-02-09", "2026-02-15"),
        search_results: dict[str, list[Any]] | None = None,
        adds_used: int = 0,
        teams: list[Any] | None = None,
        available: list[Any] | None = None,
        roster_error: Exception | None = None,
    ) -> None:
        self.roster = roster if roster is not None else [make_player("Roster One")]
        self.roster_error = roster_error
        self.stat_leaders = stat_leaders or {}
        self.matchup_dates = matchup_dates
        self.search_results = search_results or {}
        self.adds_used = adds_used
        self.searches: list[str] = []
        self.matchup_fetches = 0
        self.teams = teams if teams is not None else DEFAULT_TEAMS
        self.available = available if available is not None else [make_player("Waiver One")]
        self.available_error: Exception | None = None

    def get_user_team(self) -> Any:
        return SimpleNamespace(
            name="My Team",
            team_key="t.1",
            roster_adds=SimpleNamespace(value=self.adds_used),
            players=self._players,
        )

    def _players(self) -> list[Any]:
        if self.roster_error:
            raise self.roster_error
        return self.roster

    @property
    def league(self) -> Any:
        """yahoofantasy's League, of which only `teams()` is read here."""
        return SimpleNamespace(teams=lambda: self.teams)

    def fetch_available(self, count: int = 100) -> list[Any]:
        if self.available_error:
            raise self.available_error
        return self.available[:count]

    def get_matchup(self, my_team: Any) -> Any:
        from thefrontoffice.adapters.outbound.platforms.yahoo.types import MatchupInfo

        self.matchup_fetches += 1
        return MatchupInfo(
            context="CURRENT MATCHUP: vs Their Team\n- BLK: 12 vs 17",
            week_start=self.matchup_dates[0],
            week_end=self.matchup_dates[1],
        )

    def get_matchup_context(self, my_team: Any) -> str:
        return self.get_matchup(my_team).context

    def get_matchup_dates(self, my_team: Any) -> tuple[str, str]:
        info = self.get_matchup(my_team)
        return (info.week_start, info.week_end)

    def fetch_top_by_stat(self, per_stat: int = 10, sort_type: Timeframe = Timeframe.LAST_WEEK) -> dict[str, list[Any]]:
        return self.stat_leaders

    def search_players(self, query: str) -> list[Any]:
        self.searches.append(query)
        return self.search_results.get(query, [])


class FakeSleeperProjections:
    """Stands in for SleeperClient's NBA projection endpoints."""

    def __init__(self, rows: Any = None, error: Exception | None = None, season: str = "2026", week: int = 12):
        self.rows = rows if rows is not None else []
        self.error = error
        self.season, self.week = season, week
        self.weeks_requested: list[int] = []

    def get_state(self, sport: str = "nfl") -> Any:
        return SeasonState(week=self.week, season=self.season, season_type="regular")

    def get_nba_projections(self, season: str, week: int) -> Any:
        self.weeks_requested.append(week)
        if self.error:
            raise self.error
        return self.rows if week == self.week else []


class FakeNBA:
    """Stands in for SleeperNBAForm."""

    def __init__(self, stats: dict[str, Any] | None = None, games: dict[str, int] | None = None) -> None:
        self.stats = stats or {}
        self.games = games or {}

    def get_player_stats(self, full_name: str) -> Any:
        return self.stats.get(full_name)

    def get_remaining_games(self, team_abbr: str, start_date: date, end_date: date, now: datetime | None = None) -> int:
        return self.games.get(team_abbr.upper(), 0)

    def get_remaining_games_bulk(
        self, team_abbrs: list[str], start_date: date, end_date: date, now: datetime | None = None
    ) -> dict[str, int]:
        return {t.upper(): self.games.get(t.upper(), 0) for t in team_abbrs}


def nba_provider(
    yahoo: FakeYahoo | None = None,
    *,
    league: Any = None,
    all_leagues: list[Any] | None = None,
    nba: FakeNBA | None = None,
    sleeper: FakeSleeperProjections | None = None,
) -> YahooNBAProvider:
    """The NBA provider over these stand-ins, as bootstrap would wire it over the real clients."""
    return YahooNBAProvider(
        league,
        all_leagues=all_leagues,
        nba=nba or FakeNBA(),
        yahoo_for=lambda _: yahoo or FakeYahoo(),
        sleeper=sleeper or FakeSleeperProjections(),
        max_weekly_adds=3,
    )
