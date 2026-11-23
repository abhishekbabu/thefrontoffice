"""Tests for basketball in its own terms: `competitions/nba/model.py`."""

from thefrontoffice.adapters.outbound.competitions.nba import model
from thefrontoffice.adapters.outbound.platforms.yahoo import types as yahoo


def test_the_injured_and_unstarted_slots_are_the_ones_yahoo_files_players_in() -> None:
    """The platform cannot import the competition, so the two are kept in step
    here: an injured slot missing from either would count its player as active."""
    assert model.INJURED_SLOTS == yahoo.INJURED
    assert model.UNSTARTED_SLOTS == yahoo.UNSTARTED


def test_a_player_without_a_printed_line_reads_as_one_with_nothing_on_it() -> None:
    """The same empty line Yahoo sends for a player it has no averages for."""
    assert (dict(model.NO_LINE.stats), model.NO_LINE.points) == (yahoo.YahooLine().stats, yahoo.YahooLine().points)
