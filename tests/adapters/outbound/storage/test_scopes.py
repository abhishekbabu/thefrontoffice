"""Tests for finding a scope under its competition's former name: `storage/scopes.py`."""

from datetime import timedelta
from pathlib import Path

from thefrontoffice.adapters.outbound.cache import JsonDiskCache
from thefrontoffice.adapters.outbound.storage.scopes import former, read

WEEK = timedelta(days=7)


def test_the_competition_is_respelled_and_the_rest_kept() -> None:
    assert former("wire:nfl-sleeper:L1:8155") == "wire:NFL (Sleeper):L1:8155"


def test_a_competition_never_renamed_has_no_former_spelling() -> None:
    assert former("scout:nfl-espn:L1") is None


def test_a_scope_naming_no_competition_has_none() -> None:
    assert former("nfl-sleeper") is None


def test_a_null_kept_under_the_key_is_an_answer_and_does_not_fall_back(tmp_path: Path) -> None:
    cache = JsonDiskCache(tmp_path)
    cache.set("scout:NFL (Sleeper):L1", {"old": True})
    cache.set("scout:nfl-sleeper:L1", None)

    assert read(cache, "scout:nfl-sleeper:L1", WEEK) is None
    assert cache.get("scout:nfl-sleeper:L1", WEEK) is None
