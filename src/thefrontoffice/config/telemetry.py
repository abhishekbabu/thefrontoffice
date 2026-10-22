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

from thefrontoffice.config.settings import settings

logger = logging.getLogger(__name__)

CAPTURE_CONTENT_VAR = "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"
"""The OpenTelemetry variable deciding whether prompt text is exported."""

_configured = False


def setup_telemetry(service_name: str) -> None:
    """Configure tracing once per process.

    Idempotent because both entry points call it and Streamlit reruns its whole
    script on every interaction, which would otherwise re-instrument each
    library on every click.

    Args:
        service_name: which front end this process is, so traces from the CLI
            and the web UI stay separable in one project.
    """
    global _configured
    if _configured:
        return
    _configured = True

    import logfire

    # Set before configure(): the genai instrumentation reads it at import.
    os.environ.setdefault(CAPTURE_CONTENT_VAR, str(settings.logfire_capture_prompts).lower())

    logfire.configure(
        service_name=service_name,
        environment=settings.logfire_environment,
        token=settings.logfire_token,
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
    if settings.logfire_capture_prompts:
        logfire.instrument_openai()
    # Records validation failures on ScoutReport and TradeVerdict, which is how
    # a malformed model response actually presents.
    logfire.instrument_pydantic()

    # The app already logs through the standard library everywhere outside the
    # inbound adapters, including tenacity's retry warnings. Bridging that is
    # cheaper than re-instrumenting any of it.
    logging.getLogger().addHandler(logfire.LogfireLoggingHandler())

    if settings.logfire_token:
        logger.info(f"Telemetry enabled for {service_name} ({settings.logfire_environment})")
        if settings.logfire_capture_prompts:
            logger.warning("LOGFIRE_CAPTURE_PROMPTS is on: prompt and completion text will be sent to Logfire.")
