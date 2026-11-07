"""Tests for the cache cleaner: it clears every platform cache, and never what the manager decided."""

import clean

from thefrontoffice.config.settings import AppSettings


def _default(field: str) -> object:
    return AppSettings.model_fields[field].default


def test_every_platform_cache_the_settings_name_is_cleaned() -> None:
    platforms = {_default(f) for f in AppSettings.model_fields if f.endswith("_cache_dir") and f != "answer_cache_dir"}

    assert set(clean.DATA_CACHES) == platforms


def test_kept_answers_and_decisions_are_never_cleaned() -> None:
    kept = {_default("answer_cache_dir"), _default("item_state_dir")}

    assert kept.isdisjoint(clean.DATA_CACHES + clean.TOOL_CACHES)
