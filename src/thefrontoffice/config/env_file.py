"""Reading and writing `.env` in place, and describing what it configures.

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

from pydantic import BaseModel

from thefrontoffice.config.settings import GROUPS, AppSettings, env_var, group, is_secret

logger = logging.getLogger(__name__)

# Characters that make a bare value ambiguous to a dotenv parser: `#` starts a
# comment, whitespace and quotes end or nest a token.
_NEEDS_QUOTING = re.compile(r'[\s#"\'\\$]')


def spelled(value: object) -> str:
    """A setting's value as `.env` spells it: a boolean in lower case, nothing as empty."""
    return str(value).lower() if isinstance(value, bool) else str(value or "")


SettingKind = Literal["text", "boolean", "integer", "number", "choice"]
"""Which control edits a setting."""


def field_kind(field: str) -> tuple[SettingKind, list[str]]:
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


class Setting(BaseModel):
    """One configurable value, described without ever carrying a secret."""

    key: str
    field: str
    secret: bool
    present: bool
    kind: SettingKind
    """Which control to render."""

    choices: list[str] = []
    value: str = ""
    """What `.env` holds for it. Empty for a secret: presence is all anyone reading this needs, and all it should hold."""

    shadowed: bool = False
    """A shell variable is overriding .env, so an edit there will not take effect."""

    effective: str = ""
    """What is actually in force, including a default nothing has overridden.

    An empty field with a default behind it is not unset, and showing it as
    such invites someone to type the value it already has."""


class SettingsGroup(BaseModel):
    """The settings that unlock one thing, and what to know before setting them."""

    title: str
    note: str
    settings: list[Setting]


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


class EnvFile:
    """The `.env` at `path`, and the settings loaded from it, which every write refreshes."""

    def __init__(self, path: Path, *, settings: AppSettings) -> None:
        """
        Args:
            path: the file `settings` was loaded from.
            settings: refreshed in place after each write, never replaced.
        """
        self.path = path
        self.settings = settings

    def read_values(self) -> dict[str, str]:
        """The keys present in the file and their raw values, in file order."""
        if not self.path.exists():
            return {}
        values: dict[str, str] = {}
        for line in self.path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            values[key.strip()] = _unquote(value.strip())
        return values

    def unknown(self) -> list[str]:
        """Keys in the file that no setting reads: a typo here is silent, since the setting keeps its default."""
        known = declared()
        return [key for key in self.read_values() if key not in known]

    def write_values(self, updates: dict[str, str]) -> None:
        """Apply `updates` to the file, creating it if absent, and reload the settings from it.

        An empty value clears the key rather than writing an empty string, matching
        how `AppSettings` already treats `KEY=` — the way people write "I do not use
        this".

        Raises:
            UnknownSettingError: a key outside what AppSettings declares.
        """
        known = declared()
        if unknown := [key for key in updates if key not in known]:
            raise UnknownSettingError(unknown)

        lines = self.path.read_text(encoding="utf-8").splitlines() if self.path.exists() else []
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

        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        _restrict(self.path)
        logger.info(f"Updated {len(updates)} setting(s) in {self.path.name}")
        self.reload()

    def reload(self) -> None:
        """Re-read configuration into the settings this was handed.

        Mutated in place rather than rebound: every module imported `settings` by
        value, so replacing the object would leave all of them pointing at the
        old one.
        """
        fresh = AppSettings(_env_file=self.path)
        for field in AppSettings.model_fields:
            setattr(self.settings, field, getattr(fresh, field))

    def describe(self, field: str, stored: str = "") -> Setting:
        """One setting as it stands, with a secret reported only as present or absent.

        Args:
            stored: what the file holds for it, as `read_values` reads it.
        """
        key = env_var(field)
        kind, choices = field_kind(field)
        secret = is_secret(field)
        current = getattr(self.settings, field)
        return Setting(
            key=key,
            field=field,
            secret=secret,
            present=current is not None and current != "",
            # A boolean's stored form can be absent while its value is False, so
            # the effective value is shown rather than the raw file text.
            value="" if secret else (spelled(current) if kind == "boolean" else stored),
            effective="" if secret else spelled(current),
            kind=kind,
            choices=choices,
            shadowed=is_shadowed(key),
        )

    def groups(self) -> list[SettingsGroup]:
        """Every setting, described, under what it unlocks, in the order someone sets them up."""
        stored = self.read_values()
        described = [self.describe(field, stored.get(key, "")) for key, field in declared().items()]
        return [
            SettingsGroup(
                title=each.title,
                note=each.note,
                settings=[setting for setting in described if group(setting.field) == each],
            )
            for each in GROUPS
        ]


def _restrict(path: Path) -> None:
    """Make the file owner-only where the platform supports it.

    It holds API keys. Windows ignores POSIX modes, so a failure here is not
    worth failing the save over.
    """
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError as e:
        logger.debug(f"Could not restrict permissions on {path}: {e}")
