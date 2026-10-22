"""Shared fakes for engine tests.

The engines take their collaborators by keyword, so these stand in for Yahoo,
NBA and Gemini without any network, credentials or monkeypatching. `capture_logs`
is here for the same reason: a test that wants to assert on a log line should
name the logger it means rather than read whatever the whole process emitted.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from reports import MOCK_NBA_REPORT, MOCK_NBA_VERDICT

from thefrontoffice.adapters.outbound.competitions.nfl.sleeper import SleeperNFLProvider
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

# ── log capture ─────────────────────────────────────────────────────────


class LogCapture(logging.Handler):
    """Every record one named logger emitted inside a `capture_logs` block."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    @property
    def text(self) -> str:
        """The rendered messages, newline-joined, for substring assertions."""
        return "\n".join(record.getMessage() for record in self.records)

    def at(self, level: int) -> list[str]:
        """The messages logged at exactly `level`, for asserting on severity."""
        return [record.getMessage() for record in self.records if record.levelno == level]


@contextmanager
def capture_logs(name: str, level: int = logging.INFO) -> Iterator[LogCapture]:
    """Records from the logger called `name`, for the duration of the block.

    Narrower than pytest's `caplog`, which installs a handler at the root and
    hands back everything anything logged in that window. Naming the logger
    makes the test say which module is expected to speak, so a line that moves
    to another module fails here instead of passing on a coincidence. It also
    needs no propagation: the handler attaches to the logger under test.
    """
    capture = LogCapture()
    logger = logging.getLogger(name)
    previous_level = logger.level
    logger.addHandler(capture)
    logger.setLevel(level)
    try:
        yield capture
    finally:
        logger.removeHandler(capture)
        logger.setLevel(previous_level)


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


def _team(
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
    _team("Their Team", "t.2", rank=1, wins=5, losses=1, points="812"),
    _team("My Team", "t.1", rank=2, wins=4, losses=2, ties=1, points="790"),
]


# ── football ────────────────────────────────────────────────────────────
# Shared because the football provider is four modules now, and each of their
# test files drives the same platform.

SLEEPER_USER_ID = "user-1"


def _proj(pid: str, name: str, pos: str, pts: float, team: str = "BUF", opp: str = "MIA") -> WeeklyProjection:
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
        self.game_line_weeks: list[int] = []
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
        self.game_line_weeks = weeks
        if self.game_lines_error:
            raise self.game_lines_error
        return [line for line in self.game_lines if line.week in weeks]

    def get_season_stats(self, season: str, sport: str = "nfl") -> dict[str, SeasonStats]:
        if self.season_stats_error:
            raise self.season_stats_error
        return self.season_stats.get(season, {})

    def get_state(self, sport: str = "nfl") -> SeasonState:
        return SeasonState(week=3, season="2026", season_type="regular")

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

    def get_players(self) -> dict[str, PlayerMeta]:
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
        return self.projections

    # Signature mirrors the real client exactly, defaults included: a fake that
    # accepts anything lets a miswired call through, which is how a mangled
    # `get_trending(client, "add")` once degraded silently to "(unavailable)".
    def get_trending(self, kind: str, lookback_hours: int = 24, limit: int = 25) -> list[TrendingPlayer]:
        assert isinstance(kind, str), f"kind must be a string, got {type(kind).__name__}"
        if self.trending_error:
            raise self.trending_error
        return self.trending


def _provider(client: FakeSleeper) -> SleeperNFLProvider:
    return SleeperNFLProvider(username="me", client=client)  # type: ignore[arg-type]


DEFAULT_PROJECTIONS = {
    "qb1": _proj("qb1", "Star QB", "QB", 22.0),
    "rb1": _proj("rb1", "Good RB", "RB", 18.0),
    "rb2": _proj("rb2", "Bad RB", "RB", 4.0),
    "wr9": _proj("wr9", "Waiver WR", "WR", 14.0, team="NYJ"),
}


def _sched(week: int, day: str, home: str, away: str) -> ScheduledGame:
    return ScheduledGame(week=week, date=day, home=home, away=away)


SEASON_SCHEDULE = [
    _sched(1, "2026-09-10", "KC", "BAL"),
    _sched(1, "2026-09-13", "DAL", "NYG"),
    _sched(1, "2026-09-14", "SF", "SEA"),
    _sched(2, "2026-09-17", "MIA", "BUF"),
]


def _league_client(**extra: Any) -> FakeSleeper:
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


def _at_week(week: int, **extra: Any) -> FakeSleeper:
    client = _league_client(**extra)
    client.get_state = lambda competition="nfl": SeasonState(  # type: ignore[method-assign]
        week=week, season="2026", season_type="regular"
    )
    return client


# ── basketball ──────────────────────────────────────────────────────────


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
    ) -> None:
        self.roster = roster if roster is not None else [make_player("Roster One")]
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
            players=lambda: self.roster,
        )

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

    def fetch_top_by_stat(self, per_stat: int = 10) -> dict[str, list[Any]]:
        return self.stat_leaders

    def search_players(self, query: str) -> list[Any]:
        self.searches.append(query)
        return self.search_results.get(query, [])


class FakeNBA:
    """Stands in for SleeperNBAForm."""

    def __init__(self, stats: dict[str, Any] | None = None, games: dict[str, int] | None = None) -> None:
        self.stats = stats or {}
        self.games = games or {}

    def get_player_stats(self, full_name: str) -> Any:
        return self.stats.get(full_name)

    def get_remaining_games(self, team_abbr: str, start: date, end: date) -> int:
        return self.games.get(team_abbr.upper(), 0)

    def get_remaining_games_bulk(self, teams: list[str], start: date, end: date) -> dict[str, int]:
        return {t.upper(): self.games.get(t.upper(), 0) for t in teams}


class FakeChat:
    """Stands in for a genai Chat."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send_message(self, message: Any) -> Any:
        self.sent.append(str(message))
        return SimpleNamespace(text="[FAKE] follow-up answer")


class FakeAI:
    """Stands in for GeminiClient, recording what it was asked."""

    def __init__(
        self,
        report: Any = MOCK_NBA_REPORT,
        verdict: Any = MOCK_NBA_VERDICT,
        proposal: Any = None,
        prose: str = "[FAKE] trade prose",
    ) -> None:
        self.report = report
        self.verdict = verdict
        self.proposal = proposal
        self.prose = prose
        self.prompts: list[str] = []
        self.structured_text: list[str] = []
        self.history: Any = None
        self.search_enabled: bool | None = None
        self.chat = FakeChat()

    def generate_structured(self, prompt: str, schema: type, mock: Any = None) -> Any:
        self.prompts.append(prompt)
        return self.report

    def structure_text(self, text: str, schema: type, instruction: str, mock: Any = None) -> Any:
        self.structured_text.append(text)
        return self.verdict

    def start_chat(self, initial_history: Any = None, enable_search: bool = False) -> FakeChat:
        self.history = initial_history
        self.search_enabled = enable_search
        return self.chat

    def parse_trade_string(self, text: str) -> Any:
        from thefrontoffice.domain.models import TradeProposal

        return (
            self.proposal
            if self.proposal is not None
            else TradeProposal(giving=["LeBron James"], receiving=["Jayson Tatum"])
        )


@pytest.fixture(autouse=True)
def _isolate_from_local_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Blank every credential-derived setting for the duration of a test.

    `settings` is built from the developer's .env at import time. Without this a
    test asserting "unconfigured" behavior passes in CI, which has no .env, and
    fails on a machine that does — or worse, a test quietly exercises a real
    account. Tests that need a value set it explicitly.
    """
    from thefrontoffice.config.settings import settings

    for field in (
        "sleeper_username",
        "fpl_entry_id",
        "gemini_api_key",
        "yahoo_client_id",
        "yahoo_client_secret",
        # Without this, running the suite on a machine with a token in .env
        # exports spans from the tests into the developer's real project.
        "logfire_token",
    ):
        monkeypatch.setattr(settings, field, None)

    # Point the Yahoo token at a path that cannot exist, so a suite run does not
    # depend on whether this machine has been through the OAuth flow. A test
    # that wants an authorized client says so by pointing this somewhere real.
    monkeypatch.setattr(settings, "yahoo_token_file", str(tmp_path / "no-token"))

    # Every disk cache lands under tmp_path too. The suite must not read a cache
    # this machine happens to have warmed, nor leave one behind that the next
    # run reads as a hit.
    for field, name in (
        ("yahoo_cache_dir", "yahoo-cache"),
        ("sleeper_cache_dir", "sleeper-cache"),
        ("fpl_cache_dir", "fpl-cache"),
    ):
        monkeypatch.setattr(settings, field, str(tmp_path / name))


@pytest.fixture
def fake_ai() -> FakeAI:
    return FakeAI()


@pytest.fixture
def fake_nba() -> FakeNBA:
    return FakeNBA()


@pytest.fixture
def fake_yahoo() -> FakeYahoo:
    return FakeYahoo()
