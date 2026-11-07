"""Tests for finding a scope under its competition's former name: `storage/scopes.py`."""

from thefrontoffice.adapters.outbound.storage.scopes import former

RENAMED = {"nfl-sleeper": "NFL (Sleeper)"}


def test_the_competition_is_respelled_and_the_rest_kept() -> None:
    assert former("wire:nfl-sleeper:L1:8155", RENAMED) == "wire:NFL (Sleeper):L1:8155"


def test_a_competition_never_renamed_has_no_former_spelling() -> None:
    assert former("scout:premier-league-fpl:L1", RENAMED) is None


def test_a_scope_naming_no_competition_has_none() -> None:
    assert former("nfl-sleeper", RENAMED) is None
