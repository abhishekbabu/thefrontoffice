"""Tests for the schema the UI's types are generated from: `scripts/openapi.py`."""

from typing import get_args

import openapi
from support.wiring import wiring as fake_wiring

from thefrontoffice.adapters.inbound.remedies import Remedy
from thefrontoffice.domain.errors import ErrorCode


def _enum(model: str, field: str) -> set[object]:
    """The values the schema allows `model.field`, read off the generated document."""
    node: object = openapi.schema(fake_wiring())
    for step in ("components", "schemas", model, "properties", field, "enum"):
        assert isinstance(node, dict), step
        node = node[step]
    assert isinstance(node, list)
    return set(node)


def test_the_schema_names_every_error_code_the_page_can_be_sent() -> None:
    """A code the server can send and the client's types do not know is a remedy nobody renders."""
    assert _enum("ErrorBody", "code") == set(get_args(ErrorCode))


def test_the_schema_carries_the_remedies_the_page_branches_on() -> None:
    assert _enum("Remedy", "action") == set(get_args(Remedy.model_fields["action"].annotation))
