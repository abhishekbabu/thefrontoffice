"""Tests for what the model reads about a basketball week."""

from dataclasses import replace
from datetime import date

from support.nba import make_player
from support.prompts import named_fields, schema_fields

from thefrontoffice.adapters.outbound.competitions.nba import prompt
from thefrontoffice.adapters.outbound.competitions.nba.rules import BLOCKS, CATEGORIES, POINTS, STEALS, TURNOVERS
from thefrontoffice.adapters.outbound.platforms.yahoo.types import Matchup, MatchupSide
from thefrontoffice.application.formats import ScoutAnswer, TradeAnswer


def _week(roster_size: int = 1) -> Matchup:
    return Matchup(
        start=date(2026, 2, 9),
        end=date(2026, 2, 15),
        mine=MatchupSide(team_key="t.1", name="Mine", points="4", stats={BLOCKS.yahoo_stat: "12"}),
        opponent=MatchupSide(
            team_key="t.2", name="Theirs", points="5", stats={BLOCKS.yahoo_stat: "17", STEALS.yahoo_stat: "9"}
        ),
        opponent_roster=[make_player(f"Threat {i}", position="C") for i in range(roster_size)],
    )


def test_a_line_carries_each_category_it_has_in_league_order() -> None:
    text = prompt.categories({"TO": 2.0, "PTS": 25.0, "FG%": 0.5})
    assert text.split() == ["25.0p", "FG50.0%", "2.0to"]


def test_the_matchup_sets_each_category_side_by_side_by_its_label() -> None:
    text = prompt.matchup(_week())
    assert "BLK: 12 vs 17" in text
    assert "STL: N/A vs 9" in text
    assert "Theirs" in text
    assert all(f"- {c.label}:" in text for c in CATEGORIES)


def test_the_opponents_threats_are_capped() -> None:
    text = prompt.matchup(_week(roster_size=20))
    assert f"Threat {prompt.OPPONENT_KEY_PLAYERS - 1} " in text
    assert f"Threat {prompt.OPPONENT_KEY_PLAYERS} " not in text


def test_no_matchup_says_so_rather_than_leaving_a_gap() -> None:
    assert prompt.matchup(None) == prompt.NO_MATCHUP


def test_the_league_rules_name_the_nine_categories() -> None:
    text = prompt.scout(roster="", week=None, free_agents="", schedule_context="", trans_context="", adds_left=1)
    assert all(c.label in text for c in CATEGORIES)


def test_without_a_matchup_period_the_schedule_lists_no_clubs() -> None:
    assert "LAL" not in prompt.schedule(None, {"LAL": 3}, projected=False)
    assert "LAL: 3 games left" in prompt.schedule(_week(), {"LAL": 3}, projected=False)


WEIGHTS = {POINTS.yahoo_stat: 1.0, BLOCKS.yahoo_stat: 3.0, TURNOVERS.yahoo_stat: -1.0}


def _points_week() -> Matchup:
    week = _week()
    return replace(
        week,
        mine=replace(week.mine, points="349.90", projected="896.45"),
        opponent=replace(week.opponent, points="575.80", projected="1107.37"),
    )


def test_a_points_matchup_is_scored_in_fantasy_points_beside_yahoos_projection() -> None:
    text = prompt.matchup(_points_week(), WEIGHTS)

    assert "349.90 - 575.80" in text
    assert "896.45 - 1107.37" in text
    assert "BLK: 12 vs 17 (x3)" in text
    assert "FG%" not in text  # a stat the league does not weight is no part of the score


def test_a_points_matchup_without_a_projection_shows_none() -> None:
    assert "PROJECTED" not in prompt.matchup(_week(), WEIGHTS)


def test_the_points_rules_give_each_weight_and_no_category_list() -> None:
    text = prompt.scout(
        roster="", week=None, free_agents="", schedule_context="", trans_context="", adds_left=1, weights=WEIGHTS
    )

    assert "PTS 1, BLK 3, TO -1" in text
    assert "FG%" not in text


def test_a_stat_no_category_counts_is_named_by_its_id() -> None:
    assert prompt.weighting({"3": -0.5}) == "stat 3 -0.5"


def test_a_line_closes_on_its_fantasy_points_only_in_a_points_league() -> None:
    line = {"PTS": 20.0, "BLK": 2.0, "TO": 3.0}

    assert prompt.scored(line, WEIGHTS).endswith("= 23.0 fpts")
    assert "fpts" not in prompt.scored(line, None)


def test_a_points_trade_is_judged_in_fantasy_points() -> None:
    categories = prompt.trade(giving="", receiving="", week=None, roster="")
    points = prompt.trade(giving="", receiving="", week=None, roster="", weights=WEIGHTS)

    assert prompt.CATEGORY_LEAGUE.currency in categories
    assert prompt.points_league(WEIGHTS).currency in points


def test_the_prompts_name_only_fields_their_answers_have() -> None:
    """A guided field the schema lacks is an instruction the model cannot follow."""
    assert named_fields(prompt.NBA_SCOUT_PROMPT) <= schema_fields(ScoutAnswer)
    assert named_fields(prompt.NBA_TRADE_PROMPT) <= schema_fields(TradeAnswer)
