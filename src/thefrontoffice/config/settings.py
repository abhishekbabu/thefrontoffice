"""Central application configuration backed by environment variables.

A single flat Pydantic settings class — field names are snake_case and
pydantic-settings matches them to SCREAMING_SNAKE env vars case-insensitively.
Values are validated at import time, so a malformed .env fails immediately with
a readable error instead of raising somewhere deep in a report run.

Everything said about a setting is said on its field: which group it belongs
to, whether it is a secret, whether it names a path on this machine. The
Settings page, `just doctor`, the error that names a missing key and the test
suite's isolation all read it from there, so none keeps its own list.
"""

import types
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Union, get_args, get_origin

from pydantic import Field, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# src/thefrontoffice/config/settings.py -> repo root
PROJECT_ROOT = Path(__file__).resolve().parents[3]


Section = Literal["platforms", "ai", "advanced"]
"""Where a group sits on the Settings page: the accounts read, the models that judge, everything rarely touched."""


@dataclass(frozen=True)
class Group:
    """What a set of settings unlocks, for a person setting them up."""

    title: str
    note: str
    section: Section
    platform: str = ""
    """The platform these settings read, where they read one: its status sits beside them."""

    switch: str = ""
    """The field choosing how the platform is read, where there is more than one way: the
    settings marked with a `Mode` matter only while it reads theirs."""

    modes: tuple[tuple[str, str], ...] = ()
    """What to know about each of the switch's values, in its own order: shown for the one chosen."""


@dataclass(frozen=True)
class Mode:
    """Marks a setting needed only while its group's switch reads `value`: the rest of the time it is noise."""

    value: str


@dataclass(frozen=True)
class Hint:
    """What a setting does, where its name alone would mislead: shown under it."""

    text: str


@dataclass(frozen=True)
class Secret:
    """Marks a setting whose value must never leave the process — only whether it is set."""


SECRET = Secret()


@dataclass(frozen=True)
class Local:
    """Marks a setting naming a path on this machine: a cache, a token, what the app keeps."""


LOCAL = Local()

YAHOO = Group(
    "NBA on Yahoo",
    "",
    "platforms",
    "yahoo",
    switch="yahoo_source",
    modes=(
        (
            "oauth",
            "Needs a Yahoo developer app with Fantasy Sports read access and redirect URI "
            "https://localhost:8080, which Yahoo reviews before it answers. Until then, use session or browser.",
        ),
        ("browser", "The sync bookmark, run on a Yahoo Fantasy page, sends your leagues here."),
        ("session", "This server reads Yahoo with your signed-in session cookie."),
    ),
)
SLEEPER = Group("NFL on Sleeper", "No key needed: just the username your leagues are under.", "platforms", "sleeper")
FPL = Group(
    "Fantasy Premier League",
    "The entry id is the number in your points page's URL: fantasy.premierleague.com/entry/<THIS>/event/1",
    "platforms",
    "fpl",
)
AI = Group(
    "Model providers",
    "Optional, and free to start. Any one key turns on judging the to-do list and the wire, and asking about a "
    "player. With several, each backs up the one before when its free quota runs out: Gemini, then Groq, then "
    "OpenRouter.",
    "ai",
)
TRACING = Group(
    "Tracing",
    "Optional. Nothing is sent without a token. Prompts carry your roster and leagues, so they are sent only "
    "if you turn that on.",
    "advanced",
)
ADVANCED = Group("Files and server", "Rarely worth changing. Each field shows the value in force.", "advanced")

GROUPS = (YAHOO, SLEEPER, FPL, AI, TRACING, ADVANCED)
"""Platforms in the order the rail lists their competitions, then models, then what is rarely touched."""


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
    gemini_api_key: Annotated[str | None, AI, SECRET] = Field(default=None, validation_alias="GOOGLE_API_KEY")

    # ── Groq and OpenRouter ─────────────────────────────────────────────
    # Optional, like Gemini, and both free to start. Either key alone is
    # enough for analysis. Models are settings rather than constants because
    # a free catalog turns over within months; each pair is the strong model
    # that judges and the fast one that parses.
    groq_api_key: Annotated[str | None, AI, SECRET] = None
    groq_analysis_model: Annotated[str, AI] = "openai/gpt-oss-120b"
    groq_parsing_model: Annotated[str, AI] = "openai/gpt-oss-20b"
    openrouter_api_key: Annotated[str | None, AI, SECRET] = None
    openrouter_analysis_model: Annotated[str, AI] = "nvidia/nemotron-3.5-super-vl:free"
    openrouter_parsing_model: Annotated[str, AI] = "nvidia/nemotron-3.5-super-vl:free"
    answer_cache_dir: Annotated[str, ADVANCED, LOCAL] = ".answer_cache"
    """Where every model answer is kept — a week's judgment, each free agent's
    call — so a reload shows it and an unchanged question costs no call."""
    item_state_dir: Annotated[str, ADVANCED, LOCAL] = ".item_state"
    """Where the to-do items you dismissed or snoozed, and the players you marked untouchable, are kept, per league."""

    # ── Yahoo ───────────────────────────────────────────────────────────
    yahoo_source: Annotated[Literal["oauth", "browser", "session"], YAHOO] = "oauth"
    """Where Yahoo is read from: its API through this machine's OAuth login; or,
    while Yahoo has not approved the app, the sync bookmark run on a Yahoo
    Fantasy page, or this server fetching Yahoo's own frontend host with your
    session cookie. Neither of those needs a client id or secret."""

    yahoo_session_cookie: Annotated[str | None, YAHOO, SECRET, Mode("session")] = None
    """The Cookie header a signed-in Yahoo Fantasy page sends, for YAHOO_SOURCE=session.
    Reads your Yahoo account until it expires; signing out of Yahoo revokes it."""

    yahoo_client_id: Annotated[str | None, YAHOO, SECRET, Mode("oauth")] = None
    yahoo_client_secret: Annotated[str | None, YAHOO, SECRET, Mode("oauth")] = None
    yahoo_redirect_uri: Annotated[str, YAHOO, Mode("oauth")] = "https://localhost:8080"
    yahoo_token_file: Annotated[str, ADVANCED, LOCAL] = ".yahoofantasy"
    yahoo_cache_dir: Annotated[str, ADVANCED, LOCAL] = ".yahoo_cache"
    yahoo_max_weekly_adds: Annotated[
        int, YAHOO, Hint("Only for a league whose own weekly add limit Yahoo doesn't report.")
    ] = Field(default=3, ge=0)

    # ── Sleeper (fantasy football) ──────────────────────────────────────
    # Sleeper needs no credentials; the username is only used to find leagues.
    sleeper_username: Annotated[str | None, SLEEPER] = None
    sleeper_cache_dir: Annotated[str, ADVANCED, LOCAL] = ".sleeper_cache"

    # ── Fantasy Premier League ──────────────────────────────────────────
    # FPL needs no credentials, and has no public username lookup — the entry
    # id is the number in the URL of your own points page.
    fpl_entry_id: Annotated[int | None, FPL] = Field(default=None, gt=0)
    fpl_cache_dir: Annotated[str, ADVANCED, LOCAL] = ".fpl_cache"

    # ── ESPN ────────────────────────────────────────────────────────────
    # Public news feeds, no credentials. Read for the headlines behind a
    # player, which no fantasy platform here publishes.
    espn_cache_dir: Annotated[str, ADVANCED, LOCAL] = ".espn_cache"

    # ── Telemetry ───────────────────────────────────────────────────────
    # Optional. Without a token nothing is exported and no network call is
    # made, so a fresh clone and the test suite behave identically to before.
    logfire_token: Annotated[str | None, TRACING, SECRET] = None
    logfire_environment: Annotated[str, TRACING] = "local"
    """Separates traces from a laptop run and a deployed one in the same project."""

    logfire_capture_prompts: Annotated[bool, TRACING] = False
    """Whether to send prompt and completion text to Logfire.

    Off by default and deliberately so: a prompt carries the user's roster,
    their leagues and their FPL entry id. Timings and token counts answer
    almost every question without any of that leaving the machine.
    """

    # ── Logging ─────────────────────────────────────────────────────────
    log_level: Annotated[Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], ADVANCED] = "INFO"

    # ── Web server ──────────────────────────────────────────────────────
    port: Annotated[int, ADVANCED] = Field(default=8000, ge=1, le=65535)
    """Where `just ui` and `just api` listen. Read at startup, so a change takes a restart."""

    @field_validator("*", mode="before")
    @classmethod
    def _blank_is_unset(cls, v: object, info: ValidationInfo) -> object:
        """Treat `KEY=` in .env as absent, for any setting that may be absent.

        A commented-out or blank line is how people express "I do not use this",
        and `""` is not None — so a plain `is not None` check would report a
        credential as present and the failure would surface later, at the API
        call, instead of at startup.
        """
        blank = isinstance(v, str) and not v.strip()
        return None if blank and info.field_name is not None and optional(info.field_name) else v

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, v: object) -> object:
        """Accept `log_level=debug` in .env without forcing the caller to shout."""
        return v.upper() if isinstance(v, str) else v


def _union(field: str) -> tuple[object, ...]:
    """The members of a setting's annotation: itself alone unless it is a union."""
    annotation = AppSettings.model_fields[field].annotation
    return get_args(annotation) if get_origin(annotation) in (Union, types.UnionType) else (annotation,)


def optional(field: str) -> bool:
    """Whether a setting may be absent: its annotation admits None."""
    return type(None) in _union(field)


def value_type(field: str) -> object:
    """What kind of value a setting holds, with `| None` taken off.

    Optionality is whether a value is required, not what kind of value it is.
    A union of several real types is returned whole.
    """
    real = [member for member in _union(field) if member is not type(None)]
    return real[0] if len(real) == 1 else AppSettings.model_fields[field].annotation


def env_var(field: str) -> str:
    """The environment variable a settings field reads.

    Not always the field name upper-cased — `gemini_api_key` reads
    `GOOGLE_API_KEY` — and the variable is what a user types, so it is the name
    every public surface uses.
    """
    alias = AppSettings.model_fields[field].validation_alias
    return alias if isinstance(alias, str) else field.upper()


def is_secret(field: str) -> bool:
    """Whether a setting's value must never be read back out — only its presence."""
    return any(isinstance(mark, Secret) for mark in AppSettings.model_fields[field].metadata)


def is_local(field: str) -> bool:
    """Whether a setting names a path on this machine."""
    return any(isinstance(mark, Local) for mark in AppSettings.model_fields[field].metadata)


def mode(field: str) -> str:
    """The switch's value a setting is needed under, or empty where it is needed whatever the switch reads."""
    return next((mark.value for mark in AppSettings.model_fields[field].metadata if isinstance(mark, Mode)), "")


def hint(field: str) -> str:
    """What a setting does, where it says so, or empty."""
    return next((mark.text for mark in AppSettings.model_fields[field].metadata if isinstance(mark, Hint)), "")


def group(field: str) -> Group:
    """What a setting unlocks.

    Raises:
        LookupError: the field was declared without one, which a test forbids.
    """
    found = next((mark for mark in AppSettings.model_fields[field].metadata if isinstance(mark, Group)), None)
    if found is None:
        raise LookupError(f"Setting {field} declares no group.")
    return found


settings = AppSettings()
