"""A platform's own way in: its browser login, and its browser sync."""

from fastapi import APIRouter

from thefrontoffice.adapters.inbound.web.routes.deps import CurrentWiring, PlatformLogins
from thefrontoffice.adapters.inbound.web.routes.state import Login, Logins, LoginState
from thefrontoffice.domain.errors import NotFoundError
from thefrontoffice.domain.models import Capture, CapturePlan, CaptureReceipt, CaptureStatus
from thefrontoffice.domain.ports import BrowserCapture
from thefrontoffice.wiring import Wiring

router = APIRouter()

PLATFORM = "/api/platforms/{platform}"

LEGACY_CAPTURE = "/api/yahoo/capture"
"""Where a sync bookmark installed before the platforms moved under `/api/platforms` still hands over.

The bookmark's code lives in the person's browser, not here, so this path answers for as long as one might."""


def _login(logins: Logins, platform: str) -> Login:
    if platform not in logins:
        raise NotFoundError(f"a login to {platform!r}")
    return logins[platform]


def _capture(wiring: Wiring, platform: str) -> BrowserCapture:
    if platform not in wiring.captures:
        raise NotFoundError(f"a browser sync for {platform!r}")
    return wiring.captures[platform]()


@router.get(f"{PLATFORM}/login", response_model=LoginState)
def login_state(platform: str, logins: PlatformLogins) -> LoginState:
    return _login(logins, platform).state


@router.post(f"{PLATFORM}/login", response_model=LoginState)
def start_login(platform: str, logins: PlatformLogins) -> LoginState:
    """Begin the platform's handshake and return at once.

    The browser tab it opens is on this machine — the server and the person
    are the same place — but the click cannot be waited on inside a request,
    so progress is reported through the companion GET.
    """
    return _login(logins, platform).start()


@router.get(f"{PLATFORM}/capture", response_model=CaptureStatus)
def capture_status(platform: str, wiring: CurrentWiring) -> CaptureStatus:
    """When the platform's browser sync last stored anything, for Settings to say beside the bookmark."""
    return _capture(wiring, platform).status()


@router.get(f"{PLATFORM}/capture/plan", response_model=CapturePlan)
def capture_plan(platform: str, wiring: CurrentWiring, leagues: str = "") -> CapturePlan:
    """What the sync bookmark should fetch next, for the comma-separated league keys it has found so far.

    Called from the platform's own page, so the bookmark knows nothing of
    what the app reads: it fetches what this says, hands it back, and asks
    again until there is nothing new to fetch.
    """
    return _capture(wiring, platform).plan([key for key in leagues.split(",") if key])


@router.post(f"{PLATFORM}/capture", response_model=CaptureReceipt)
def ingest_capture(platform: str, capture: Capture, wiring: CurrentWiring) -> CaptureReceipt:
    """Store what the sync bookmark fetched before replying: the hand-over is the only copy."""
    return _capture(wiring, platform).ingest(capture)


@router.get(f"{LEGACY_CAPTURE}/plan", response_model=CapturePlan, include_in_schema=False)
def legacy_capture_plan(wiring: CurrentWiring, leagues: str = "") -> CapturePlan:
    """`capture_plan` for Yahoo, where an older bookmark asks for it."""
    return capture_plan("yahoo", wiring, leagues)


@router.post(LEGACY_CAPTURE, response_model=CaptureReceipt, include_in_schema=False)
def legacy_ingest_capture(capture: Capture, wiring: CurrentWiring) -> CaptureReceipt:
    """`ingest_capture` for Yahoo, where an older bookmark hands over."""
    return ingest_capture("yahoo", capture, wiring)
