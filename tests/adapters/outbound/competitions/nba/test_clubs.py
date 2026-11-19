"""Tests for an NBA club in each platform's spelling: `nba/clubs.py`."""

from thefrontoffice.adapters.outbound.competitions.nba.clubs import espn_club


def test_the_clubs_espn_spells_differently_read_in_its_spelling() -> None:
    assert [espn_club(t) for t in ("GSW", "NOP", "NYK", "SAS", "UTA", "WAS")] == ["GS", "NO", "NY", "SA", "UTAH", "WSH"]


def test_a_club_both_spell_alike_is_left_as_it_is_upper_cased() -> None:
    assert (espn_club("PHX"), espn_club("bkn")) == ("PHX", "BKN")
