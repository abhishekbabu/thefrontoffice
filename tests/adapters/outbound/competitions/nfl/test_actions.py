"""Tests for the week's to-do list: `nfl/actions.py`, through the summary.

The fake league plays week 3. Its slots are QB, RB, WR and FLEX, small enough
that every scenario can say exactly who is where.
"""

from dataclasses import replace
from datetime import UTC, datetime

from support.espn import FakeESPN
from support.nfl import SLEEPER_USER_ID, FakeSleeper, nfl_provider, proj

from thefrontoffice.adapters.outbound.platforms.espn.errors import ESPNAPIError
from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport
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

QB = proj("qb", "Quinn Back", "QB", 20.0, team="KC", opp="LV")
RB = proj("rb", "Ron Back", "RB", 15.0, team="NYJ", opp="NE")
WR = proj("wr", "Wade Receiver", "WR", 14.0, team="KC", opp="LV")
FLEX = proj("te", "Ty End", "TE", 9.0, team="MIA", opp="BUF")
BENCH_RB = proj("rb2", "Bench Back", "RB", 8.0, team="NYJ", opp="NE")
BENCH_WR = proj("wr2", "Bench Receiver", "WR", 6.0, team="KC", opp="LV")


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


def _actions(client: FakeSleeper, espn: FakeESPN | None = None) -> list[Action]:
    actions = nfl_provider(client, espn).summary("L1").actions
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
    assert "Sun 27 Sep" in action.when


def test_a_ruled_out_starter_is_benched_even_while_sleeper_still_projects_him() -> None:
    """The projection solve keeps whoever projects highest, and Sleeper does not
    always zero a player it has ruled out. A ruling beats a number."""
    client = _client([QB, _ruled_out(RB, points=15.0), WR, FLEX, BENCH_RB], ["qb", "rb", "wr", "te"], ["rb2"])

    [action] = _actions(client)

    assert action.player_id == "rb2"
    _names_the_swap(action, start=BENCH_RB, out=RB)


def _report(player: WeeklyProjection, status: str) -> FakeESPN:
    """ESPN's injury report, naming one player."""
    report = InjuryReport(name=player.name, club=player.team, status=status, updated=datetime(2026, 9, 22, tzinfo=UTC))
    return FakeESPN(injuries=[report])


def test_a_starter_the_injury_report_has_back_to_questionable_is_not_benched() -> None:
    """Sleeper keeps last week's Out until somebody changes it; the dated report is this week's."""
    client = _client([QB, _ruled_out(RB, points=15.0), WR, FLEX, BENCH_RB], ["qb", "rb", "wr", "te"], ["rb2"])

    assert not [a for a in _actions(client, _report(RB, "Questionable")) if a.replaces == "rb"]


def test_a_starter_the_injury_report_rules_out_is_benched_whatever_sleeper_says() -> None:
    client = _client([QB, RB, WR, FLEX, BENCH_RB], ["qb", "rb", "wr", "te"], ["rb2"])

    [action] = _actions(client, _report(RB, "Out"))

    _names_the_swap(action, start=BENCH_RB, out=RB)


def test_without_the_injury_report_sleepers_designation_stands() -> None:
    client = _client([QB, _ruled_out(RB, points=15.0), WR, FLEX, BENCH_RB], ["qb", "rb", "wr", "te"], ["rb2"])

    [action] = _actions(client, FakeESPN(injuries_error=ESPNAPIError("down")))

    _names_the_swap(action, start=BENCH_RB, out=RB)


def test_a_starter_on_bye_is_flagged_once_the_league_has_fixtures() -> None:
    on_bye = replace(RB, opponent="", points=0.0)
    client = _client([QB, on_bye, WR, FLEX, BENCH_RB], ["qb", "rb", "wr", "te"], ["rb2"])

    [action] = _actions(client)

    assert (action.urgency, action.player_id) == ("now", "rb2")


def test_an_empty_slot_is_filled_from_the_bench() -> None:
    client = _client([QB, WR, FLEX, BENCH_RB], ["qb", "0", "wr", "te"], ["rb2"])

    [action] = _actions(client)

    assert (action.kind, action.urgency, action.player_id) == ("lineup", "now", "rb2")


def test_with_no_bench_cover_the_best_free_agent_who_can_play_is_named() -> None:
    """Not merely the best projection: one on bye or ruled out would fill nothing."""
    free = proj("fa1", "Free Back", "RB", 11.0, team="KC", opp="LV")
    free_on_bye = proj("fa2", "Idle Back", "RB", 30.0, team="KC", opp="")
    free_injured = replace(proj("fa3", "Hurt Back", "RB", 25.0, team="KC", opp="LV"), injury_status="IR")
    wrong_position = proj("fa4", "Free Receiver", "WR", 40.0, team="KC", opp="LV")
    client = _client(
        [QB, _ruled_out(RB), WR, FLEX, free, free_on_bye, free_injured, wrong_position],
        ["qb", "rb", "wr", "te"],
        [],
    )

    [action] = [a for a in _actions(client) if a.key.startswith("hole:")]

    assert (action.kind, action.urgency, action.player_id) == ("waiver", "now", "fa1")
    assert free.name in action.title and RB.name in action.title
    # Sleeper publishes no waiver time, so none is invented.
    assert action.when == ""


def test_a_hole_nobody_anywhere_can_fill_is_not_a_task() -> None:
    client = _client([QB, _ruled_out(RB), WR, FLEX], ["qb", "rb", "wr", "te"], [])

    assert _actions(client) == []


def test_two_holes_are_never_pointed_at_the_same_free_agent() -> None:
    free_a = proj("fa1", "Free Back", "RB", 11.0, team="KC", opp="LV")
    free_b = proj("fa2", "Other Back", "RB", 7.0, team="KC", opp="LV")
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
    # With nothing played yet, each is worth his projection.
    assert "12.00" in action.reason and "5.00" in action.reason


def _two_games(player: WeeklyProjection, points: float) -> list[NFLGameLine]:
    """Weeks 1 and 2 at `points`, on two thirds of the snaps."""
    return [
        NFLGameLine(
            player_id=player.player_id,
            week=week,
            team=player.team,
            opponent="LV",
            position=player.position,
            stats={"off_snp": 40, "tm_off_snp": 60, "pts_ppr": points},
        )
        for week in (1, 2)
    ]


def test_a_bench_player_worth_more_starts_though_he_projects_less() -> None:
    """The live case: the bench receiver projects a point less but scores far more; worth, not projection, decides."""
    starter = replace(WR, points=11.0)
    hot = replace(BENCH_WR, points=10.0)
    client = _client(
        [QB, RB, starter, FLEX, hot],
        ["qb", "rb", "wr", "te"],
        ["wr2"],
        game_lines=_two_games(starter, 4.0) + _two_games(hot, 16.0),
    )

    [action] = _actions(client)

    assert (action.player_id, action.replaces) == ("wr2", "wr")
    # Each at half form, half projection, a tenth up for steady snaps: 14.30 vs 8.25.
    assert "14.30" in action.reason and "8.25" in action.reason
    assert [(p.side, p.player_id) for p in action.players] == [("in", "wr2"), ("out", "wr")]


def test_a_bench_player_ahead_by_less_than_the_margin_is_no_swap() -> None:
    """Half a point is a coin flip, not a decision: the list leaves the lineup be."""
    client = _client([QB, RB, WR, FLEX, replace(BENCH_WR, points=FLEX.points + 0.5)], ["qb", "rb", "wr", "te"], ["wr2"])

    assert _actions(client) == []


def test_a_bench_player_on_bye_is_never_started_however_well_he_has_scored() -> None:
    idle = replace(BENCH_WR, team="NE", opponent="")
    client = _client(
        [QB, RB, WR, replace(FLEX, points=5.0), idle],
        ["qb", "rb", "wr", "te"],
        ["wr2"],
        game_lines=_two_games(idle, 30.0),
    )

    assert not [a for a in _actions(client) if a.player_id == "wr2"]


def test_a_ruled_out_starter_is_covered_by_the_bench_player_worth_most() -> None:
    projected = replace(BENCH_RB, points=9.0)
    scoring = proj("rb3", "Scoring Back", "RB", 7.0, team="NYJ", opp="NE")
    client = _client(
        [QB, _ruled_out(RB), WR, FLEX, projected, scoring],
        ["qb", "rb", "wr", "te"],
        ["rb2", "rb3"],
        game_lines=_two_games(_ruled_out(RB), 25.0) + _two_games(projected, 2.0) + _two_games(scoring, 15.0),
    )

    [action] = [a for a in _actions(client) if a.replaces == "rb"]

    assert action.player_id == "rb3"


def test_starting_a_questionable_player_says_so() -> None:
    doubtful = replace(BENCH_WR, points=12.0, injury_status="Questionable")
    client = _client([QB, RB, WR, replace(FLEX, points=5.0), doubtful], ["qb", "rb", "wr", "te"], ["wr2"])

    [action] = _actions(client)

    assert "questionable" in action.reason


def test_a_swap_closes_at_the_earlier_of_the_two_kickoffs() -> None:
    thursday = proj("wr3", "Thursday Receiver", "WR", 12.0, team="BUF", opp="MIA")
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


def test_a_player_in_injured_reserve_is_not_cover_for_a_bye() -> None:
    """He cannot be started from a reserve slot, however healthy his projection."""
    client = _week_four_bye([replace(BENCH_RB, points=0.0)])
    client.rosters = [replace(client.rosters[0], reserve_ids=[BENCH_RB.player_id])]

    [action] = _actions(client)

    assert (action.kind, action.when) == ("waiver", "week 4")


# ── the trade deadline ──────────────────────────────────────────────────


def _at_deadline(deadline: int) -> list[Action]:
    return _actions(
        _client([QB, RB, WR, FLEX], ["qb", "rb", "wr", "te"], [], league=replace(LEAGUE, trade_deadline=deadline))
    )


def test_the_last_week_to_trade_says_so() -> None:
    [action] = _at_deadline(3)

    assert (action.kind, action.urgency, action.when) == ("trade", "soon", "week 3")
    # The week is the deadline's label alone, not restated in the title or the reason.
    assert "3" not in action.title + action.reason


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

    assert [(p.side, p.name, p.held) for p in action.players] == [
        ("in", "Bench Receiver", "bench"),
        ("out", "Ty End", "starter"),
    ]
    assert _figures(action, "Bench Receiver")["Snap% (L3)"] == "50%"
    assert _figures(action, "Ty End")["Proj"] == "5.00"


def test_compared_players_share_the_same_rows_in_the_same_order() -> None:
    """Side by side only reads if every row lines up: a figure one of them lacks is a dash, not a missing row."""
    better = replace(BENCH_WR, points=12.0)
    benched = replace(FLEX, points=5.0)
    client = _client([QB, RB, WR, benched, better], ["qb", "rb", "wr", "te"], ["wr2"], game_lines=_played(better))

    [action] = _actions(client)

    labels = [[figure.label for figure in p.figures] for p in action.players]
    assert labels[0] == labels[1]
    assert _figures(action, "Ty End")["Snap% (L3)"] == "—"


def test_a_row_no_compared_player_has_is_left_out() -> None:
    """Nobody here is hurt or trending, so neither row is a pair of dashes."""
    better = replace(BENCH_WR, points=12.0)
    benched = replace(FLEX, points=5.0)
    client = _client([QB, RB, WR, benched, better], ["qb", "rb", "wr", "te"], ["wr2"], game_lines=_played(better))

    [action] = _actions(client)

    assert "Status" not in _figures(action, "Ty End") and "Trend" not in _figures(action, "Ty End")


def test_a_compared_item_keeps_only_news_as_evidence() -> None:
    """The role and the matchup are figures in the comparison; a sentence repeating them is noise."""
    better = replace(BENCH_WR, points=12.0)
    benched = replace(FLEX, points=5.0)
    client = _client(
        [QB, RB, WR, benched, better], ["qb", "rb", "wr", "te"], ["wr2"], game_lines=_played(better, benched)
    )

    [action] = _actions(client)

    assert action.evidence == []


def test_covering_a_player_who_cannot_play_compares_him_with_his_cover() -> None:
    client = _client(
        [QB, _ruled_out(RB), WR, FLEX, BENCH_RB],
        ["qb", "rb", "wr", "te"],
        ["rb2"],
        game_lines=_played(RB, BENCH_RB),
    )

    [action] = _actions(client)

    assert [p.name for p in action.players] == ["Bench Back", "Ron Back"]
    # Ruled out projects nothing, which says nothing about him: his row says why instead.
    assert _figures(action, "Ron Back")["Proj"] == "—"
    assert _figures(action, "Ron Back")["Status"] == "out"


def test_a_waiver_pick_for_a_hole_is_compared_with_the_starter_he_covers() -> None:
    free = proj("fa1", "Free Back", "RB", 11.0, team="KC", opp="LV")
    client = _client([QB, _ruled_out(RB), WR, FLEX, free], ["qb", "rb", "wr", "te"], [], game_lines=_played(free))

    [action] = _actions(client)

    assert [(p.name, p.held) for p in action.players] == [("Free Back", "free agent"), ("Ron Back", "starter")]
    assert _figures(action, "Free Back")["Proj"] == "11.00"


def test_an_item_that_moves_one_player_keeps_its_evidence() -> None:
    """Nobody to compare him with: what his number rests on is said under the item, as before."""
    client = _client([QB, RB, WR, BENCH_WR], ["qb", "rb", "wr"], ["wr2"], game_lines=_played(BENCH_WR))

    [action] = _actions(client)

    assert action.player_id == "wr2" and not action.replaces
    assert action.players == []
    assert [stat.label for stat in action.evidence] == ["Bench Receiver"]


def _figures(action: Action, name: str) -> dict[str, str]:
    """One compared player's rows, by label."""
    [player] = [p for p in action.players if p.name == name]
    return {figure.label: figure.value for figure in player.figures}


def test_only_finished_weeks_are_read_for_evidence() -> None:
    """Week 3 is under way: a Monday starter has a line of noughts until then.

    Week 2 gives him half the snaps; were week 3's full share read too, the
    two games together would read as three quarters.
    """
    better = replace(BENCH_WR, points=12.0)
    benched = replace(FLEX, points=5.0)
    this_week = replace(_played(better)[0], week=3, stats={"off_snp": 60, "tm_off_snp": 60, "pts_ppr": 30})
    client = _client(
        [QB, RB, WR, benched, better],
        ["qb", "rb", "wr", "te"],
        ["wr2"],
        game_lines=[*_played(better, benched), this_week],
    )

    [action] = _actions(client)

    assert _figures(action, better.name)["Snap% (L3)"] == "50%"


def test_stat_lines_that_will_not_load_leave_the_list_without_evidence() -> None:
    client = _client([QB, _ruled_out(RB), WR, FLEX, BENCH_RB], ["qb", "rb", "wr", "te"], ["rb2"])
    client.unloaded_weeks = set(range(1, 19))

    [action] = _actions(client)

    assert action.player_id == "rb2"
    assert action.evidence == []


def test_a_move_carries_the_latest_headline_about_each_player_in_it() -> None:
    from datetime import datetime

    from thefrontoffice.adapters.outbound.platforms.espn.types import NewsArticle

    better = replace(BENCH_WR, points=12.0)
    client = _client([QB, RB, WR, replace(FLEX, points=5.0), better], ["qb", "rb", "wr", "te"], ["wr2"])
    article = NewsArticle(article_id="1", published=datetime.now(UTC), headline=f"{better.name} is the new WR1")

    [action] = _actions(client, FakeESPN({better.team: [article]}))

    assert any(line.label == better.name and article.headline in line.value for line in action.evidence)


def test_news_that_will_not_load_leaves_the_list_as_it_was() -> None:
    from thefrontoffice.adapters.outbound.platforms.espn.errors import ESPNAPIError

    client = _client([QB, _ruled_out(RB), WR, FLEX, BENCH_RB], ["qb", "rb", "wr", "te"], ["rb2"])

    [action] = _actions(client, FakeESPN(error=ESPNAPIError("down")))

    assert action.player_id == "rb2"


# ── identity, so a verdict can find its row again ───────────────────────


def test_every_task_has_a_key_and_no_two_share_one() -> None:
    better = replace(BENCH_WR, points=12.0)
    client = _client(
        [QB, _ruled_out(RB), WR, replace(FLEX, points=5.0), BENCH_RB, better],
        ["qb", "rb", "wr", "te"],
        ["rb2", "wr2"],
        league=replace(LEAGUE, trade_deadline=4),
    )

    keys = [a.key for a in _actions(client)]

    assert all(keys) and len(set(keys)) == len(keys)


def test_a_hole_keeps_its_key_when_a_better_answer_turns_up() -> None:
    """Keyed on the problem, so a verdict on the old answer reads as stale
    beside the new one rather than disappearing."""
    worse = proj("fa1", "Free Back", "RB", 8.0, team="KC", opp="LV")
    better = proj("fa2", "Other Back", "RB", 15.0, team="KC", opp="LV")
    before = _actions(_client([QB, _ruled_out(RB), WR, FLEX, worse], ["qb", "rb", "wr", "te"], []))
    after = _actions(_client([QB, _ruled_out(RB), WR, FLEX, worse, better], ["qb", "rb", "wr", "te"], []))

    assert before[0].key == after[0].key
    assert before[0].fingerprint != after[0].fingerprint


# ── a free agent who outscores a starter ────────────────────────────────


def _season(player: WeeklyProjection, points: float) -> list[NFLGameLine]:
    """Two finished games for `player`, each worth `points`: enough to judge him on his season."""
    return [
        NFLGameLine(
            player_id=player.player_id,
            week=week,
            team=player.team,
            opponent="LV",
            position=player.position,
            stats={"off_snp": 40, "pts_ppr": points},
        )
        for week in (1, 2)
    ]


def _upgrades(actions: list[Action]) -> list[Action]:
    return [a for a in actions if a.key.startswith("upgrade:")]


def test_a_free_agent_who_clearly_outscores_a_starter_is_a_pickup_to_start_over_him() -> None:
    better = proj("fa1", "Free Receiver", "WR", 20.0, team="KC", opp="LV")
    client = _client([QB, RB, WR, FLEX, BENCH_RB, better], ["qb", "rb", "wr", "te"], ["rb2"])

    [action] = _upgrades(_actions(client))

    assert (action.kind, action.player_id, action.replaces) == ("waiver", "fa1", "te")


def test_a_free_agent_barely_ahead_of_a_starter_is_not_worth_a_claim() -> None:
    edge = proj("fa1", "Free Receiver", "WR", FLEX.points + 1.0, team="KC", opp="LV")
    client = _client([QB, RB, WR, FLEX, BENCH_RB, edge], ["qb", "rb", "wr", "te"], ["rb2"])

    assert _upgrades(_actions(client)) == []


def test_a_starter_having_one_bad_week_is_not_replaced_by_a_free_agent() -> None:
    """Measured on his season as well: a star's poor matchup is not a reason to let him go."""
    better = proj("fa1", "Free Receiver", "WR", 15.0, team="KC", opp="LV")
    client = _client(
        [QB, RB, WR, FLEX, BENCH_RB, better], ["qb", "rb", "wr", "te"], ["rb2"], game_lines=_season(FLEX, 25.0)
    )

    assert _upgrades(_actions(client)) == []


def test_a_free_agent_is_measured_against_the_lineup_after_the_bench_has_moved() -> None:
    """With the starter ruled out, the bench back covers him; a free agent has to beat the cover."""
    free = proj("fa1", "Free Back", "RB", BENCH_RB.points + 1.0, team="KC", opp="LV")
    client = _client([QB, _ruled_out(RB), WR, FLEX, BENCH_RB, free], ["qb", "rb", "wr", "te"], ["rb2"])

    assert _upgrades(_actions(client)) == []


def test_a_free_defense_over_yours_names_yours_as_the_drop() -> None:
    """A lineup starts one defense, and nobody keeps a spare."""
    league = replace(LEAGUE, roster_positions=["QB", "RB", "WR", "FLEX", "DEF", "BN", "BN"])
    mine = proj("MIA", "Miami Dolphins", "DEF", 5.0, team="MIA", opp="BUF")
    theirs = proj("LV", "Las Vegas Raiders", "DEF", 10.0, team="LV", opp="KC")
    client = _client([QB, RB, WR, FLEX, mine, BENCH_RB, theirs], ["qb", "rb", "wr", "te", "MIA"], ["rb2"], league)

    [action] = _upgrades(_actions(client))

    assert (action.player_id, action.replaces, action.drop) == ("LV", "MIA", "MIA")


def test_a_starter_whose_game_has_kicked_off_is_not_replaced() -> None:
    """Thursday's starter is locked in: no claim can take his place this week."""
    better = proj("fa1", "Free Back", "RB", 20.0, team="KC", opp="LV")
    thursday = replace(RB, team="MIA", opponent="BUF")
    flex = replace(FLEX, points=18.0)
    schedule = [replace(SCHEDULE[0], status="in_game"), *SCHEDULE[1:]]
    client = _client([QB, thursday, WR, flex, better], ["qb", "rb", "wr", "te"], [], schedule=schedule)

    assert _upgrades(_actions(client)) == []


# ── a role that grew ────────────────────────────────────────────────────


def _rising(player: WeeklyProjection) -> list[NFLGameLine]:
    """Weeks 1 and 2: a part-timer on 4 points, then most of the snaps and 14 points in the two weeks played since."""
    return [
        NFLGameLine(
            player_id=player.player_id,
            week=week,
            team=player.team,
            opponent="LV",
            position=player.position,
            stats={"off_snp": snaps, "tm_off_snp": 60, "pts_ppr": points},
        )
        for week, snaps, points in ((1, 15, 4.0), (2, 18, 4.0), (3, 50, 14.0), (4, 50, 14.0))
    ]


def _with_free_agent(free: WeeklyProjection) -> FakeSleeper:
    client = _client([QB, RB, WR, FLEX, free], ["qb", "rb", "wr", "te"], [], game_lines=_rising(free))
    client.week = 5
    client.season_schedule = [*SCHEDULE, ScheduledGame(week=5, date="2026-10-11", home="KC", away="LV")]
    return client


def test_a_free_agent_whose_role_just_grew_is_worth_picking_up() -> None:
    free = proj("wr9", "Rising Receiver", "WR", 8.0, team="KC", opp="LV")

    [action] = [a for a in _actions(_with_free_agent(free)) if a.player_id == "wr9"]

    assert action.kind == "waiver"
    assert any(stat.label == free.name for stat in action.evidence)


def test_a_breakouts_evidence_leaves_the_role_change_to_its_reason() -> None:
    """The reason already says how his role grew; the line under it carries only what it does not."""
    free = proj("wr9", "Rising Receiver", "WR", 8.0, team="KC", opp="LV")

    [action] = [a for a in _actions(_with_free_agent(free)) if a.player_id == "wr9"]

    [his] = [stat for stat in action.evidence if stat.label == free.name]
    assert "role growing" not in his.value


def test_a_growing_role_the_projection_has_given_up_on_is_left_alone() -> None:
    """Projected near nothing again usually means the starter is back."""
    free = proj("wr9", "Rising Receiver", "WR", 1.0, team="KC", opp="LV")

    assert all(a.player_id != "wr9" for a in _actions(_with_free_agent(free)))


def _teammate(pid: str, weeks: tuple[int, ...], team: str = "KC") -> list[NFLGameLine]:
    """A regular receiver: four snaps in five in each of these weeks."""
    return [
        NFLGameLine(
            player_id=pid,
            week=week,
            team=team,
            opponent="LV",
            position="WR",
            stats={"off_snp": 48, "tm_off_snp": 60, "pts_ppr": 15.0},
        )
        for week in weeks
    ]


def _filling_in(status: str) -> list[Action]:
    """The free agent's jump came in weeks 3 and 4, both of which KC's regular receiver missed."""
    free = proj("wr9", "Rising Receiver", "WR", 8.0, team="KC", opp="LV")
    client = _with_free_agent(free)
    client.game_lines = [*(client.game_lines or []), *_teammate("wr7", (1, 2))]
    catalog = client.players_catalog or {}
    catalog["wr7"] = PlayerMeta(
        player_id="wr7", name="Regular Receiver", position="WR", team="KC", injury_status=status
    )
    return [a for a in _actions(client) if a.player_id == "wr9"]


def test_a_jump_while_a_regular_teammate_sat_is_no_pickup_once_he_is_due_back() -> None:
    assert _filling_in("Questionable") == []


def test_a_jump_while_a_regular_teammate_sat_is_a_pickup_while_he_is_ruled_out() -> None:
    [action] = _filling_in("Out")

    assert action.kind == "waiver"


def test_a_growing_role_worth_less_than_every_starter_he_could_replace_is_no_pickup() -> None:
    """Worth (10.67 + 6) / 2 = 8.33 against a 9-point flex: the role grew into less than you start already."""
    free = proj("wr9", "Rising Receiver", "WR", 6.0, team="KC", opp="LV")

    assert all(a.player_id != "wr9" for a in _actions(_with_free_agent(free)))


# ── who goes to make room ───────────────────────────────────────────────


def _scored(player: WeeklyProjection, *points: float) -> list[NFLGameLine]:
    """His finished weeks, one game each from week 1, at these scores."""
    return [
        NFLGameLine(
            player_id=player.player_id,
            week=week,
            team=player.team,
            opponent="LV",
            position=player.position,
            stats={"off_snp": 40, "tm_off_snp": 60, "pts_ppr": pts},
        )
        for week, pts in enumerate(points, start=1)
    ]


FREE_RB = proj("fa1", "Free Back", "RB", 12.0, team="KC", opp="LV")
# A bench that cannot play RB, so a ruled-out RB needs a pickup. LEAGUE holds seven.
WEAK = proj("wr2", "Weak Receiver", "WR", 6.0, team="KC", opp="LV")
ON_BYE = proj("wr3", "Idle Receiver", "WR", 0.0, team="NE", opp="")
BACKUP_QB = proj("qb2", "Backup QB", "QB", 9.0, team="KC", opp="LV")


def _full_roster(*extra: WeeklyProjection, lines: list[NFLGameLine] | None = None) -> FakeSleeper:
    return _client(
        [QB, _ruled_out(RB), WR, FLEX, WEAK, ON_BYE, BACKUP_QB, FREE_RB, *extra],
        ["qb", "rb", "wr", "te"],
        ["wr2", "wr3", "qb2"],
        game_lines=lines
        if lines is not None
        else _scored(WEAK, 4.0, 5.0) + _scored(ON_BYE, 18.0, 20.0) + _scored(BACKUP_QB, 8.0, 9.0),
    )


def test_a_pickup_on_a_full_roster_names_who_to_drop() -> None:
    [action] = [a for a in _actions(_full_roster()) if a.kind == "waiver"]

    assert action.drop == "wr2"
    assert WEAK.name in action.title


def test_the_drop_is_judged_on_his_season_not_a_week_he_is_on_bye() -> None:
    """The receiver on bye projects nothing this week and averages the most; he stays."""
    [action] = [a for a in _actions(_full_roster()) if a.kind == "waiver"]

    assert action.drop != ON_BYE.player_id


def _bench_pair(hot: WeeklyProjection, lines: list[NFLGameLine]) -> Action:
    """A full roster needing a pickup, choosing between a hot receiver and a cold one projected for 6."""
    cold = proj("wr2", "Cold Receiver", "WR", 6.0, team="KC", opp="LV")
    client = _client(
        [QB, _ruled_out(RB), WR, FLEX, cold, hot, BACKUP_QB, FREE_RB],
        ["qb", "rb", "wr", "te"],
        ["wr2", "wr3", "qb2"],
        game_lines=lines + _scored(BACKUP_QB, 30.0, 30.0),
    )
    # Week 6, so five weeks are played: enough for a season and a recent run to disagree.
    client.week = 6
    client.season_schedule = [*SCHEDULE, *(replace(game, week=6) for game in SCHEDULE[:3])]
    [action] = [a for a in _actions(client) if a.kind == "waiver"]
    return action


def test_the_drop_weighs_recent_form_beside_the_projection() -> None:
    """Hot of late and cold of late, with the cold one ahead on the season: form decides who goes."""
    hot = proj("wr3", "Hot Receiver", "WR", 6.0, team="KC", opp="LV")
    cold_games = [replace(line, player_id="wr2") for line in _scored(hot, 15.0, 15.0, 5.0, 5.0, 4.7)]

    action = _bench_pair(hot, _scored(hot, 1.0, 1.0, 13.0, 13.0, 13.6) + cold_games)

    assert action.drop == "wr2"
    assert _figures(action, "Cold Receiver")["Pts/g (L3)"] == "4.90"
    assert _figures(action, "Cold Receiver")["Proj"] == "6.00"


def test_a_hot_player_on_bye_is_not_dropped_for_his_empty_week() -> None:
    hot = proj("wr3", "Hot Receiver", "WR", 0.0, team="NE", opp="")
    cold_games = [replace(line, player_id="wr2") for line in _scored(hot, 5.0, 5.0, 4.7)]

    action = _bench_pair(hot, _scored(hot, 13.0, 13.0, 13.6) + cold_games)

    assert action.drop == "wr2"


def test_a_drop_on_bye_is_priced_on_his_season_not_his_empty_week() -> None:
    idle = proj("wr3", "Idle Receiver", "WR", 0.0, team="NE", opp="")
    cold_games = [replace(line, player_id="wr2") for line in _scored(idle, 9.0, 9.0, 9.0)]

    action = _bench_pair(idle, _scored(idle, 2.0, 2.0, 2.0) + cold_games)

    assert action.drop == "wr3"
    assert _figures(action, "Idle Receiver")["Pts/g (season)"] == "2.00"
    assert _figures(action, "Idle Receiver")["Proj"] == "—"


def test_a_player_with_nothing_to_go_on_is_the_last_resort() -> None:
    """No games played and no game this week: an unknown, not the weakest."""
    unknown = proj("wr3", "New Receiver", "WR", 0.0, team="NE", opp="")
    cold_games = [replace(line, player_id="wr2") for line in _scored(unknown, 1.0, 1.0)]

    action = _bench_pair(unknown, cold_games)

    assert action.drop == "wr2"


def test_a_roster_with_a_spot_open_drops_nobody() -> None:
    client = _client([QB, _ruled_out(RB), WR, FLEX, FREE_RB], ["qb", "rb", "wr", "te"], [])

    [action] = [a for a in _actions(client) if a.kind == "waiver"]

    assert action.drop == ""


def test_a_bench_player_whose_recent_games_were_fill_in_is_valued_beside_the_teammate_back() -> None:
    """A part-timer on 1 a game beside KC's regular receiver, 13 the two weeks he sat; he plays this week, so 1 counts."""
    filler = proj("wr3", "Fill-in Receiver", "WR", 6.0, team="KC", opp="LV")
    cold_games = [replace(line, player_id="wr2") for line in _scored(filler, 5.0, 5.0, 5.0, 5.0, 5.0)]
    client = _client(
        [QB, _ruled_out(RB), WR, FLEX, proj("wr2", "Cold Receiver", "WR", 6.0, team="KC", opp="LV"), filler, BACKUP_QB]
        + [FREE_RB],
        ["qb", "rb", "wr", "te"],
        ["wr2", "wr3", "qb2"],
        game_lines=[
            *_snapped(filler, 10, 10, 10, points=1.0),
            *(replace(line, week=line.week + 3) for line in _snapped(filler, 50, 50, points=13.0)),
        ]
        + cold_games
        + _scored(BACKUP_QB, 30.0, 30.0)
        + _teammate("wr7", (1, 2, 3)),
    )
    client.week = 6
    client.season_schedule = [*SCHEDULE, *(replace(game, week=6) for game in SCHEDULE[:3])]
    catalog = client.players_catalog or {}
    catalog["wr7"] = PlayerMeta(player_id="wr7", name="Regular Receiver", position="WR", team="KC")

    [action] = [a for a in _actions(client) if a.kind == "waiver"]

    assert action.drop == filler.player_id
    assert "1.00/game" in action.reason


def _snapped(player: WeeklyProjection, *snaps: float, points: float = 5.0) -> list[NFLGameLine]:
    """`points` a game from week 1, on these snaps of 60."""
    return [
        NFLGameLine(
            player_id=player.player_id,
            week=week,
            team=player.team,
            opponent="LV",
            position=player.position,
            stats={"off_snp": snap, "tm_off_snp": 60, "pts_ppr": points},
        )
        for week, snap in enumerate(snaps, start=1)
    ]


def test_between_two_alike_on_points_the_one_whose_snaps_swing_goes() -> None:
    swinging = proj("wr3", "Swinging Receiver", "WR", 6.0, team="KC", opp="LV")
    # 'Cold Receiver' (wr2), also projected 6, on two thirds of the snaps every week.
    steady = [replace(line, player_id="wr2") for line in _snapped(swinging, 40, 40, 40, 40, 40)]

    action = _bench_pair(swinging, _snapped(swinging, 40, 10, 45, 12, 40) + steady)

    assert action.drop == swinging.player_id


def test_a_role_ramping_up_to_his_most_snaps_is_not_read_as_one_that_swings() -> None:
    """A debut's snaps climb too soon for a trend. 5.30 a game on 10, 20 then 45 snaps against 5.00 on a
    steady third: without the tenth off, the climber is worth (5.30 + 6) / 2 = 5.65 to 5.50."""
    rising = proj("wr3", "Rising Receiver", "WR", 6.0, team="KC", opp="LV")
    steady = [replace(line, player_id="wr2") for line in _snapped(rising, 20, 20, 20, 20, 20)]

    action = _bench_pair(rising, _snapped(rising, 10, 10, 10, 20, 45, points=5.3) + steady)

    assert action.drop == "wr2"


def test_between_two_close_on_points_the_regular_stays() -> None:
    """5 a game on five snaps in six against 5.30 on a third of them: the steady role outweighs the 0.30."""
    regular = proj("wr3", "Regular Receiver", "WR", 6.0, team="KC", opp="LV")
    part_timer = [replace(line, player_id="wr2") for line in _snapped(regular, 20, 20, 20, 20, 20, points=5.3)]

    action = _bench_pair(regular, _snapped(regular, 50, 50, 50, 50, 50) + part_timer)

    assert action.drop == "wr2"


# A starting back at NYJ with his handcuff on the bench, and a quarterback ruled out with nobody behind him.
STARTING_RB = proj("rb", "Christian Starter", "RB", 15.0, team="NYJ", opp="NE")
HANDCUFF = proj("rb3", "Kaelon Backup", "RB", 3.0, team="NYJ", opp="NE")
FREE_QB = proj("qb9", "Free QB", "QB", 14.0, team="KC", opp="LV")


def _cuffed(*bench: WeeklyProjection, depth: int = 2) -> Action:
    """A full roster needing a quarterback, with the handcuff `depth` on the NYJ chart behind the starter."""
    league = replace(LEAGUE, roster_positions=["QB", "RB", "WR", "FLEX"] + ["BN"] * (1 + len(bench)))
    client = _client(
        [_ruled_out(QB), STARTING_RB, WR, FLEX, HANDCUFF, *bench, FREE_QB],
        ["qb", "rb", "wr", "te"],
        ["rb3", *(p.player_id for p in bench)],
        league=league,
        game_lines=_scored(HANDCUFF, 2.0, 2.0) + [line for p in bench for line in _scored(p, 4.0, 5.0)],
    )
    catalog = client.players_catalog or {}
    catalog["rb"] = replace(catalog["rb"], depth_chart_order=1)
    catalog["rb3"] = replace(catalog["rb3"], depth_chart_order=depth)
    [action] = [a for a in _actions(client) if a.kind == "waiver"]
    return action


def test_a_handcuff_is_dropped_after_every_ordinary_bench_player() -> None:
    """He scores least, but he is the starter's insurance: the weaker-looking ordinary player goes first."""
    action = _cuffed(WEAK)

    assert action.drop == WEAK.player_id


def test_a_back_his_club_lists_nowhere_is_dropped_on_his_figures() -> None:
    action = _cuffed(WEAK, depth=0)

    assert action.drop == HANDCUFF.player_id
    assert "handcuff" not in action.reason


def test_a_handcuff_left_as_the_only_drop_says_whose_he_is() -> None:
    action = _cuffed()

    assert action.drop == HANDCUFF.player_id
    assert "handcuff" in action.reason and "Starter" in action.reason


# A MIA back on your bench, next behind MIA's first back, whom you do not roster.
STASH = proj("rb7", "Kaelon Stash", "RB", 3.0, team="MIA", opp="BUF")
WORKHORSE = PlayerMeta(player_id="rb8", name="Christian Workhorse", position="RB", team="MIA", depth_chart_order=1)


def _workhorse_games(snaps: int, points: float) -> list[NFLGameLine]:
    """`WORKHORSE`'s weeks 1 and 2, on `snaps` of his club's 60, scoring `points`."""
    return [
        NFLGameLine(
            player_id=WORKHORSE.player_id,
            week=week,
            team="MIA",
            opponent="LV",
            position="RB",
            stats={"off_snp": snaps, "tm_off_snp": 60, "pts_ppr": points},
        )
        for week in (1, 2)
    ]


def _stashed(
    *bench: WeeklyProjection,
    snaps: int = 50,
    points: float = 30.0,
    status: str = "",
    slots: tuple[str, ...] = ("QB", "RB", "WR", "FLEX"),
    lines: list[NFLGameLine] | None = None,
) -> Action:
    """A full roster needing a quarterback, with `STASH` on the bench behind a workhorse on `snaps` of 60 a game."""
    league = replace(LEAGUE, roster_positions=[*slots] + ["BN"] * (1 + len(bench)))
    client = _client(
        [_ruled_out(QB), STARTING_RB, WR, FLEX, STASH, *bench, FREE_QB],
        ["qb", "rb", "wr", "te"],
        ["rb7", *(p.player_id for p in bench)],
        league=league,
        game_lines=_scored(STASH, 2.0, 2.0) + (_workhorse_games(snaps, points) if lines is None else lines),
    )
    catalog = client.players_catalog or {}
    catalog["rb7"] = replace(catalog["rb7"], depth_chart_order=2)
    catalog[WORKHORSE.player_id] = replace(WORKHORSE, injury_status=status)
    [action] = [a for a in _actions(client) if a.kind == "waiver"]
    return action


def test_a_back_behind_another_managers_workhorse_is_dropped_after_every_ordinary_player() -> None:
    action = _stashed(WEAK)

    assert action.drop == WEAK.player_id


def test_a_stash_left_as_the_only_drop_says_whose_work_he_would_inherit() -> None:
    action = _stashed()

    assert action.drop == STASH.player_id
    assert "stash" in action.reason and "Workhorse" in action.reason


def test_a_back_behind_a_committee_back_is_no_stash() -> None:
    """Half the snaps is a share of the work, not the work."""
    action = _stashed(WEAK, snaps=30)

    assert action.drop == STASH.player_id
    assert "stash" not in action.reason


def test_a_back_behind_a_first_back_ruled_out_is_no_stash() -> None:
    """He is already the starter, and his own figures say so."""
    assert _stashed(WEAK, status="IR").drop == STASH.player_id


def test_a_back_behind_a_workhorse_who_would_not_start_for_you_is_no_stash() -> None:
    """Five a game would not beat the weakest back or flex you start, so inheriting it changes nothing."""
    assert _stashed(WEAK, points=5.0).drop == STASH.player_id


def test_a_back_behind_a_first_back_with_no_games_to_read_is_no_stash() -> None:
    assert _stashed(WEAK, lines=[]).drop == STASH.player_id


def test_a_league_with_no_slot_a_back_can_fill_has_no_stash() -> None:
    assert _stashed(WEAK, slots=("QB", "WR", "TE")).drop == STASH.player_id


def test_a_stash_is_dropped_before_a_handcuff() -> None:
    """A handcuff insures points you score already; a stash only a chance at more, however much better he looks."""
    league = replace(LEAGUE, roster_positions=["QB", "RB", "WR", "FLEX", "BN", "BN"])
    # Better than the handcuff, though not enough to start over the tight end: a starter is never the drop.
    better_stash = replace(STASH, points=6.0)
    client = _client(
        [_ruled_out(QB), STARTING_RB, WR, FLEX, HANDCUFF, better_stash, FREE_QB],
        ["qb", "rb", "wr", "te"],
        ["rb3", "rb7"],
        league=league,
        game_lines=_scored(HANDCUFF, 2.0, 2.0) + _scored(better_stash, 6.0, 6.0) + _workhorse_games(50, 30.0),
    )
    catalog = client.players_catalog or {}
    catalog["rb"] = replace(catalog["rb"], depth_chart_order=1)
    catalog["rb3"] = replace(catalog["rb3"], depth_chart_order=2)
    catalog["rb7"] = replace(catalog["rb7"], depth_chart_order=2)
    catalog[WORKHORSE.player_id] = WORKHORSE

    [action] = [a for a in _actions(client) if a.kind == "waiver"]

    assert action.drop == better_stash.player_id
    assert "stash" in action.reason


def _with_breakout(projected: float, weak: WeeklyProjection = WEAK) -> list[Action]:
    # Not at KC, where the weak receiver on your bench was a regular before the jump: his absence would explain it.
    rising = proj("wr9", "Rising Receiver", "WR", projected, team="LV", opp="KC")
    client = _client(
        [QB, RB, WR, FLEX, weak, ON_BYE, BACKUP_QB, rising],
        ["qb", "rb", "wr", "te"],
        ["wr2", "wr3", "qb2"],
        game_lines=_scored(WEAK, 4.0, 5.0)
        + _scored(ON_BYE, 18.0, 20.0)
        + _scored(BACKUP_QB, 8.0, 9.0)
        + _rising(rising),
    )
    client.week = 5
    client.season_schedule = [*SCHEDULE, ScheduledGame(week=5, date="2026-10-11", home="KC", away="LV")]
    return _actions(client)


def test_a_breakout_worth_more_than_the_weakest_on_the_bench_names_him_to_drop() -> None:
    [action] = [a for a in _with_breakout(8.0) if a.player_id == "wr9"]

    assert action.drop == "wr2"


def test_a_breakout_and_his_drop_are_compared_without_restating_the_role_change() -> None:
    """The reason says how his role grew; the comparison carries what it does not, the drop's figures beside his."""
    [action] = [a for a in _with_breakout(8.0) if a.player_id == "wr9"]

    assert [(p.side, p.player_id) for p in action.players] == [("in", "wr9"), ("out", "wr2")]
    assert "Trend" not in _figures(action, "Rising Receiver")
    assert _figures(action, "Rising Receiver")["Snap% (L3)"] == "66%"


def test_a_breakout_worth_less_than_anyone_on_the_bench_is_not_worth_a_spot() -> None:
    """Optional, unlike filling a hole: a flier is not worth a better player."""
    assert all(a.player_id != "wr9" for a in _with_breakout(3.0))


def test_a_breakout_projected_above_his_drop_does_not_claim_the_projection_lags() -> None:
    [action] = [a for a in _with_breakout(8.0) if a.player_id == "wr9"]

    assert "lag" not in action.reason


def test_a_breakout_projected_below_his_drop_says_the_projection_lags() -> None:
    """Projected 8 against the drop's 9, but worth more on what he has done since the jump."""
    [action] = [a for a in _with_breakout(8.0, weak=replace(WEAK, points=9.0)) if a.player_id == "wr9"]

    assert action.drop == WEAK.player_id
    assert "lag" in action.reason


# ── starters riding on one game ─────────────────────────────────────────

STACK_TE = proj("te", "Ty End", "TE", 9.0, team="KC", opp="LV")
"""With the quarterback and the receiver, a third starter in Kansas City against Las Vegas."""


def _stacked(*bench: WeeklyProjection, schedule: list[ScheduledGame] = SCHEDULE) -> list[Action]:
    players = [QB, RB, WR, STACK_TE, *bench]
    client = _client(players, ["qb", "rb", "wr", "te"], [p.player_id for p in bench], schedule=schedule)
    return [a for a in _actions(client) if a.key.startswith("stack:")]


def test_three_starters_in_one_game_offer_the_bench_start_that_spreads_them() -> None:
    [action] = _stacked(BENCH_RB)

    # The weakest of the three makes way for the best bench player from another game.
    assert (action.player_id, action.replaces) == (BENCH_RB.player_id, STACK_TE.player_id)


def test_two_starters_in_one_game_are_not_a_stack() -> None:
    players = [QB, RB, WR, FLEX, BENCH_RB]
    client = _client(players, ["qb", "rb", "wr", "te"], ["rb2"])

    assert not [a for a in _actions(client) if a.key.startswith("stack:")]


def test_a_bench_player_from_the_same_game_spreads_nothing() -> None:
    assert _stacked(BENCH_WR) == []


def test_a_stack_whose_game_has_kicked_off_is_no_longer_a_decision() -> None:
    started = [replace(g, status="in_game") if g.home == "KC" and g.week == 3 else g for g in SCHEDULE]

    assert _stacked(BENCH_RB, schedule=started) == []


# ── a teammate ahead of yours who may sit ───────────────────────────────


def _snaps(player_id: str, team: str, position: str, share: float) -> list[NFLGameLine]:
    """Two finished weeks at a steady share of his club's snaps."""
    return [
        NFLGameLine(
            player_id=player_id,
            week=week,
            team=team,
            opponent="LV",
            position=position,
            stats={"off_snp": round(60 * share), "tm_off_snp": 60, "rec_tgt": 5, "pts_ppr": 10},
        )
        for week in (1, 2)
    ]


def _behind(
    status: str,
    *,
    his_share: float = 0.9,
    mine: float = 0.4,
    of: str = "wr2",
    bench: float = 6.0,
    starters: tuple[str, ...] = ("qb", "rb", "wr", "te"),
) -> list[Action]:
    """What the list says about Bench Receiver (KC), projected `bench` — or another of yours, `of` — while
    Star Wideout, a teammate on nobody's roster here, is `status`. Both played weeks 1 and 2, his 10 a game."""
    client = _client(
        [QB, RB, WR, FLEX, replace(BENCH_WR, points=bench)],
        list(starters),
        ["wr2"],
        game_lines=_snaps("star", "KC", "WR", his_share) + _snaps("wr2", "KC", "WR", mine),
    )
    client.players_catalog = {
        **(client.players_catalog or {}),
        "star": PlayerMeta(player_id="star", name="Star Wideout", position="WR", team="KC", injury_status=status),
    }
    return [a for a in _actions(client) if a.key.startswith("teammate:") and a.player_id == of]


def test_a_questionable_regular_beside_your_player_is_a_status_to_check_before_kickoff() -> None:
    """Projections leave a questionable starter in and his backup where he was;
    whether the work moves is settled by the inactives, not the numbers."""
    [action] = _behind("Questionable")

    assert (action.kind, action.urgency, action.player_id, action.key) == ("lineup", "soon", "wr2", "teammate:wr2:star")
    assert "Star Wideout" in action.title and "Bench Receiver" in action.title
    assert "Sun 27 Sep" in action.when
    assert not action.replaces and not action.drop


def test_a_bench_player_behind_a_doubtful_teammate_is_weighed_against_the_starter_he_would_replace() -> None:
    """The decision is a start, so the item names who it would bench — the weakest starter in a slot he can play."""
    [action] = _behind("Questionable")

    assert [(p.side, p.name, p.held) for p in action.players] == [
        ("in", "Bench Receiver", "bench"),
        ("out", "Ty End", "starter"),
    ]
    assert "Ty End" in action.title


def test_the_doubtful_teammate_is_named_as_a_teammate_not_as_one_of_yours() -> None:
    """A model read 'Star Wideout (questionable)' as a player on the roster; the item has to say whose he is."""
    [action] = _behind("Questionable")

    assert "Teammate Star Wideout" in action.reason
    assert "Star Wideout" not in [p.name for p in action.players]


def test_a_starter_behind_a_doubtful_teammate_compares_nobody() -> None:
    """Already in the lineup, he has no one to be weighed against: the item stays a single-player one."""
    [action] = _behind("Questionable", of="wr")

    assert action.players == []
    assert "Star Wideout" in action.title


def test_a_teammate_already_ruled_out_still_names_whose_work_grows() -> None:
    [action] = _behind("Out")

    assert action.player_id == "wr2"
    assert "Star Wideout" in action.title


def test_a_bench_player_who_would_not_beat_the_starter_even_with_the_teammate_out_is_no_start() -> None:
    """Worth (10 + 1) / 2 = 5.50, a fifth more is 6.60, against Ty End's 9: there is no start to make."""
    assert _behind("Questionable", bench=1.0) == []


def test_a_bench_player_with_no_starter_to_replace_has_no_teammate_check() -> None:
    """The flex is empty, which the lineup's own item fills; a bench player is never told to 'keep' his seat."""
    assert _behind("Questionable", starters=("qb", "rb", "wr")) == []


def test_a_starter_a_bench_player_beats_even_with_the_teammate_out_is_not_kept_in() -> None:
    """Wade Receiver's 14, a fifth more, is 16.80; Bench Receiver is worth (10 + 30) / 2 = 20 at his slot."""
    assert _behind("Questionable", bench=30.0, of="wr") == []


def test_a_starter_worth_more_than_any_bench_player_with_the_teammate_out_is_kept_in() -> None:
    [action] = _behind("Questionable", of="wr")

    assert "Wade Receiver" in action.title and "Star Wideout" in action.title
    assert "16.80" in action.reason and "8.00" in action.reason


def _without_star(before: float, after: float) -> list[Action]:
    """Bench Receiver (projected 6) in week 5: `before` a game in weeks 1 and 2, which Star Wideout
    (questionable) missed, and `after` in weeks 3 and 4 beside him."""
    lines = [
        replace(line, week=week, stats={**line.stats, "pts_ppr": points})
        for week, points in ((1, before), (2, before), (3, after), (4, after))
        for line in _snaps("wr2", "KC", "WR", 0.4)[:1]
    ] + [replace(line, week=line.week + 2) for line in _snaps("star", "KC", "WR", 0.9)]
    client = _client([QB, RB, WR, FLEX, BENCH_WR], ["qb", "rb", "wr", "te"], ["wr2"], game_lines=lines)
    client.week = 5
    client.season_schedule = [*SCHEDULE, *(replace(game, week=5) for game in SCHEDULE[:3])]
    client.players_catalog = {
        **(client.players_catalog or {}),
        "star": PlayerMeta(
            player_id="star", name="Star Wideout", position="WR", team="KC", injury_status="Questionable"
        ),
    }
    return [a for a in _actions(client) if a.key.startswith("teammate:wr2:")]


def test_a_bench_player_who_scored_less_without_the_teammate_is_no_start() -> None:
    """Form (2 + 14 + 14) / 3 = 10 would pass with a fifth more (9.60 against 9); without him he
    scored 2 a game, worth (2 + 6) / 2 = 4."""
    assert _without_star(2.0, 14.0) == []


def test_a_bench_player_who_scored_more_without_the_teammate_is_a_start_on_those_games() -> None:
    """Form (14 + 2 + 2) / 3 = 6 would fail even with a fifth more (7.20 against 9); without him
    he scored 14 a game, worth (14 + 6) / 2 = 10."""
    [action] = _without_star(14.0, 2.0)

    assert [p.name for p in action.players] == ["Bench Receiver", "Ty End"]
    assert "14.00" in action.reason and "10.00" in action.reason


def test_a_depth_player_sitting_moves_nothing() -> None:
    assert _behind("Questionable", his_share=0.3, mine=0.2) == []


def test_a_regular_held_to_fewer_snaps_than_yours_still_counts() -> None:
    """A starter playing through an injury plays less, and still takes his targets with him when he sits."""
    [action] = _behind("Questionable", his_share=0.6, mine=0.8)

    assert action.player_id == "wr2"


def test_a_long_ruling_is_already_in_the_projections() -> None:
    """IR outlasts the week, so the projection has long since moved the work."""
    assert _behind("IR") == []


# ── a player injured reserve no longer takes ───────────────────────────

HEALING = proj("wr8", "Healing Receiver", "WR", 7.0, team="KC", opp="LV")


def _on_ir(status: str, client: FakeSleeper | None = None) -> FakeSleeper:
    """Healing Receiver held on IR under `status`, on a full roster unless another is given."""
    client = client or _full_roster(HEALING)
    roster = client.rosters[0]
    client.rosters = [replace(roster, player_ids=[*roster.player_ids, "wr8"], reserve_ids=["wr8"], ir_ids=["wr8"])]
    catalog = client.get_nfl_players()
    client.players_catalog = {**catalog, "wr8": replace(catalog["wr8"], injury_status=status)}
    return client


def _ir_items(client: FakeSleeper) -> list[Action]:
    return [a for a in _actions(client) if a.key.startswith("ir:")]


def test_a_player_on_ir_the_slot_no_longer_takes_comes_first_with_who_to_drop() -> None:
    actions = _actions(_on_ir("Questionable"))

    first = actions[0]
    assert (first.key, first.urgency, first.player_id, first.drop) == ("ir:wr8:QUESTIONABLE", "now", "wr8", "wr2")


def test_a_player_still_designated_ir_needs_nothing() -> None:
    assert _ir_items(_on_ir("IR")) == []


def test_out_is_ineligible_unless_the_league_lets_ir_take_it() -> None:
    assert len(_ir_items(_on_ir("Out"))) == 1

    lenient = _full_roster(HEALING)
    lenient.league = replace(lenient.league, ir_allows=frozenset({"IR", "OUT"}))
    assert _ir_items(_on_ir("Out", lenient)) == []


def test_activating_into_an_open_spot_drops_nobody() -> None:
    client = _on_ir("Questionable", _client([QB, RB, WR, FLEX, HEALING], ["qb", "rb", "wr", "te"], []))

    [item] = _ir_items(client)

    assert item.drop == ""


def test_a_pickup_never_names_the_drop_the_ir_move_already_spent() -> None:
    drops = [a.drop for a in _actions(_on_ir("Questionable")) if a.drop]

    assert "wr2" in drops
    assert len(drops) == len(set(drops))
