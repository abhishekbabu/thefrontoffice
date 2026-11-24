"""Tests for how a prompt names the untouchables: `competitions/untouchables.py`."""

from thefrontoffice.adapters.outbound.competitions.untouchables import given, note


def test_nobody_untouchable_adds_nothing_to_a_prompt() -> None:
    assert note(frozenset()) == []


def test_every_untouchable_is_named_once_in_one_line() -> None:
    [line] = note(frozenset({"Kaelon Black", "Jordyn Tyson"}))

    assert "Kaelon Black" in line and "Jordyn Tyson" in line
    assert "\n" not in line


def test_a_trade_giving_no_untouchable_adds_nothing_and_one_giving_some_names_each() -> None:
    assert given(frozenset()) == []
    [line] = given(frozenset({"Coby White"}))
    assert "Coby White" in line
