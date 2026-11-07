"""Print the HTTP API's OpenAPI schema, which the web client's types are generated from.

Read by `web/scripts/api-types.mjs` rather than fetched from a running server,
so generating the types needs no port, no credentials and nothing listening.
The routes close over the wiring without calling it, so the real one is safe
to hand over: nothing here reaches a platform or a model.

Run with `just api-types`.
"""

import json
import sys

from thefrontoffice import bootstrap
from thefrontoffice.adapters.inbound.web.api import create_app
from thefrontoffice.bootstrap import Wiring


def schema(wiring: Wiring) -> dict[str, object]:
    """The schema the API serves at `/api/openapi.json`."""
    return create_app(wiring).openapi()


def main() -> int:
    json.dump(schema(bootstrap.wiring()), sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
