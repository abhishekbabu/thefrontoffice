"""Tests for the IR stash to-do: `nfl/stash.py`, through the summary and the prompt.

The fake league plays week 3 with one IR slot and playoffs from week 15, so the
regular season ends in week 14. KC plays every Sunday. The free agent `ir1` is
on IR, back for week 6, and projects 12 a week once back.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from support.nfl import SLEEPER_USER_ID, FakeESPN, FakeSleeper, game_line, nfl_provider, proj

from thefrontoffice.adapters.outbound.platforms.espn.types import InjuryReport
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
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
    roster_positions=["QB", "RB", "WR", "FLEX", "BN", "BN"],
    playoff_week_start=15,
    ir_slots=1,
)

WEEK_3 = date(2026, 9, 27)
SCHEDULE = [
    ScheduledGame(week=w, date=(WEEK_3 + timedelta(weeks=w - 3)).isoformat(), home="KC", away="LV")
    for w in range(3, 18)
]

STARTERS = [
    proj("qb", "Quinn Back", "QB", 20.0, team="KC", opp="LV"),
    proj("rb", "Ron Back", "RB", 15.0, team="KC", opp="LV"),
    proj("wr", "Wade Receiver", "WR", 14.0, team="KC", opp="LV"),
    proj("te", "Ty End", "TE", 9.0, team="KC", opp="LV"),
]
BENCH = proj("wr2", "Bench Receiver", "WR", 6.0, team="KC", opp="LV")
BENCH_RB = proj("rb2", "Bench Back", "RB", 7.0, team="KC", opp="LV")


def _week_of(week: int) -> date:
    return WEEK_3 + timedelta(weeks=week - 3)


def _client(
    hurt: dict[str, tuple[float, int]],
    bench: list[WeeklyProjection] | None = None,
    league: SleeperLeague = LEAGUE,
    ir_ids: list[str] | None = None,
) -> tuple[FakeSleeper, FakeESPN]:
    """`hurt` is each free agent on IR: what he projects a week, and the week ESPN expects him back."""
    bench = [BENCH] if bench is None else bench
    held = [*STARTERS, *bench]
    projections = {p.player_id: p for p in held} | {
        pid: proj(pid, pid.upper(), "WR", points, team="KC", opp="LV") for pid, (points, _) in hurt.items()
    }
    ids = [p.player_id for p in held] + (ir_ids or [])
    client = FakeSleeper(
        projections=projections,
        league=league,
        season_schedule=SCHEDULE,
        rosters=[
            SleeperRoster(
                roster_id=1,
                owner_id=SLEEPER_USER_ID,
                player_ids=ids,
                starter_ids=[p.player_id for p in STARTERS],
                reserve_ids=ir_ids or [],
                ir_ids=ir_ids or [],
            )
        ],
    )
    client.players_catalog = {
        p.player_id: PlayerMeta(player_id=p.player_id, name=p.name, position=p.position, team=p.team) for p in held
    } | {
        pid: PlayerMeta(
            player_id=pid, name=pid.upper(), position="WR", team="KC", injury_status="IR", espn_id=f"e-{pid}"
        )
        for pid in [*hurt, *(ir_ids or [])]
    }
    reports = [
        InjuryReport(
            name=pid.upper(),
            club="KC",
            status="Injured Reserve",
            updated=datetime(2026, 9, 22, tzinfo=UTC),
            athlete_id=f"e-{pid}",
            returns=_week_of(week),
        )
        for pid, (_, week) in hurt.items()
    ]
    return client, FakeESPN(injuries=reports)


def _stashes(client: FakeSleeper, espn: FakeESPN) -> list[Action]:
    actions = nfl_provider(client, espn).summary("L1").actions
    assert actions is not None
    return [a for a in actions if a.key.startswith("stash:")]


def test_an_empty_ir_slot_stashes_a_free_agent_back_before_the_playoffs_into_the_open_spot() -> None:
    [item] = _stashes(*_client({"ir1": (12.0, 6)}))

    assert (item.key, item.kind, item.player_id, item.drop) == ("stash:ir1", "waiver", "ir1", "")
    assert "wk 6" in item.reason
    assert "108.0" in item.reason


def test_a_full_roster_names_the_weakest_bench_player_to_drop_for_the_claim() -> None:
    [item] = _stashes(*_client({"ir1": (12.0, 6)}, bench=[BENCH, BENCH_RB]))

    assert item.drop == "wr2"
    assert "Bench Receiver" in item.title


def test_one_slot_takes_only_the_best_candidate() -> None:
    assert [a.player_id for a in _stashes(*_client({"ir1": (12.0, 6), "ir2": (15.0, 8)}))] == ["ir2"]


def test_two_empty_slots_take_a_candidate_each() -> None:
    roomy = replace(LEAGUE, ir_slots=2)
    found = _stashes(*_client({"ir1": (12.0, 6), "ir2": (15.0, 8)}, league=roomy))

    assert {a.player_id for a in found} == {"ir1", "ir2"}


def test_nothing_to_stash_without_an_empty_ir_slot() -> None:
    assert _stashes(*_client({"ir1": (12.0, 6)}, league=replace(LEAGUE, ir_slots=0))) == []
    assert _stashes(*_client({"ir1": (12.0, 6)}, ir_ids=["held"])) == []


def test_a_player_back_only_in_the_playoffs_is_not_a_stash() -> None:
    assert _stashes(*_client({"ir1": (12.0, 15)})) == []


def test_a_player_back_too_late_to_score_much_is_not_a_stash() -> None:
    # Week 14 alone: 12 points.
    assert _stashes(*_client({"ir1": (12.0, 14)})) == []


def test_a_player_worth_less_than_the_weakest_bench_player_is_not_a_stash() -> None:
    # Nine weeks at 3: enough points, but half the bench receiver's 6 a week.
    assert _stashes(*_client({"ir1": (3.0, 6)})) == []


def test_a_player_with_no_return_date_is_not_a_stash() -> None:
    client, _ = _client({"ir1": (12.0, 6)})

    assert _stashes(client, FakeESPN()) == []


def test_projections_ahead_that_will_not_load_leave_the_stash_out() -> None:
    client, espn = _client({"ir1": (12.0, 6)})
    client.unloaded_weeks = {9}

    assert _stashes(client, espn) == []


def test_the_judge_sees_the_stash_among_the_items_it_rules_on() -> None:
    client, espn = _client({"ir1": (12.0, 6)})

    context = nfl_provider(client, espn).build_context("L1")

    assert any(task.key == "stash:ir1" for task in context.tasks)


def test_his_form_before_the_injury_counts_beside_a_modest_projection() -> None:
    client, espn = _client({"ir1": (3.0, 6)})
    client.game_lines = [
        game_line("ir1", week, team="KC", opponent="LV", off_snp=50, tm_off_snp=60, rec_tgt=9, pts_ppr=20.0)
        for week in (1, 2)
    ]

    [item] = _stashes(client, espn)

    assert [line.label for line in item.evidence] == ["IR1"]


def test_a_roster_with_no_bench_to_drop_still_says_the_claim_needs_a_spot() -> None:
    starters_only = replace(LEAGUE, roster_positions=["QB", "RB", "WR", "FLEX"])

    [item] = _stashes(*_client({"ir1": (12.0, 6)}, bench=[], league=starters_only))

    assert item.drop == ""
