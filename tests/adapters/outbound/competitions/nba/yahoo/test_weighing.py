"""Tests for the week weighed: `nba/yahoo/weighing.py`."""

from support.nba import make_player

from thefrontoffice.adapters.outbound.competitions.nba.yahoo.weighing import open_reserve


def test_the_injured_slots_open_are_those_the_settings_give_that_nobody_holds() -> None:
    held = [make_player("Hurt", "PF,C", "OKC", key="hurt", selected_position="IL")]

    assert open_reserve({"PG": 1, "IL": 2, "IL+": 1}, held) == ("IL", "IL+")
    assert open_reserve({"PG": 1, "IL": 1}, held) == ()
    assert open_reserve({"PG": 1}, []) == ()
