"""The Fantasy Premier League game, standing in: a player built from the few fields a rule turns on,
and a client serving one manager's season."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from thefrontoffice.adapters.outbound.competitions.premier_league.fpl import FPLProvider
from thefrontoffice.adapters.outbound.platforms.fpl.types import (
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


def player(
    pid: int,
    position: str,
    points: float,
    cost: int = 50,
    team: str = "ARS",
    *,
    status: str = "a",
    news: str = "",
    chance_of_playing: int | None = None,
    penalties_order: int | None = None,
    corners_order: int | None = None,
) -> Player:
    """A player whose form, points a game and expected points are all `points`, so one number sets him."""
    return Player(
        id=pid,
        name=f"P{pid}",
        full_name=f"Player {pid}",
        position=position,
        team=team,
        cost=cost,
        expected_points=points,
        expected_this=points,
        form=points,
        points_per_game=points,
        total_points=int(points * 10),
        selected_by=5.0,
        minutes=900,
        status=status,
        news=news,
        chance_of_playing=chance_of_playing,
        penalties_order=penalties_order,
        corners_order=corners_order,
    )


ENTRY_ID = 77
LEAGUE_ID = "900"
H2H_LEAGUE_ID = "950"


# A fifteen whose set eleven is deliberately not the best one: P15, the strongest
# forward, starts on the bench behind P7, the weakest defender.
SQUAD_PLAYERS = {
    1: player(1, "GKP", 4.0, team="ARS"),
    2: player(2, "GKP", 1.0, team="MCI"),
    3: player(3, "DEF", 6.0),
    4: player(4, "DEF", 5.0),
    5: player(5, "DEF", 4.0),
    6: player(6, "DEF", 3.0),
    7: player(7, "DEF", 0.5),
    8: player(8, "MID", 8.0),
    9: player(9, "MID", 7.0),
    10: player(10, "MID", 6.0),
    11: player(11, "MID", 5.0),
    12: player(12, "MID", 1.0),
    13: player(13, "FWD", 7.5),
    14: player(14, "FWD", 2.0),
    15: player(15, "FWD", 9.0, team="MCI"),
}

MARKET = {
    100: player(100, "DEF", 7.0, cost=55, team="LIV"),
    101: player(101, "MID", 9.5, cost=120, team="LIV"),
    102: player(102, "FWD", 8.0, cost=200, team="LIV"),
    103: player(103, "MID", 9.0, cost=60, team="LIV", status="i"),
}

STARTING_IDS = [1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13]
BENCH_IDS = [2, 12, 14, 15]


def _picks() -> list[Pick]:
    # Every real squad names both, and the vice is the one that matters when
    # the captain does not play — a fixture without one cannot catch that.
    picks = [
        Pick(
            element=pid,
            position=i,
            multiplier=2 if pid == 8 else 1,
            is_captain=pid == 8,
            is_vice_captain=pid == STARTING_IDS[1],
        )
        for i, pid in enumerate(STARTING_IDS, start=1)
    ]
    picks += [Pick(element=pid, position=i, multiplier=0) for i, pid in enumerate(BENCH_IDS, start=12)]
    return picks


# The game issues a set per half, so each name appears twice.
DEFAULT_CHIPS = [
    Chip(name="wildcard", start_event=2, stop_event=19),
    Chip(name="wildcard", start_event=20, stop_event=38),
    Chip(name="freehit", start_event=2, stop_event=19),
    Chip(name="bboost", start_event=1, stop_event=19),
    Chip(name="3xc", start_event=1, stop_event=19),
    Chip(name="freehit", start_event=20, stop_event=38),
]

DEFAULT_H2H_SEASON = {
    1: H2HMatch(opponent_entry=99, opponent_name="Rival FC", my_points=60, opponent_points=44),
    2: H2HMatch(opponent_entry=98, opponent_name="Other FC", my_points=31, opponent_points=55),
    3: H2HMatch(opponent_entry=97, opponent_name="Third FC", my_points=0, opponent_points=0),
}

DEFAULT_TABLE = [
    TableRow(rank=1, entry=99, entry_name="Rival FC", manager="A Rival", total=6, played=2, won=2, points_for=104),
    TableRow(
        rank=2,
        entry=ENTRY_ID,
        entry_name="Front Office FC",
        manager="Abhishek Babu",
        total=3,
        played=2,
        won=1,
        lost=1,
        points_for=91,
    ),
]

DEFAULT_PAST_SEASONS = [
    PastSeason(
        season="2023/24",
        total_points=180,
        minutes=2500,
        starts=28,
        goals=20,
        assists=5,
        clean_sheets=2,
        goals_conceded=30,
        saves=0,
        bonus=20,
        expected_goals=18.5,
        expected_assists=4.1,
        start_cost=110,
        end_cost=118,
    ),
    PastSeason(
        season="2024/25",
        total_points=210,
        minutes=2900,
        starts=33,
        goals=24,
        assists=7,
        clean_sheets=3,
        goals_conceded=26,
        saves=0,
        bonus=28,
        expected_goals=22.0,
        expected_assists=5.5,
        start_cost=118,
        end_cost=124,
    ),
]


class FakeFPL:
    """Stands in for FPLClient; checked against `FPLSource` wherever a provider is built over it."""

    def __init__(
        self,
        *,
        leagues: list[MiniLeague] | None = None,
        upcoming: int = 5,
        bank: int = 30,
        history: list[GameweekResult] | None = None,
        fixtures: list[Fixture] | None = None,
        fixtures_error: Exception | None = None,
        active_chip: str = "",
        points_on_bench: int = 0,
        squad: Squad | None = None,
        past_seasons: list[PastSeason] | None = None,
        past_seasons_error: Exception | None = None,
        h2h_season: dict[int, H2HMatch] | None = None,
        h2h_season_error: Exception | None = None,
        standings: list[TableRow] | None = None,
        standings_error: Exception | None = None,
        live: dict[int, LiveStat] | None = None,
        live_error: Exception | None = None,
        chips: list[Chip] | None = None,
        chips_played: list[ChipPlay] | None = None,
        chips_error: Exception | None = None,
        clubs: list[Club] | None = None,
        clubs_error: Exception | None = None,
        players: dict[int, Player] | None = None,
    ) -> None:
        self.players = players
        self.clubs = (
            clubs
            if clubs is not None
            else [
                Club(short_name="ARS", name="Arsenal", code=3),
                Club(short_name="TOT", name="Spurs", code=6),
            ]
        )
        self.clubs_error = clubs_error
        self.past_seasons = past_seasons if past_seasons is not None else list(DEFAULT_PAST_SEASONS)
        self.past_seasons_error = past_seasons_error
        self.leagues = (
            leagues
            if leagues is not None
            else [
                MiniLeague(id=314, name="Overall", rank=340112, rank_count=9000000, is_private=False),
                MiniLeague(id=900, name="Work League", rank=3, rank_count=12, is_private=True),
                MiniLeague(id=950, name="Hood h2h", rank=1, is_private=True, is_h2h=True),
            ]
        )
        self.upcoming = upcoming
        self.squad = squad or Squad(
            gameweek=upcoming - 1,
            picks=_picks(),
            bank=bank,
            value=1004,
            points_on_bench=points_on_bench,
            active_chip=active_chip,
        )
        self.history = (
            history
            if history is not None
            else [GameweekResult(event=e, points=50, transfers_made=0, transfers_cost=0) for e in range(1, upcoming)]
        )
        self.fixtures = (
            fixtures
            if fixtures is not None
            else [
                Fixture(event=upcoming, home="ARS", away="LIV", home_difficulty=2, away_difficulty=4),
            ]
        )
        self.fixtures_error = fixtures_error
        self.squad_requests: list[int] = []
        self.h2h_season = h2h_season if h2h_season is not None else DEFAULT_H2H_SEASON
        self.h2h_season_error = h2h_season_error
        self.standings = standings if standings is not None else DEFAULT_TABLE
        self.standings_error = standings_error
        self.live = live if live is not None else {}
        self.live_error = live_error
        self.chips = chips if chips is not None else list(DEFAULT_CHIPS)
        self.chips_played = chips_played or []
        self.chips_error = chips_error

    def upcoming_gameweek(self, now: datetime | None = None) -> Gameweek:
        return Gameweek(
            id=self.upcoming,
            name=f"Gameweek {self.upcoming}",
            deadline=datetime(2026, 9, 12, tzinfo=UTC),
            average_score=51,
        )

    def get_entry(self, entry_id: int) -> Entry:
        return Entry(
            entry_id=entry_id,
            name="Front Office FC",
            manager="Abhishek Babu",
            overall_points=412,
            overall_rank=340112,
            current_event=self.upcoming - 1,
            leagues=self.leagues,
        )

    def get_squad(self, entry_id: int, gameweek: int) -> Squad:
        self.squad_requests.append(gameweek)
        return self.squad

    def get_players(self) -> dict[int, Player]:
        return self.players if self.players is not None else {**SQUAD_PLAYERS, **MARKET}

    def get_past_seasons(self, element_id: int) -> list[PastSeason]:
        if self.past_seasons_error:
            raise self.past_seasons_error
        return self.past_seasons

    def get_history(self, entry_id: int) -> list[GameweekResult]:
        return self.history

    def get_h2h_match(self, league_id: int, entry_id: int, gameweek: int) -> H2HMatch | None:
        return H2HMatch(opponent_entry=99, opponent_name="Rival FC", my_points=40, opponent_points=52)

    def get_fixtures(self, gameweek: int) -> list[Fixture]:
        if self.fixtures_error:
            raise self.fixtures_error
        return self.fixtures

    def get_clubs(self) -> dict[str, Club]:
        if self.clubs_error:
            raise self.clubs_error
        return {c.short_name: c for c in self.clubs}

    def get_chips(self) -> list[Chip]:
        if self.chips_error:
            raise self.chips_error
        return self.chips

    def get_chips_played(self, entry_id: int) -> list[ChipPlay]:
        if self.chips_error:
            raise self.chips_error
        return self.chips_played

    def current_gameweek(self) -> Gameweek | None:
        return next((gw for gw in self.get_gameweeks() if gw.is_current), None)

    def get_live(self, gameweek: int) -> dict[int, LiveStat]:
        if self.live_error:
            raise self.live_error
        return self.live

    def get_gameweeks(self) -> list[Gameweek]:
        return [
            Gameweek(
                id=i,
                name=f"Gameweek {i}",
                deadline=datetime(2026, 8, 8, 17, 30, tzinfo=UTC) + timedelta(days=i - 1),
                # The one being played is the one before the next deadline,
                # which is the whole distinction this fake exists to model.
                is_current=i == self.upcoming - 1,
                average_score=50,
            )
            for i in range(1, 39)
        ]

    def get_h2h_season(self, league_id: int, entry_id: int) -> dict[int, H2HMatch]:
        if self.h2h_season_error:
            raise self.h2h_season_error
        return self.h2h_season

    def get_standings(self, league_id: int, is_h2h: bool) -> list[TableRow]:
        if self.standings_error:
            raise self.standings_error
        return self.standings


def _with_fake[**P](fake: Callable[P, FakeFPL]) -> Callable[P, FPLProvider]:
    """A provider over a fake built from the same keywords the fake takes, each one checked against it."""

    def build(*args: P.args, **kwargs: P.kwargs) -> FPLProvider:
        return FPLProvider(ENTRY_ID, client=fake(*args, **kwargs))

    return build


provider = _with_fake(FakeFPL)
