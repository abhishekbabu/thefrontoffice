"""Tests for an FPL gameweek as the week view reads it: both squads, the rows, the swaps, the chips."""

from dataclasses import replace

import pytest
from support.fpl import (
    DOUBTFUL_P3,
    ENTRY_ID,
    H2H_LEAGUE_ID,
    LEAGUE_ID,
    MARKET,
    SQUAD_PLAYERS,
    WITH_CITY,
    FakeFPL,
    provider,
)
from support.summary import mine

from thefrontoffice.adapters.outbound.competitions.premier_league import worth
from thefrontoffice.adapters.outbound.competitions.premier_league.fpl import FPLProvider
from thefrontoffice.adapters.outbound.platforms.fpl.errors import FPLAPIError
from thefrontoffice.adapters.outbound.platforms.fpl.types import (
    Chip,
    ChipPlay,
    Fixture,
    GameweekResult,
    LiveStat,
    Pick,
    Squad,
)
from thefrontoffice.domain.errors import NotFoundError
from thefrontoffice.domain.models import Spot, Summary

H2H_LEAGUE = "950"


# ── nothing to say ──────────────────────────────────────────────────────


def test_the_summary_warns_on_a_doubtful_starter() -> None:
    """Starting a doubtful player is the mistake the page exists to surface."""
    lineup = mine(provider(players=DOUBTFUL_P3).summary(LEAGUE_ID)).lineup
    spots = {spot.player_id: spot for spot in lineup}

    assert spots["3"].tone == "warning"


def test_the_summary_lists_the_swap_and_the_armband_the_best_eleven_implies() -> None:
    """P15 is the strongest forward and starts on the bench behind P7; the to-do list carries both moves."""
    summary = provider(fixtures=WITH_CITY).summary(LEAGUE_ID)
    lineup = [(a.player_id, a.replaces) for a in summary.actions or [] if a.kind == "lineup"]

    assert lineup == [("15", "7"), ("15", "")]


def test_the_header_compares_the_eleven_as_set_with_the_best_at_their_worth() -> None:
    """Every ARS and MCI player is at home to a difficulty-2 side: a tenth over his projection.
    The eleven as set expects 64.0 of projection and the best 73.5, each counting its captain twice."""
    summary = provider(fixtures=WITH_CITY).summary(LEAGUE_ID)

    assert _stats(summary)["Lineup"] == f"{64.0 * 1.1:.1f} · best {round(73.5 * 1.1, 2):.1f} pts"


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


# ── the week as it is actually going ────────────────────────────────────

LIVE = {
    8: LiveStat(points=12, minutes=90),  # played, hauled
    9: LiveStat(points=1, minutes=64),  # played, blanked
    10: LiveStat(points=0, minutes=0),  # kicks off later
}


def _live_spots() -> dict[str, Spot]:
    return {s.player_id: s for s in mine(provider(live=LIVE).summary(H2H_LEAGUE)).lineup}


def test_a_haul_is_toned_good() -> None:
    haul = _live_spots()["8"]  # the captain, so doubled

    assert (haul.value, haul.tone) == ("24 pts", "good")


def test_a_blank_is_toned_as_a_warning() -> None:
    blank = _live_spots()["9"]

    assert (blank.value, blank.tone) == ("1 pts", "warning")


def test_a_player_yet_to_kick_a_ball_keeps_their_projection() -> None:
    """Nought against somebody whose match is on Sunday says they blanked."""
    lineup = mine(provider(live=LIVE).summary(H2H_LEAGUE)).lineup

    waiting = [s for s in lineup if s.value.endswith("xPts")]
    assert waiting, "a squad of eleven cannot all have played"
    assert all("0 pts" not in s.value for s in waiting)


def _triple_captain() -> Squad:
    picks = [
        Pick(element=p.element, position=p.position, multiplier=3, is_captain=True) if p.is_captain else p
        for p in FakeFPL().squad.picks
    ]
    return Squad(gameweek=4, picks=picks, bank=30, value=1004, active_chip="3xc")


def test_a_triple_captain_scores_three_times() -> None:
    lineup = mine(provider(live=LIVE, squad=_triple_captain()).summary(H2H_LEAGUE)).lineup
    captain = next(s for s in lineup if s.mark == "C")

    assert captain.value == "36 pts"


def test_the_weeks_total_counts_the_triple_captain_three_times() -> None:
    """P8 (12, captained) and P9 (1) have played; P10 has not kicked a ball."""
    assert mine(provider(live=LIVE, squad=_triple_captain()).summary(H2H_LEAGUE)).points == "37 pts · 72.0 proj"


def test_the_weeks_total_counts_the_captain_twice() -> None:
    assert mine(provider(live=LIVE).summary(H2H_LEAGUE)).points == "25 pts · 64.0 proj"


def test_a_week_under_way_says_so_rather_than_naming_a_deadline() -> None:
    assert provider(live=LIVE).summary(H2H_LEAGUE).window == "Gameweek 4 · in progress"


def test_before_a_ball_is_kicked_a_side_reads_its_projection_alone() -> None:
    """Zero reads as a bad week rather than a week that has not started."""
    assert mine(provider().summary(H2H_LEAGUE)).points == "64.0 proj"


def test_the_opponent_reads_the_games_total_beside_their_projection_once_under_way() -> None:
    summary = provider(live=LIVE, fixtures=[_arsenal(started=True)]).summary(H2H_LEAGUE)

    assert summary.opponent is not None
    assert summary.opponent.points.startswith("52 pts · ")
    assert summary.opponent.points.endswith(" proj")


def _arsenal(*, started: bool = False, finished: bool = False) -> Fixture:
    return Fixture(
        event=4, home="ARS", away="LIV", home_difficulty=2, away_difficulty=4, started=started, finished=finished
    )


def test_a_row_sets_what_he_scored_beside_his_projection_for_this_gameweek() -> None:
    """The captain's guess is doubled as his points are, so the two are the same kind of number."""
    captain = _live_spots()["8"]

    assert (captain.scoring, captain.scored, captain.projection) == ("live", "24", "16.0")


def test_a_row_not_yet_kicked_off_is_projected_with_no_score() -> None:
    waiting = _live_spots()["10"]

    assert (waiting.scoring, waiting.scored, waiting.projection) == ("projected", "", "6.0")


def test_once_his_club_kicks_off_a_nought_is_a_score_not_a_match_to_come() -> None:
    lineup = mine(provider(live=LIVE, fixtures=[_arsenal(started=True)]).summary(H2H_LEAGUE)).lineup
    unused = next(s for s in lineup if s.player_id == "10")

    assert (unused.scoring, unused.scored, unused.value) == ("live", "0", "0 pts")


def test_a_row_is_final_once_every_match_his_club_has_is_over() -> None:
    side = mine(provider(live=LIVE, fixtures=[_arsenal(started=True, finished=True)]).summary(H2H_LEAGUE))
    rows = {s.player_id: s for s in (*side.lineup, *side.bench)}

    assert rows["8"].scoring == "final"
    assert rows["15"].scoring == "projected", "MCI has no fixture this gameweek"


def test_the_projection_is_this_gameweeks_not_the_next() -> None:
    """`ep_next` is next week's guess once a deadline has passed; beside this week's points it misleads."""
    catalog = {pid: replace(p, expected_this=p.expected_points / 2) for pid, p in SQUAD_PLAYERS.items()}
    lineup = mine(provider(live=LIVE, players=catalog).summary(H2H_LEAGUE)).lineup

    assert next(s for s in lineup if s.player_id == "10").projection == "3.0"


def test_a_missing_live_feed_falls_back_to_projections() -> None:
    """Enrichment, not a dependency."""
    summary = provider(live_error=FPLAPIError("down")).summary(H2H_LEAGUE)

    assert summary.mine is not None
    assert all(s.value.endswith("xPts") for s in mine(summary).lineup)


# ── chips, and the armbands ─────────────────────────────────────────────


def _chips(over: FPLProvider | None = None) -> dict[str, str]:
    boosts = (over or provider()).summary(H2H_LEAGUE).boosts
    assert boosts is not None
    return {stat.label: stat.value for stat in boosts.stats}


def test_the_chips_carry_the_leagues_own_word_for_them() -> None:
    """The UI knows nothing about football; the title comes with the data."""
    boosts = provider().summary(H2H_LEAGUE).boosts

    assert boosts is not None
    assert boosts.title == "Chips"


def test_a_chip_inside_its_window_is_available_until_it_closes() -> None:
    assert _chips()["Bench Boost"] == "available until GW19"


def test_the_chips_say_how_many_can_be_played_now_and_when_this_halfs_expire() -> None:
    boosts = provider().summary(H2H_LEAGUE).boosts

    assert boosts is not None
    available = [label for label, value in _chips().items() if value.startswith("available")]
    assert boosts.note.startswith(f"{len(available)} available")
    assert "GW19 deadline" in boosts.note and "Wed 26 Aug" in boosts.note


def test_a_chip_played_in_the_first_half_leaves_the_second_halfs() -> None:
    """The game issues a Wildcard per half; spending one spends only that half's."""
    chips = _chips(provider(upcoming=12, chips_played=[ChipPlay(name="wildcard", event=9)]))

    assert chips["Wildcard"] == "played GW9 · again from GW20"
    assert chips["Free Hit"] == "available until GW19"


def test_a_second_half_chip_is_available_once_the_first_was_played() -> None:
    chips = _chips(provider(upcoming=25, chips_played=[ChipPlay(name="wildcard", event=9)]))

    assert chips["Wildcard"] == "available until GW38"


def test_a_first_half_chip_left_unplayed_says_it_was_lost() -> None:
    chips = _chips(provider(upcoming=25))

    assert chips["Free Hit"] == "available until GW38 · one expired unplayed"
    assert chips["Bench Boost"] == "expired"


def test_a_chip_played_in_its_last_window_says_so_once_the_season_is_past_it() -> None:
    chips = _chips(
        provider(
            chips=[Chip(name="freehit", start_event=1, stop_event=2)],
            upcoming=30,
            chips_played=[ChipPlay(name="freehit", event=2)],
        )
    )

    assert chips["Free Hit"] == "played GW2"


def test_a_chip_whose_window_has_not_opened_says_when_it_does() -> None:
    """A Wildcard cannot be played in GW1, and the game says so rather than
    leaving a manager to find that out at the deadline."""
    assert _chips(provider(upcoming=2))["Wildcard"] == "from GW2"


def test_a_chip_already_played_says_which_week_it_went() -> None:
    played = _chips(provider(chips_played=[ChipPlay(name="bboost", event=3)]))

    assert played["Bench Boost"] == "played GW3"
    assert played["Triple Captain"] == "available until GW19"


def test_a_chip_whose_windows_have_all_closed_is_still_listed() -> None:
    """An unplayed Free Hit is a thing that was lost, and a row saying so is
    worth more than a row quietly missing."""
    gone = _chips(provider(chips=[Chip(name="freehit", start_event=1, stop_event=2)], upcoming=30))

    assert gone["Free Hit"] == "expired"


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
    marks = [s.mark for s in mine(summary).lineup + mine(summary).bench if s.mark]

    assert sorted(marks) == ["C", "VC"]


def test_the_opponents_armbands_are_marked_too() -> None:
    """Both sides are read across, so they have to say the same things."""
    opponent = provider().summary(H2H_LEAGUE).opponent

    assert opponent is not None
    assert any(s.mark == "C" for s in opponent.lineup)


# ── other gameweeks ─────────────────────────────────────────────────────


def _stats(summary: Summary) -> dict[str, str]:
    return {stat.label: stat.value for stat in summary.headline}


def test_the_gameweek_being_played_says_where_it_sits_in_the_season() -> None:
    weeks = provider().summary("900").weeks

    assert weeks is not None
    assert (weeks.week, weeks.current, weeks.first, weeks.last) == (4, 4, 1, 38)


def test_a_gameweek_played_reads_the_squad_picked_for_it_and_what_fpl_credited() -> None:
    fake = FakeFPL(history=[GameweekResult(event=2, points=63, transfers_made=0, transfers_cost=0)])
    summary = FPLProvider(ENTRY_ID, client=fake).week_of("900", 2)

    assert fake.squad_requests == [2]
    assert _stats(summary) == {"Points": "63", "Average": "50"}
    assert mine(summary).points == "63 pts"
    assert summary.window == "Gameweek 2 · final"
    assert summary.opponent is None  # a classic league has no tie
    assert summary.actions is None
    assert summary.weeks is not None and (summary.weeks.week, summary.weeks.current) == (2, 4)


def test_a_head_to_head_gameweek_played_reads_as_its_final_score() -> None:
    summary = provider().week_of("950", 2)

    assert _stats(summary)["Final"] == "40 – 52"
    assert summary.opponent is not None and summary.opponent.points == "52 pts"


def test_the_next_gameweek_is_the_squad_held_now_at_fpls_projection_for_it() -> None:
    fake = FakeFPL()
    summary = FPLProvider(ENTRY_ID, client=fake).week_of("900", 5)

    assert fake.squad_requests == [4]  # its picks are not published until the deadline passes
    assert list(_stats(summary)) == ["Deadline"]
    assert all(spot.value.endswith("xPts") for spot in mine(summary).lineup)
    assert mine(summary).points.endswith("proj")


def test_a_gameweek_further_out_has_no_projection_rather_than_the_next_ones() -> None:
    summary = provider().week_of("900", 8)

    assert {spot.value for spot in mine(summary).lineup} == {"—"}
    assert mine(summary).points == ""


def test_a_gameweek_outside_the_season_is_refused() -> None:
    with pytest.raises(NotFoundError):
        provider().week_of("900", 39)
    with pytest.raises(NotFoundError):
        provider().games_of("900", 0)


# ── once the gameweek is over ───────────────────────────────────────────

FINISHED_LIVE = {8: LiveStat(points=12, minutes=90), 9: LiveStat(points=1, minutes=64)}


def _between_gameweeks() -> FPLProvider:
    """GW4 finished and still FPL's current one; GW5's deadline is next."""
    return provider(finished=4, live=FINISHED_LIVE)


def test_once_the_gameweek_is_over_the_week_view_is_the_next_one() -> None:
    summary = _between_gameweeks().summary(H2H_LEAGUE)

    assert summary.window == "Gameweek 5 · deadline Sat 12 Sep, 00:00"
    assert summary.weeks is not None and (summary.weeks.week, summary.weeks.current) == (5, 5)


def test_the_next_gameweek_shows_the_squad_as_last_picked_at_its_projection() -> None:
    # ep_this is still GW4's; ep_next is the one for GW5.
    catalog = {pid: replace(p, expected_this=0.0) for pid, p in {**SQUAD_PLAYERS, **MARKET}.items()}
    fake = FakeFPL(finished=4, live=FINISHED_LIVE, players=catalog)
    summary = FPLProvider(ENTRY_ID, client=fake).summary(H2H_LEAGUE)
    value = worth.gather(fake, fake.upcoming_gameweek())
    expected = sum(value(catalog[pick.element]) * pick.multiplier for pick in fake.squad.picks)

    assert mine(summary).detail == "GW4 picks"
    assert all(spot.scoring == "projected" for spot in mine(summary).lineup)
    assert mine(summary).points == f"{expected:.1f} proj"  # each at his worth for GW5, the captain doubled
    assert summary.opponent is not None and summary.opponent.points.endswith(" proj")


def test_a_finished_gameweek_browsed_reads_final_with_its_score() -> None:
    summary = _between_gameweeks().week_of(H2H_LEAGUE, 4)

    assert summary.window == "Gameweek 4 · final"
    assert _stats(summary)["Final"] == "40 – 52"


def test_a_finished_gameweek_is_final_however_many_minutes_were_played() -> None:
    """Minutes in a finished week are its history, not a match under way."""
    assert "in progress" not in _between_gameweeks().week_of("900", 4).window


def test_a_gameweek_under_way_browsed_reads_its_live_score() -> None:
    summary = provider(live=LIVE).week_of(H2H_LEAGUE, 4)

    assert summary.window == "Gameweek 4 · in progress"
    assert _stats(summary)["Live"] == "40 – 52"


def test_a_gameweek_whose_matches_are_all_over_reads_final_before_fpl_closes_it() -> None:
    summary = provider(live=LIVE, fixtures=[_arsenal(started=True, finished=True)]).summary(H2H_LEAGUE)

    assert summary.window == "Gameweek 4 · final"


def test_before_the_season_the_week_view_has_no_squad_but_the_league_has_its_calendar() -> None:
    schedule = provider(upcoming=1).schedule(H2H_LEAGUE)

    assert [row.label for row in schedule.season if row.is_current] == ["Gameweek 1"]
    assert all(not m.yours for m in schedule.matches)


# ── what degrades and what fails ────────────────────────────────────────


def test_a_tie_that_will_not_load_leaves_your_own_side() -> None:
    summary = provider(h2h_match_error=FPLAPIError("down")).summary(H2H_LEAGUE)

    assert summary.opponent is None
    assert mine(summary).lineup


def test_a_played_gameweek_without_its_history_reads_no_points_rather_than_nought() -> None:
    summary = provider(history_error=FPLAPIError("down")).week_of(LEAGUE_ID, 2)

    assert "Points" not in _stats(summary)
    assert mine(summary).points == ""


def test_a_season_with_no_chips_issued_shows_no_chips() -> None:
    assert provider(chips=[]).summary(H2H_LEAGUE).boosts is None


def test_the_week_carries_a_to_do_list_even_when_there_is_nothing_to_do() -> None:
    """An empty list is an answer — nothing to do — where None would say nothing was computed."""
    from thefrontoffice.adapters.outbound.competitions.premier_league.rules import best_lineup, effective_points

    best = best_lineup(list(SQUAD_PLAYERS.values()), effective_points)
    picks = [
        Pick(
            element=p.id,
            position=i,
            multiplier=2 if p is best.captain else 1,
            is_captain=p is best.captain,
            is_vice_captain=p is best.vice,
        )
        for i, p in enumerate(best.starters, start=1)
    ]
    picks += [Pick(element=p.id, position=i, multiplier=0) for i, p in enumerate(best.bench, start=12)]
    squad = Squad(gameweek=4, picks=picks, bank=0, value=1004)

    assert provider(squad=squad, fixtures=WITH_CITY, chips=[]).summary(LEAGUE_ID).actions == []
