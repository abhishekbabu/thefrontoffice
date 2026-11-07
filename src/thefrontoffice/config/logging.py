"""One logging setup, called once per process by each entry point.

The vendor loggers are quietened deliberately rather than left at their
defaults: yahoofantasy and the OAuth stack narrate every request at INFO, which
buries this app's own lines in a report that makes dozens of them.
"""

import logging
import sys

from thefrontoffice.config.settings import settings


def setup_logging(level: str | None = None) -> None:
    """Send this app's logs to stdout at `level` (the configured one where not given), and quieten the libraries.

    Handlers are added only when there are none, so a second call from another
    entry point in the same process does not double every line.
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(level or settings.log_level)

    if not root_logger.handlers:
        # Bound at call time, after stdout has been reconfigured to UTF-8.
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S"))
        root_logger.addHandler(handler)

    logging.getLogger("yahoofantasy").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("oauthlib").setLevel(logging.WARNING)
    logging.getLogger("requests_oauthlib").setLevel(logging.WARNING)
