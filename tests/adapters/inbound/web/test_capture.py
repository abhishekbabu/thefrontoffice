"""Tests for the gate in front of the browser-sync routes: which pages may call them, and how much they may send."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from support.wiring import wiring as fake_wiring

from thefrontoffice.adapters.inbound.web import api as web
from thefrontoffice.adapters.inbound.web.capture import CaptureGate, allowed_origin

PLAN = "/api/platforms/yahoo/capture/plan"
YAHOO_PAGE = "https://basketball.fantasysports.yahoo.com"
ELSEWHERE = "https://example.com"


@pytest.fixture
def client() -> TestClient:
    return TestClient(web.create_app(fake_wiring()))


@pytest.mark.parametrize(
    "origin",
    ["https://basketball.fantasysports.yahoo.com", "https://football.fantasysports.yahoo.com"],
)
def test_a_yahoo_fantasy_page_may_call_the_sync(origin: str) -> None:
    assert allowed_origin(origin)


@pytest.mark.parametrize(
    "origin",
    [
        "https://fantasysports.yahoo.com.evil.com",
        "https://basketball.fantasysports.yahoo.com.evil.com",
        "https://evilfantasysports.yahoo.com",
        "https://fantasysports.yahoo.com",
        "http://basketball.fantasysports.yahoo.com",
        "https://basketball.fantasysports.yahoo.com:8443",
        "https://basketball.fantasysports.yahoo.com/",
        "https://sports.yahoo.com",
        "null",
        "",
    ],
)
def test_no_other_page_may(origin: str) -> None:
    assert not allowed_origin(origin)


def test_a_yahoo_page_is_answered_the_preflight_chrome_asks_before_reaching_this_machine(client: TestClient) -> None:
    response = client.options(
        PLAN,
        headers={
            "Origin": YAHOO_PAGE,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Private-Network": "true",
        },
    )

    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == YAHOO_PAGE
    assert response.headers["access-control-allow-private-network"] == "true"
    assert "POST" in response.headers["access-control-allow-methods"]
    assert "content-type" in response.headers["access-control-allow-headers"]


def test_a_yahoo_page_may_read_the_answer(client: TestClient) -> None:
    response = client.get(PLAN, headers={"Origin": YAHOO_PAGE})

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == YAHOO_PAGE


@pytest.mark.parametrize("method", ["OPTIONS", "GET", "POST"])
def test_any_other_page_is_refused_before_anything_runs(client: TestClient, method: str) -> None:
    response = client.request(method, PLAN, headers={"Origin": ELSEWHERE})

    assert (response.status_code, response.json()["code"]) == (403, "invalid_request")
    assert "access-control-allow-origin" not in response.headers


def test_a_request_from_no_page_at_all_passes(client: TestClient) -> None:
    """No `Origin` means no other site's page sent it: Settings reading the status, or a terminal."""
    response = client.get("/api/platforms/yahoo/capture")

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_every_other_route_stays_same_origin(client: TestClient) -> None:
    response = client.get("/api/capabilities", headers={"Origin": YAHOO_PAGE})

    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def _echo_app(max_bytes: int) -> TestClient:
    async def echo(request: Request) -> JSONResponse:
        return JSONResponse({"bytes": len(await request.body())})

    return TestClient(
        CaptureGate(Starlette(routes=[Route("/api/platforms/yahoo/capture", echo, methods=["POST"])]), max_bytes)
    )


def test_a_body_within_the_limit_reaches_the_route_whole() -> None:
    response = _echo_app(10).post("/api/platforms/yahoo/capture", content=b"x" * 10, headers={"Origin": YAHOO_PAGE})

    assert response.json() == {"bytes": 10}
    assert response.headers["access-control-allow-origin"] == YAHOO_PAGE


def test_a_body_past_the_limit_is_refused_whatever_its_headers_claim() -> None:
    def chunks() -> Iterator[bytes]:
        yield b"x" * 8
        yield b"x" * 8

    response = _echo_app(10).post("/api/platforms/yahoo/capture", content=chunks(), headers={"Origin": YAHOO_PAGE})

    assert response.status_code == 413
    assert response.headers["access-control-allow-origin"] == YAHOO_PAGE
