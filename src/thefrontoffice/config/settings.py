"""Central application configuration backed by environment variables.

A single flat Pydantic settings class — field names are snake_case and
pydantic-settings matches them to SCREAMING_SNAKE env vars case-insensitively.
Values are validated at import time, so a malformed .env fails immediately with
a readable error instead of raising somewhere deep in a report run.
"""

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/thefrontoffice/config/settings.py -> repo root
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class AppSettings(BaseSettings):
    """One field per environment variable, plus static tuning constants."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Gemini ──────────────────────────────────────────────────────────
    # Optional. Absent means the app simply has no analysis to offer: nothing
    # that needs a model is shown, rather than shown and then refused.
    gemini_api_key: str | None = Field(default=None, validation_alias="GOOGLE_API_KEY")
    default_model: str = "gemini-2.5-pro"

    # ── Groq and OpenRouter ─────────────────────────────────────────────
    # Optional, like Gemini, and both free to start. Either key alone is
    # enough for analysis. Models are settings rather than constants because
    # a free catalog turns over within months; each pair is the strong model
    # that judges and the fast one that parses.
    groq_api_key: str | None = None
    groq_analysis_model: str = "openai/gpt-oss-120b"
    groq_parsing_model: str = "openai/gpt-oss-20b"
    openrouter_api_key: str | None = None
    openrouter_analysis_model: str = "nvidia/nemotron-3-super-120b-a12b:free"
    openrouter_parsing_model: str = "nvidia/nemotron-3-super-120b-a12b:free"
    answer_cache_dir: str = ".answer_cache"
    """Where every model answer is kept — a week's judgment, each free agent's
    call — so a reload shows it and an unchanged question costs no call."""
    item_state_dir: str = ".item_state"
    """Where the to-do items you dismissed or snoozed are remembered, per league."""

    # ── Yahoo ───────────────────────────────────────────────────────────
    yahoo_client_id: str | None = None
    yahoo_client_secret: str | None = None
    yahoo_redirect_uri: str = "https://localhost:8080"
    yahoo_token_file: str = ".yahoofantasy"
    yahoo_cache_dir: str = ".yahoo_cache"
    yahoo_max_weekly_adds: int = Field(default=3, ge=0)

    # ── Sleeper (fantasy football) ──────────────────────────────────────
    # Sleeper needs no credentials; the username is only used to find leagues.
    sleeper_username: str | None = None
    sleeper_cache_dir: str = ".sleeper_cache"

    # ── Fantasy Premier League ──────────────────────────────────────────
    # FPL needs no credentials, and has no public username lookup — the entry
    # id is the number in the URL of your own points page.
    fpl_entry_id: int | None = Field(default=None, gt=0)
    fpl_cache_dir: str = ".fpl_cache"

    # ── ESPN ────────────────────────────────────────────────────────────
    # Public news feeds, no credentials. Read for the headlines behind a
    # player, which no fantasy platform here publishes.
    espn_cache_dir: str = ".espn_cache"

    # ── Telemetry ───────────────────────────────────────────────────────
    # Optional. Without a token nothing is exported and no network call is
    # made, so a fresh clone and the test suite behave identically to before.
    logfire_token: str | None = None
    logfire_environment: str = "local"
    """Separates traces from a laptop run and a deployed one in the same project."""

    logfire_capture_prompts: bool = False
    """Whether to send prompt and completion text to Logfire.

    Off by default and deliberately so: a prompt carries the user's roster,
    their leagues and their FPL entry id. Timings and token counts answer
    almost every question without any of that leaving the machine.
    """

    # ── Logging ─────────────────────────────────────────────────────────
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator(
        "gemini_api_key",
        "groq_api_key",
        "openrouter_api_key",
        "yahoo_client_id",
        "yahoo_client_secret",
        "sleeper_username",
        "fpl_entry_id",
        "logfire_token",
        mode="before",
    )
    @classmethod
    def _blank_is_unset(cls, v: object) -> object:
        """Treat `KEY=` in .env as absent rather than as an empty string.

        A commented-out or blank line is how people express "I do not use this",
        and `""` is not None — so a plain `is not None` check would report a
        credential as present and the failure would surface later, at the API
        call, instead of at startup.
        """
        return None if isinstance(v, str) and not v.strip() else v

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, v: object) -> object:
        """Accept `log_level=debug` in .env without forcing the caller to shout."""
        return v.upper() if isinstance(v, str) else v


settings = AppSettings()
