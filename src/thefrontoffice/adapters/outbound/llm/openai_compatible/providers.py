"""The OpenAI-compatible providers this app can use, and where each is configured.

Each is a base URL, a key and two models — the strong one that judges and
the fast one that parses, the same split Gemini's Pro and Flash make. Read
from settings at call time, so a key saved in Settings takes effect on the
next call rather than the next restart.
"""

from dataclasses import dataclass

from thefrontoffice.config.settings import settings

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@dataclass(frozen=True)
class Provider:
    name: str
    """As a person would say it, for logs and error messages: 'Groq'."""

    setting: str
    """The environment variable holding the key, which an error points at."""

    base_url: str
    api_key: str | None
    analysis_model: str
    parsing_model: str


def groq() -> Provider:
    return Provider(
        name="Groq",
        setting="GROQ_API_KEY",
        base_url=GROQ_BASE_URL,
        api_key=settings.groq_api_key,
        analysis_model=settings.groq_analysis_model,
        parsing_model=settings.groq_parsing_model,
    )


def openrouter() -> Provider:
    return Provider(
        name="OpenRouter",
        setting="OPENROUTER_API_KEY",
        base_url=OPENROUTER_BASE_URL,
        api_key=settings.openrouter_api_key,
        analysis_model=settings.openrouter_analysis_model,
        parsing_model=settings.openrouter_parsing_model,
    )
