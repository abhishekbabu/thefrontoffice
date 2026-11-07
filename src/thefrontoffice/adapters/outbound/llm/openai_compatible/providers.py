"""The OpenAI-compatible providers this app can use, and where each is configured.

Each is a base URL, a key and two models — the strong one that judges and
the fast one that parses, the same split Gemini's Pro and Flash make. Built
from the settings the composition root hands over, per call, so a key saved
while the app runs takes effect on the next call rather than the next restart.
"""

from dataclasses import dataclass

from thefrontoffice.config.settings import AppSettings, env_var

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


def groq(config: AppSettings) -> Provider:
    return Provider(
        name="Groq",
        setting=env_var("groq_api_key"),
        base_url=GROQ_BASE_URL,
        api_key=config.groq_api_key,
        analysis_model=config.groq_analysis_model,
        parsing_model=config.groq_parsing_model,
    )


def openrouter(config: AppSettings) -> Provider:
    return Provider(
        name="OpenRouter",
        setting=env_var("openrouter_api_key"),
        base_url=OPENROUTER_BASE_URL,
        api_key=config.openrouter_api_key,
        analysis_model=config.openrouter_analysis_model,
        parsing_model=config.openrouter_parsing_model,
    )
