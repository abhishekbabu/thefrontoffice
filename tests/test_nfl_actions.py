"""Tests for the week's to-do list: `nfl/actions.py`, through the summary.

The fake league plays week 3. Its slots are QB, RB, WR and FLEX, small enough
that every scenario can say exactly who is where.
"""

from dataclasses import replace

from conftest import SLEEPER_USER_ID, FakeSleeper, _proj, _provider

from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    NFLGameLine,
    PlayerMeta,
    ScheduledGame,
    SleeperLeague,
    SleeperRoster,
    WeeklyProjection,
)
from thefrontoffice.domain.models import Action

LEAGUE = SleeperLeague(
    league_id="L1",
    name="Sunday Money",
    season="2026",
    total_rosters=12,
    scoring_format="pts_ppr",
    roster_positions=["QB", "RB", "WR", "FLEX", "BN", "BN", "BN"],
)

# Week 3: BUF-MIA on Thursday, NYJ-NE and KC-LV on Sunday. Week 4: BUF and NE
# are on bye.
SCHEDULE = [
    ScheduledGame(week=3, date="2026-09-24", home="BUF", away="MIA"),
    ScheduledGame(week=3, date="2026-09-27", home="NYJ", away="NE"),
    ScheduledGame(week=3, date="2026-09-27", home="KC", away="LV"),
    ScheduledGame(week=4, date="2026-10-04", home="MIA", away="NYJ"),
    ScheduledGame(week=4, date="2026-10-04", home="KC", away="LV"),
]

QB = _proj("qb", "Quinn Back", "QB", 20.0, team="KC", opp="LV")
RB = _proj("rb", "Ron Back", "RB", 15.0, team="NYJ", opp="NE")
WR = _proj("wr", "Wade Receiver", "WR", 14.0, team="KC", opp="LV")
FLEX = _proj("te", "Ty End", "TE", 9.0, team="KC", opp="LV")
BENCH_RB = _proj("rb2", "Bench Back", "RB", 8.0, team="NYJ", opp="NE")
BENCH_WR = _proj("wr2", "Bench Receiver", "WR", 6.0, team="KC", opp="LV")


def _client(
    projections: list[WeeklyProjection],
    starters: list[str],
    bench: list[str],
    league: SleeperLeague = LEAGUE,
    schedule: list[ScheduledGame] = SCHEDULE,
    game_lines: list[NFLGameLine] | None = None,
) -> FakeSleeper:
    client = FakeSleeper(
        game_lines=game_lines,
        projections={p.player_id: p for p in projections},
        league=league,
        season_schedule=schedule,
        rosters=[
            SleeperRoster(roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=starters + bench, starter_ids=starters)
        ],
    )
    client.players_catalog = {
        p.player_id: PlayerMeta(player_id=p.player_id, name=p.name, position=p.position, team=p.team)
        for p in projections
    }
    return client


def _actions(client: FakeSleeper) -> list[Action]:
    actions = _provider(client).summary("L1").actions
    assert actions is not None
    return actions


def _names_the_swap(action: Action, start: WeeklyProjection, out: WeeklyProjection) -> None:
    """Who comes in and who goes out is the move; how the title phrases it is not."""
    assert start.name in action.title and out.name in action.title
    assert action.title.index(start.name) < action.title.index(out.name)


def _ruled_out(player: WeeklyProjection, points: float = 0.0) -> WeeklyProjection:
    return replace(player, injury_status="Out", points=points)


# ── starters who cannot play ────────────────────────────────────────────


def test_a_starter_ruled_out_is_swapped_for_the_bench_player_who_covers_him() -> None:
    client = _client([QB, _ruled_out(RB), WR, FLEX, BENCH_RB], ["qb", "rb", "wr", "te"], ["rb2"])

    [action] = _actions(client)

    assert (action.kind, action.urgency, action.player_id) == ("lineup", "now", "rb2")
    _names_the_swap(action, start=BENCH_RB, out=RB)
    assert "ruled out" in action.reason
    assert "Sun 27 Sep" in action.when


def test_a_ruled_out_starter_is_benched_even_while_sleeper_still_projects_him() -> None:
    """The projection solve keeps whoever projects highest, and Sleeper does not
    always zero a player it has ruled out. A ruling beats a number."""
    client = _client([QB, _ruled_out(RB, points=15.0), WR, FLEX, BENCH_RB], ["qb", "rb", "wr", "te"], ["rb2"])

    [action] = _actions(client)

    assert action.player_id == "rb2"
    _names_the_swap(action, start=BENCH_RB, out=RB)


def test_a_starter_on_bye_is_flagged_once_the_league_has_fixtures() -> None:
    on_bye = replace(RB, opponent="", points=0.0)
    client = _client([QB, on_bye, WR, FLEX, BENCH_RB], ["qb", "rb", "wr", "te"], ["rb2"])

    [action] = _actions(client)

    assert (action.urgency, action.player_id) == ("now", "rb2")
    assert "no game" in action.reason


def test_an_empty_slot_is_filled_from_the_bench() -> None:
    client = _client([QB, WR, FLEX, BENCH_RB], ["qb", "0", "wr", "te"], ["rb2"])

    [action] = _actions(client)

    assert (action.kind, action.urgency, action.player_id) == ("lineup", "now", "rb2")
    assert "empty" in action.reason


def test_with_no_bench_cover_the_best_free_agent_who_can_play_is_named() -> None:
    """Not merely the best projection: one on bye or ruled out would fill nothing."""
    free = _proj("fa1", "Free Back", "RB", 11.0, team="KC", opp="LV")
    free_on_bye = _proj("fa2", "Idle Back", "RB", 30.0, team="KC", opp="")
    free_injured = replace(_proj("fa3", "Hurt Back", "RB", 25.0, team="KC", opp="LV"), injury_status="IR")
    wrong_position = _proj("fa4", "Free Receiver", "WR", 40.0, team="KC", opp="LV")
    client = _client(
        [QB, _ruled_out(RB), WR, FLEX, free, free_on_bye, free_injured, wrong_position],
        ["qb", "rb", "wr", "te"],
        [],
    )

    [action] = _actions(client)

    assert (action.kind, action.urgency, action.player_id) == ("waiver", "now", "fa1")
    assert free.name in action.title and RB.name in action.title
    # Sleeper publishes no waiver time, so none is invented.
    assert action.when == ""


def test_a_hole_nobody_anywhere_can_fill_is_not_a_task() -> None:
    client = _client([QB, _ruled_out(RB), WR, FLEX], ["qb", "rb", "wr", "te"], [])

    assert _actions(client) == []


def test_two_holes_are_never_pointed_at_the_same_free_agent() -> None:
    free_a = _proj("fa1", "Free Back", "RB", 11.0, team="KC", opp="LV")
    free_b = _proj("fa2", "Other Back", "RB", 7.0, team="KC", opp="LV")
    rb_out, te_out = _ruled_out(RB), _ruled_out(replace(FLEX, position="RB"))
    client = _client([QB, rb_out, WR, te_out, free_a, free_b], ["qb", "rb", "wr", "te"], [])

    picks = [a.player_id for a in _actions(client)]

    assert sorted(picks) == ["fa1", "fa2"]


# ── swaps the bench allows ──────────────────────────────────────────────


def test_a_projection_upgrade_is_worth_doing_but_not_urgent() -> None:
    better = replace(BENCH_WR, points=12.0)
    client = _client([QB, RB, WR, replace(FLEX, points=5.0), better], ["qb", "rb", "wr", "te"], ["wr2"])

    [action] = _actions(client)

    assert (action.kind, action.urgency, action.player_id) == ("lineup", "soon", "wr2")
    _names_the_swap(action, start=better, out=FLEX)
    assert "+7.0" in action.reason


def test_starting_a_questionable_player_says_so() -> None:
    doubtful = replace(BENCH_WR, points=12.0, injury_status="Questionable")
    client = _client([QB, RB, WR, replace(FLEX, points=5.0), doubtful], ["qb", "rb", "wr", "te"], ["wr2"])

    [action] = _actions(client)

    assert "questionable" in action.reason


def test_a_swap_closes_at_the_earlier_of_the_two_kickoffs() -> None:
    thursday = _proj("wr3", "Thursday Receiver", "WR", 12.0, team="BUF", opp="MIA")
    client = _client([QB, RB, WR, replace(FLEX, points=5.0), thursday], ["qb", "rb", "wr", "te"], ["wr3"])

    [action] = _actions(client)

    assert "Thu 24 Sep" in action.when


def test_nothing_is_suggested_for_a_player_whose_game_has_kicked_off() -> None:
    """He is locked in or out, so the move is no longer one anybody can make."""
    started = [replace(g, status="in_game") if g.week == 3 and g.home == "NYJ" else g for g in SCHEDULE]
    client = _client([QB, _ruled_out(RB), WR, FLEX, BENCH_RB], ["qb", "rb", "wr", "te"], ["rb2"], schedule=started)

    assert _actions(client) == []


# ── next week ───────────────────────────────────────────────────────────


def _week_four_bye(bench: list[WeeklyProjection]) -> FakeSleeper:
    on_bye_next = replace(RB, team="BUF", opponent="MIA")
    return _client([QB, on_bye_next, WR, FLEX, *bench], ["qb", "rb", "wr", "te"], [p.player_id for p in bench])


def test_a_starter_on_bye_next_week_with_nobody_behind_him_is_flagged() -> None:
    [action] = _actions(_week_four_bye([]))

    assert (action.kind, action.urgency, action.when) == ("waiver", "later", "week 4")
    assert action.player_id == "rb"
    assert RB.name in action.reason


def test_a_bye_the_bench_covers_needs_nothing() -> None:
    assert _actions(_week_four_bye([replace(BENCH_RB, points=0.0)])) == []


def test_an_injured_bench_player_is_not_cover_for_a_bye() -> None:
    [action] = _actions(_week_four_bye([_ruled_out(BENCH_RB)]))

    assert (action.kind, action.when) == ("waiver", "week 4")


def test_a_bench_player_on_bye_too_is_not_cover() -> None:
    [action] = _actions(_week_four_bye([replace(BENCH_RB, team="NE", points=0.0)]))

    assert (action.kind, action.when) == ("waiver", "week 4")


# ── the trade deadline ──────────────────────────────────────────────────


def _at_deadline(deadline: int) -> list[Action]:
    return _actions(
        _client([QB, RB, WR, FLEX], ["qb", "rb", "wr", "te"], [], league=replace(LEAGUE, trade_deadline=deadline))
    )


def test_the_last_week_to_trade_says_so() -> None:
    [action] = _at_deadline(3)

    assert (action.kind, action.urgency, action.when) == ("trade", "soon", "week 3")


def test_a_deadline_next_week_is_planning() -> None:
    [action] = _at_deadline(4)

    assert (action.kind, action.urgency, action.when) == ("trade", "later", "week 4")


def test_a_distant_passed_or_absent_deadline_is_not_a_task() -> None:
    for deadline in (10, 2, 0):
        assert _at_deadline(deadline) == []


# ── the list as a whole ─────────────────────────────────────────────────


def test_the_most_urgent_task_comes_first() -> None:
    better = replace(BENCH_WR, points=12.0)
    client = _client(
        [QB, _ruled_out(RB), WR, replace(FLEX, points=5.0), BENCH_RB, better],
        ["qb", "rb", "wr", "te"],
        ["rb2", "wr2"],
        league=replace(LEAGUE, trade_deadline=4),
    )

    assert [a.urgency for a in _actions(client)] == ["now", "soon", "later"]


def test_a_healthy_week_has_nothing_to_do() -> None:
    """An empty list, which is an answer — not None, which would mean unasked."""
    assert _actions(_client([QB, RB, WR, FLEX], ["qb", "rb", "wr", "te"], [])) == []


# ── what each move rests on ─────────────────────────────────────────────


def _played(*players: WeeklyProjection) -> list[NFLGameLine]:
    """One finished week for each player, all against LV."""
    return [
        NFLGameLine(
            player_id=p.player_id,
            week=2,
            team=p.team,
            opponent="LV",
            position=p.position,
            stats={"off_snp": 30, "tm_off_snp": 60, "rec_tgt": 5, "pts_ppr": 10},
        )
        for p in players
    ]


def test_a_swap_shows_the_role_and_matchup_of_both_players() -> None:
    """Both, because the choice is between them, and the projection gap alone
    does not say whether the bench player's role is real."""
    better = replace(BENCH_WR, points=12.0)
    benched = replace(FLEX, points=5.0)
    client = _client(
        [QB, RB, WR, benched, better], ["qb", "rb", "wr", "te"], ["wr2"], game_lines=_played(better, benched)
    )

    [action] = _actions(client)

    assert [stat.label for stat in action.evidence] == ["Bench Receiver", "Ty End"]
    assert all(stat.value for stat in action.evidence)


def test_covering_a_player_who_cannot_play_shows_only_the_one_coming_in() -> None:
    client = _client(
        [QB, _ruled_out(RB), WR, FLEX, BENCH_RB],
        ["qb", "rb", "wr", "te"],
        ["rb2"],
        game_lines=_played(RB, BENCH_RB),
    )

    [action] = _actions(client)

    assert [stat.label for stat in action.evidence] == ["Bench Back"]


def test_a_waiver_pick_shows_what_his_projection_rests_on() -> None:
    free = _proj("fa1", "Free Back", "RB", 11.0, team="KC", opp="LV")
    client = _client([QB, _ruled_out(RB), WR, FLEX, free], ["qb", "rb", "wr", "te"], [], game_lines=_played(free))

    [action] = _actions(client)

    assert [stat.label for stat in action.evidence] == ["Free Back"]


def test_only_finished_weeks_are_read_for_evidence() -> None:
    """Week 3 is under way: a Monday starter has a line of noughts until then."""
    client = _client([QB, RB, WR, FLEX], ["qb", "rb", "wr", "te"], [])

    _actions(client)

    assert client.game_line_weeks == [1, 2]


def test_stat_lines_that_will_not_load_leave_the_list_without_evidence() -> None:
    from thefrontoffice.domain.errors import SleeperAPIError

    client = _client([QB, _ruled_out(RB), WR, FLEX, BENCH_RB], ["qb", "rb", "wr", "te"], ["rb2"])
    client.game_lines_error = SleeperAPIError("down")

    [action] = _actions(client)

    assert action.player_id == "rb2"
    assert action.evidence == []
