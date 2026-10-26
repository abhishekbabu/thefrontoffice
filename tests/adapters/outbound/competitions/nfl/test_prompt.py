"""Tests for the text a model reads.

Covers `nfl/prompt.py`. The assertions are on prompt *content* — the league
rules live there, and a prompt that renders is not a prompt that is right.
"""

import re
from datetime import UTC
from typing import Any

from support.nfl import DEFAULT_PROJECTIONS, SLEEPER_USER_ID, FakeESPN, FakeSleeper, nfl_provider, proj
from support.summary import mine

from thefrontoffice.adapters.outbound.platforms.sleeper.errors import SleeperAPIError
from thefrontoffice.adapters.outbound.platforms.sleeper.types import (
    NFLGameLine,
    SleeperLeague,
    SleeperRoster,
    TrendingPlayer,
)
from thefrontoffice.domain.models import Stat, task_id

# ── context ─────────────────────────────────────────────────────────────


def _context(**kwargs: Any) -> Any:
    client = FakeSleeper(projections=dict(DEFAULT_PROJECTIONS), **kwargs)
    return nfl_provider(client).build_context("L1")


def _lineup_stat(context: Any) -> Stat:
    return next(stat for stat in context.headline if stat.label == "Lineup")


def _figures(text: str) -> list[float]:
    """Every one-decimal figure in a piece of text, in order: the numbers, not the words around them."""
    return [float(x) for x in re.findall(r"\d+\.\d\b", text)]


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
            SleeperRoster(
                roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb2"]
            )
        ],
    )
    context = nfl_provider(client).build_context("L1")

    [task] = context.tasks
    assert task.player_id == "rb1"
    # The id and the move on one line, which is what a verdict is matched by.
    assert any(task_id(1) in line and task.title in line for line in context.prompt.splitlines())


def test_a_player_with_no_projection_is_kept_at_zero() -> None:
    """A bye or an inactive is a zero, and the report must see it — not silently
    drop the player from the roster."""
    client = FakeSleeper(
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[SleeperRoster(roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=["qb1", "bye1"], starter_ids=["qb1"])],
    )
    ctx = nfl_provider(client).build_context("L1")
    assert "Bye Guy" in ctx.roster_lines


def test_matchup_opponent_and_live_score_are_surfaced() -> None:
    ctx = _context(
        matchups=[
            {"roster_id": 1, "matchup_id": 7, "points": 60.2},
            {"roster_id": 2, "matchup_id": 7, "points": 71.8},
        ],
        rosters=[
            SleeperRoster(
                roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb2"]
            ),
            SleeperRoster(roster_id=2, owner_id="user-2", player_ids=[], starter_ids=[], wins=3, losses=0),
        ],
    )
    assert "Rival" in ctx.situation
    assert "60.2" in ctx.situation
    assert "71.8" in ctx.situation


def test_a_week_with_no_matchup_reports_no_opponent_figures() -> None:
    """Paired with nobody is not a 0-0 scoreline against somebody."""
    labels = {s.label for s in _context(matchups=[{"roster_id": 1, "matchup_id": None}]).headline}

    assert not labels & {"Opponent", "Live"}


def test_trending_players_are_included_with_their_projection() -> None:
    ctx = _context(trending=[TrendingPlayer(player_id="wr9", count=41234)])
    assert "Waiver WR" in ctx.prompt
    assert "41,234" in ctx.prompt


def test_trending_failure_degrades_without_losing_the_report() -> None:
    """An independent signal, not load-bearing."""
    ctx = _context(trending_error=SleeperAPIError("429"))
    assert ctx.roster_lines  # the rest still built


def test_the_lineup_figure_is_the_current_total_beside_the_best() -> None:
    """The gap is the point: how many points are sitting on the bench."""
    client = FakeSleeper(
        league=SMALL_LEAGUE,
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[
            SleeperRoster(
                roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb2"]
            )
        ],
    )
    lineup = _lineup_stat(nfl_provider(client).build_context("L1"))

    assert _figures(lineup.value) == [26.0, 40.0]  # 22 + 4, and 22 + 18
    assert lineup.tone == "warning"


def test_no_bench_gap_is_reported_when_already_optimal() -> None:
    client = FakeSleeper(
        league=SMALL_LEAGUE,
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[
            SleeperRoster(
                roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb1"]
            )
        ],
    )
    lineup = _lineup_stat(nfl_provider(client).build_context("L1"))

    assert _figures(lineup.value) == [40.0]  # no best beside it: this is the best
    assert lineup.tone == "neutral"


def test_a_player_is_never_both_starting_and_benched() -> None:
    """The lineup block shows what is set; the bench holds everyone else."""
    client = FakeSleeper(
        league=SMALL_LEAGUE,
        projections=dict(DEFAULT_PROJECTIONS),
        rosters=[
            SleeperRoster(
                roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb2"]
            )
        ],
    )
    side = mine(nfl_provider(client).summary("L1"))

    starting = {spot.player_id for spot in side.lineup if spot.player_id}
    benched = {spot.player_id for spot in side.bench}
    assert starting and benched and not (starting & benched)


def test_the_bench_gap_matches_the_printed_figures() -> None:
    """The three numbers in the prompt must agree once rounded.

    26.06 and 40.14 print as 26.1 and 40.1; a gap taken before rounding would
    print 14.1 beside them, and read as arithmetic that does not add up.
    """
    projections = {
        "qb1": proj("qb1", "Star QB", "QB", 22.02),
        "rb1": proj("rb1", "Good RB", "RB", 18.12),
        "rb2": proj("rb2", "Bad RB", "RB", 4.04),
    }
    client = FakeSleeper(
        league=SMALL_LEAGUE,
        projections=projections,
        rosters=[
            SleeperRoster(
                roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb2"]
            )
        ],
    )
    current, best, gap = _figures(nfl_provider(client).build_context("L1").constraints)

    assert (current, best) == (26.1, 40.1)
    assert gap == round(best - current, 1)


# ── headline figures ────────────────────────────────────────────────────


def test_the_weeks_header_leaves_the_record_to_the_league_view() -> None:
    """Record and points for answer how the season is going, which is the league view's question."""
    week = {stat.label for stat in _context().headline}

    assert "Record" not in week and "Lineup" in week


def test_points_left_on_the_bench_ride_with_the_lineup_and_warn() -> None:
    lineup = next(
        s
        for s in nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).build_context("L1").headline
        if s.label == "Lineup"
    )

    assert lineup.tone == "warning"  # Good RB sits while Bad RB starts


def test_the_header_agrees_with_the_prompt_about_the_lineup_total() -> None:
    """Two numbers for the same thing, differing in the last decimal, reads as
    a bug even when neither is wrong."""
    context = nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).build_context("L1")

    current, best = _figures(_lineup_stat(context).value)
    assert _figures(context.constraints)[:2] == [current, best]


def test_the_header_carries_the_matchup() -> None:
    """The question the page is opened to answer: who, and am I ahead."""
    client = FakeSleeper(
        projections=DEFAULT_PROJECTIONS,
        matchups=[
            {"roster_id": 1, "matchup_id": 7, "points": 88.5},
            {"roster_id": 2, "matchup_id": 7, "points": 71.0},
        ],
    )
    labels = {s.label: s for s in nfl_provider(client).build_context("L1").headline}

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
    live = next(s for s in nfl_provider(client).build_context("L1").headline if s.label == "Live")

    assert live.tone == "warning"


def test_a_week_with_no_opponent_reports_no_matchup_figures() -> None:
    """A bye or a missing scoreboard is not a 0-0 scoreline."""
    labels = {s.label for s in nfl_provider(FakeSleeper(projections=DEFAULT_PROJECTIONS)).build_context("L1").headline}

    assert "Live" not in labels
    assert "Lineup" in labels  # the rest of the header still stands


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
    context = nfl_provider(client).build_context("L1")

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
    """45 of 60 snaps is his role; MIA giving up 17.0 a game to backs is his matchup."""
    client = FakeSleeper(projections=dict(DEFAULT_PROJECTIONS), game_lines=_played())

    line = nfl_provider(client).build_context("L1").roster_lines["Good RB"]

    assert "75%" in line and "17.0" in line


def test_with_nothing_played_the_lines_are_the_projection_alone() -> None:
    """No role or matchup line beneath any player: there is nothing to read them from."""
    assert all(line.count("\n") == 1 for line in _context().roster_lines.values())


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
            SleeperRoster(
                roster_id=1, owner_id=SLEEPER_USER_ID, player_ids=["qb1", "rb1", "rb2"], starter_ids=["qb1", "rb2"]
            )
        ],
        game_lines=lines,
    )

    context = nfl_provider(client).build_context("L1")

    [task] = context.tasks
    assert task.evidence
    assert all(line.value in context.prompt for line in task.evidence)


def test_each_player_line_carries_his_latest_news() -> None:
    from datetime import datetime

    from thefrontoffice.adapters.outbound.platforms.espn.types import NewsArticle

    article = NewsArticle(
        article_id="1", published=datetime.now(UTC), headline="Good RB takes over", summary="Lead back now."
    )
    client = FakeSleeper(projections=dict(DEFAULT_PROJECTIONS))

    prompt = nfl_provider(client, FakeESPN({"BUF": [article]})).build_context("L1").prompt

    assert article.headline in prompt and article.summary in prompt
