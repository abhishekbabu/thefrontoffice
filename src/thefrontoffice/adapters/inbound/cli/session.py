"""One CLI session: the wiring it runs over, and the competitions it was configured for."""

from collections.abc import Callable

from thefrontoffice.bootstrap import CompetitionEntry, Wiring
from thefrontoffice.domain.ports import CompetitionProvider


class Session:
    """Holds the configured competitions, and builds a provider for each command that asks.

    Built per command, never kept: a provider holds the week it gathered, and a
    session left open across a waiver run would go on answering from the week
    before it. Building contacts nothing, so a competition nobody asks about
    costs nothing either.
    """

    def __init__(self, wiring: Wiring, *, read: Callable[[str], str] = input) -> None:
        """
        Args:
            read: what prompts for a follow-up question; the terminal's own `input` but in a test.
        """
        self.wiring = wiring
        self.read = read
        self.entries = wiring.registry.configured()
        """The competitions this machine has credentials for, as they stood when the session began."""

    def provider(self, entry: CompetitionEntry) -> CompetitionProvider:
        """A fresh provider for `entry`: call once per command.

        Raises:
            NotConfiguredError: this machine has no credentials for it.
        """
        return entry.open()
