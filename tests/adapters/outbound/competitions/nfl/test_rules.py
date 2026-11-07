"""Tests for football's shared facts: `competitions/nfl/rules.py`."""

from thefrontoffice.adapters.outbound.competitions.nfl.rules import FANTASY_POSITIONS, FLEX_ELIGIBILITY
from thefrontoffice.adapters.outbound.platforms.sleeper.types import STARTING_SLOTS


def test_every_scoring_slot_sleeper_lists_is_a_position_or_a_flex_the_rules_know() -> None:
    """The platform cannot import the competition, so the two lists are kept
    in step here: a slot Sleeper scores that the rules do not know would be
    filled by no one, and a position the rules score that Sleeper never
    starts would never reach a lineup."""
    assert set(STARTING_SLOTS) == FANTASY_POSITIONS | FLEX_ELIGIBILITY.keys()


def test_a_flex_slot_accepts_only_positions_the_league_scores() -> None:
    for slot, positions in FLEX_ELIGIBILITY.items():
        assert set(positions) <= FANTASY_POSITIONS, slot
