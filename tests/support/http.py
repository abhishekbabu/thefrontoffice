"""Stand-ins for `requests`, for the public-API clients and the transport they share."""

from typing import Any

import requests


def http_error(status: int) -> requests.exceptions.HTTPError:
    """A failed request carrying a real Response with `status`: all the retry and outage checks read off one."""
    response = requests.Response()
    response.status_code = status
    return requests.exceptions.HTTPError(response=response)


class FakeResponse:
    """A `requests` response carrying a payload and a status."""

    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise http_error(self.status_code)

    def json(self) -> Any:
        return self._payload


class FakeSession:
    """Stands in for a `requests` session for the public-API clients: canned payloads by URL substring.

    The first route whose fragment is in the URL answers, so list the most
    specific first; anything unrouted is a 404. Every URL asked for is kept.
    """

    def __init__(self, routes: dict[str, Any], error: Exception | None = None) -> None:
        self.routes = routes
        self.error = error
        self.requests: list[str] = []

    def get(self, url: str, timeout: int = 0) -> FakeResponse:
        self.requests.append(url)
        if self.error:
            raise self.error
        for fragment, payload in self.routes.items():
            if fragment in url:
                return FakeResponse(payload)
        return FakeResponse(None, status=404)
