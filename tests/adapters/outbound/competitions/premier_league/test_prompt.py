"""Tests for what the model reads about a Premier League gameweek, beyond what `test_fpl.py` renders."""

from support.prompts import named_fields, schema_fields

from thefrontoffice.adapters.outbound.competitions.premier_league import prompt
from thefrontoffice.application.formats import ScoutAnswer


def test_the_prompt_names_only_fields_its_answer_has() -> None:
    """A guided field the schema lacks is an instruction the model cannot follow."""
    assert named_fields(prompt.FPL_SCOUT_PROMPT) <= schema_fields(ScoutAnswer)
