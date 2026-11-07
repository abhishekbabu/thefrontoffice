"""Fantasy basketball on Yahoo, standing in: the league platform, Sleeper's form and projections beside it."""

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from thefrontoffice.adapters.outbound.competitions.nba.form import FormSource
from thefrontoffice.adapters.outbound.competitions.nba.rules import BLOCKS
from thefrontoffice.adapters.outbound.competitions.nba.yahoo import YahooNBAProvider
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog, PlayerMeta, ScheduledGame, SeasonState
from thefrontoffice.adapters.outbound.platforms.yahoo.types import (
    Matchup,
    MatchupSide,
    TeamStanding,
    Timeframe,
    YahooLeague,
    YahooPlayer,
    YahooTeam,
)


def make_player(
    name: str,
    position: str = "PF",
    team: str = "LAL",
    key: str | None = None,
    status: str = "",
    selected_position: str = "",
    injury_note: str = "",
) -> YahooPlayer:
    return YahooPlayer(
        player_key=key or name.lower().replace(" ", "-"),
        name=name,
        position=position,
        team=team,
        status=status,
        injury_note=injury_note,
        slot=selected_position,
    )


def yahoo_team(
    name: str,
    key: str,
    rank: int,
    wins: int,
    losses: int,
    ties: int = 0,
    points: str = "",
    mine: bool = False,
) -> YahooTeam:
    return YahooTeam(
        team_key=key,
        name=name,
        is_mine=mine,
        standing=TeamStanding(rank=rank, wins=wins, losses=losses, ties=ties, points_for=points),
    )


DEFAULT_TEAMS = [
    yahoo_team("Their Team", "t.2", rank=1, wins=5, losses=1, points="812"),
    yahoo_team("My Team", "t.1", rank=2, wins=4, losses=2, ties=1, points="790", mine=True),
]


class FakeYahoo:
    """Stands in for YahooClient: the user's team is t.1, holding `roster`; every other team holds one player."""

    def __init__(
        self,
        roster: list[YahooPlayer] | None = None,
        stat_leaders: dict[str, list[YahooPlayer]] | None = None,
        matchup_dates: tuple[date, date] | None = (date(2026, 2, 9), date(2026, 2, 15)),
        search_results: dict[str, list[YahooPlayer]] | None = None,
        adds_used: int = 0,
        teams: list[YahooTeam] | None = None,
        available: list[YahooPlayer] | None = None,
        roster_error: Exception | None = None,
    ) -> None:
        self.roster_players = roster if roster is not None else [make_player("Roster One", selected_position="PF")]
        self.roster_error = roster_error
        self.stat_leaders = stat_leaders or {}
        self.matchup_dates = matchup_dates
        self.search_results = search_results or {}
        self.adds_used = adds_used
        self.matchup_fetches = 0
        self.league_teams = teams if teams is not None else DEFAULT_TEAMS
        self.available = available if available is not None else [make_player("Waiver One")]

    def get_user_team(self) -> YahooTeam:
        return YahooTeam(team_key="t.1", name="My Team", is_mine=True, adds_used=self.adds_used)

    def roster(self, team_key: str) -> list[YahooPlayer]:
        if team_key != "t.1":
            name = next((t.name for t in self.league_teams if t.team_key == team_key), team_key)
            return [make_player(f"{name} One", selected_position="PF")]
        if self.roster_error:
            raise self.roster_error
        return self.roster_players

    def teams(self) -> list[YahooTeam]:
        return self.league_teams

    def fetch_available(self, count: int = 100) -> list[YahooPlayer]:
        return self.available[:count]

    def get_matchup(self, team_key: str) -> Matchup | None:
        """This week against Their Team, 12 blocks to 17; no matchup when built without dates."""
        self.matchup_fetches += 1
        if self.matchup_dates is None:
            return None
        start, end = self.matchup_dates
        return Matchup(
            start=start,
            end=end,
            mine=MatchupSide(team_key="t.1", name="My Team", points="4", stats={BLOCKS.yahoo_stat: "12"}),
            opponent=MatchupSide(team_key="t.2", name="Their Team", points="5", stats={BLOCKS.yahoo_stat: "17"}),
            opponent_roster=[make_player("Their Star", position="C")],
        )

    def fetch_top_by_stat(
        self, stats: Mapping[str, str], per_stat: int = 10, sort_type: Timeframe = Timeframe.LAST_WEEK
    ) -> dict[str, list[YahooPlayer]]:
        """The leaders this was built with, for the categories asked about."""
        return {name: self.stat_leaders[name] for name in stats if name in self.stat_leaders}

    def search_players(self, query: str) -> list[YahooPlayer]:
        return self.search_results.get(query, [])

    def players(self, player_keys: list[str]) -> list[YahooPlayer]:
        """Anybody this league was built with, on a roster or not."""
        everyone = [
            *self.roster_players,
            *(p for t in self.league_teams if t.team_key != "t.1" for p in self.roster(t.team_key)),
            *self.available,
            *(p for found in self.search_results.values() for p in found),
            *(p for leaders in self.stat_leaders.values() for p in leaders),
        ]
        return [p for key in player_keys if (p := next((p for p in everyone if p.player_key == key), None))]


def yahoo_league(key: str = "466.l.1", name: str = "One") -> YahooLeague:
    return YahooLeague(league_key=key, name=name, league_type="head", current_week=5)


class FakeYahooAuth:
    """Stands in for YahooAuth, finding the leagues it was built with."""

    def __init__(self, leagues: list[YahooLeague] | None = None) -> None:
        self.leagues = leagues if leagues is not None else [yahoo_league()]
        self.searches: list[tuple[str, int]] = []

    def find_leagues(self, game_code: str, season: int) -> list[YahooLeague]:
        self.searches.append((game_code, season))
        return self.leagues


class FakeSleeperProjections:
    """Stands in for SleeperClient's NBA projection endpoints."""

    def __init__(self, rows: Any = None, error: Exception | None = None, season: str = "2026", week: int = 12):
        self.rows = rows if rows is not None else []
        self.error = error
        self.season, self.week = season, week

    def get_nba_state(self) -> SeasonState:
        return SeasonState(week=self.week, season=self.season, season_type="regular")

    def get_nba_projections(self, season: str, week: int) -> Any:
        if self.error:
            raise self.error
        return self.rows if week == self.week else []


class FakeSleeperNBA:
    """Stands in for SleeperClient's basketball box scores, schedule and catalog, read by SleeperNBAForm."""

    def __init__(
        self,
        logs: dict[str, list[NBAGameLog]] | None = None,
        schedule: list[ScheduledGame] | None = None,
        catalog: dict[str, PlayerMeta] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.logs = logs or {}
        self.schedule = schedule or []
        self.catalog = catalog or {"p1": PlayerMeta(player_id="p1", name="Nikola Jokic", position="C", team="DEN")}
        self.error = error

    def get_nba_game_logs(self, season: str, weeks: list[int]) -> dict[str, list[NBAGameLog]]:
        if self.error:
            raise self.error
        return self.logs

    def get_nba_schedule(self, season: str) -> list[ScheduledGame]:
        if self.error:
            raise self.error
        return self.schedule

    def get_nba_players(self) -> dict[str, PlayerMeta]:
        if self.error:
            raise self.error
        return self.catalog

    def get_nba_state(self) -> SeasonState:
        return SeasonState(week=10, season="2026", season_type="regular")


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
    nba: FormSource | None = None,
    sleeper: FakeSleeperProjections | None = None,
) -> YahooNBAProvider:
    """The NBA provider over these stand-ins, as bootstrap would wire it over the real clients."""
    return YahooNBAProvider(
        auth=FakeYahooAuth(),
        yahoo_for=lambda _: yahoo or FakeYahoo(),
        nba=nba or FakeNBA(),
        sleeper=sleeper or FakeSleeperProjections(),
        max_weekly_adds=3,
    )
