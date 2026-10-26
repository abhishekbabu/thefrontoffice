"""Reading a week's summary in a test."""

from thefrontoffice.domain.models import Side, Summary


def mine(summary: Summary) -> Side:
    """Your side of the week, which every summary under test has.

    Asserted rather than assumed, so a summary that lost it fails here by name
    instead of as an AttributeError three attributes later.
    """
    assert summary.mine is not None
    return summary.mine
