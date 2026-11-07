"""One CLI session: the wiring it runs over, and the providers built so far."""

from thefrontoffice.bootstrap import CompetitionEntry, Wiring
from thefrontoffice.domain.ports import CompetitionProvider


class Session:
    """Holds the configured competitions and their providers, building each on first use.

    Construction is deferred because building a provider can open an OAuth
    flow, which a user who does not play that competition must never be made
    to sit through.
    """

    def __init__(self, wiring: Wiring) -> None:
        self.wiring = wiring
        self.entries = wiring.registry.configured()
        """The competitions this machine has credentials for, as they stood when the session began."""
        self._providers: dict[str, CompetitionProvider] = {}

    def provider(self, entry: CompetitionEntry) -> CompetitionProvider:
        if entry.key not in self._providers:
            self._providers[entry.key] = entry.open()
        return self._providers[entry.key]
