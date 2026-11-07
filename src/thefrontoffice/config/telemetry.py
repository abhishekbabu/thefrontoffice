"""OpenTelemetry tracing, exported to Logfire.

Everything worth measuring in this app happens inside a library: the outbound
HTTP to Yahoo, Sleeper and FPL, and the Gemini calls. Both have
auto-instrumentation, so tracing is configured here and nowhere else — no span
is opened by hand, and neither `domain/` nor `application/` learns that
telemetry exists. That is the whole reason this stays a config concern rather
than becoming a port.

Inert without a token. `send_to_logfire="if-token-present"` means a fresh clone,
CI and the test suite make no network call and need no secret, while the
instrumentation itself is still installed — so a missing token changes where
spans go, not whether the code runs.
"""

import logging
import os

from thefrontoffice.config.settings import AppSettings, settings

logger = logging.getLogger(__name__)

CAPTURE_CONTENT_VAR = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"
"""The OpenTelemetry variable deciding whether prompt text is exported."""


class Telemetry:
    """Tracing for one process, configured from `config` on the first setup and left alone after.

    Once because instrumenting a library twice would trace each call twice.
    """

    def __init__(self, config: AppSettings) -> None:
        self._config = config
        self.configured = False

    def setup(self, service_name: str) -> None:
        """Configure tracing, unless it already is.

        Args:
            service_name: which front end this process is, so traces from the CLI
                and the web UI stay separable in one project.
        """
        if self.configured:
            return
        self.configured = True
        config = self._config

        import logfire

        # Set before configure(): the genai instrumentation reads it at import.
        os.environ.setdefault(CAPTURE_CONTENT_VAR, str(config.logfire_capture_prompts).lower())

        logfire.configure(
            service_name=service_name,
            environment=config.logfire_environment,
            token=config.logfire_token,
            send_to_logfire="if-token-present",
            # The CLI already prints a formatted UI to stdout; a second stream of
            # spans through the same terminal would be unreadable.
            console=False,
        )

        logfire.instrument_requests()
        logfire.instrument_google_genai()
        # Unlike genai's, this instrumentation records message text whatever the
        # capture setting says, and a message carries the user's roster. So it
        # runs only where prompts are being exported anyway; otherwise each call's
        # model, latency and token counts still arrive through its log line.
        if config.logfire_capture_prompts:
            logfire.instrument_openai()
        # Records validation failures on the answer formats the model fills, which
        # is how a malformed model response actually presents.
        logfire.instrument_pydantic()

        # The app already logs through the standard library everywhere outside the
        # inbound adapters, including tenacity's retry warnings. Bridging that is
        # cheaper than re-instrumenting any of it.
        logging.getLogger().addHandler(logfire.LogfireLoggingHandler())

        if config.logfire_token:
            logger.info(f"Telemetry enabled for {service_name} ({config.logfire_environment})")
            if config.logfire_capture_prompts:
                logger.warning("LOGFIRE_CAPTURE_PROMPTS is on: prompt and completion text will be sent to Logfire.")


PROCESS = Telemetry(settings)
"""This process's tracing: each entry point sets it up once."""


def setup_telemetry(service_name: str) -> None:
    """Configure this process's tracing once; see `Telemetry.setup`."""
    PROCESS.setup(service_name)
