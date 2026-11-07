"""Tests for what the model reads about a basketball week."""

from datetime import date

from thefrontoffice.adapters.outbound.competitions.nba import prompt
from thefrontoffice.adapters.outbound.competitions.nba.rules import BLOCKS, CATEGORIES, STEALS
from thefrontoffice.adapters.outbound.platforms.yahoo.types import Matchup, MatchupSide, RosteredPlayer


def _week(roster_size: int = 1) -> Matchup:
    return Matchup(
        start=date(2026, 2, 9),
        end=date(2026, 2, 15),
        mine=MatchupSide(team_key="t.1", name="Mine", points="4", stats={BLOCKS.yahoo_stat: "12"}),
        opponent=MatchupSide(
            team_key="t.2", name="Theirs", points="5", stats={BLOCKS.yahoo_stat: "17", STEALS.yahoo_stat: "9"}
        ),
        opponent_roster=[RosteredPlayer(name=f"Threat {i}", position="C") for i in range(roster_size)],
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
