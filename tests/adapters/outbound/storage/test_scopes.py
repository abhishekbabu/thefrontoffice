"""Tests for finding a scope under its competition's former name: `storage/scopes.py`."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from thefrontoffice.adapters.outbound.cache import DiskCache
from thefrontoffice.adapters.outbound.storage.scopes import former, read


def test_the_competition_is_respelled_and_the_rest_kept() -> None:
    assert former("wire:nfl-sleeper:L1:8155") == "wire:NFL (Sleeper):L1:8155"


def test_a_competition_never_renamed_has_no_former_spelling() -> None:
    assert former("scout:nfl-espn:L1") is None


def test_a_scope_naming_no_competition_has_none() -> None:
    assert former("nfl-sleeper") is None


def test_a_refiled_value_keeps_its_age_rather_than_living_another_keep_for(tmp_path: Path) -> None:
    """Moving an entry to its new scope is not storing it again: it expires
    when it would have under the old one."""
    filed = datetime.now(UTC) - timedelta(days=2)  # `read` looks at the real clock
    cache = DiskCache(tmp_path)
    cache.set("scout:NFL (Sleeper):L1", {"kept": True}, now=filed)

    read(cache, "scout:nfl-sleeper:L1", timedelta(days=30))

    after_old_expiry = filed + timedelta(days=31)
    assert cache.get("scout:nfl-sleeper:L1", timedelta(days=30), now=after_old_expiry) is None
    assert cache.get("scout:nfl-sleeper:L1", timedelta(days=30), now=filed + timedelta(days=29)) == {"kept": True}
