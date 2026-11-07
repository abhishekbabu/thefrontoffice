"""Yahoo's transport, standing in: the SDK context both the login and the league reader ask through."""

import threading
from typing import Any

from yahoofantasy.api.parse import parse_response

SDK_STORE_TTL = 3600
"""How long the SDK's own store keeps a response when not told otherwise."""


class FakeContext:
    """Stands in for yahoofantasy's Context, answering in Yahoo's own XML, which the real parser reads.

    `answers` maps the start of a query to its response; any other query gets
    `response`. `make_request` is how everything but the scoreboard is fetched;
    `_load_or_fetch` is the scoreboard's, read through the SDK's store.
    """

    def __init__(
        self,
        response: str = "<fantasy_content/>",
        error: Exception | None = None,
        answers: dict[str, str] | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.answers = answers or {}
        self.fail_first: list[Exception] = []
        """Raised one per request, before any answer."""
        self.requests: list[tuple[str, str | bool]] = []
        self.barrier: threading.Barrier | None = None
        """Held by each request until all its parties arrive, so serial requests never finish."""
        self.store_ttls: list[int] = []
        """The freshness each read through the SDK's store asked for."""

    def make_request(self, url: str, league: str | bool = False) -> str:
        self.requests.append((url, league))
        self._fail()
        if self.barrier:
            self.barrier.wait()
        return self._answer(url)

    def _load_or_fetch(self, persist_path: str, query: str, *, league: str, persist_ttl: int = SDK_STORE_TTL) -> Any:
        self.store_ttls.append(persist_ttl)
        self._fail()
        return parse_response(self._answer(query))

    def _fail(self) -> None:
        if self.fail_first:
            raise self.fail_first.pop(0)
        if self.error:
            raise self.error

    def _answer(self, query: str) -> str:
        return next((xml for prefix, xml in self.answers.items() if query.startswith(prefix)), self.response)

    @property
    def queries(self) -> list[str]:
        return [query for query, _ in self.requests]
