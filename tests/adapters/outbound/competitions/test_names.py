"""Tests for cross-platform player-name matching.

A wrong match silently attributes one player's numbers to another, so the
policy refuses ambiguity rather than guessing.
"""

from thefrontoffice.adapters.outbound.competitions.names import NameIndex, normalize_name

# ── normalization ───────────────────────────────────────────────────────


def test_accents_are_stripped() -> None:
    assert normalize_name("Luka Dončić") == normalize_name("Luka Doncic")


def test_generational_suffixes_are_dropped() -> None:
    assert normalize_name("Jaren Jackson Jr.") == normalize_name("Jaren Jackson")
    assert normalize_name("Gary Trent II") == normalize_name("Gary Trent")


def test_a_hyphen_separates_words_but_an_apostrophe_does_not() -> None:
    assert normalize_name("Karl-Anthony Towns") == "karl anthony towns"
    assert normalize_name("De'Aaron Fox") == "deaaron fox"


def test_case_and_extra_whitespace_are_ignored() -> None:
    assert normalize_name("  LeBRON   james ") == normalize_name("LeBron James")


def test_distinct_players_do_not_collapse() -> None:
    assert normalize_name("Nikola Jokic") != normalize_name("Nikola Jovic")


def test_an_empty_name_normalizes_to_empty() -> None:
    assert normalize_name("") == ""
    assert normalize_name("...") == ""


# ── lookup ──────────────────────────────────────────────────────────────


def _index(*names: str) -> NameIndex[str]:
    index: NameIndex[str] = NameIndex()
    for name in names:
        index.add(name, name)
    return index


def test_an_exact_match_wins() -> None:
    assert _index("Josh Allen").lookup("Josh Allen") == "Josh Allen"


def test_a_differently_spelled_name_still_matches() -> None:
    assert _index("Luka Dončić").lookup("Luka Doncic") == "Luka Dončić"


def test_a_unique_surname_matches_a_differing_first_name() -> None:
    assert _index("Cameron Johnson").lookup("Cam Johnson") == "Cameron Johnson"


def test_an_ambiguous_surname_resolves_to_nothing() -> None:
    """Two Jacksons must not resolve to whichever was added first."""
    index = _index("Jaren Jackson", "Andrew Jackson")
    assert index.lookup("Reggie Jackson") is None


def test_an_exact_match_survives_an_ambiguous_surname() -> None:
    index = _index("Jaren Jackson", "Andrew Jackson")
    assert index.lookup("Jaren Jackson") == "Jaren Jackson"


def test_ambiguity_is_detected_whichever_order_names_arrive() -> None:
    forwards = _index("Josh Allen", "Keenan Allen")
    backwards = _index("Keenan Allen", "Josh Allen")
    assert forwards.lookup("Some Allen") is None
    assert backwards.lookup("Some Allen") is None


def test_a_third_player_with_the_same_surname_stays_ambiguous() -> None:
    index = _index("Josh Allen", "Keenan Allen", "Braylon Allen")
    assert index.lookup("Some Allen") is None
    assert index.lookup("Keenan Allen") == "Keenan Allen"


def test_an_unknown_name_matches_nothing() -> None:
    assert _index("Josh Allen").lookup("Nobody At All") is None


def test_an_empty_name_matches_nothing() -> None:
    assert _index("Josh Allen").lookup("") is None


def test_an_unnameable_entry_is_not_indexed() -> None:
    index: NameIndex[str] = NameIndex()
    index.add("...", "value")
    assert index.is_empty


def test_size_and_emptiness_are_reported() -> None:
    index = _index("Josh Allen", "Keenan Allen")
    assert len(index) == 2
    assert not index.is_empty
    assert NameIndex().is_empty
