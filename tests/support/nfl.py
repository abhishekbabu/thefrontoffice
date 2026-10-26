"""Fantasy football on Sleeper, standing in: the league platform, ESPN beside it, and a small league to play.

The default league is two teams in week 3; `league_client` and `at_week` give
it a schedule, both rosters and a matchup. Everything a test does not set is
the same every time, so a test states only what its rule turns on.
"""

from typing import Any

from thefrontoffice.adapters.outbound.competitions.nfl.sleeper import SleeperNFLProvider
from thefrontoffice.adapters.outbound.platforms.espn.types import NewsArticle, ScoreboardGame
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    NFLGameLine,
    PlayerMeta,
    ScheduledGame,
    SeasonState,
    SeasonStats,
    SleeperLeague,
    SleeperRoster,
    SleeperUser,
    Transaction,
    TrendingPlayer,
    WeeklyProjection,
)

SLEEPER_USER_ID = "user-1"


def proj(pid: str, name: str, pos: str, pts: float, team: str = "BUF", opp: str = "MIA") -> WeeklyProjection:
    return WeeklyProjection(player_id=pid, name=name, position=pos, team=team, opponent=opp, points=pts)


class FakeSleeper:
    """Stands in for SleeperClient."""

    def __init__(
        self,
        rosters: list[SleeperRoster] | None = None,
        projections: dict[str, WeeklyProjection] | None = None,
        league: SleeperLeague | None = None,
        matchups: list[dict[str, Any]] | None = None,
        trending: list[TrendingPlayer] | None = None,
        trending_error: Exception | None = None,
        season_stats: dict[str, dict[str, SeasonStats]] | None = None,
        season_stats_error: Exception | None = None,
        season_schedule: list[ScheduledGame] | None = None,
        schedule_error: Exception | None = None,
        transactions: dict[int, list[Transaction]] | None = None,
        transactions_error: Exception | None = None,
        game_lines: list[NFLGameLine] | None = None,
        game_lines_error: Exception | None = None,
    ) -> None:
        self.game_lines = game_lines if game_lines is not None else []
        self.game_lines_error = game_lines_error
        self.last_season_lines: list[NFLGameLine] = []
        self.game_line_calls: list[tuple[str, list[int]]] = []
        self.season_stats = season_stats if season_stats is not None else {}
        self.season_stats_error = season_stats_error
        self.season_schedule = season_schedule if season_schedule is not None else []
        self.matchups_error: Exception | None = None
        self.players_catalog: dict[str, PlayerMeta] | None = None
        self.schedule_error = schedule_error
        self.transactions = transactions if transactions is not None else {}
        self.transactions_error = transactions_error
        self.league = league or SleeperLeague(
            league_id="L1",
            name="Sunday Money",
            season="2026",
            total_rosters=12,
            scoring_format="pts_ppr",
            roster_positions=["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF", "BN", "BN"],
        )
        self.rosters = (
            rosters
            if rosters is not None
            else [
                SleeperRoster(
                    roster_id=1,
                    owner_id=SLEEPER_USER_ID,
                    player_ids=["qb1", "rb1", "rb2"],
                    starter_ids=["qb1", "rb2"],
                    wins=2,
                    losses=1,
                    points_for=250.5,
                )
            ]
        )
        self.projections = projections or {}
        self.weekly_projections: dict[int, dict[str, WeeklyProjection]] = {}
        """Projections for particular weeks, where a test needs them to differ; `projections` otherwise."""
        self.matchups = matchups or []
        self.trending = trending or []
        self.trending_error = trending_error
        self.matchup_fetches = 0

    def get_matchups_bulk(self, league_id: str, weeks: list[int]) -> dict[int, list[dict[str, Any]]]:
        return {w: self.get_matchups(league_id, w) for w in weeks}

    def get_season_schedule(self, season: str, sport: str = "nfl") -> list[ScheduledGame]:
        if self.schedule_error:
            raise self.schedule_error
        return self.season_schedule

    def get_transactions(self, league_id: str, week: int) -> list[Transaction]:
        if self.transactions_error:
            raise self.transactions_error
        return self.transactions.get(week, [])

    def get_nfl_game_lines(self, season: str, weeks: list[int]) -> list[NFLGameLine]:
        self.game_line_calls.append((season, weeks))
        if self.game_lines_error:
            raise self.game_lines_error
        source = self.game_lines if season == self.get_state().season else self.last_season_lines
        return [line for line in source if line.week in weeks]

    @property
    def game_line_weeks(self) -> list[int]:
        """The weeks of this season last asked for: what a range could have been shaped by."""
        this = [weeks for season, weeks in self.game_line_calls if season == self.get_state().season]
        return this[-1] if this else []

    def get_season_stats(self, season: str, sport: str = "nfl") -> dict[str, SeasonStats]:
        if self.season_stats_error:
            raise self.season_stats_error
        return self.season_stats.get(season, {})

    week = 3
    """The NFL week in progress. Set it rather than replacing `get_state`."""

    def get_state(self, sport: str = "nfl") -> SeasonState:
        return SeasonState(week=self.week, season="2026", season_type="regular")

    def get_nfl_state(self) -> SeasonState:
        return self.get_state()

    def get_user(self, username: str) -> SleeperUser:
        return SleeperUser(user_id=SLEEPER_USER_ID, username=username, display_name=username)

    def get_leagues(self, user_id: str, season: str) -> list[SleeperLeague]:
        return [self.league]

    def get_rosters(self, league_id: str) -> list[SleeperRoster]:
        return self.rosters

    def get_league_users(self, league_id: str) -> dict[str, str]:
        return {SLEEPER_USER_ID: "Me", "user-2": "Rival"}

    def get_matchups(self, league_id: str, week: int) -> list[dict[str, Any]]:
        self.matchup_fetches += 1
        if self.matchups_error:
            raise self.matchups_error
        return self.matchups

    def get_players(self, sport: str = "nfl") -> dict[str, PlayerMeta]:
        if self.players_catalog is not None:
            return self.players_catalog
        return {
            "qb1": PlayerMeta(player_id="qb1", name="Star QB", position="QB", team="BUF"),
            "rb1": PlayerMeta(player_id="rb1", name="Good RB", position="RB", team="BUF"),
            "rb2": PlayerMeta(player_id="rb2", name="Bad RB", position="RB", team="BUF"),
            "wr9": PlayerMeta(player_id="wr9", name="Waiver WR", position="WR", team="NYJ"),
            "bye1": PlayerMeta(player_id="bye1", name="Bye Guy", position="TE", team="LAR"),
            # Sleeper files every team defense in the same catalog under the
            # club's own abbreviation, named the way somebody says it — which
            # is also how a caller turns "BUF" into "Buffalo Bills".
            "BUF": PlayerMeta(player_id="BUF", name="Buffalo Bills", position="DEF", team="BUF"),
            "MIA": PlayerMeta(player_id="MIA", name="Miami Dolphins", position="DEF", team="MIA"),
            "NYJ": PlayerMeta(player_id="NYJ", name="New York Jets", position="DEF", team="NYJ"),
        }

    def get_projections(self, season: str, week: int, scoring: str) -> dict[str, WeeklyProjection]:
        return self.weekly_projections.get(week, self.projections)

    # Signature mirrors the real client exactly, defaults included: a fake that
    # accepts anything lets a miswired call through, which is how a mangled
    # `get_trending(client, "add")` once degraded silently to "(unavailable)".
    def get_trending(self, kind: str = "add", lookback_hours: int = 24, limit: int = 25) -> list[TrendingPlayer]:
        assert isinstance(kind, str), f"kind must be a string, got {type(kind).__name__}"
        if self.trending_error:
            raise self.trending_error
        return self.trending


class FakeESPN:
    """Stands in for ESPNClient: each club's articles, keyed by ESPN's abbreviation."""

    def __init__(
        self,
        news: dict[str, list[NewsArticle]] | None = None,
        error: Exception | None = None,
        scoreboard: list[ScoreboardGame] | None = None,
        scoreboard_error: Exception | None = None,
    ) -> None:
        self.news = news or {}
        self.error = error
        self.scoreboard = scoreboard or []
        self.scoreboard_error = scoreboard_error
        self.asked: list[str] = []

    def get_team_news(self, league: str, clubs: list[str]) -> dict[str, list[NewsArticle]]:
        self.asked = clubs
        if self.error:
            raise self.error
        return {club: self.news[club] for club in clubs if club in self.news}

    def get_scoreboard(self, league: str, season: str, week: int) -> list[ScoreboardGame]:
        if self.scoreboard_error:
            raise self.scoreboard_error
        return self.scoreboard


def nfl_provider(client: FakeSleeper, espn: FakeESPN | None = None) -> SleeperNFLProvider:
    """The NFL provider over these stand-ins, as bootstrap would wire it over the real clients."""
    return SleeperNFLProvider(username="me", client=client, espn=espn or FakeESPN())


DEFAULT_PROJECTIONS = {
    "qb1": proj("qb1", "Star QB", "QB", 22.0),
    "rb1": proj("rb1", "Good RB", "RB", 18.0),
    "rb2": proj("rb2", "Bad RB", "RB", 4.0),
    "wr9": proj("wr9", "Waiver WR", "WR", 14.0, team="NYJ"),
}


def sched(week: int, day: str, home: str, away: str) -> ScheduledGame:
    return ScheduledGame(week=week, date=day, home=home, away=away)


SEASON_SCHEDULE = [
    sched(1, "2026-09-10", "KC", "BAL"),
    sched(1, "2026-09-13", "DAL", "NYG"),
    sched(1, "2026-09-14", "SF", "SEA"),
    sched(2, "2026-09-17", "MIA", "BUF"),
]


def league_client(**extra: Any) -> FakeSleeper:
    return FakeSleeper(
        projections=DEFAULT_PROJECTIONS,
        season_schedule=SEASON_SCHEDULE,
        rosters=[
            SleeperRoster(
                roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=["qb1", "rb1"], starter_ids=["qb1"], wins=2
            ),
            SleeperRoster(roster_id=2, owner_id="them", player_ids=["rb2"], starter_ids=["rb2"], wins=3),
        ],
        matchups=[
            {"roster_id": 1, "matchup_id": 7, "points": 88.5},
            {"roster_id": 2, "matchup_id": 7, "points": 96.1},
        ],
        **extra,
    )


def at_week(week: int, **extra: Any) -> FakeSleeper:
    client = league_client(**extra)
    client.week = week
    return client


def game_line(
    pid: str, week: int, position: str = "WR", team: str = "KC", opponent: str = "LV", **stats: float
) -> NFLGameLine:
    """One player's line from one game, with whatever stats the test turns on."""
    return NFLGameLine(player_id=pid, week=week, team=team, opponent=opponent, position=position, stats=stats)
