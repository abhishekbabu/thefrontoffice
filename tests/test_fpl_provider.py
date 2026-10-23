"""Tests for the Fantasy Premier League provider.

The assertions are mostly on prompt content: the rules of the game are what
the prompt has to carry, and a report that omits the captaincy or the transfer
allowance is wrong however well it renders.
"""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from conftest import mine

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
from thefrontoffice.domain.errors import FPLAPIError, LeagueNotFoundError, PlayerNotFoundError, TeamNotFoundError
from thefrontoffice.domain.models import PlayerQuery

ENTRY_ID = 77
LEAGUE_ID = "900"
H2H_LEAGUE_ID = "950"


def player(pid: int, position: str, points: float, cost: int = 50, team: str = "ARS", **kwargs: object) -> Player:
    return Player(
        id=pid,
        name=f"P{pid}",
        full_name=f"Player {pid}",
        position=position,
        team=team,
        cost=cost,
        expected_points=points,
        form=points,
        points_per_game=points,
        total_points=int(points * 10),
        selected_by=5.0,
        minutes=900,
        **kwargs,  # type: ignore[arg-type]
    )


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
    """Stands in for FPLClient."""

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
    ) -> None:
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
        return {**SQUAD_PLAYERS, **MARKET}

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
                deadline=datetime(2026, 8, 7 + i, 17, 30, tzinfo=UTC),
                # The one being played is the one before the next deadline,
                # which is the whole distinction this fake exists to model.
                is_current=i == self.upcoming - 1,
                average_score=50,
            )
            for i in range(1, 9)
        ]

    def get_h2h_season(self, league_id: int, entry_id: int) -> dict[int, H2HMatch]:
        if self.h2h_season_error:
            raise self.h2h_season_error
        return self.h2h_season

    def get_standings(self, league_id: int, is_h2h: bool) -> list[TableRow]:
        if self.standings_error:
            raise self.standings_error
        return self.standings


def provider(**kwargs: object) -> FPLProvider:
    return FPLProvider(ENTRY_ID, client=FakeFPL(**kwargs))  # type: ignore[arg-type]


# ── configuration ───────────────────────────────────────────────────────


def test_an_unset_entry_id_is_reported_before_any_request() -> None:
    with pytest.raises(LeagueNotFoundError, match="FPL_ENTRY_ID"):
        FPLProvider(None, client=FakeFPL()).list_leagues()  # type: ignore[arg-type]


def test_the_registry_advertises_no_trade_support() -> None:
    """FPL managers transfer against the market; they do not trade each other."""
    assert not hasattr(FPLProvider, "build_trade_context")


# ── leagues ─────────────────────────────────────────────────────────────


def test_only_invitational_leagues_are_listed() -> None:
    """Everyone is in Overall and in one league per gameweek; nobody competes there."""
    refs = provider().list_leagues()
    assert [ref.name for ref in refs] == ["Work League", "Hood h2h"]
    assert refs[0].league_id == LEAGUE_ID
    assert "3 of 12" in refs[0].detail


def test_a_manager_in_no_private_league_still_has_something_to_scout() -> None:
    refs = provider(leagues=[]).list_leagues()
    assert refs[0].league_id == str(ENTRY_ID)
    assert "overall rank 340,112" in refs[0].detail


# ── the squad ───────────────────────────────────────────────────────────


def test_the_squad_read_is_the_last_completed_gameweek() -> None:
    """Picks are published only once a deadline passes."""
    client = FakeFPL()
    FPLProvider(ENTRY_ID, client=client).roster(LEAGUE_ID)  # type: ignore[arg-type]
    assert client.squad_requests == [4]


def test_before_the_season_there_is_no_squad_to_read() -> None:
    with pytest.raises(FPLAPIError, match="season has not started"):
        provider(upcoming=1).roster(LEAGUE_ID)


def test_roster_rows_mark_the_captain_and_the_bench() -> None:
    rows = {c.columns["Player"]: c.columns for c in provider().roster(LEAGUE_ID)}
    assert rows["P8"]["Slot"] == "C"
    assert rows["P3"]["Slot"] == "XI"
    assert rows["P15"]["Slot"] == "BN"
    assert rows["P3"]["Price"] == "£5.0m"


def test_roster_rows_report_a_doubt() -> None:
    squad = Squad(gameweek=4, picks=_picks(), bank=30, value=1004)
    fake = FakeFPL(squad=squad)
    fake.get_players = lambda: {  # type: ignore[method-assign]
        **{k: v for k, v in SQUAD_PLAYERS.items() if k != 3},
        3: player(3, "DEF", 6.0, status="d", chance_of_playing=50),
        **MARKET,
    }
    rows = {c.columns["Player"]: c.columns for c in FPLProvider(ENTRY_ID, client=fake).roster(LEAGUE_ID)}
    assert rows["P3"]["Status"] == "doubtful 50%"


# ── the prompt ──────────────────────────────────────────────────────────


def test_the_prompt_shows_the_eleven_that_is_set_not_the_best_one() -> None:
    """Otherwise the changes block recommends starting someone already listed."""
    prompt = provider().build_context(LEAGUE_ID).prompt
    eleven = prompt.split("YOUR CURRENT ELEVEN")[1].split("BENCH")[0]
    assert "- P7 " in eleven
    assert "- P15 " not in eleven


def test_the_prompt_names_the_captain_the_manager_chose() -> None:
    eleven = provider().build_context(LEAGUE_ID).prompt.split("YOUR CURRENT ELEVEN")[1].split("BENCH")[0]
    assert "- P8 (C)" in eleven


def test_the_bench_keeps_its_substitution_order() -> None:
    """Auto-subs come on in the order the manager listed, so it is a decision."""
    bench = provider().build_context(LEAGUE_ID).prompt.split("BENCH (in substitution")[1].split("LINEUP CHANGES")[0]
    listed = [line.split()[1] for line in bench.splitlines() if line.startswith("- ")]
    assert listed == ["P2", "P12", "P14", "P15"]


def test_the_implied_change_pairs_the_two_players() -> None:
    prompt = provider().build_context(LEAGUE_ID).prompt
    changes = prompt.split("LINEUP CHANGES")[1].split("FIXTURES")[0]
    assert "START P15 (FWD) for P7" in changes


def test_the_prompt_states_the_transfer_allowance_and_the_cost_of_exceeding_it() -> None:
    prompt = provider().build_context(LEAGUE_ID).prompt
    # Four unused gameweeks, so the allowance has rolled up to its cap.
    assert "FREE TRANSFERS: 5." in prompt
    assert "costs 4 points" in prompt
    assert "at most 5 transfer(s)" in prompt


def test_the_prompt_states_the_bank_in_the_games_own_units() -> None:
    assert "£3.0m in the bank" in provider(bank=30).build_context(LEAGUE_ID).prompt


def test_the_prompt_quantifies_what_the_best_shape_would_add() -> None:
    constraints = provider().build_context(LEAGUE_ID).constraints
    assert "best legal eleven is a" in constraints
    assert "more than the current shape" in constraints


def test_a_chip_played_last_gameweek_is_flagged() -> None:
    assert "CHIP PLAYED LAST GAMEWEEK: bboost" in provider(active_chip="bboost").build_context(LEAGUE_ID).prompt


def test_points_left_on_the_bench_are_flagged() -> None:
    assert "7 points were left on the bench" in provider(points_on_bench=7).build_context(LEAGUE_ID).prompt


def test_the_mini_league_standing_is_carried() -> None:
    assert "MINI-LEAGUE: Work League — 3 of 12" in provider().build_context(LEAGUE_ID).prompt


# ── fixtures ────────────────────────────────────────────────────────────


def test_a_fixture_carries_its_difficulty_and_whether_it_is_at_home() -> None:
    fixtures = provider().build_context(LEAGUE_ID).prompt.split("FIXTURES THIS GAMEWEEK")[1].split("AFFORDABLE")[0]
    assert "- ARS: vs LIV (difficulty 2)" in fixtures


def test_a_club_with_no_fixture_is_called_a_blank() -> None:
    """The most important thing the report can be told: those players score zero."""
    fixtures = provider().build_context(LEAGUE_ID).prompt.split("FIXTURES THIS GAMEWEEK")[1].split("AFFORDABLE")[0]
    assert "- MCI: no fixture — blank gameweek, every MCI player scores 0." in fixtures


def test_two_fixtures_in_one_gameweek_are_called_a_double() -> None:
    doubled = [
        Fixture(event=5, home="ARS", away="LIV", home_difficulty=2, away_difficulty=4),
        Fixture(event=5, home="MCI", away="ARS", home_difficulty=3, away_difficulty=5),
    ]
    fixtures = provider(fixtures=doubled).build_context(LEAGUE_ID).prompt.split("FIXTURES THIS GAMEWEEK")[1]
    assert "double gameweek" in fixtures


def test_losing_the_fixtures_shrinks_the_prompt_rather_than_failing() -> None:
    prompt = provider(fixtures_error=FPLAPIError("down")).build_context(LEAGUE_ID).prompt
    assert "- (unavailable)" in prompt


# ── the market ──────────────────────────────────────────────────────────


def test_owned_players_are_not_offered_in_the_market() -> None:
    market = provider().build_context(LEAGUE_ID).prompt.split("TOP AVAILABLE PLAYERS")[1]
    assert "- P8 " not in market
    assert "- P101 " in market


def test_an_unavailable_player_is_not_offered() -> None:
    market = provider().build_context(LEAGUE_ID).prompt.split("TOP AVAILABLE PLAYERS")[1]
    assert "P103" not in market


def test_a_transfer_beyond_the_bank_is_not_offered() -> None:
    """P102 is £20.0m against a squad's cheapest £5.0m and a £3.0m bank."""
    transfers = provider().build_context(LEAGUE_ID).prompt.split("AFFORDABLE TRANSFERS")[1].split("TOP AVAILABLE")[0]
    assert "P100" in transfers
    assert "P102" not in transfers


def test_the_briefing_keeps_the_squad_and_only_the_players_named() -> None:
    from reports import MOCK_FPL_REPORT

    context = provider().build_context(LEAGUE_ID)
    briefing = context.briefing(MOCK_FPL_REPORT)
    assert "P8" in briefing
    assert len(briefing) < len(context.prompt)
    assert "re-run the report" in briefing


# ── nothing to say ──────────────────────────────────────────────────────


def test_an_optimal_eleven_produces_no_change_recommendations() -> None:
    """Silence would read as "we did not check", so the absence is stated."""
    from thefrontoffice.adapters.outbound.competitions.premier_league.squad import best_lineup

    best = best_lineup(list(SQUAD_PLAYERS.values()))
    optimal = [Pick(element=p.id, position=i, multiplier=1) for i, p in enumerate(best.starters, start=1)]
    optimal += [Pick(element=p.id, position=i, multiplier=0) for i, p in enumerate(best.bench, start=12)]
    squad = Squad(gameweek=4, picks=optimal, bank=30, value=1004)

    prompt = FPLProvider(ENTRY_ID, client=FakeFPL(squad=squad)).build_context(LEAGUE_ID).prompt
    assert "already the best legal shape" in prompt


def test_an_empty_bank_with_no_upgrade_says_so() -> None:
    prompt = provider(bank=0).build_context(LEAGUE_ID).prompt
    transfers = prompt.split("AFFORDABLE TRANSFERS")[1].split("TOP AVAILABLE")[0]
    assert "nothing in the bank buys an upgrade" in transfers


# ── headline figures ────────────────────────────────────────────────────


def _headline(**kwargs: object) -> dict[str, str]:
    context = provider(**kwargs).build_context(LEAGUE_ID)
    return {stat.label: stat.value for stat in context.headline}


def test_the_header_carries_the_squads_standing_and_its_money() -> None:
    labels = _headline()
    assert labels["Points"] == "412"
    assert labels["Overall"] == "340,112"
    assert labels["Mini-league"] == "3 of 12"
    assert labels["Bank"] == "£3.0m"


def test_points_left_on_the_bench_are_the_figure_that_warns() -> None:
    """The only entry that is a mistake rather than a fact."""
    context = provider().build_context(LEAGUE_ID)
    bench = next(stat for stat in context.headline if stat.label == "On bench")
    assert bench.tone == "warning"


def test_an_optimal_eleven_leaves_nothing_on_the_bench_to_report() -> None:
    from thefrontoffice.adapters.outbound.competitions.premier_league.squad import best_lineup

    best = best_lineup(list(SQUAD_PLAYERS.values()))
    # Captained, because FPL always is — and the comparison only holds between
    # two elevens that each count a captain twice.
    picks = [
        Pick(element=p.id, position=i, multiplier=2 if p is best.captain else 1, is_captain=p is best.captain)
        for i, p in enumerate(best.starters, start=1)
    ]
    picks += [Pick(element=p.id, position=i, multiplier=0) for i, p in enumerate(best.bench, start=12)]
    squad = Squad(gameweek=4, picks=picks, bank=30, value=1004)

    context = FPLProvider(ENTRY_ID, client=FakeFPL(squad=squad)).build_context(LEAGUE_ID)
    assert not [stat for stat in context.headline if stat.label == "On bench"]


def test_a_manager_in_no_mini_league_gets_no_mini_league_figure() -> None:
    assert "Mini-league" not in _headline(leagues=[])


def test_the_header_names_the_gameweek_and_when_it_locks() -> None:
    """A transfer after the deadline counts for the week after it."""
    labels = _headline()

    assert labels["Gameweek"] == "5"
    assert labels["Deadline"].endswith("UTC")


def test_the_summary_marks_the_captain_and_the_doubts() -> None:
    """Starting a ruled-out player is the mistake the page exists to surface."""
    summary = provider().summary(LEAGUE_ID)
    spots = {spot.player.replace(" (C)", ""): spot for spot in mine(summary).lineup}

    assert any(spot.player.endswith("(C)") for spot in mine(summary).lineup)
    assert spots["P7"].tone == "neutral"
    assert summary.swaps  # P15 is the strongest forward and starts on the bench


def test_a_competition_with_no_action_list_says_none_rather_than_nothing_to_do() -> None:
    """An empty list would read as "all done" on a page that never checked."""
    assert provider().summary(LEAGUE_ID).actions is None


def test_the_summary_reports_a_blank_gameweek_on_the_player_not_just_the_club() -> None:
    """A club with no fixture means every one of its players scores zero."""
    summary = provider(fixtures=[]).summary(LEAGUE_ID)

    assert all("no fixture" in spot.detail for spot in mine(summary).lineup)
    assert all(spot.tone == "warning" for spot in mine(summary).lineup)


# ── the matchup ─────────────────────────────────────────────────────────


def test_a_head_to_head_league_shows_who_you_are_playing() -> None:
    summary = provider().summary(H2H_LEAGUE_ID)

    assert summary.opponent is not None
    assert summary.opponent.name == "Rival FC"
    assert summary.opponent.lineup


def test_a_classic_league_has_no_opponent_to_show() -> None:
    """A table is not a fixture, so inventing one would be a lie."""
    assert provider().summary(LEAGUE_ID).opponent is None


def test_the_squads_say_which_gameweek_they_were_fielded_in() -> None:
    """Picks are only published once locked, while every projection beside them
    is for the gameweek still open."""
    summary = provider().summary(LEAGUE_ID)

    assert summary.mine is not None
    assert "GW4" in mine(summary).detail


def test_only_a_blank_or_a_double_is_worth_warning_about() -> None:
    """Every row already carries its own fixture; listing them all repeats the
    page back at itself."""
    warnings = {stat.label: stat for stat in provider().summary(LEAGUE_ID).fixtures}

    assert warnings["MCI"].tone == "warning"  # no fixture in the fake week
    assert "ARS" not in warnings  # an ordinary fixture is not a warning


# ── one player ──────────────────────────────────────────────────────────


def test_a_player_carries_the_numbers_fpl_judges_them_on() -> None:
    """Expected goals arrive in the same payload as the price, which is why
    this sport needs no second stats provider."""
    detail = provider().player(LEAGUE_ID, "8")
    labels = {stat.label for group in detail.groups for stat in group.stats}

    assert detail.name == "Player 8"
    assert {"xG", "xA", "xGI", "Form", "Owned by", "Price"} <= labels


def test_a_players_fixture_is_for_the_gameweek_still_open() -> None:
    detail = provider().player(LEAGUE_ID, "8")
    assert any(stat.label == "Fixture" for group in detail.groups for stat in group.stats)


def test_a_flagged_player_is_toned_and_carries_the_news() -> None:
    fake = FakeFPL()
    fake.get_players = lambda: {  # type: ignore[method-assign]
        **SQUAD_PLAYERS,
        3: player(3, "DEF", 6.0, status="i", chance_of_playing=0, news="Hamstring - expected back 12 Sep"),
        **MARKET,
    }
    detail = FPLProvider(ENTRY_ID, client=fake).player(LEAGUE_ID, "3")

    assert detail.tone == "warning"
    assert "Hamstring" in detail.note


def test_an_unknown_player_is_refused_by_name() -> None:
    with pytest.raises(PlayerNotFoundError, match="nope"):
        provider().player(LEAGUE_ID, "nope")


def test_a_players_numbers_are_grouped_rather_than_listed() -> None:
    """Twenty figures in one list is a wall; the same twenty under headings can
    be read without looking for anything."""
    titles = [group.title for group in provider().player(LEAGUE_ID, "8").groups]

    assert titles == ["This week", "Underlying", "Set pieces", "Market"]


def test_set_pieces_list_only_the_duties_actually_held() -> None:
    """ "Not on penalties" for every player who is not would be rows of nothing."""
    fake = FakeFPL()
    fake.get_players = lambda: {  # type: ignore[method-assign]
        **SQUAD_PLAYERS,
        8: player(8, "MID", 8.0, penalties_order=1, corners_order=2),
        **MARKET,
    }
    detail = FPLProvider(ENTRY_ID, client=fake).player(LEAGUE_ID, "8")
    pieces = next(g for g in detail.groups if g.title == "Set pieces")

    assert [(s.label, s.value) for s in pieces.stats] == [("Penalties", "#1"), ("Corners", "#2")]
    assert pieces.stats[0].tone == "good"  # first choice is worth noticing


def test_a_player_on_no_set_pieces_says_so_once() -> None:
    pieces = next(g for g in provider().player(LEAGUE_ID, "8").groups if g.title == "Set pieces")
    assert [s.value for s in pieces.stats] == ["none"]


def test_a_keeper_gets_the_numbers_only_a_keeper_has() -> None:
    """Saves on an attacker is a zero nobody asked for."""
    labels = {row.label for row in provider().player(LEAGUE_ID, "1").tables[0].rows}
    assert {"Saves", "Clean sheets", "Conceded"} <= labels


def test_an_attacker_is_not_given_a_keepers_line() -> None:
    labels = {row.label for row in provider().player(LEAGUE_ID, "13").tables[0].rows}
    assert "Saves" not in labels


# ── the seasons behind the price ────────────────────────────────────────


def _season_table(**kwargs: object) -> dict[str, list[str]]:
    """The by-season table as {row label: values}, columns newest first."""
    detail = provider(**kwargs).player(LEAGUE_ID, "8")
    table = detail.tables[0]
    return {"__columns__": table.columns, **{row.label: row.values for row in table.rows}}


def test_the_seasons_are_columns_so_they_can_be_read_across() -> None:
    """A stack makes you hold last year's goals in your head while scrolling
    to this year's."""
    table = _season_table()

    assert table["__columns__"] == ["2025/26", "2024/25", "2023/24"]


def test_the_current_season_leads_the_table() -> None:
    """It is the one the others are being compared against."""
    assert _season_table()["__columns__"][0] == "2025/26"


def test_a_season_nobody_has_played_yet_reports_nothing() -> None:
    """A column of noughts claims the season has answers it does not have."""
    table = _season_table()

    assert table["Points"][0] == "N/A"
    assert table["Goals"][0] == "N/A"


def test_a_finished_season_is_scored_per_start_not_per_appearance() -> None:
    """A substitute cameo and a full ninety are not the same denominator."""
    assert _season_table()["Per start"][1] == f"{210 / 33:.1f}"


def test_a_finished_season_carries_the_markets_verdict_on_it() -> None:
    """What the price did over it is the closest thing FPL has to one."""
    assert _season_table()["Price"][1] == "£11.8m → £12.4m"


def test_a_price_is_known_whether_or_not_the_season_has_started() -> None:
    """Unlike a total, it is a fact about today rather than an accumulation —
    N/A against a number the market view shows would be wrong."""
    assert _season_table()["Price"][0] == "£5.0m"


def test_a_player_with_no_history_still_gets_a_column_for_this_season() -> None:
    """A promoted club's signing has no FPL record, which is not an error."""
    table = _season_table(past_seasons=[])

    assert table["__columns__"] == ["This season"]


def test_a_failed_history_lookup_does_not_take_the_player_down() -> None:
    """Everything else on the page was already fetched and is still true."""
    detail = provider(past_seasons_error=FPLAPIError("down")).player(LEAGUE_ID, "8")

    assert detail.name
    assert detail.tables[0].columns == ["This season"]


def test_a_player_carries_a_portrait_keyed_by_optas_code() -> None:
    """Not the element id, which FPL reassigns between seasons."""
    fake = FakeFPL()
    catalog = fake.get_players()
    catalog[8] = replace(catalog[8], code=223094)
    fake.get_players = lambda: catalog  # type: ignore[method-assign]

    detail = FPLProvider(ENTRY_ID, client=fake).player(LEAGUE_ID, "8")
    assert detail.image_url.endswith("/p223094.png")


def test_a_player_with_no_photo_code_is_given_no_url() -> None:
    """An empty string is a missing photo; a URL built from zero is a 404."""
    fake = FakeFPL()
    catalog = fake.get_players()
    catalog[8] = replace(catalog[8], code=0)
    fake.get_players = lambda: catalog  # type: ignore[method-assign]

    detail = FPLProvider(ENTRY_ID, client=fake).player(LEAGUE_ID, "8")
    assert detail.image_url == ""


# ── the league beyond this gameweek ─────────────────────────────────────

H2H_LEAGUE = "950"


def test_the_season_lists_every_gameweek_with_its_deadline() -> None:
    """A gameweek is bounded by its deadline: after it nothing can change."""
    season = provider().schedule(H2H_LEAGUE).season

    assert [row.label for row in season[:3]] == ["Gameweek 1", "Gameweek 2", "Gameweek 3"]
    assert season[0].date == "Sat 8 Aug, 17:30"


def test_a_played_gameweek_carries_its_tie_and_whether_it_was_won() -> None:
    season = {row.label: row for row in provider().schedule(H2H_LEAGUE).season}

    assert season["Gameweek 1"].result == "60-44"
    assert season["Gameweek 1"].tone == "good"
    assert season["Gameweek 2"].tone == "warning"


def test_the_row_marked_now_is_the_one_being_played() -> None:
    """Not the next deadline. The week view and the season table have to agree
    about which row is "now", or one of them is describing a different week."""
    season = {row.label: row for row in provider().schedule(H2H_LEAGUE).season}
    current = [row.label for row in season.values() if row.is_current]

    assert current == ["Gameweek 4"]
    assert season["Gameweek 4"].result == ""  # in progress is not a result


def test_a_classic_league_has_deadlines_but_no_opponents() -> None:
    """It is a running table, not a set of fixtures — and the calendar is
    still what somebody came for."""
    season = provider().schedule("900").season

    assert all(row.opponent == "" for row in season)
    assert all(row.date for row in season)


def test_the_table_says_which_row_is_yours() -> None:
    standings = provider().schedule(H2H_LEAGUE).standings

    assert [row.name for row in standings] == ["Rival FC", "Front Office FC"]
    assert [row.is_mine for row in standings] == [False, True]


def test_an_h2h_table_shows_league_points_and_the_tiebreak() -> None:
    """The table is on league points; the FPL total decides ties."""
    standings = provider().schedule(H2H_LEAGUE).standings

    assert standings[0].points == "6 (104 pts)"
    assert standings[0].record == "2W 0D 0L"


def test_a_classic_table_is_just_the_points() -> None:
    standings = provider().schedule("900").standings

    assert standings[0].points == "6"


def test_the_matches_carry_a_difficulty_for_each_side() -> None:
    """A fixture is easy for one of these clubs and hard for the other."""
    matches = provider().schedule(H2H_LEAGUE).matches

    assert matches
    assert all("FDR" in m.detail for m in matches)


def test_fpl_has_no_activity_feed_so_there_is_no_empty_promise() -> None:
    assert provider().schedule(H2H_LEAGUE).activity == []


def test_a_failed_table_leaves_the_rest_of_the_page() -> None:
    schedule = provider(standings_error=FPLAPIError("down")).schedule(H2H_LEAGUE)

    assert schedule.standings == []
    assert schedule.season


def test_a_failed_h2h_season_still_lists_the_gameweeks() -> None:
    schedule = provider(h2h_season_error=FPLAPIError("down")).schedule(H2H_LEAGUE)

    assert schedule.season
    assert all(row.opponent == "" for row in schedule.season)


def test_failed_fixtures_leave_no_matches_rather_than_failing() -> None:
    assert provider(fixtures_error=FPLAPIError("down")).schedule(H2H_LEAGUE).matches == []


def test_the_week_view_shows_the_gameweek_being_played() -> None:
    """The bug this distinction exists for: on a Saturday in August the week
    you can still act on is next week's, and the one being played — where the
    points are landing — is this one."""
    assert provider().summary(H2H_LEAGUE).window.startswith("Gameweek 4")


def test_a_gameweek_with_no_ball_kicked_yet_shows_its_deadline() -> None:
    assert provider().summary(H2H_LEAGUE).window == "Gameweek 4 · deadline Tue 11 Aug, 17:30"


# ── the week as it is actually going ────────────────────────────────────

LIVE = {
    8: LiveStat(points=12, minutes=90),  # played, hauled
    9: LiveStat(points=1, minutes=64),  # played, blanked
    10: LiveStat(points=0, minutes=0),  # kicks off later
}


def test_a_player_who_has_played_shows_what_they_scored() -> None:
    """The number somebody is looking for once a gameweek is under way."""
    spots = {s.player: s for s in mine(provider(live=LIVE).summary(H2H_LEAGUE)).lineup}

    scored = next(s for s in spots.values() if s.value.endswith("pts"))
    assert scored.value in {"12 pts", "24 pts", "1 pts"}


def test_a_haul_and_a_blank_are_toned_apart() -> None:
    lineup = mine(provider(live=LIVE).summary(H2H_LEAGUE)).lineup
    by_value = {s.value: s.tone for s in lineup}

    assert by_value.get("12 pts") == "good" or by_value.get("24 pts") == "good"
    assert by_value.get("1 pts") == "warning"


def test_a_player_yet_to_kick_a_ball_keeps_their_projection() -> None:
    """Nought against somebody whose match is on Sunday says they blanked."""
    lineup = mine(provider(live=LIVE).summary(H2H_LEAGUE)).lineup

    waiting = [s for s in lineup if s.value.endswith("xPts")]
    assert waiting, "a squad of eleven cannot all have played"
    assert all("0 pts" not in s.value for s in waiting)


def test_a_captain_scores_double() -> None:
    lineup = mine(provider(live=LIVE).summary(H2H_LEAGUE)).lineup
    captain = next((s for s in lineup if "(C)" in s.player), None)

    if captain and captain.value.endswith("pts"):
        assert captain.value == "24 pts"


def test_a_week_under_way_says_so_rather_than_naming_a_deadline() -> None:
    assert provider(live=LIVE).summary(H2H_LEAGUE).window == "Gameweek 4 · in progress"


def test_before_a_ball_is_kicked_there_is_no_score() -> None:
    """Zero reads as a bad week rather than a week that has not started."""
    assert mine(provider().summary(H2H_LEAGUE)).points == ""


def test_a_missing_live_feed_falls_back_to_projections() -> None:
    """Enrichment, not a dependency."""
    summary = provider(live_error=FPLAPIError("down")).summary(H2H_LEAGUE)

    assert summary.mine is not None
    assert all(s.value.endswith("xPts") for s in mine(summary).lineup)


# ── the rest of the league ──────────────────────────────────────────────


def test_the_teams_list_puts_you_first() -> None:
    teams = provider().teams(H2H_LEAGUE)

    assert teams[0].is_mine
    assert teams[0].name == "Front Office FC"


def test_the_table_is_the_membership_list() -> None:
    """FPL publishes no separate one, so a league with no readable table has
    no teams to browse either."""
    assert provider(standings_error=FPLAPIError("down")).teams(H2H_LEAGUE) == []


def test_another_managers_squad_comes_back_in_your_own_columns() -> None:
    p = provider()

    mine = p.roster(H2H_LEAGUE)
    theirs = p.roster_of(H2H_LEAGUE, "99")

    assert set(theirs[0].columns) == set(mine[0].columns)


def test_a_team_id_that_is_not_an_entry_is_refused() -> None:
    with pytest.raises(TeamNotFoundError):
        provider().roster_of(H2H_LEAGUE, "not-a-number")


def test_the_market_excludes_what_you_already_own() -> None:
    """FPL has no waiver wire — every player is buyable — so the question is
    not who is free but who is worth the money."""
    owned = {int(card.player_id) for card in provider().roster(H2H_LEAGUE)}

    market = {int(card.player_id) for card in provider().free_agents(H2H_LEAGUE, PlayerQuery()).players}

    assert not (owned & market)


def test_the_market_is_ranked_on_the_games_own_projection() -> None:
    """Which is what a transfer is actually decided on."""
    values = [float(card.columns["xPts"]) for card in provider().free_agents(H2H_LEAGUE, PlayerQuery()).players]

    assert values == sorted(values, reverse=True)


def test_the_market_has_no_lineup_column() -> None:
    """A player you do not own is not in a lineup of yours."""
    assert "Slot" not in provider().free_agents(H2H_LEAGUE, PlayerQuery()).players[0].columns


# ── the way across to the platform ──────────────────────────────────────


def test_a_head_to_head_league_links_to_its_own_kind_of_table() -> None:
    """The two formats are different pages: a h2h league opened as a classic
    one shows a table it does not play by."""
    refs = {ref.name: ref.url for ref in provider().list_leagues()}

    assert refs["Hood h2h"].endswith("/leagues/950/standings/h")
    assert refs["Work League"].endswith("/leagues/900/standings/c")


def test_a_team_links_to_that_managers_entry() -> None:
    teams = {t.name: t.url for t in provider().teams(H2H_LEAGUE)}

    assert teams["Rival FC"] == "https://fantasy.premierleague.com/entry/99/event/1"


def test_a_player_has_no_link_because_fpl_publishes_no_player_page() -> None:
    """An empty string is honest; a constructed URL that 404s is not."""
    assert provider().player(LEAGUE_ID, "8").url == ""


# ── chips, and the armbands ─────────────────────────────────────────────


def _chips(**kwargs: object) -> dict[str, str]:
    boosts = provider(**kwargs).summary(H2H_LEAGUE).boosts
    assert boosts is not None
    return {stat.label: stat.value for stat in boosts.stats}


def test_the_chips_carry_the_leagues_own_word_for_them() -> None:
    """The UI knows nothing about football; the title comes with the data."""
    boosts = provider().summary(H2H_LEAGUE).boosts

    assert boosts is not None
    assert boosts.title == "Chips"


def test_a_chip_inside_its_window_is_available() -> None:
    assert _chips()["Bench Boost"] == "available"


def test_a_chip_whose_window_has_not_opened_says_when_it_does() -> None:
    """A Wildcard cannot be played in GW1, and the game says so rather than
    leaving a manager to find that out at the deadline."""
    assert _chips(upcoming=2)["Wildcard"] == "from GW2"


def test_a_chip_already_played_says_which_week_it_went() -> None:
    played = _chips(chips_played=[ChipPlay(name="bboost", event=3)])

    assert played["Bench Boost"] == "played GW3"


def test_a_chip_whose_windows_have_all_closed_is_still_listed() -> None:
    """An unplayed Free Hit is a thing that was lost, and a row saying so is
    worth more than a row quietly missing."""
    gone = _chips(chips=[Chip(name="freehit", start_event=1, stop_event=2)], upcoming=30)

    assert gone["Free Hit"] == "gone unplayed"


def test_one_row_per_chip_rather_than_one_per_window() -> None:
    """The game issues each twice; a manager decides about the chip."""
    labels = list(_chips())

    assert labels == ["Wildcard", "Free Hit", "Bench Boost", "Triple Captain"]


def test_a_failed_chip_lookup_leaves_the_rest_of_the_week() -> None:
    summary = provider(chips_error=FPLAPIError("down")).summary(H2H_LEAGUE)

    assert summary.boosts is None
    assert summary.mine is not None


def test_the_vice_captain_is_marked_as_well_as_the_captain() -> None:
    """The vice is the whole point when the captain does not play, so a squad
    that shows only the armband shows half the decision."""
    summary = provider().summary(H2H_LEAGUE)
    marked = [s.player for s in mine(summary).lineup + mine(summary).bench if "(" in s.player]

    assert any(p.endswith("(C)") for p in marked)
    assert any(p.endswith("(V)") for p in marked)


def test_the_opponents_armbands_are_marked_too() -> None:
    """Both sides are read across, so they have to say the same things."""
    opponent = provider().summary(H2H_LEAGUE).opponent

    assert opponent is not None
    assert any("(C)" in s.player for s in opponent.lineup)


def test_the_drawer_names_the_club_in_full_with_its_crest() -> None:
    detail = provider().player(LEAGUE_ID, "1")
    assert detail.team_name == "Arsenal"
    # Filed under the club's media code, not its bootstrap id.
    assert detail.team_logo_url == "https://resources.premierleague.com/premierleague/badges/70/t3.png"


def test_a_club_that_will_not_load_falls_back_to_the_abbreviation() -> None:
    """Worse than the full name, no worse than before, and not a failed page."""
    detail = provider(clubs_error=FPLAPIError("down")).player(LEAGUE_ID, "1")
    assert detail.team_name == detail.team
    assert detail.team_logo_url == ""
