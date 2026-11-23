"""What a route is handed: the wiring, the competition its path names, and that competition's provider.

Everything comes from the `Wiring` the app was created with, kept on
`app.state`, so a test's fakes reach every route the same way the real wiring
does.

A route that reads `competition` through a dependency still names it first in
its own signature: FastAPI lists a route's own parameters before its
dependencies', and that order is the client's generated types.

A route with a body resolves its competition itself instead: FastAPI runs
every dependency before it reads the body, so a refusal there would answer a
malformed request that has always been a 422.
"""

from typing import Annotated

from fastapi import Depends, Request, params

from thefrontoffice.adapters.inbound.web.routes.state import Chats, Logins
from thefrontoffice.domain.ports import CompetitionProvider
from thefrontoffice.wiring import CompetitionEntry, Wiring


def _wiring(request: Request) -> Wiring:
    wiring: Wiring = request.app.state.wiring
    return wiring


def _chats(request: Request) -> Chats:
    chats: Chats = request.app.state.chats
    return chats


def _logins(request: Request) -> Logins:
    logins: Logins = request.app.state.logins
    return logins


CurrentWiring = Annotated[Wiring, Depends(_wiring)]
"""The wiring the app was created with."""

OpenChats = Annotated[Chats, Depends(_chats)]
"""The conversations this process holds."""

PlatformLogins = Annotated[Logins, Depends(_logins)]
"""Each platform's browser login, by the platform's name."""


def _entry(competition: str, wiring: CurrentWiring) -> CompetitionEntry:
    return wiring.registry.find(competition)


Entry = Annotated[CompetitionEntry, Depends(_entry)]
"""The registry entry the path's `competition` names.

Raises `UnknownCompetitionError` where none does."""


def _provider(entry: Entry) -> CompetitionProvider:
    return entry.open()


Provider = Annotated[CompetitionProvider, Depends(_provider)]
"""The named competition's provider, built. Raises `NotConfiguredError` without its credentials."""


def Capability[P](port: type[P]) -> params.Depends:
    """The named competition's provider as `port`: `Annotated[WireProvider, Capability(WireProvider)]`.

    Named like a type because it is read as one, beside the port it opens.

    Refused unbuilt, in the words of `CAPABILITIES`, where it cannot do what
    `port` offers.
    """

    def opened(entry: Entry) -> P:
        return entry.open_as(port)

    return Depends(opened)
