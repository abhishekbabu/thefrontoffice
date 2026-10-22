"""Reading and writing `.env` in place.

The counterpart to `settings.py`: that module loads configuration, this one
edits the file it loads from, so the UI can set a credential without anyone
opening an editor.

Two rules make the edit safe. Only keys `AppSettings` actually declares are
written, so a typo cannot silently add a line nothing reads — the same failure
`just doctor` exists to catch, and here it is refused outright. And the file is
rewritten line by line rather than regenerated, so comments, ordering and any
key this app does not own all survive.
"""

import logging
import os
import re
import stat
import types
from pathlib import Path
from typing import Literal, Union, get_args, get_origin

from thefrontoffice.config.settings import PROJECT_ROOT, AppSettings, settings

logger = logging.getLogger(__name__)

ENV_PATH = PROJECT_ROOT / ".env"

# Any one of these turns analysis on.
MODEL_KEYS = ("GOOGLE_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY")

# Values whose contents must never be read back out — only their presence.
SECRET_KEYS = frozenset({*MODEL_KEYS, "YAHOO_CLIENT_ID", "YAHOO_CLIENT_SECRET", "LOGFIRE_TOKEN"})

# Characters that make a bare value ambiguous to a dotenv parser: `#` starts a
# comment, whitespace and quotes end or nest a token.
_NEEDS_QUOTING = re.compile(r'[\s#"\'\\$]')


def env_var(field: str) -> str:
    """The environment variable a settings field reads.

    Not always the field name upper-cased — `gemini_api_key` reads
    `GOOGLE_API_KEY` — and the variable is what a user types, so it is the name
    every public surface uses.
    """
    alias = AppSettings.model_fields[field].validation_alias
    return alias if isinstance(alias, str) else field.upper()


def field_kind(field: str) -> tuple[str, list[str]]:
    """How a setting should be edited, derived from its own annotation.

    A settings page that renders every value as a text box invites a typo the
    validator then rejects on save. `bool` is checked before `int` because in
    Python it is one.

    Returns:
        The control to use, and the allowed values when there are a fixed few.
    """
    annotation = AppSettings.model_fields[field].annotation
    # Unwrap `X | None`: optionality is about whether a value is required, not
    # about what kind of value it is.
    if get_origin(annotation) in (Union, types.UnionType):
        real = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(real) == 1:
            annotation = real[0]

    if get_origin(annotation) is Literal:
        return "choice", [str(value) for value in get_args(annotation)]
    if annotation is bool:
        return "boolean", []
    if annotation is int:
        return "integer", []
    if annotation is float:
        return "number", []
    return "text", []


def declared() -> dict[str, str]:
    """Every environment variable this app reads, mapped to its field name."""
    return {env_var(field): field for field in AppSettings.model_fields}


def is_shadowed(key: str) -> bool:
    """Whether a real environment variable is overriding `.env` for this key.

    pydantic-settings reads the process environment ahead of the file, so a key
    exported in the shell makes an edit here look as though it did nothing.
    Worth saying out loud rather than letting someone save three times.
    """
    return key in os.environ


def read_values() -> dict[str, str]:
    """The keys present in `.env` and their raw values, in file order."""
    if not ENV_PATH.exists():
        return {}
    values: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = _unquote(value.strip())
    return values


def _unquote(value: str) -> str:
    """Reverse `_format`, and read what a dotenv parser would.

    A double-quoted value carries backslash escapes; a single-quoted one is
    literal. Escapes are undone in one pass so a written `\\\\` does not become
    an unescape of the pair that follows it.
    """
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        inner = value[1:-1]
        return re.sub(r"\\(.)", r"\1", inner) if value[0] == '"' else inner
    return value


def _format(value: str) -> str:
    """Render a value so a dotenv parser reads back exactly what was typed."""
    if value and _NEEDS_QUOTING.search(value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


class UnknownSettingError(ValueError):
    """A key no `AppSettings` field reads. Writing it would be a silent no-op."""

    def __init__(self, keys: list[str]) -> None:
        super().__init__(f"No setting reads {', '.join(sorted(keys))}.")
        self.keys = keys


def write_values(updates: dict[str, str]) -> None:
    """Apply `updates` to `.env`, creating it if absent.

    An empty value clears the key rather than writing an empty string, matching
    how `AppSettings` already treats `KEY=` — the way people write "I do not use
    this".

    Raises:
        UnknownSettingError: a key outside what AppSettings declares.
    """
    known = declared()
    if unknown := [key for key in updates if key not in known]:
        raise UnknownSettingError(unknown)

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    remaining = dict(updates)

    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key = stripped.partition("=")[0].strip()
        if key in remaining:
            lines[index] = f"{key}={_format(remaining.pop(key))}"

    if remaining:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend(f"{key}={_format(value)}" for key, value in remaining.items())

    ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _restrict(ENV_PATH)
    logger.info(f"Updated {len(updates)} setting(s) in .env")
    reload_settings()


def _restrict(path: Path) -> None:
    """Make the file owner-only where the platform supports it.

    It holds API keys. Windows ignores POSIX modes, so a failure here is not
    worth failing the save over.
    """
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError as e:
        logger.debug(f"Could not restrict permissions on {path}: {e}")


def reload_settings() -> None:
    """Re-read configuration into the existing singleton.

    Mutated in place rather than rebound: every module imported `settings` by
    value, so replacing the object here would leave all of them pointing at the
    old one.
    """
    fresh = AppSettings()
    for field in AppSettings.model_fields:
        setattr(settings, field, getattr(fresh, field))
