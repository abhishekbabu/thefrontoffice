"""Tests for the week's to-do list: `nfl/actions.py`, through the summary.

The fake league plays week 3. Its slots are QB, RB, WR and FLEX, small enough
that every scenario can say exactly who is where.
"""

from dataclasses import replace
from datetime import UTC, datetime

from support.nfl import SLEEPER_USER_ID, FakeESPN, FakeSleeper, nfl_provider, proj

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
    assert "+7.0" in action.reason


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
    free = proj("fa1", "Free Back", "RB", 11.0, team="KC", opp="LV")
    client = _client([QB, _ruled_out(RB), WR, FLEX, free], ["qb", "rb", "wr", "te"], [], game_lines=_played(free))

    [action] = _actions(client)

    assert [stat.label for stat in action.evidence] == ["Free Back"]


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

    [his] = [stat for stat in action.evidence if stat.label == better.name]
    assert "50%" in his.value and "75%" not in his.value


def test_stat_lines_that_will_not_load_leave_the_list_without_evidence() -> None:
    from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError

    client = _client([QB, _ruled_out(RB), WR, FLEX, BENCH_RB], ["qb", "rb", "wr", "te"], ["rb2"])
    client.game_lines_error = SleeperAPIError("down")

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
    better = proj("fa1", "Free Receiver", "WR", 20.0, team="KC", opp="LV")
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
    """Weeks 1 and 2: a part-timer, then most of the snaps in the latest week played."""
    return [
        NFLGameLine(
            player_id=player.player_id,
            week=week,
            team=player.team,
            opponent="LV",
            position=player.position,
            stats={"off_snp": snaps, "tm_off_snp": 60, "pts_ppr": 4},
        )
        for week, snaps in ((1, 15), (2, 18), (3, 50))
    ]


def _with_free_agent(free: WeeklyProjection) -> FakeSleeper:
    client = _client([QB, RB, WR, FLEX, free], ["qb", "rb", "wr", "te"], [], game_lines=_rising(free))
    client.week = 4
    client.season_schedule = [*SCHEDULE, ScheduledGame(week=4, date="2026-10-04", home="NYJ", away="NE")]
    return client


def test_a_free_agent_whose_role_just_grew_is_worth_picking_up() -> None:
    free = proj("wr9", "Rising Receiver", "WR", 8.0, team="KC", opp="LV")

    [action] = [a for a in _actions(_with_free_agent(free)) if a.player_id == "wr9"]

    assert (action.kind, action.key) == ("waiver", "rise:wr9")
    assert any(stat.label == free.name for stat in action.evidence)


def test_a_growing_role_the_projection_has_given_up_on_is_left_alone() -> None:
    """Projected near nothing again usually means the starter is back."""
    free = proj("wr9", "Rising Receiver", "WR", 1.0, team="KC", opp="LV")

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


def test_a_roster_with_a_spot_open_drops_nobody() -> None:
    client = _client([QB, _ruled_out(RB), WR, FLEX, FREE_RB], ["qb", "rb", "wr", "te"], [])

    [action] = [a for a in _actions(client) if a.kind == "waiver"]

    assert action.drop == ""


def _with_breakout(projected: float) -> list[Action]:
    rising = proj("wr9", "Rising Receiver", "WR", projected, team="KC", opp="LV")
    client = _client(
        [QB, RB, WR, FLEX, WEAK, ON_BYE, BACKUP_QB, rising],
        ["qb", "rb", "wr", "te"],
        ["wr2", "wr3", "qb2"],
        game_lines=_scored(WEAK, 4.0, 5.0)
        + _scored(ON_BYE, 18.0, 20.0)
        + _scored(BACKUP_QB, 8.0, 9.0)
        + _rising(rising),
    )
    client.week = 4
    return _actions(client)


def test_a_breakout_worth_more_than_the_weakest_on_the_bench_names_him_to_drop() -> None:
    [action] = [a for a in _with_breakout(8.0) if a.player_id == "wr9"]

    assert action.drop == "wr2"


def test_a_breakout_worth_less_than_anyone_on_the_bench_is_not_worth_a_spot() -> None:
    """Optional, unlike filling a hole: a flier is not worth a better player."""
    assert all(a.player_id != "wr9" for a in _with_breakout(3.0))


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
