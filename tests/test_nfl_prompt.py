"""Tests for the text a model reads.

Covers `nfl/prompt.py`. The assertions are on prompt *content* — the league
rules live there, and a prompt that renders is not a prompt that is right.
"""

from typing import Any

from conftest import (
    DEFAULT_PROJECTIONS,
    SLEEPER_USER_ID,
    FakeESPN,
    FakeSleeper,
    _proj,
    _provider,
)

from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    NFLGameLine,
    SleeperLeague,
    SleeperRoster,
    TrendingPlayer,
)
from thefrontoffice.domain.errors import SleeperAPIError
from thefrontoffice.domain.models import task_id

MY_ID = SLEEPER_USER_ID


# ── context ─────────────────────────────────────────────────────────────


def _context(**kwargs: Any) -> Any:
    client = FakeSleeper(projections=dict(DEFAULT_PROJECTIONS), **kwargs)
    return _provider(client).build_context("L1")


def test_prompt_names_the_scoring_format() -> None:
    """Every projection is in that currency; getting it wrong ranks by the wrong number."""
    assert "Full PPR" in _context().prompt


def test_roster_and_available_players_are_separated() -> None:
    ctx = _context()
    assert "Star QB" in ctx.roster_lines
    assert "Waiver WR" in ctx.candidate_lines
    assert "Waiver WR" not in ctx.roster_lines


def test_rostered_players_are_never_offered_as_waiver_adds() -> None:
    ctx = _context()
    assert "Good RB" not in ctx.candidate_lines


SMALL_LEAGUE = SleeperLeague(
    league_id="L1",
    name="Sunday Money",
    season="2026",
    total_rosters=12,
    scoring_format="pts_ppr",
    roster_positions=["QB", "RB", "BN", "BN"],
)


def test_the_to_do_list_is_shown_numbered_so_each_verdict_can_find_its_row() -> None:
    """One RB slot, and the worse RB is starting — the same item the page shows."""
    client = FakeSleeper(
        league=SMALL_LEAGUE,
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[
            SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb2"])
        ],
    )
    context = _provider(client).build_context("L1")

    [task] = context.tasks
    assert task.player_id == "rb1"
    # The id and the move on one line, which is what a verdict is matched by.
    assert any(task_id(1) in line and task.title in line for line in context.prompt.splitlines())


def test_a_week_with_nothing_to_decide_says_so() -> None:
    client = FakeSleeper(
        league=SMALL_LEAGUE,
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[
            SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb1"])
        ],
    )
    context = _provider(client).build_context("L1")

    assert context.tasks == []


def test_an_unfilled_slot_is_shown_as_empty() -> None:
    """A thin roster must read as a hole in the lineup, not silently shrink it."""
    assert "(empty)" in _context().prompt


def test_a_player_with_no_projection_is_kept_at_zero() -> None:
    """A bye or an inactive is a zero, and the report must see it — not silently
    drop the player from the roster."""
    client = FakeSleeper(
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "bye1"], starter_ids=["qb1"])],
    )
    ctx = _provider(client).build_context("L1")
    assert "Bye Guy" in ctx.roster_lines
    assert "0.0 proj pts" in ctx.roster_lines["Bye Guy"]
    assert "(no game)" in ctx.roster_lines["Bye Guy"]


def test_matchup_opponent_and_live_score_are_surfaced() -> None:
    ctx = _context(
        matchups=[
            {"roster_id": 1, "matchup_id": 7, "points": 60.2},
            {"roster_id": 2, "matchup_id": 7, "points": 71.8},
        ],
        rosters=[
            SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb2"]),
            SleeperRoster(roster_id=2, owner_id="user-2", player_ids=[], starter_ids=[], wins=3, losses=0),
        ],
    )
    assert "Rival" in ctx.situation
    assert "60.2" in ctx.situation
    assert "71.8" in ctx.situation


def test_a_week_with_no_matchup_says_so() -> None:
    assert "No head-to-head matchup" in _context(matchups=[{"roster_id": 1, "matchup_id": None}]).situation


def test_trending_players_are_included_with_their_projection() -> None:
    ctx = _context(trending=[TrendingPlayer(player_id="wr9", count=41234)])
    assert "Waiver WR" in ctx.prompt
    assert "41,234" in ctx.prompt


def test_trending_failure_degrades_without_losing_the_report() -> None:
    """An independent signal, not load-bearing."""
    ctx = _context(trending_error=SleeperAPIError("429"))
    assert "(unavailable)" in ctx.prompt
    assert ctx.roster_lines  # the rest still built


def test_constraints_compare_current_and_best_lineups() -> None:
    """The gap is the point: how many points are sitting on the bench."""
    client = FakeSleeper(
        league=SMALL_LEAGUE,
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[
            SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb2"])
        ],
    )
    constraints = _provider(client).build_context("L1").constraints
    assert "LINEUP SLOTS" in constraints
    assert "Current lineup projects 26.0" in constraints  # 22 + 4
    assert "best legal lineup projects 40.0" in constraints  # 22 + 18
    assert "14.0 points are sitting on the bench" in constraints


def test_no_bench_gap_is_reported_when_already_optimal() -> None:
    client = FakeSleeper(
        league=SMALL_LEAGUE,
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[
            SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb1"])
        ],
    )
    assert "sitting on the bench" not in _provider(client).build_context("L1").constraints


def test_a_player_is_never_both_starting_and_benched() -> None:
    """The lineup block shows what is set; the bench holds everyone else."""
    client = FakeSleeper(
        league=SMALL_LEAGUE,
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[
            SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb2"])
        ],
    )
    prompt = _provider(client).build_context("L1").prompt
    lineup_block = prompt.split("YOUR CURRENT LINEUP")[1].split("BENCH:")[0]
    bench_block = prompt.split("BENCH:")[1].split("LINEUP CHANGES")[0]
    starting = {line.split(": ")[1].split(" (")[0] for line in lineup_block.strip().splitlines() if ": " in line}
    benched = {line.split("- ")[1].split(" (")[0] for line in bench_block.strip().splitlines() if line.startswith("- ")}
    assert not (starting & benched), f"{starting & benched} both starting and benched"


def test_the_bench_gap_matches_the_printed_figures() -> None:
    """The three numbers in the prompt must agree once rounded."""
    import re

    projections = {
        "qb1": _proj("qb1", "Star QB", "QB", 22.04),
        "rb1": _proj("rb1", "Good RB", "RB", 18.06),
        "rb2": _proj("rb2", "Bad RB", "RB", 4.04),
    }
    client = FakeSleeper(
        league=SMALL_LEAGUE,
        projections=projections,
        rosters=[
            SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb2"])
        ],
    )
    constraints = _provider(client).build_context("L1").constraints
    current, best = (float(x) for x in re.findall(r"projects (\d+\.\d)", constraints))
    gap_match = re.search(r"so (\d+\.\d) points are sitting", constraints)
    assert gap_match is not None
    assert float(gap_match.group(1)) == round(best - current, 1)


def test_roster_rows_mark_starters_and_bench() -> None:
    client = FakeSleeper(
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "rb1"], starter_ids=["qb1"])],
    )
    rows = [c.columns for c in _provider(client).roster("L1")]
    assert {r["Player"]: r["Slot"] for r in rows} == {"Star QB": "START", "Good RB": "BN"}


def test_roster_rows_skip_players_missing_from_the_catalog() -> None:
    client = FakeSleeper(rosters=[SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["ghost"], starter_ids=[])])
    assert _provider(client).roster("L1") == []


# ── headline figures ────────────────────────────────────────────────────


def test_the_header_carries_the_weeks_standing() -> None:
    context = _provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).build_context("L1")
    labels = {stat.label: stat.value for stat in context.headline}

    assert labels["Week"] == "3"
    assert labels["Record"] == "2-1"
    assert labels["Points for"] == "250.5"


def test_the_header_agrees_with_the_prompt_about_the_lineup_total() -> None:
    """Two numbers for the same thing, differing in the last decimal, reads as
    a bug even when neither is wrong."""
    context = _provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).build_context("L1")
    lineup = next(stat for stat in context.headline if stat.label == "Lineup")

    assert f"Current lineup projects {lineup.value} points" in context.constraints


def test_the_header_carries_the_matchup() -> None:
    """The question the page is opened to answer: who, and am I ahead."""
    client = FakeSleeper(
        projections=DEFAULT_PROJECTIONS,
        matchups=[
            {"roster_id": 1, "matchup_id": 7, "points": 88.5},
            {"roster_id": 2, "matchup_id": 7, "points": 71.0},
        ],
    )
    labels = {s.label: s for s in _provider(client).build_context("L1").headline}

    assert "Opponent" in labels
    assert (labels["Live"].value, labels["Live"].tone) == ("88.5 – 71.0", "good")
    assert "Margin" not in labels  # the same two numbers, subtracted


def test_trailing_is_the_figure_that_warns() -> None:
    client = FakeSleeper(
        projections=DEFAULT_PROJECTIONS,
        matchups=[
            {"roster_id": 1, "matchup_id": 7, "points": 60.0},
            {"roster_id": 2, "matchup_id": 7, "points": 84.0},
        ],
    )
    live = next(s for s in _provider(client).build_context("L1").headline if s.label == "Live")

    assert live.tone == "warning"


def test_a_week_with_no_opponent_reports_no_matchup_figures() -> None:
    """A bye or a missing scoreboard is not a 0-0 scoreline."""
    labels = {s.label for s in _provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).build_context("L1").headline}

    assert "Live" not in labels
    assert "Week" in labels  # the rest of the header still stands


def test_the_matchup_is_fetched_once_for_both_the_prompt_and_the_header() -> None:
    """Deriving them separately would pull the scoreboard twice per report, and
    the scoreboard is the one thing here that changes minute to minute."""
    client = FakeSleeper(
        projections=DEFAULT_PROJECTIONS,
        matchups=[
            {"roster_id": 1, "matchup_id": 7, "points": 88.5},
            {"roster_id": 2, "matchup_id": 7, "points": 71.0},
        ],
    )
    context = _provider(client).build_context("L1")

    assert client.matchup_fetches == 1
    assert "OPPONENT:" in context.situation
    assert any(s.label == "Opponent" for s in context.headline)


# ── what the projections rest on ────────────────────────────────────────


def _played() -> list[NFLGameLine]:
    """Good RB's first two games, both against MIA's run defense."""
    return [
        NFLGameLine(
            player_id="rb1",
            week=w,
            team="BUF",
            opponent="MIA",
            position="RB",
            stats={"off_snp": 45, "tm_off_snp": 60, "rush_att": 16, "pts_ppr": 17},
        )
        for w in (1, 2)
    ]


def test_each_player_line_carries_his_role_and_matchup() -> None:
    client = FakeSleeper(projections=dict(DEFAULT_PROJECTIONS), game_lines=_played())
    provider = _provider(client)
    good_rb = DEFAULT_PROJECTIONS["rb1"]

    prompt = provider.build_context("L1").prompt

    described = provider._week("L1").evidence.describe(good_rb)
    assert described and described in prompt


def test_with_nothing_played_the_lines_are_the_projection_alone() -> None:
    assert "of snaps" not in _context().prompt


def test_a_to_do_item_carries_its_evidence_into_the_prompt() -> None:
    """The model is asked to overrule on role and matchup, so it has to see them."""
    lines = [
        NFLGameLine(
            player_id=pid,
            week=1,
            team="BUF",
            opponent="MIA",
            position="RB",
            stats={"off_snp": snaps, "tm_off_snp": 60, "rush_att": 10, "pts_ppr": 12},
        )
        for pid, snaps in (("rb1", 45), ("rb2", 15))
    ]
    client = FakeSleeper(
        league=SMALL_LEAGUE,
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[
            SleeperRoster(roster_id=1, owner_id=MY_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb2"])
        ],
        game_lines=lines,
    )

    context = _provider(client).build_context("L1")

    [task] = context.tasks
    assert task.evidence
    assert all(line.value in context.prompt for line in task.evidence)


def test_each_player_line_carries_his_latest_news() -> None:
    from datetime import datetime, timezone

    from thefrontoffice.adapters.outbound.platforms.espn.types import NewsArticle

    article = NewsArticle(
        article_id="1", published=datetime.now(timezone.utc), headline="Good RB takes over", summary="Lead back now."
    )
    client = FakeSleeper(projections=dict(DEFAULT_PROJECTIONS))

    prompt = _provider(client, FakeESPN({"BUF": [article]})).build_context("L1").prompt

    assert article.headline in prompt and article.summary in prompt
