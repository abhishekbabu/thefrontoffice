"""Fantasy basketball on Yahoo, standing in: the league platform, Sleeper's form and projections beside it."""

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from support.espn import FakeESPN
from thefrontoffice.adapters.outbound.competitions.names import NameIndex
from thefrontoffice.adapters.outbound.competitions.nba.form import BoxScores, FormSource
from thefrontoffice.adapters.outbound.competitions.nba.rules import BLOCKS, CATEGORIES, TURNOVERS
from thefrontoffice.adapters.outbound.competitions.nba.week import ScheduleSource
from thefrontoffice.adapters.outbound.competitions.nba.yahoo import YahooNBAProvider
from thefrontoffice.adapters.outbound.platforms.sleeper.types import NBAGameLog, PlayerMeta, ScheduledGame, SeasonState
from thefrontoffice.adapters.outbound.platforms.yahoo.types import (
    LeagueSettings,
    Matchup,
    MatchupSide,
    Pairing,
    StatCategory,
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


def game_log(pid: str, day: int, minutes: float = 30.0, team: str = "TOR", **stats: float) -> NBAGameLog:
    """One game in November 2026, for `team`."""
    return NBAGameLog(player_id=pid, date=f"2026-11-{day:02d}", opponent="BOS", stats=stats, team=team, minutes=minutes)


def box_scores(logs: dict[str, list[NBAGameLog]], names: dict[str, str], team: str = "TOR") -> BoxScores:
    """These games, each player named in Sleeper's catalog and found by his name."""
    index: NameIndex[str] = NameIndex()
    for pid, name in names.items():
        index.add(name, pid)
    players = {pid: PlayerMeta(player_id=pid, name=name, team=team) for pid, name in names.items()}
    return BoxScores(logs=logs, players=players, index=index)


def toronto() -> BoxScores:
    """Barnes (s1) played TOR's first four games and sat the next four; Poeltl (c1) played all
    eight, six points a game beside him and twelve without."""
    return box_scores(
        {
            "s1": [game_log("s1", d, 35.0, pts=25) for d in (1, 2, 3, 4)],
            "c1": [game_log("c1", d, 20.0, pts=6 if d <= 4 else 12) for d in range(1, 9)],
        },
        {"s1": "Scottie Barnes", "c1": "Jakob Poeltl"},
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
        risers: list[YahooPlayer] | None = None,
        roster_error: Exception | None = None,
        weights: dict[str, float] | None = None,
        max_weekly_adds: int | None = 3,
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
        self.risers = risers or []
        """The wire by the last week's rank; `available` is by the season's."""
        self.wire_depths: Mapping[Timeframe, int] = {}
        self.weights = weights or {}
        self.max_weekly_adds = max_weekly_adds
        self.week_stats: dict[int, tuple[dict[str, str], dict[str, str]]] = {}
        """Each side's categories by week, by Yahoo stat id: mine, then theirs."""
        self.week_points: dict[int, tuple[tuple[str, str], tuple[str, str]]] = {}
        """Each side's fantasy points by week, scored then projected: mine, then theirs."""
        self.pairings: list[int] = []
        self.season_weeks: dict[int, Pairing | None] | None = None
        """Your side of each week's scoreboard; every week against Their Team when None."""
        self.standings_error: Exception | None = None
        self.wire_error: Exception | None = None

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

    def standings(self) -> list[YahooTeam]:
        if self.standings_error:
            raise self.standings_error
        return self.league_teams

    def season(self, team_key: str, weeks: list[int]) -> dict[int, Pairing | None]:
        if self.season_weeks is not None:
            return {week: self.season_weeks.get(week) for week in weeks}
        return {week: self.pairing(team_key, week) for week in weeks}

    def fetch_available(self, depths: Mapping[Timeframe, int]) -> dict[Timeframe, list[YahooPlayer]]:
        """`available` by season rank and `risers` by the last week's, each as deep as asked; nothing by any other."""
        self.wire_depths = depths
        if self.wire_error:
            raise self.wire_error
        by = {Timeframe.SEASON: self.available, Timeframe.LAST_WEEK: self.risers}
        return {sort_type: by.get(sort_type, [])[:depth] for sort_type, depth in depths.items()}

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

    def settings(self) -> LeagueSettings:
        """The nine categories, turnovers won by fewer, with the weights and add limit this was built with;
        six teams make playoffs from week 19."""
        return LeagueSettings(
            categories=[StatCategory(c.yahoo_stat, c.label, fewer_wins=c is TURNOVERS) for c in CATEGORIES],
            weights=self.weights,
            max_weekly_adds=self.max_weekly_adds,
            playoff_start_week=19,
            playoff_teams=6,
        )

    def pairing(self, team_key: str, week: int) -> Pairing | None:
        """Any week against Their Team, with the categories this was built with for it; 12 blocks to 17 otherwise."""
        self.pairings.append(week)
        if self.matchup_dates is None:
            return None
        start, end = self.matchup_dates
        mine, theirs = self.week_stats.get(week, ({BLOCKS.yahoo_stat: "12"}, {BLOCKS.yahoo_stat: "17"}))
        (my_points, my_projected), (their_points, their_projected) = self.week_points.get(week, (("", ""), ("", "")))
        return Pairing(
            start=start,
            end=end,
            mine=MatchupSide(team_key="t.1", name="My Team", points=my_points, projected=my_projected, stats=mine),
            opponent=MatchupSide(
                team_key="t.2", name="Their Team", points=their_points, projected=their_projected, stats=theirs
            ),
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
            *self.risers,
            *(p for found in self.search_results.values() for p in found),
            *(p for leaders in self.stat_leaders.values() for p in leaders),
        ]
        return [p for key in player_keys if (p := next((p for p in everyone if p.player_key == key), None))]


def yahoo_league(key: str = "466.l.1", name: str = "One", scoring_type: str = "head") -> YahooLeague:
    return YahooLeague(league_key=key, name=name, league_type="head", current_week=5, scoring_type=scoring_type)


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
    """Stands in for SleeperClient's basketball box scores, schedule and catalog, read by SleeperNBAForm and SleeperNBASchedule."""

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
    """Stands in for SleeperNBAForm and SleeperNBASchedule both: one player's form, one club's games, the box scores.

    A club's games left are its count in `games` whatever the window, or where `dated` lists its
    games' days, those inside the window asked about.
    """

    def __init__(
        self,
        stats: dict[str, Any] | None = None,
        games: dict[str, int] | None = None,
        slate: list[ScheduledGame] | None = None,
        scores: BoxScores | None = None,
        dated: dict[str, list[date]] | None = None,
    ) -> None:
        self.stats = stats or {}
        self.games = games or {}
        self.slate = slate or []
        self.scores = scores or BoxScores()
        self.dated = dated or {}

    def games_between(self, start_date: date, end_date: date) -> list[ScheduledGame]:
        return [g for g in self.slate if start_date.isoformat() <= g.date <= end_date.isoformat()]

    def get_player_stats(self, full_name: str) -> Any:
        return self.stats.get(full_name)

    def box_scores(self) -> BoxScores:
        return self.scores

    def get_remaining_games(self, team_abbr: str, start_date: date, end_date: date, now: datetime | None = None) -> int:
        club = team_abbr.upper()
        if club in self.dated:
            return sum(1 for day in self.dated[club] if start_date <= day <= end_date)
        return self.games.get(club, 0)

    def get_remaining_games_bulk(
        self, team_abbrs: list[str], start_date: date, end_date: date, now: datetime | None = None
    ) -> dict[str, int]:
        return {t.upper(): self.get_remaining_games(t, start_date, end_date) for t in team_abbrs}


def nba_provider(
    yahoo: FakeYahoo | None = None,
    *,
    nba: FakeNBA | None = None,
    form: FormSource | None = None,
    games: ScheduleSource | None = None,
    sleeper: FakeSleeperProjections | None = None,
    league: YahooLeague | None = None,
    espn: FakeESPN | None = None,
) -> YahooNBAProvider:
    """The NBA provider over these stand-ins, as bootstrap would wire it over the real clients.

    `nba` stands in for both Sleeper readers; `form` or `games` replaces one of them.
    """
    sleeper_nba = nba or FakeNBA()
    return YahooNBAProvider(
        auth=FakeYahooAuth([league] if league else None),
        yahoo_for=lambda _: yahoo or FakeYahoo(),
        form=form or sleeper_nba,
        games=games or sleeper_nba,
        sleeper=sleeper or FakeSleeperProjections(),
        espn=espn or FakeESPN(),
        fallback_weekly_adds=3,
    )
