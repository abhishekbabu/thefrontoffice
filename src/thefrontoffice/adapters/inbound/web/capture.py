"""The gate in front of the browser-sync routes: who may call them across origins, and how much they may send.

The sync bookmark runs on a Yahoo Fantasy page and calls this server from
there, so those routes — and only those — answer cross-origin requests, and
only from Yahoo Fantasy's own pages. Chrome asks first whether a public page
may reach a server on this machine at all (Private Network Access), in the same
preflight. Everything else this server answers stays same-origin.

The origin check is CSRF protection, not authentication: a request carrying no
`Origin` did not come from another site's page, and passes as it always has.
"""

import json
import re

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from thefrontoffice.adapters.inbound.remedies import ErrorBody
from thefrontoffice.domain.errors import InvalidRequestError

CAPTURE_ORIGIN = re.compile(r"https://(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+fantasysports\.yahoo\.com")
"""A page on any subdomain of fantasysports.yahoo.com, over https and on its default port — the whole origin, not a prefix."""

CAPTURE_ROUTE = re.compile(r"/api/[a-z0-9-]+/capture(?:/plan)?")

MAX_CAPTURE_BYTES = 48 * 1024 * 1024
"""A sweep of five leagues is about 12 MB in one round at most; well past that is not a sync."""


def allowed_origin(origin: str) -> bool:
    """Whether a page at `origin` may call the sync routes."""
    return CAPTURE_ORIGIN.fullmatch(origin) is not None


class CaptureGate:
    """ASGI middleware: CORS and a body limit for the sync routes, nothing for any other."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_CAPTURE_BYTES) -> None:
        self._app = app
        self._max = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not CAPTURE_ROUTE.fullmatch(scope["path"]):
            await self._app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        origin = headers.get("origin")
        if origin is not None and not allowed_origin(origin):
            await _refuse(send, 403, f"{origin} may not call this server.")
            return
        if scope["method"] == "OPTIONS" and origin is not None:
            await _preflight(send, origin)
            return
        if scope["method"] == "POST":
            body = await _read(receive, self._max)
            if body is None:
                await _refuse(send, 413, f"A sync may send at most {self._max // (1024 * 1024)} MB at once.", origin)
                return
            receive = _replay(body, receive)
        await self._app(scope, receive, _allowing(send, origin))


def _cors(origin: str | None) -> list[tuple[bytes, bytes]]:
    if origin is None:
        return []
    return [(b"access-control-allow-origin", origin.encode()), (b"vary", b"Origin")]


async def _preflight(send: Send, origin: str) -> None:
    headers = [
        *_cors(origin),
        (b"access-control-allow-methods", b"GET, POST"),
        (b"access-control-allow-headers", b"content-type"),
        # Chrome's Private Network Access: a public page reaching a server on this machine.
        (b"access-control-allow-private-network", b"true"),
        (b"access-control-max-age", b"600"),
    ]
    await send({"type": "http.response.start", "status": 204, "headers": headers})
    await send({"type": "http.response.body", "body": b""})


async def _refuse(send: Send, status: int, reason: str, origin: str | None = None) -> None:
    body = json.dumps(ErrorBody.of(InvalidRequestError([reason])).model_dump()).encode()
    headers = [*_cors(origin), (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


async def _read(receive: Receive, limit: int) -> bytes | None:
    """The whole request body, or None once it runs past `limit` bytes — whatever its headers claimed."""
    body = bytearray()
    while True:
        message = await receive()
        if message["type"] != "http.request":
            return bytes(body)
        body += message.get("body", b"")
        if len(body) > limit:
            return None
        if not message.get("more_body", False):
            return bytes(body)


def _replay(body: bytes, receive: Receive) -> Receive:
    """`receive` for an app downstream, handing it the body already read and then whatever follows."""
    sent = False

    async def wrapped() -> Message:
        nonlocal sent
        if sent:
            return await receive()
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    return wrapped


def _allowing(send: Send, origin: str | None) -> Send:
    """`send`, with the allowed origin added to the response's headers."""

    async def wrapped(message: Message) -> None:
        if message["type"] == "http.response.start":
            message = {**message, "headers": [*message.get("headers", []), *_cors(origin)]}
        await send(message)

    return wrapped
