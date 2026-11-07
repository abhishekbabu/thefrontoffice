"""Tests for the answer formats the model fills: `application/formats.py`."""

import pytest
from pydantic import BaseModel

from thefrontoffice.application.formats import (
    CallAnswer,
    MoveAnswer,
    ScoutAnswer,
    TradeAnswer,
    TradeSides,
    VerdictAnswer,
    WireAnswer,
)
from thefrontoffice.domain.models import Move, PlayerCall, ScoutReport, TaskVerdict, TradeVerdict

FORMATS = (ScoutAnswer, MoveAnswer, VerdictAnswer, WireAnswer, CallAnswer, TradeAnswer, TradeSides)


@pytest.mark.parametrize("schema", FORMATS, ids=lambda s: s.__name__)
def test_every_field_carries_a_description_for_the_model(schema: type[BaseModel]) -> None:
    """Field descriptions are the schema's instructions to the model — a field
    without one gives it nothing to go on."""
    undocumented = [n for n, f in schema.model_fields.items() if not f.description]
    assert not undocumented


PAIRS = [(MoveAnswer, Move), (VerdictAnswer, TaskVerdict), (TradeAnswer, TradeVerdict), (CallAnswer, PlayerCall)]


@pytest.mark.parametrize(("answer", "domain"), PAIRS, ids=lambda s: s.__name__)
def test_what_the_model_writes_is_what_the_domain_keeps(answer: type[BaseModel], domain: type[BaseModel]) -> None:
    """The engines build the domain's answer from the model's field by field; a field one lacks would be lost."""
    assert set(answer.model_fields) <= set(domain.model_fields)


@pytest.mark.parametrize(("answer", "domain"), PAIRS, ids=lambda s: s.__name__)
def test_the_domain_carries_none_of_the_instructions(answer: type[BaseModel], domain: type[BaseModel]) -> None:
    """Instructions live in the formats, so a prompt change never changes the domain."""
    assert not [name for name in answer.model_fields if domain.model_fields[name].description]


def test_a_report_keeps_every_part_of_the_judgement_but_the_verdicts_it_files_under_tasks() -> None:
    assert set(ScoutAnswer.model_fields) - {"verdicts"} <= set(ScoutReport.model_fields)
