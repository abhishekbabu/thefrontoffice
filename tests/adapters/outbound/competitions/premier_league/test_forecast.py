"""Tests for a head-to-head gameweek as the simulation reads it: elevens, captains, benches, blanks and doubles."""

from dataclasses import replace

from support.fpl import BENCH_IDS, SQUAD_PLAYERS, STARTING_IDS, game, player

from thefrontoffice.adapters.outbound.competitions.premier_league.forecast import (
    Gameweek,
    everyone,
    matchup,
    recent_from,
    side,
)
from thefrontoffice.adapters.outbound.competitions.premier_league.rules import Roster, roster
from thefrontoffice.adapters.outbound.platforms.fpl.types import LiveStat, Opponent, Pick, Player, Squad
from thefrontoffice.application.forecasting import simulate

CLUBS = ("ARS", "MCI")


def squad(captain: int = 8, chip: str = "", multiplier: int = 2, catalog: dict[int, Player] | None = None) -> Roster:
    picks = [
        Pick(element=pid, position=i, multiplier=multiplier if pid == captain else 1, is_captain=pid == captain)
        for i, pid in enumerate(STARTING_IDS, start=1)
    ]
    picks += [Pick(element=pid, position=i, multiplier=0) for i, pid in enumerate(BENCH_IDS, start=12)]
    return roster(Squad(gameweek=10, picks=picks, bank=0, value=1000, active_chip=chip), catalog or SQUAD_PLAYERS)


def week(
    fixtures: dict[str, list[Opponent]] | None = None,
    games: dict[int, list] | None = None,
    live: dict[int, LiveStat] | None = None,
    to_come: bool = True,
) -> Gameweek:
    return Gameweek(
        fixtures=fixtures if fixtures is not None else {club: [Opponent("LIV", 3, True)] for club in CLUBS},
        games=games or {},
        live=live or {},
        recent_from=3,
        to_come=to_come,
    )


def by_id(drawn: tuple) -> dict[str, list]:
    found: dict[str, list] = {}
    for o in drawn:
        found.setdefault(o.player_id, []).append(o)
    return found


def test_each_match_he_played_lately_is_one_draw_and_a_missed_one_counts_against_him_playing() -> None:
    games = {8: [game(2, 15), game(3, 6), game(4, 0, minutes=0), game(5, 9)]}
    drawn = by_id(side(squad(captain=9), week(games=games), "mine"))["8"][0]

    assert drawn.samples == (6.0, 9.0)  # GW2 is before the window
    assert round(drawn.plays, 2) == 0.67  # played two of the three recent matches


def test_fpls_own_chance_stands_in_for_how_often_he_played_and_ruled_out_is_nought() -> None:
    catalog = {
        **SQUAD_PLAYERS,
        3: player(3, "DEF", 6.0, status="d", chance_of_playing=75),
        4: player(4, "DEF", 5.0, status="i"),
    }
    drawn = by_id(side(squad(catalog=catalog), week(), "mine"))

    assert drawn["3"][0].plays == 0.75
    assert drawn["4"][0].plays == 0.0


def test_a_player_with_no_recent_match_is_drawn_from_his_points_a_match() -> None:
    drawn = by_id(side(squad(), week(), "mine"))["3"][0]
    assert drawn.samples == (6.0,)
    assert drawn.plays == 1.0


def test_the_captain_counts_twice_on_the_same_draw_and_triple_captain_three_times() -> None:
    assert len(by_id(side(squad(captain=8), week(), "mine"))["8"]) == 2
    # A gameweek to come is played with last week's picks, not last week's chip.
    assert len(by_id(side(squad(captain=8, multiplier=3), week(), "mine"))["8"]) == 2
    assert len(by_id(side(squad(captain=8, multiplier=3), week(to_come=False), "mine"))["8"]) == 3


def test_a_blank_plays_no_match_and_a_double_plays_two() -> None:
    fixtures = {"ARS": [Opponent("LIV", 3, True), Opponent("CHE", 4, False)]}  # Man City blank
    drawn = by_id(side(squad(), week(fixtures=fixtures), "mine"))

    assert drawn["3"][0].games == 2
    assert drawn["1"][0].games == 2


def test_a_bench_player_comes_on_with_the_chance_enough_starters_ahead_of_him_miss_out() -> None:
    # P1 (keeper) and P3 are at Man City, which blanks: the bench keeper and the first outfielder come on.
    catalog = {**SQUAD_PLAYERS, 1: replace(SQUAD_PLAYERS[1], team="MCI"), 3: replace(SQUAD_PLAYERS[3], team="MCI")}
    fixtures = {"ARS": [Opponent("LIV", 3, True)]}
    drawn = by_id(side(squad(catalog=catalog), week(fixtures=fixtures), "mine"))

    # P2, the bench keeper, is himself at Man City: he comes on, and adds nothing.
    assert drawn["2:bench:mine"][0].games == 0
    assert drawn["12:bench:mine"][0].plays == 1.0
    assert "14:bench:mine" not in drawn  # nobody else is missing


def test_a_doubt_ahead_brings_the_bench_on_for_his_share_alone() -> None:
    catalog = {**SQUAD_PLAYERS, 3: player(3, "DEF", 6.0, status="d", chance_of_playing=75)}
    drawn = by_id(side(squad(catalog=catalog), week(), "mine"))
    assert drawn["12:bench:mine"][0].plays == 0.25


def test_bench_boost_counts_all_fifteen_once_its_picks_are_published() -> None:
    drawn = by_id(side(squad(chip="bboost"), week(to_come=False), "mine"))
    assert {"2", "12", "14", "15"} <= set(drawn)


def test_what_he_has_already_is_on_the_board_and_a_match_under_way_is_counted_played() -> None:
    fixtures = {club: [Opponent("LIV", 3, True, started=True)] for club in CLUBS}
    live = {8: LiveStat(points=7, minutes=60), 3: LiveStat(points=0, minutes=0)}
    drawn = by_id(side(squad(), week(fixtures=fixtures, live=live, to_come=False), "mine"))

    assert (drawn["8"][0].floor, drawn["8"][0].games) == (7.0, 0)
    # His match is behind him and he had no part in it: the bench comes on for him.
    assert drawn["12:bench:mine"][0].plays == 1.0


def test_the_same_eleven_on_both_sides_is_one_draw_so_nothing_is_in_it() -> None:
    """A player both managers own scores the same for both: drawn once, he cancels out."""
    games = {pid: [game(5, 2), game(6, 12)] for pid in STARTING_IDS}
    assert simulate(matchup(squad(), squad(), week(games=games), seed=1), simulations=500).win == 0.5


def test_a_stronger_eleven_is_favoured() -> None:
    games = {pid: [game(5, 12)] for pid in STARTING_IDS}
    weak = {pid + 200: replace(p, id=pid + 200, points_per_game=1.0) for pid, p in SQUAD_PLAYERS.items()}
    picks = [Pick(element=pid + 200, position=i, multiplier=1) for i, pid in enumerate(STARTING_IDS, start=1)]
    rival = roster(Squad(gameweek=10, picks=picks, bank=0, value=1000), weak)

    assert simulate(matchup(squad(), rival, week(games=games), seed=1), simulations=500).win > 0.9


def test_the_logs_a_forecast_reads_are_everyone_once() -> None:
    assert sorted(everyone(squad(), squad())) == sorted(SQUAD_PLAYERS)


def test_the_window_reaches_eight_gameweeks_back_and_never_before_the_first() -> None:
    assert recent_from(11) == 3
    assert recent_from(4) == 1
