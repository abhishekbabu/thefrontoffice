"""Authorize this machine with Yahoo, once.

The OAuth2 handshake opens a browser and waits for a click, so it cannot run
inside the web server or anywhere else non-interactive — those paths report a
missing token and point here. The token is cached in `.yahoofantasy`.

The login is verified before reporting success. Yahoo will hand back a token
that authenticates and yet permits nothing, if the developer app had no API
permissions saved at the moment you authorized; announcing "logged in" and
letting the first report fail is how an afternoon disappears.

Run with `just yahoo-login`, or `just yahoo-login --force` to replace a token.
"""

import sys
from pathlib import Path

from thefrontoffice.bootstrap import yahoo_auth
from thefrontoffice.config.logging import setup_logging
from thefrontoffice.config.settings import settings
from thefrontoffice.domain.errors import FrontOfficeError


def main() -> int:
    setup_logging()
    force = "--force" in sys.argv
    token = Path(settings.yahoo_token_file)

    if token.exists() and not force:
        print("  Already authorized. Checking the token still works…")
        return _verify()

    if token.exists():
        # Discarded rather than overwritten: a re-authorization exists to obtain
        # a *new* grant, and leaving the old one in place invites reusing it.
        token.unlink()
        print(f"  Removed {token}.")

    print("  A browser window will open — authorize the app there.")
    try:
        yahoo_auth().login(force=True)
    except FrontOfficeError as e:
        print(f"  ❌ {e}")
        return 1
    return _verify()


def _verify() -> int:
    try:
        yahoo_auth().verify()
    except FrontOfficeError as e:
        print(f"  ❌ {e}")
        return 1
    print("  ✅ Authorized, and Yahoo accepted a Fantasy Sports read.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
